"""OpenAPI 3.0 spetsifikatsiyasi (Swagger UI: /api/docs)."""

_ERROR = {"$ref": "#/components/schemas/Error"}


def _err(desc):
    return {"description": desc, "content": {"application/json": {"schema": _ERROR}}}


OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "SamDU AI Yordamchi API",
        "version": "1.0.0",
        "description": (
            "Sharof Rashidov nomidagi Samarqand davlat universiteti axborot yordamchisi API si. "
            "Veb va mobil ilovalar uchun.\n\n"
            "**Matnli chat:** `POST /api/v1/chat` (to'liq javob) yoki `POST /api/v1/chat/stream` (SSE oqim).\n\n"
            "**Ovozli chat:** `POST /api/v1/live/token` → qaytgan `websocket_url` ga ulanish → "
            "`setup` xabarini yuborish → 16 kHz PCM audio yuborish / 24 kHz PCM audio qabul qilish. "
            "Model `search_samdu` funksiyasini chaqirsa, `POST /api/v1/search` natijasini `toolResponse` sifatida qaytaring. "
            "To'liq protokol: loyihadagi `API.md` fayli.\n\n"
            "**Cheklovlar:** har bir IP uchun daqiqasiga chat — 20, search — 60, live/token — 6 so'rov. "
            "Oshib ketsa `429` va `Retry-After` sarlavhasi qaytadi."
        ),
    },
    "servers": [{"url": "/"}],
    "tags": [
        {"name": "Chat", "description": "Matnli savol-javob"},
        {"name": "Voice", "description": "Ovozli real vaqt suhbati"},
        {"name": "Service", "description": "Xizmat endpointlari"},
    ],
    "paths": {
        "/api/v1/chat": {
            "post": {
                "tags": ["Chat"],
                "summary": "Savolga to'liq javob olish",
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/ChatRequest"},
                    "example": {"question": "SamDU rektori kim?", "history": []},
                }}},
                "responses": {
                    "200": {"description": "Javob", "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/ChatResponse"}}}},
                    "400": _err("Noto'g'ri so'rov (empty_question, question_too_long)"),
                    "429": _err("So'rovlar limiti oshdi (rate_limited)"),
                    "502": _err("Javob yaratishda xato (generation_failed)"),
                    "503": _err("Server band (busy)"),
                },
            }
        },
        "/api/v1/chat/stream": {
            "post": {
                "tags": ["Chat"],
                "summary": "Javobni oqim (Server-Sent Events) ko'rinishida olish",
                "description": (
                    "Javob `text/event-stream` formatida bo'laklab keladi:\n\n"
                    "```\nevent: delta\ndata: {\"text\": \"SamDU rektori \"}\n\n"
                    "event: delta\ndata: {\"text\": \"— Xalmuradov Rustam Ibragimovich.\"}\n\n"
                    "event: done\ndata: {\"sources\": [{\"title\": \"SamDU rektori\", \"url\": \"https://...\"}], "
                    "\"cached\": false, \"latency_ms\": 1430}\n```\n\n"
                    "Xato bo'lsa: `event: error` / `data: {\"code\": \"generation_failed\", \"message\": \"...\"}`.\n\n"
                    "Validatsiya va limit xatolari oqim boshlanmasdan oddiy JSON (400/429) bilan qaytadi."
                ),
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/ChatRequest"},
                    "example": {"question": "Kredit-modul tizimi nima?"},
                }}},
                "responses": {
                    "200": {"description": "SSE oqimi", "content": {"text/event-stream": {"schema": {"type": "string"}}}},
                    "400": _err("Noto'g'ri so'rov"),
                    "429": _err("So'rovlar limiti oshdi"),
                },
            }
        },
        "/api/v1/search": {
            "post": {
                "tags": ["Voice"],
                "summary": "Bilim bazasidan qidiruv (model chaqirilmaydi)",
                "description": "Ovozli seansda `search_samdu` funksiya chaqiruviga javob berish uchun ishlatiladi. Tez ishlaydi (~0.3–0.7 s).",
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/SearchRequest"},
                    "example": {"query": "SamDU rektori", "top_k": 5},
                }}},
                "responses": {
                    "200": {"description": "Topilgan ma'lumotlar", "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/SearchResponse"}}}},
                    "400": _err("Bo'sh so'rov"),
                    "429": _err("So'rovlar limiti oshdi"),
                },
            }
        },
        "/api/v1/live/token": {
            "post": {
                "tags": ["Voice"],
                "summary": "Ovozli seans uchun bir martalik token olish",
                "description": (
                    "Token bitta seans uchun amal qiladi; seansni `session_start_deadline` gacha boshlash kerak "
                    "(2 daqiqa), seans esa `expires_at` gacha davom etishi mumkin (30 daqiqa). Model, ovoz va "
                    "ko'rsatmalar tokenga qulflangan. Har bir yangi ovozli seans uchun yangi token oling."
                ),
                "responses": {
                    "200": {"description": "Token", "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/LiveTokenResponse"}}}},
                    "429": _err("So'rovlar limiti oshdi"),
                    "503": _err("Ovozli xizmat vaqtincha mavjud emas (voice_unavailable)"),
                },
            }
        },
        "/api/v1/suggestions": {
            "get": {
                "tags": ["Service"],
                "summary": "Tavsiya etilgan savollar (tezkor tugmalar uchun)",
                "responses": {"200": {"description": "Ro'yxat", "content": {"application/json": {"example": {
                    "status": "success",
                    "suggestions": [{"title": "Qabul", "question": "SamDUga qabul qilish tartibi qanday?"}],
                }}}}},
            }
        },
        "/api/v1/health": {
            "get": {
                "tags": ["Service"],
                "summary": "Xizmat holati",
                "responses": {"200": {"description": "OK", "content": {"application/json": {"example": {
                    "status": "ok", "knowledge_chunks": 1444, "uptime_seconds": 3600}}}}},
            }
        },
    },
    "components": {
        "schemas": {
            "HistoryItem": {
                "type": "object",
                "required": ["role", "content"],
                "properties": {
                    "role": {"type": "string", "enum": ["user", "assistant"]},
                    "content": {"type": "string", "maxLength": 1500},
                },
            },
            "ChatRequest": {
                "type": "object",
                "required": ["question"],
                "properties": {
                    "question": {"type": "string", "maxLength": 1000, "description": "Foydalanuvchi savoli (o'zbek, rus, ingliz)"},
                    "history": {
                        "type": "array",
                        "description": "Ixtiyoriy: davomiy savollar uchun oldingi xabarlar (oxirgi 6 tasi hisobga olinadi). Server suhbatni saqlamaydi.",
                        "items": {"$ref": "#/components/schemas/HistoryItem"},
                    },
                },
            },
            "Source": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "url": {"type": "string", "nullable": True}},
            },
            "ChatResponse": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "success"},
                    "answer": {"type": "string", "description": "Markdown formatidagi javob"},
                    "sources": {"type": "array", "items": {"$ref": "#/components/schemas/Source"}},
                    "cached": {"type": "boolean"},
                    "latency_ms": {"type": "integer"},
                },
            },
            "SearchRequest": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "maxLength": 500},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                },
            },
            "SearchResponse": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "success"},
                    "found": {"type": "boolean"},
                    "context": {"type": "string", "description": "Modelga qaytariladigan matn"},
                    "sources": {"type": "array", "items": {"$ref": "#/components/schemas/Source"}},
                },
            },
            "LiveTokenResponse": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "success"},
                    "token": {"type": "string"},
                    "websocket_url": {"type": "string", "description": "Shu manzilga WebSocket orqali ulaning"},
                    "expires_at": {"type": "string", "format": "date-time"},
                    "session_start_deadline": {"type": "string", "format": "date-time"},
                    "setup": {"type": "object", "description": "Ulangandan so'ng birinchi yuboriladigan xabar"},
                    "audio": {"type": "object", "description": "Kirish/chiqish audio formatlari"},
                    "tool": {"type": "object", "description": "Funksiya nomi va unga javob olish endpointi"},
                },
            },
            "Error": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "error"},
                    "code": {"type": "string", "example": "rate_limited"},
                    "message": {"type": "string"},
                },
            },
        }
    },
}
