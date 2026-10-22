# SamDU AI Yordamchi — API hujjati (v1)

Interaktiv hujjat (Swagger): **`/api/docs`** · OpenAPI spetsifikatsiyasi: **`/api/openapi.json`**
(standart holatda yopiq — ochish uchun `.env` ga `ENABLE_API_DOCS=true`)

- Base URL: `https://<server>/api/v1`
- Format: JSON (UTF-8), `Content-Type: application/json`
- Autentifikatsiya: mobil ilova har bir so'rovda `X-API-Key: <kalit>` sarlavhasini yuboradi
  (kalitlar serverdagi `.env` → `CLIENT_API_KEYS`). Veb sahifa esa avtomatik beriladigan
  sessiya cookie si bilan ishlaydi. `/chat`, `/chat/stream`, `/search`, `/live/token` uchun majburiy.
- CORS: yoqilgan (`CORS_ORIGINS` orqali sozlanadi)

| Endpoint | Metod | Vazifasi |
|---|---|---|
| `/chat` | POST | Savolga to'liq javob |
| `/chat/stream` | POST | Javobni oqim (SSE) ko'rinishida olish |
| `/live/token` | POST | Ovozli seans uchun bir martalik token |
| `/search` | POST | Bilim bazasidan qidiruv (ovozli seansdagi funksiya chaqiruvi uchun) |
| `/suggestions?lang=uz\|en` | GET | Tezkor savollar ro'yxati |
| `/health` | GET | Xizmat holati |

---

## 1. Matnli chat

### `POST /chat`

```json
{
  "question": "SamDUda qanday fakultetlar bor?",
  "history": [
    {"role": "user", "content": "Salom"},
    {"role": "assistant", "content": "Assalomu alaykum! ..."}
  ],
  "lang": "uz"
}
```

- `question` — majburiy, 1000 belgigacha. O'zbek (lotin/kirill), rus va ingliz tillarida.
- `lang` — ixtiyoriy, `"uz"` yoki `"en"` (ilovada tanlangan til). Javob **savol tilida** beriladi:
  inglizcha savolga — inglizcha, o'zbekcha savolga — o'zbekcha. Til aniq bo'lmasa (masalan, "GPA"), `lang` ishlatiladi.
- `history` — ixtiyoriy. Server suhbatni **saqlamaydi**; davomiy savollar ("uning telefoni-chi?") uchun
  ilova oxirgi xabarlarni yuboradi (oxirgi 6 tasi hisobga olinadi, har biri 1500 belgigacha).

Javob `200`:

```json
{
  "status": "success",
  "answer": "SamDUda **20 dan ortiq** fakultet va institut mavjud ...",
  "sources": [{"title": "SamDU fakultetlari", "url": "https://www.samdu.uz/uz"}],
  "cached": false,
  "latency_ms": 1480
}
```

`answer` — **Markdown** formatida (qalin matn, ro'yxatlar). Mobil ilovada Markdown renderer ishlating
(Flutter: `flutter_markdown`, Android: `Markwon`, iOS: `AttributedString(markdown:)`).

```bash
curl -X POST https://<server>/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Kredit-modul tizimi nima?"}'
```

### `POST /chat/stream` (tavsiya etiladi — birinchi so'zlar ~1–1.5 s da chiqadi)

So'rov tanasi `/chat` bilan bir xil. Javob `text/event-stream`:

```
event: delta
data: {"text": "SamDUda "}

event: delta
data: {"text": "qator fakultetlar mavjud."}

event: done
data: {"sources": [{"title": "SamDU fakultetlari", "url": "..."}], "cached": false, "latency_ms": 1430}
```

- `delta` matnlarini ketma-ket qo'shib boring.
- `done` — oxirgi hodisa (manbalar shu yerda).
- `error` — `{"code": "generation_failed", "message": "..."}` (foydalanuvchiga `message` ni ko'rsating).
- Validatsiya/limit xatolari oqim boshlanmasdan oddiy JSON bilan qaytadi (400/429).

JavaScript namunasi:

```js
const res = await fetch("/api/v1/chat/stream", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({question}),
});
const reader = res.body.getReader();
const decoder = new TextDecoder();
let buf = "";
for (;;) {
  const {value, done} = await reader.read();
  if (done) break;
  buf += decoder.decode(value, {stream: true});
  let i;
  while ((i = buf.indexOf("\n\n")) !== -1) {
    const block = buf.slice(0, i); buf = buf.slice(i + 2);
    const event = /event: (\w+)/.exec(block)?.[1];
    const data = JSON.parse(/data: (.*)/.exec(block)?.[1] || "{}");
    if (event === "delta") appendText(data.text);
    if (event === "done") showSources(data.sources);
  }
}
```

---

## 2. Ovozli chat (real vaqt)

Audio **serverimiz orqali o'tmaydi** — ilova ovozli xizmatga to'g'ridan-to'g'ri ulanadi, server faqat
qisqa muddatli bir martalik token beradi. Shuning uchun server yuklamasi minimal, kechikish esa past.

```
Ilova ──POST /live/token──▶ Server          (token, websocket_url)
Ilova ══WebSocket═════════▶ Ovozli xizmat   (audio ⇄ audio)
          ◀── toolCall: search_samdu(query)
Ilova ──POST /search──────▶ Server          (bilim bazasidan matn)
          ──▶ toolResponse
```

### 2.1. Token olish — `POST /live/token`

So'rov tanasi (ixtiyoriy): `{"lang": "en"}` — ovozli yordamchi tili (`uz` standart). Tanlangan tilda gapiradi va tinglaydi.

```json
{
  "status": "success",
  "token": "auth_tokens/…",
  "websocket_url": "wss://…BidiGenerateContentConstrained?access_token=auth_tokens/…",
  "expires_at": "2026-10-19T08:00:00+00:00",
  "session_start_deadline": "2026-10-19T07:32:00+00:00",
  "setup": {"setup": {"model": "models/…"}},
  "audio": {
    "input":  {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1, "mime_type": "audio/pcm;rate=16000"},
    "output": {"encoding": "pcm_s16le", "sample_rate": 24000, "channels": 1}
  },
  "tool": {"name": "search_samdu", "endpoint": "/api/v1/search"},
  "lang": "en"
}
```

- Token **bitta seans** uchun. Seansni 2 daqiqa ichida boshlang; seans 30 daqiqagacha davom etishi mumkin.
- Har bir yangi ovozli suhbat uchun yangi token oling. Tokenni saqlamang va qayta ishlatmang.
- Ovoz, til, ko'rsatmalar va funksiyalar tokenga qulflangan — ilova ularni o'zgartirmaydi.

### 2.2. Seans protokoli

Barcha xabarlar — JSON (WebSocket kadrlari matn yoki binary bo'lib kelishi mumkin; binary bo'lsa UTF-8 matnga o'giring).

**1) Ulanish va sozlash.** `websocket_url` ga ulaning va javobdagi `setup` obyektini aynan yuboring:

```json
{"setup": {"model": "models/…"}}
```

Server `{"setupComplete": {}}` qaytaradi — shundan keyin audio yuborish mumkin.

**2) Mikrofon audiosini yuborish.** 16 kHz, mono, 16-bit little-endian PCM. ~100 ms bo'laklar (3200 bayt), base64:

```json
{"realtimeInput": {"audio": {"data": "<base64 PCM>", "mimeType": "audio/pcm;rate=16000"}}}
```

Gap tugashi avtomatik aniqlanadi (VAD) — alohida "tugadi" signali kerak emas.
Matn bilan yozish ham mumkin: `{"realtimeInput": {"text": "SamDU qayerda joylashgan?"}}`.

**3) Serverdan keladigan xabarlar:**

| Xabar | Ma'nosi | Ilova nima qiladi |
|---|---|---|
| `serverContent.modelTurn.parts[].inlineData.data` | Javob audiosi (24 kHz PCM16, base64) | Navbat bilan ijro etadi |
| `serverContent.inputTranscription.text` | Foydalanuvchi nutqi matni (bo'laklab) | Ekranga chiqaradi |
| `serverContent.outputTranscription.text` | Javob matni (bo'laklab) | Ekranga / chat tarixiga |
| `serverContent.interrupted: true` | Foydalanuvchi gapni bo'ldi | Ijroni **darhol to'xtatadi**, navbatni tozalaydi |
| `serverContent.turnComplete: true` | Javob tugadi | Tinglash holatiga qaytadi |
| `toolCall.functionCalls[]` | Bilim bazasidan ma'lumot kerak | 4-bandga qarang |
| `goAway` | Seans tez orada yopiladi | Foydalanuvchiga xabar, kerak bo'lsa yangi token bilan qayta ulanish |

**4) Funksiya chaqiruvi (`search_samdu`).** Kelgan xabar:

```json
{"toolCall": {"functionCalls": [{"id": "call_123", "name": "search_samdu", "args": {"query": "SamDU fakultetlari"}}]}}
```

Ilova serverdan qidiradi:

```bash
POST /api/v1/search
{"query": "SamDU fakultetlari", "top_k": 5}
→ {"status": "success", "found": true, "context": "[1] SamDU fakultetlari | ...", "sources": [...]}
```

va natijani seansga qaytaradi (`id` va `name` aynan bo'lsin):

```json
{"toolResponse": {"functionResponses": [
  {"id": "call_123", "name": "search_samdu", "response": {"result": "<context matni yoki 'Ma'lumot topilmadi.'>"}}
]}}
```

### 2.3. Mobil ilova uchun maslahatlar

- **Audio sessiya:** iOS — `AVAudioSession` `.playAndRecord` + `.voiceChat` rejimi (aks-sado so'ndirish);
  Android — `AudioRecord` (`VOICE_COMMUNICATION` manbasi, 16000 Hz, `ENCODING_PCM_16BIT`) va `AudioTrack` (24000 Hz).
- **Ijro:** kelgan PCM bo'laklarini bitta oqimli pleyerga ketma-ket yozing; `interrupted` kelganda buferni tozalang.
- **Qayta ulanish:** WebSocket uzilsa, yangi token oling (eski token bir martalik).
- **Ruxsat:** mikrofon ruxsatini token so'rashdan oldin oling — token 2 daqiqada eskiradi.
- Brauzer bo'yicha to'liq ishlaydigan namuna: [static/js/voice.js](static/js/voice.js).

---

## 3. Xatolar

Barcha xatolar bir xil formatda:

```json
{"status": "error", "code": "rate_limited", "message": "So'rovlar soni oshib ketdi. 12 soniyadan so'ng qayta urinib ko'ring."}
```

| HTTP | `code` | Sabab |
|---|---|---|
| 401 | `unauthorized` | `X-API-Key` yo'q/noto'g'ri yoki veb sessiya muddati tugagan |
| 400 | `empty_question`, `question_too_long`, `empty_query`, `invalid_request` | Noto'g'ri so'rov |
| 404 | `not_found` | Endpoint topilmadi |
| 429 | `rate_limited` | Limit oshdi (`Retry-After` sarlavhasida soniyalar) |
| 502 | `generation_failed` | Javob yaratishda vaqtinchalik xato |
| 503 | `busy` | Server band (bir vaqtdagi so'rovlar chegarasi) |
| 503 | `voice_unavailable` | Ovozli xizmat vaqtincha mavjud emas |

`message` maydoni foydalanuvchiga ko'rsatish uchun tayyor matn.

## 4. Limitlar (har bir IP va har bir veb sessiya uchun)

| Endpoint | Daqiqasiga | Kuniga | Butun server, daqiqasiga | `.env` o'zgaruvchilari |
|---|---|---|---|---|
| `/chat`, `/chat/stream` | 10 | 150 | 300 | `RATE_LIMIT_CHAT`, `RATE_LIMIT_CHAT_DAILY`, `GLOBAL_LIMIT_CHAT` |
| `/search` | 40 | 1000 | — | `RATE_LIMIT_SEARCH`, `RATE_LIMIT_SEARCH_DAILY` |
| `/live/token` | 3 | 20 | 30 | `RATE_LIMIT_LIVE_TOKEN`, `RATE_LIMIT_LIVE_TOKEN_DAILY`, `GLOBAL_LIMIT_LIVE_TOKEN` |
