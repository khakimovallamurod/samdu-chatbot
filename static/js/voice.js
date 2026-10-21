/*
 * SamDU ovozli yordamchi: real vaqt ovozli seansi.
 * Server faqat bir martalik token beradi; audio to'g'ridan-to'g'ri seansga uzatiladi.
 * Model ma'lumot so'rasa (search_samdu), /api/v1/search orqali bilim bazasidan javob olinadi.
 */
(function () {
  const IN_RATE = 16000;
  const OUT_RATE = 24000;

  // Mikrofon oqimini 16 kHz PCM16 ga aylantiruvchi AudioWorklet (100 ms bo'laklar)
  const CAPTURE_WORKLET = `
    class Capture extends AudioWorkletProcessor {
      constructor() {
        super();
        this.ratio = sampleRate / ${IN_RATE};
        this.buf = new Int16Array(${IN_RATE / 10});
        this.idx = 0; this.acc = 0; this.n = 0; this.pos = 0;
        this.levelSum = 0; this.levelCount = 0; this.blocks = 0; this.chunkSq = 0;
      }
      process(inputs) {
        const ch = inputs[0] && inputs[0][0];
        if (!ch) return true;
        for (let i = 0; i < ch.length; i++) {
          const s = ch[i];
          this.levelSum += s * s; this.levelCount++;
          this.acc += s; this.n++; this.pos += 1;
          if (this.pos >= this.ratio) {
            let v = this.acc / this.n;
            v = v > 1 ? 1 : v < -1 ? -1 : v;
            this.buf[this.idx++] = v < 0 ? v * 0x8000 : v * 0x7fff;
            this.chunkSq += v * v;
            this.acc = 0; this.n = 0; this.pos -= this.ratio;
            if (this.idx === this.buf.length) {
              const rms = Math.sqrt(this.chunkSq / this.buf.length);
              this.port.postMessage({ pcm: this.buf.buffer, rms }, [this.buf.buffer]);
              this.chunkSq = 0;
              this.buf = new Int16Array(${IN_RATE / 10});
              this.idx = 0;
            }
          }
        }
        if (++this.blocks % 6 === 0) {
          this.port.postMessage({ level: Math.sqrt(this.levelSum / this.levelCount) });
          this.levelSum = 0; this.levelCount = 0;
        }
        return true;
      }
    }
    registerProcessor("samdu-capture", Capture);
  `;

  // Shovqin filtri (noise gate): fon shovqiniga moslashadi, jim paytda modelga jimlik yuboriladi
  const GATE = {
    minThreshold: 0.012, // eng past ovoz chegarasi (RMS)
    ratio: 3,            // nutq fon shovqinidan necha baravar baland bo'lishi kerak
    hangChunks: 8,       // ovoz pasaygach yana 800 ms uzatib turish (so'z oxiri kesilmasin)
    preroll: 3,          // gap boshidan oldingi 300 ms ham yuboriladi (boshi kesilmasin)
  };

  // Foydalanuvchiga ko'rinadigan xabarlar (UZ / EN)
  const MSG = {
    uz: {
      startFailed: "Ovozli suhbatni boshlab bo'lmadi.",
      micDenied: "Mikrofonga ruxsat berilmadi. Brauzer sozlamalarida mikrofonga ruxsat bering.",
      micMissing: "Mikrofon topilmadi.",
      unavailable: "Ovozli yordamchi vaqtincha mavjud emas.",
      timeout: "Ulanish vaqti tugadi. Qayta urinib ko'ring.",
      connectFailed: "Ovozli xizmatga ulanib bo'lmadi.",
      ended: "Ovozli seans yakunlandi. Qayta boshlash uchun mikrofon tugmasini bosing.",
      goAway: "Seans vaqti tugamoqda. Davom etish uchun qayta boshlang.",
      notFound: "Ma'lumot topilmadi.",
      toolPrefix: "Quyidagi ma'lumotlar asosida javobni FAQAT O'ZBEK TILIDA ayting:\n\n",
    },
    en: {
      startFailed: "Could not start the voice chat.",
      micDenied: "Microphone access was denied. Please allow the microphone in your browser settings.",
      micMissing: "No microphone found.",
      unavailable: "The voice assistant is temporarily unavailable.",
      timeout: "Connection timed out. Please try again.",
      connectFailed: "Could not connect to the voice service.",
      ended: "The voice session has ended. Press the microphone button to start again.",
      goAway: "The session is about to end. Please start again to continue.",
      notFound: "No information found.",
      toolPrefix: "Answer ONLY IN ENGLISH, translating accurately from the information below:\n\n",
    },
  };

  function base64FromBuffer(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(binary);
  }

  function int16FromBase64(b64) {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return new Int16Array(bytes.buffer, 0, bytes.length >> 1);
  }

  class LiveVoice {
    constructor(handlers = {}) {
      this.h = handlers; // onState, onLevel, onTranscript, onTurn, onError, onClose
      this.lang = "uz";
      this.ws = null;
      this.muted = false;
      this.active = false;
      this.sources = new Set();
      this.nextTime = 0;
      this.userText = "";
      this.botText = "";
      this.turnDone = false;
      this.resetGate();
    }

    resetGate() {
      this.noiseFloor = 0.004;
      this.hang = 0;
      this.preQueue = [];
    }

    sendAudio(buffer) {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      this.ws.send(JSON.stringify({
        realtimeInput: { audio: { data: base64FromBuffer(buffer), mimeType: `audio/pcm;rate=${IN_RATE}` } },
      }));
    }

    handleMicChunk(buffer, rms) {
      // Fon shovqini darajasini sekin kuzatamiz (jim paytda tez, gap paytida juda sekin moslashadi)
      const k = rms < this.noiseFloor * 1.5 ? 0.05 : 0.002;
      this.noiseFloor = this.noiseFloor * (1 - k) + rms * k;
      const threshold = Math.max(GATE.minThreshold, this.noiseFloor * GATE.ratio);

      if (rms > threshold) {
        if (this.hang === 0) { this.preQueue.forEach((b) => this.sendAudio(b)); this.preQueue = []; }
        this.hang = GATE.hangChunks;
        this.sendAudio(buffer);
      } else if (this.hang > 0) {
        this.hang--;
        this.sendAudio(buffer);
      } else {
        // Jimlik: real audio o'rniga nol yuboriladi — vaqt uzluksiz qoladi, shovqin esa modelga yetmaydi
        this.preQueue.push(buffer);
        if (this.preQueue.length > GATE.preroll) this.sendAudio(new ArrayBuffer(this.preQueue.shift().byteLength));
      }
    }

    msg(key) {
      return (MSG[this.lang] || MSG.uz)[key];
    }

    emit(name, ...args) {
      if (typeof this.h[name] === "function") this.h[name](...args);
    }

    setState(state) {
      this.state = state;
      this.emit("onState", state);
    }

    async start() {
      if (this.active) return;
      this.active = true;
      this.resetGate();
      this.setState("connecting");

      // AudioContext lar foydalanuvchi bosgan zahoti yaratiladi (iOS/Safari talabi)
      const AC = window.AudioContext || window.webkitAudioContext;
      this.micCtx = new AC();
      this.outCtx = new AC({ sampleRate: OUT_RATE });
      this.outGain = this.outCtx.createGain();
      this.analyser = this.outCtx.createAnalyser();
      this.analyser.fftSize = 256;
      this.outGain.connect(this.analyser);
      this.analyser.connect(this.outCtx.destination);

      try {
        const [tokenData, stream] = await Promise.all([
          this.fetchToken(),
          navigator.mediaDevices.getUserMedia({
            audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
          }),
        ]);
        if (!this.active) { stream.getTracks().forEach((t) => t.stop()); return; }
        this.stream = stream;
        await this.connect(tokenData);
        await this.startMic();
        this.setState("listening");
        this.levelLoop();
      } catch (err) {
        let msg = err && err.message ? err.message : this.msg("startFailed");
        if (err && (err.name === "NotAllowedError" || err.name === "SecurityError")) {
          msg = this.msg("micDenied");
        } else if (err && err.name === "NotFoundError") {
          msg = this.msg("micMissing");
        }
        this.emit("onError", msg);
        this.stop();
      }
    }

    async fetchToken() {
      const res = await fetch("/api/v1/live/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lang: this.lang }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || this.msg("unavailable"));
      return data;
    }

    connect(tokenData) {
      return new Promise((resolve, reject) => {
        const ws = new WebSocket(tokenData.websocket_url);
        ws.binaryType = "arraybuffer";
        this.ws = ws;
        let ready = false;
        const timer = setTimeout(() => { if (!ready) reject(new Error(this.msg("timeout"))); }, 12000);

        ws.onopen = () => ws.send(JSON.stringify(tokenData.setup));
        ws.onmessage = (ev) => {
          const text = typeof ev.data === "string" ? ev.data : new TextDecoder().decode(ev.data);
          let msg;
          try { msg = JSON.parse(text); } catch (e) { return; }
          if (msg.setupComplete !== undefined && !ready) {
            ready = true;
            clearTimeout(timer);
            resolve();
            return;
          }
          this.handleMessage(msg);
        };
        ws.onerror = () => { if (!ready) { clearTimeout(timer); reject(new Error(this.msg("connectFailed"))); } };
        ws.onclose = (ev) => {
          clearTimeout(timer);
          if (!ready) { reject(new Error(this.msg("connectFailed"))); return; }
          if (this.active) {
            if (ev.code !== 1000) this.emit("onError", this.msg("ended"));
            this.stop();
          }
        };
      });
    }

    async startMic() {
      if (this.micCtx.state === "suspended") await this.micCtx.resume();
      if (this.outCtx.state === "suspended") await this.outCtx.resume();
      const url = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: "application/javascript" }));
      await this.micCtx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      this.micSource = this.micCtx.createMediaStreamSource(this.stream);
      this.worklet = new AudioWorkletNode(this.micCtx, "samdu-capture");
      this.worklet.port.onmessage = (e) => {
        if (e.data.level !== undefined) { this.micLevel = e.data.level; return; }
        if (this.muted) return;
        this.handleMicChunk(e.data.pcm, e.data.rms);
      };
      this.micSource.connect(this.worklet);
    }

    handleMessage(msg) {
      if (msg.toolCall) { this.handleToolCall(msg.toolCall); return; }
      if (msg.goAway) { this.emit("onError", this.msg("goAway")); return; }
      const sc = msg.serverContent;
      if (!sc) return;

      if (sc.interrupted) {
        // Foydalanuvchi gapni bo'ldi — ijroni darhol to'xtatamiz
        this.stopPlayback();
        this.setState("listening");
      }
      if (sc.inputTranscription && sc.inputTranscription.text) {
        if (this.turnDone && this.botText.trim()) this.flushTurn();
        this.userText += sc.inputTranscription.text;
        this.emit("onTranscript", "user", this.userText.trim());
      }
      if (sc.outputTranscription && sc.outputTranscription.text) {
        this.botText += sc.outputTranscription.text;
        this.emit("onTranscript", "bot", this.botText.trim());
      }
      const parts = (sc.modelTurn && sc.modelTurn.parts) || [];
      for (const part of parts) {
        if (part.inlineData && part.inlineData.data) this.play(part.inlineData.data);
      }
      if (sc.turnComplete) {
        this.turnDone = true;
        if (!this.sources.size && this.state !== "searching") this.setState("listening");
        // Transkripsiya audiodan biroz kechikib kelishi mumkin
        clearTimeout(this.flushTimer);
        this.flushTimer = setTimeout(() => { if (this.turnDone && this.botText.trim()) this.flushTurn(); }, 900);
      }
    }

    flushTurn() {
      const user = this.userText.trim();
      const bot = this.botText.trim();
      if (user || bot) this.emit("onTurn", user, bot);
      this.userText = "";
      this.botText = "";
      this.turnDone = false;
    }

    async handleToolCall(toolCall) {
      this.setState("searching");
      const calls = toolCall.functionCalls || [];
      const responses = await Promise.all(calls.map(async (fc) => {
        let result = this.msg("notFound");
        if (fc.name === "search_samdu") {
          try {
            const res = await fetch("/api/v1/search", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ query: (fc.args && fc.args.query) || "", top_k: 5 }),
            });
            const data = await res.json();
            // Bazada ruscha matnlar ham bor — model javobni baribir o'zbekcha berishi uchun eslatma
            if (res.ok && data.found) result = this.msg("toolPrefix") + data.context;
          } catch (e) { /* bo'sh natija qaytariladi */ }
        }
        return { id: fc.id, name: fc.name, response: { result } };
      }));
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ toolResponse: { functionResponses: responses } }));
      }
    }

    play(b64) {
      const pcm = int16FromBase64(b64);
      if (!pcm.length) return;
      const buffer = this.outCtx.createBuffer(1, pcm.length, OUT_RATE);
      const ch = buffer.getChannelData(0);
      for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000;
      const src = this.outCtx.createBufferSource();
      src.buffer = buffer;
      src.connect(this.outGain);
      const startAt = Math.max(this.nextTime, this.outCtx.currentTime + 0.03);
      src.start(startAt);
      this.nextTime = startAt + buffer.duration;
      this.sources.add(src);
      this.setState("speaking");
      src.onended = () => {
        this.sources.delete(src);
        if (!this.sources.size && this.active && this.state === "speaking") this.setState("listening");
      };
    }

    stopPlayback() {
      for (const src of this.sources) { try { src.stop(); } catch (e) {} }
      this.sources.clear();
      this.nextTime = 0;
    }

    levelLoop() {
      if (!this.active) return;
      let level = 0;
      if (this.state === "speaking" && this.analyser) {
        const data = new Uint8Array(this.analyser.frequencyBinCount);
        this.analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; sum += v * v; }
        level = Math.sqrt(sum / data.length) * 4;
      } else if (this.state === "listening" && !this.muted) {
        level = (this.micLevel || 0) * 6;
      }
      this.emit("onLevel", Math.min(1, level));
      this.raf = requestAnimationFrame(() => this.levelLoop());
    }

    setMuted(muted) {
      this.muted = muted;
      if (this.stream) this.stream.getAudioTracks().forEach((t) => { t.enabled = !muted; });
    }

    stop() {
      if (!this.active) return;
      this.active = false;
      clearTimeout(this.flushTimer);
      if (this.userText || this.botText) this.flushTurn();
      cancelAnimationFrame(this.raf);
      this.stopPlayback();
      if (this.ws) { try { this.ws.close(1000); } catch (e) {} this.ws = null; }
      if (this.worklet) { this.worklet.port.onmessage = null; this.worklet.disconnect(); }
      if (this.micSource) this.micSource.disconnect();
      if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
      if (this.micCtx) this.micCtx.close().catch(() => {});
      if (this.outCtx) this.outCtx.close().catch(() => {});
      this.worklet = this.micSource = this.stream = this.micCtx = this.outCtx = null;
      this.setState("idle");
      this.emit("onClose");
    }
  }

  window.LiveVoice = LiveVoice;
})();
