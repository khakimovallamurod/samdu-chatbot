# SamDU AI Yordamchi

Sharof Rashidov nomidagi Samarqand davlat universiteti uchun matnli va ovozli AI yordamchi.
SamDU Sun'iy intellekt va raqamli texnologiyalar laboratoriyasi ishlanmasi. O'zbek va ingliz tillarida ishlaydi.
Faqat SamDU haqidagi ma'lumotlar asosida javob beradi (`new-documents/` + www.samdu.uz + ai-lab.sampc.uz).

## Tuzilma

| Fayl | Vazifasi |
|---|---|
| `flaskapp.py` | Flask ilova: veb sahifa, `/api/docs`, CORS, xatolar |
| `api.py` | REST API `/api/v1/*` (mobil va veb uchun) |
| `rag.py` | Javob berish mantig'i: tezkor javoblar, kesh, generatsiya (oddiy va oqimli) |
| `knowledge.py` | Gibrid qidiruv: vektor (ChromaDB) + kalit so'z (BM25), RRF |
| `live.py` | Ovozli seans uchun bir martalik token |
| `security.py` | API himoyasi: veb sessiya cookie si va mobil ilova kaliti |
| `prompts.py` | Matnli va ovozli yordamchi ko'rsatmalari |
| `ingest.py` | `new-documents/*.txt` → ChromaDB (bazani noldan quradi) |
| `web_scraper.py` | samdu.uz va ai-lab.sampc.uz sahifalarini yig'ish |
| `config.py` | Barcha sozlamalar (`.env` orqali o'zgartiriladi) |
| `API.md` | Mobil ilova uchun API hujjati |

## O'rnatish

```bash
pip install -r requirements.txt
echo "AI_API_KEY=..." > .env
python ingest.py            # bazani qurish (~30 s)
python flaskapp.py          # http://localhost:8800
```

Bilim bazasini yangilash: `new-documents/` ga `.txt` qo'shing (yoki `python web_scraper.py`), so'ng
`python ingest.py` va serverni qayta ishga tushiring. Yangi fayl uchun chiroyli manba nomini
`config.py` dagi `SOURCE_TITLES` ga qo'shing.

## Production

```bash
gunicorn -w 2 -k gthread --threads 16 --timeout 120 -b 127.0.0.1:8800 flaskapp:app
```

- `--preload` ishlatmang (har bir worker bazani o'zi ochadi).
- nginx ortida: `.env` ga `TRUST_PROXY=true` qo'shing (aks holda barcha foydalanuvchilar bitta IP
  hisoblanib, limitga tez tushadi) va oqim uchun buferlashni o'chiring:

```nginx
location / {
    proxy_pass http://127.0.0.1:8800;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;          # /api/v1/chat/stream uchun
    proxy_read_timeout 120s;
}
```

- Ovozli rejim brauzerda faqat **HTTPS** (yoki `localhost`) da ishlaydi — mikrofon talabi.

## Server yuklamasini kamaytirish choralari

- Ovozli audio serverdan o'tmaydi: server faqat token beradi, mijoz to'g'ridan-to'g'ri ulanadi.
- Salomlashish, minnatdorchilik, "kimsan?" kabi savollarga model chaqirilmaydi.
- Bazada mos ma'lumot bo'lmasa (begona mavzu) — model chaqirilmaydi.
- Javoblar (30 daqiqa) va savol vektorlari (6 soat) xotirada keshlanadi.
- Bir vaqtdagi generatsiyalar soni cheklangan (`MAX_CONCURRENT_GENERATIONS`), ortig'i navbatda kutadi.
- API ga faqat sahifa bergan imzolangan HttpOnly cookie (veb) yoki `X-API-Key` (mobil ilova) bilan
  kirish mumkin — endpointni Network dan ko'chirib, skript bilan chaqirib bo'lmaydi.
- Limitlar IP va sessiya bo'yicha (daqiqalik + kunlik) hamda butun server bo'yicha (ko'p IP dan hujumga qarshi).
- Statik fayllar URL ida kontent xeshi (`?v=...`) bor va ular 1 yilga keshlanadi: F5 da qayta yuklanmaydi.
- Server suhbat tarixini saqlamaydi (stateless).

## `.env` sozlamalari (ixtiyoriy)

| O'zgaruvchi | Standart | Izoh |
|---|---|---|
| `CHAT_THINKING_LEVEL` | `minimal` | Oddiy savollar uchun (eng tez) |
| `CHAT_THINKING_LEVEL_NUMERIC` | `low` | Formula va raqamli savollar uchun (aniqroq) |
| `LIVE_VOICE` | `Kore` | Ovoz |
| `MAX_VECTOR_DISTANCE` | `0.36` | Qidiruvda o'xshashlik chegarasi |
| `RATE_LIMIT_CHAT` / `_SEARCH` / `_LIVE_TOKEN` | `10` / `40` / `3` | Daqiqasiga, har bir IP va sessiya |
| `RATE_LIMIT_CHAT_DAILY` / `_SEARCH_DAILY` / `_LIVE_TOKEN_DAILY` | `150` / `1000` / `20` | Kuniga |
| `GLOBAL_LIMIT_CHAT` / `GLOBAL_LIMIT_LIVE_TOKEN` | `300` / `30` | Butun server, daqiqasiga |
| `REQUIRE_CLIENT_AUTH` | `true` | API uchun cookie yoki `X-API-Key` talab qilish |
| `CLIENT_API_KEYS` | — | Mobil ilova kalitlari (vergul bilan) |
| `SECRET_KEY` | `AI_API_KEY` dan | Sessiya cookie sini imzolash |
| `SESSION_TTL` | `43200` | Sessiya muddati, soniya |
| `MAX_CONCURRENT_GENERATIONS` | `16` | |
| `ANSWER_CACHE_TTL` | `1800` | Soniya |
| `TRUST_PROXY` | `false` | nginx ortida `true` |
| `CORS_ORIGINS` | `*` | |
| `ENABLE_API_DOCS` | `false` | `/api/docs` ni ochish uchun `true` |
| `PORT` | `8800` | `python flaskapp.py` uchun |

Qo'shimcha: veb sahifaga `/?q=Savol+matni` havolasi bilan kirilsa, savol avtomatik yuboriladi.
