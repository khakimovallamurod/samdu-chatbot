(function () {
  const STORAGE_KEY = "samdu-chat-v2";
  const MAX_STORED = 40;
  const HISTORY_FOR_API = 6;

  const $ = (id) => document.getElementById(id);
  const ui = {
    chatArea: $("chatArea"), welcome: $("welcome"), messages: $("messages"),
    form: $("composer"), input: $("input"), send: $("sendBtn"), micBtn: $("micBtn"),
    clear: $("clearBtn"), newChat: $("newChatBtn"), toast: $("toast"),
    sidebar: $("sidebar"), backdrop: $("sidebarBackdrop"),
    voice: {
      overlay: $("voiceOverlay"), status: $("voiceStatus"), orb: $("orb"),
      user: $("voiceUserText"), bot: $("voiceBotText"), mute: $("voiceMute"),
      end: $("voiceEnd"),
    },
  };

  let history = loadHistory();
  let busy = false;

  // ---------- Til (UZ / EN) ----------
  const I18N = {
    uz: {
      pageTitle: "SamDU AI Yordamchi",
      assistant: "AI yordamchi", newChat: "Yangi suhbat", topics: "Mavzular", light: "Yorug'", dark: "Qorong'i",
      university: "Samarqand davlat universiteti", official: "Rasmiy AI yordamchi",
      welcomeTitle: "Qanday yordam bera olaman?",
      welcomeText: "Qabul, fakultetlar, rahbariyat va universitet tartib-qoidalari haqida yozing yoki",
      welcomeVoice: "ovozli so'rang",
      placeholder: "SamDU haqida savol bering...",
      footer: "© 2026 SamDU Sun'iy intellekt va raqamli texnologiyalar laboratoriyasi · Muhim ma'lumotlarni rasmiy manbalardan tekshiring",
      voiceTitle: "SamDU ovozli yordamchi",
      send: "Yuborish", voiceMode: "Ovozli rejim", voiceTag: "Ovozli", voiceReply: "Ovozli javob",
      thinking: "Ma'lumot izlanmoqda...", copy: "Nusxa olish", copied: "Nusxa olindi",
      error: "Kechirasiz, xatolik yuz berdi.", network: "Tarmoq xatosi. Internet aloqasini tekshiring.",
      unsupported: "Brauzeringiz ovozli suhbatni qo'llab-quvvatlamaydi (HTTPS kerak).",
      voiceHint: "Savolingizni ovoz chiqarib bering. Masalan: “SamDU rektori kim?”",
      micMuted: "Mikrofon o'chirilgan", theme: "Mavzuni almashtirish", clear: "Suhbatni tozalash", mic: "Ovozli suhbat",
      status: { connecting: "Ulanmoqda...", listening: "Tinglayapman — gapiring", searching: "Ma'lumot qidirilmoqda...", speaking: "Javob bermoqda...", idle: "" },
    },
    en: {
      pageTitle: "SamSU AI Assistant",
      assistant: "AI assistant", newChat: "New chat", topics: "Topics", light: "Light", dark: "Dark",
      university: "Samarkand State University", official: "Official AI assistant",
      welcomeTitle: "How can I help you?",
      welcomeText: "Ask about admission, faculties, leadership and university regulations, or",
      welcomeVoice: "ask by voice",
      placeholder: "Ask anything about SamSU...",
      footer: "© 2026 SamSU Artificial Intelligence and Digital Technologies Laboratory · Please verify important information with official sources",
      voiceTitle: "SamSU voice assistant",
      send: "Send", voiceMode: "Voice mode", voiceTag: "Voice", voiceReply: "Voice reply",
      thinking: "Looking up information...", copy: "Copy", copied: "Copied",
      error: "Sorry, something went wrong.", network: "Network error. Please check your internet connection.",
      unsupported: "Your browser does not support voice chat (HTTPS is required).",
      voiceHint: "Ask your question out loud. For example: “Who is the rector of SamSU?”",
      micMuted: "Microphone is muted", theme: "Toggle theme", clear: "Clear chat", mic: "Voice chat",
      status: { connecting: "Connecting...", listening: "Listening — go ahead", searching: "Looking up information...", speaking: "Answering...", idle: "" },
    },
  };
  let lang = "uz";
  try { lang = localStorage.getItem("samdu-lang") === "en" ? "en" : "uz"; } catch (e) {}
  const t = (key) => I18N[lang][key];

  function applyLang(next) {
    lang = next === "en" ? "en" : "uz";
    try { localStorage.setItem("samdu-lang", lang); } catch (e) {}
    document.documentElement.lang = lang;
    document.title = t("pageTitle");
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    document.querySelectorAll("[data-t-uz]").forEach((el) => { el.textContent = el.dataset[lang === "en" ? "tEn" : "tUz"]; });
    document.querySelectorAll("[data-q-uz]").forEach((el) => { el.dataset.question = el.dataset[lang === "en" ? "qEn" : "qUz"]; });
    document.querySelectorAll(".theme-toggle").forEach((el) => { el.title = t("theme"); el.setAttribute("aria-label", t("theme")); });
    ui.clear.title = t("clear"); ui.clear.setAttribute("aria-label", t("clear"));
    ui.micBtn.title = t("mic"); ui.micBtn.setAttribute("aria-label", t("mic"));
    if (window.voice) window.voice.lang = lang;
    autoResize();
  }

  // ---------- Saqlash ----------
  // Suhbat faqat joriy tab davomida saqlanadi (sessionStorage): sahifa yangilansa qoladi,
  // tab/brauzer yopilib qayta ochilganda yangi suhbat boshlanadi.
  try { localStorage.removeItem(STORAGE_KEY); } catch (e) {} // eski versiyadan qolgan doimiy tarixni o'chirish
  function loadHistory() {
    try { return JSON.parse(sessionStorage.getItem(STORAGE_KEY)) || []; } catch (e) { return []; }
  }
  function saveHistory() {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-MAX_STORED))); } catch (e) {}
  }

  // ---------- Yordamchilar ----------
  marked.setOptions({ breaks: true, gfm: true });
  // Formulalar: markdown dan oldin ajratib olinadi (aks holda _ va * buziladi), keyin KaTeX bilan chiziladi
  function renderMarkdown(text) {
    const maths = [];
    const stash = (tex, display) => { maths.push({ tex, display }); return `@@MATH${maths.length - 1}@@`; };
    const src = (text || "")
      .replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => stash(tex, true))
      .replace(/\\\[([\s\S]+?)\\\]/g, (_, tex) => stash(tex, true))
      .replace(/\\\(([\s\S]+?)\\\)/g, (_, tex) => stash(tex, false))
      .replace(/(^|[^\\$\w])\$([^\s$](?:[^$\n]*?[^\s$])?)\$(?![\w$])/g,
        (m, pre, tex) => (/[\\^_=+{}]/.test(tex) ? pre + stash(tex, false) : m));
    let html = DOMPurify.sanitize(marked.parse(src));
    if (maths.length) {
      html = html.replace(/@@MATH(\d+)@@/g, (_, i) => {
        const m = maths[Number(i)];
        if (!window.katex) return escapeHtml(m.tex);
        try { return katex.renderToString(m.tex, { displayMode: m.display, throwOnError: false, output: "html" }); }
        catch (e) { return escapeHtml(m.tex); }
      });
    }
    const tpl = document.createElement("template");
    tpl.innerHTML = html;
    tpl.content.querySelectorAll("a").forEach((a) => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
    return tpl.innerHTML;
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function toast(text) {
    ui.toast.textContent = text;
    ui.toast.classList.remove("hidden");
    clearTimeout(toast.t);
    toast.t = setTimeout(() => ui.toast.classList.add("hidden"), 3500);
  }

  function nearBottom() {
    const el = ui.chatArea;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 140;
  }
  function scrollToBottom(force) {
    if (force || nearBottom()) ui.chatArea.scrollTop = ui.chatArea.scrollHeight;
  }

  function showMessages() {
    ui.welcome.classList.add("hidden");
    ui.messages.classList.remove("hidden");
  }

  function autoResize() {
    ui.input.style.height = "auto";
    ui.input.style.height = Math.min(ui.input.scrollHeight, 192) + "px";
    // Matn bo'lmasa asosiy tugma ovozli rejimni ochadi (ChatGPT kabi)
    const hasText = !!ui.input.value.trim();
    ui.send.disabled = busy;
    ui.send.querySelector(".icon-send").classList.toggle("hidden", !hasText);
    ui.send.querySelector(".icon-voice").classList.toggle("hidden", hasText);
    ui.send.setAttribute("aria-label", hasText ? t("send") : t("voiceMode"));
    ui.send.title = hasText ? t("send") : t("voiceMode");
  }

  // ---------- Xabarlarni chizish ----------
  const ICON_COPY = '<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75"/></svg>';
  const ICON_MIC_SMALL = '<svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 18.75a6 6 0 0 0 6-6v-1.5m-6 7.5a6 6 0 0 1-6-6v-1.5m6 7.5v3.75M12 15.75a3 3 0 0 1-3-3V4.5a3 3 0 1 1 6 0v8.25a3 3 0 0 1-3 3Z"/></svg>';

  function addUserMessage(text, voice) {
    showMessages();
    const row = document.createElement("div");
    row.className = "msg-enter flex justify-end";
    row.innerHTML = `
      <div class="max-w-[85%] rounded-3xl bg-zinc-100 px-4 py-2.5 text-[15px] leading-relaxed text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100">
        ${voice ? `<span class="mb-1 flex items-center gap-1 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">${ICON_MIC_SMALL} ${t("voiceTag")}</span>` : ""}
        <div class="whitespace-pre-wrap break-words">${escapeHtml(text)}</div>
      </div>`;
    ui.messages.appendChild(row);
    scrollToBottom(true);
  }

  function addBotMessage(voice) {
    showMessages();
    const row = document.createElement("div");
    row.className = "msg-enter flex gap-3";
    row.innerHTML = `
      <img src="/static/images/samdulogo.png" alt="" class="mt-0.5 h-8 w-8 shrink-0 rounded-full bg-white ring-1 ring-zinc-200 dark:ring-zinc-700" />
      <div class="min-w-0 flex-1 pt-1">
        ${voice ? `<div class="mb-1 flex items-center gap-1 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">${ICON_MIC_SMALL} ${t("voiceReply")}</div>` : ""}
        <div class="bubble prose-chat"><div class="thinking"><span class="thinking-dot"></span><span class="shimmer">${t("thinking")}</span></div></div>
        <div class="sources mt-4 hidden flex-wrap gap-1.5"></div>
        <div class="actions mt-2 hidden items-center gap-1">
          <button class="copy-btn inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-700 dark:text-zinc-500 dark:hover:bg-zinc-800 dark:hover:text-zinc-200">${ICON_COPY}<span>${t("copy")}</span></button>
        </div>
      </div>`;
    ui.messages.appendChild(row);
    scrollToBottom(true);
    const bubble = row.querySelector(".bubble");
    const sourcesEl = row.querySelector(".sources");
    const actions = row.querySelector(".actions");
    let text = "";
    let rafPending = false;
    let finished = false;

    const render = () => {
      rafPending = false;
      if (finished) return;
      const stick = nearBottom();
      bubble.innerHTML = renderMarkdown(text);
      bubble.classList.add("streaming-cursor");
      if (stick) scrollToBottom(true);
    };

    return {
      reset() {
        // Server javobni qaytadan boshladi — yarim matnni tozalaymiz
        text = "";
        bubble.innerHTML = `<div class="thinking"><span class="thinking-dot"></span><span class="shimmer">${t("thinking")}</span></div>`;
      },
      append(delta) {
        text += delta;
        if (!rafPending) { rafPending = true; requestAnimationFrame(render); }
      },
      finish(sources, errorText) {
        finished = true;
        const partial = errorText && text;
        if (errorText && !text) text = errorText;
        bubble.innerHTML = renderMarkdown(text);
        bubble.classList.remove("streaming-cursor");
        if (partial) {
          // Javobning bir qismi kelgan bo'lsa, matn oddiy ko'rinishda qoladi, ostida qisqa ogohlantirish
          bubble.insertAdjacentHTML("beforeend", `<p class="mt-3 text-sm text-red-600 dark:text-red-400">${escapeHtml(errorText)}</p>`);
        } else if (errorText) {
          bubble.classList.add("text-red-600", "dark:text-red-400");
        }
        renderSources(sourcesEl, sources);
        actions.classList.remove("hidden");
        actions.classList.add("flex");
        actions.querySelector(".copy-btn").onclick = async () => {
          try { await navigator.clipboard.writeText(text); toast(t("copied")); } catch (e) {}
        };
        scrollToBottom();
        return text;
      },
    };
  }

  function renderSources(el, sources) {
    if (!sources || !sources.length) return;
    el.innerHTML = sources.map((s) => {
      const label = escapeHtml(s.title);
      const cls = "inline-flex max-w-full items-center gap-1.5 rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400";
      const dot = '<span class="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500"></span>';
      return s.url
        ? `<a href="${encodeURI(s.url)}" target="_blank" rel="noopener" class="${cls} transition hover:border-emerald-300 hover:text-emerald-700 dark:hover:border-emerald-800 dark:hover:text-emerald-400">${dot}<span class="truncate">${label}</span></a>`
        : `<span class="${cls}">${dot}<span class="truncate">${label}</span></span>`;
    }).join("");
    el.classList.remove("hidden");
    el.classList.add("flex");
  }

  function restore() {
    if (!history.length) return;
    for (const m of history) {
      if (m.role === "user") addUserMessage(m.content, m.voice);
      else {
        const msg = addBotMessage(m.voice);
        msg.append(m.content);
        msg.finish(m.sources);
      }
    }
    scrollToBottom(true);
  }

  // ---------- So'rov yuborish (SSE oqim) ----------
  async function ask(question) {
    question = question.trim();
    if (!question || busy) return;
    busy = true;
    ui.input.value = "";
    autoResize();

    const apiHistory = history.slice(-HISTORY_FOR_API).map((m) => ({ role: m.role, content: m.content }));
    addUserMessage(question);
    history.push({ role: "user", content: question });
    const bot = addBotMessage();
    let sources = [];
    let errorText = null;

    try {
      const res = await fetch("/api/v1/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, history: apiHistory, lang }),
      });
      if (!res.ok || !res.body) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.message || t("error"));
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const raw = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          let event = "message", data = "";
          for (const line of raw.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (!data) continue;
          const payload = JSON.parse(data);
          if (event === "delta") bot.append(payload.text);
          else if (event === "reset") bot.reset();
          else if (event === "done") sources = payload.sources || [];
          else if (event === "error") errorText = payload.message;
        }
      }
    } catch (e) {
      errorText = e.message && e.message !== "Failed to fetch" ? e.message : t("network");
    }

    const answer = bot.finish(sources, errorText);
    if (!errorText && answer) history.push({ role: "assistant", content: answer, sources });
    else history.pop(); // muvaffaqiyatsiz savol API tarixiga kirmasin
    saveHistory();
    busy = false;
    autoResize();
    ui.input.focus({ preventScroll: true });
  }

  function resetChat() {
    if (voice.active) voice.stop();
    history = [];
    saveHistory();
    ui.messages.innerHTML = "";
    ui.messages.classList.add("hidden");
    ui.welcome.classList.remove("hidden");
    closeSidebar();
    ui.input.focus();
  }

  // ---------- Ovozli suhbat ----------
  const voice = new window.LiveVoice({
    onState(state) {
      ui.voice.orb.dataset.state = state;
      ui.voice.orb.dataset.muted = voice.muted ? "true" : "false";
      ui.voice.status.textContent = voice.muted && state === "listening" ? t("micMuted") : t("status")[state] || "";
    },
    onLevel(level) { ui.voice.orb.style.setProperty("--level", level.toFixed(3)); },
    onTranscript(role, text) {
      if (role === "user") { ui.voice.user.textContent = text; ui.voice.bot.textContent = ""; }
      else ui.voice.bot.textContent = text.length > 220 ? "…" + text.slice(-220) : text;
    },
    onTurn(user, bot) {
      if (user) { addUserMessage(user, true); history.push({ role: "user", content: user, voice: true }); }
      if (bot) {
        const msg = addBotMessage(true);
        msg.append(bot);
        msg.finish([]);
        history.push({ role: "assistant", content: bot, voice: true });
      }
      saveHistory();
    },
    onError(msg) { toast(msg); },
    onClose() { closeVoiceOverlay(); },
  });

  function openVoice() {
    ui.voice.overlay.classList.remove("hidden");
    ui.voice.overlay.classList.add("flex");
    ui.voice.user.textContent = "";
    ui.voice.bot.textContent = t("voiceHint");
    setMuted(false);
    voice.lang = lang;
    voice.start();
  }
  function closeVoiceOverlay() {
    ui.voice.overlay.classList.add("hidden");
    ui.voice.overlay.classList.remove("flex");
    ui.voice.orb.style.setProperty("--level", 0);
  }
  function setMuted(m) {
    voice.setMuted(m);
    ui.voice.mute.querySelector(".mic-on").classList.toggle("hidden", m);
    ui.voice.mute.querySelector(".mic-off").classList.toggle("hidden", !m);
    ui.voice.mute.classList.toggle("is-muted", m);
    ui.voice.orb.dataset.muted = m ? "true" : "false";
    if (voice.state === "listening") ui.voice.status.textContent = m ? t("micMuted") : t("status").listening;
  }

  // ---------- Hodisalar ----------
  function openSidebar() { ui.sidebar.classList.remove("-translate-x-full"); ui.backdrop.classList.remove("hidden"); }
  function closeSidebar() { ui.sidebar.classList.add("-translate-x-full"); ui.backdrop.classList.add("hidden"); }

  ui.form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (ui.input.value.trim()) ask(ui.input.value);
    else startVoice();
  });
  ui.input.addEventListener("input", autoResize);
  ui.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(ui.input.value); }
  });
  document.querySelectorAll("[data-question]").forEach((btn) =>
    btn.addEventListener("click", () => { closeSidebar(); ask(btn.dataset.question); }));
  ui.clear.addEventListener("click", resetChat);
  ui.newChat.addEventListener("click", resetChat);
  $("openSidebar").addEventListener("click", openSidebar);
  $("closeSidebar").addEventListener("click", closeSidebar);
  ui.backdrop.addEventListener("click", closeSidebar);
  // Mavzu: sarlavhadagi tugma almashtiradi, sidebar dagi tugmalar aniq tanlaydi
  function setTheme(dark) {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("samdu-theme", dark ? "dark" : "light"); } catch (e) {}
  }
  document.querySelectorAll(".theme-toggle").forEach((b) =>
    b.addEventListener("click", () => setTheme(!document.documentElement.classList.contains("dark"))));
  document.querySelectorAll(".theme-set").forEach((b) =>
    b.addEventListener("click", () => setTheme(b.dataset.theme === "dark")));

  function startVoice() {
    if (!navigator.mediaDevices || !window.AudioWorkletNode) {
      toast(t("unsupported"));
      return;
    }
    openVoice();
  }
  ui.micBtn.addEventListener("click", startVoice);
  document.querySelectorAll(".voice-link").forEach((b) => b.addEventListener("click", startVoice));
  ui.voice.mute.addEventListener("click", () => setMuted(!voice.muted));
  ui.voice.end.addEventListener("click", () => voice.stop());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && voice.active) voice.stop();
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); resetChat(); }
  });

  window.voice = voice;
  document.querySelectorAll(".lang-set").forEach((b) => b.addEventListener("click", () => applyLang(b.dataset.lang)));
  applyLang(lang);
  restore();
  autoResize();

  // ?q=... havolasi orqali kelgan savolni avtomatik yuborish (masalan, samdu.uz dan havola)
  const initialQuestion = new URLSearchParams(location.search).get("q");
  if (initialQuestion) {
    window.history.replaceState(null, "", location.pathname);
    ask(initialQuestion.slice(0, 1000));
  }
})();
