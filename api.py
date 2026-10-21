"""REST API (veb va mobil ilovalar uchun): /api/v1/*"""
import json
import logging
import time

from flask import Blueprint, Response, jsonify, request, stream_with_context

import rag
from config import RATE_LIMIT_CHAT, RATE_LIMIT_LIVE_TOKEN, RATE_LIMIT_SEARCH
from knowledge import get_kb
from live import create_live_token
from utils import RateLimiter

log = logging.getLogger(__name__)
api = Blueprint("api", __name__, url_prefix="/api/v1")
limiter = RateLimiter()
STARTED_AT = time.time()

SUGGESTIONS = [
    {"key": "admission", "title": {"uz": "Qabul", "en": "Admission"},
     "question": {"uz": "SamDUga qabul qilish tartibi qanday? Qanday hujjatlar kerak?",
                  "en": "How does admission to SamSU work and which documents are required?"}},
    {"key": "faculties", "title": {"uz": "Fakultetlar", "en": "Faculties"},
     "question": {"uz": "SamDUda qanday fakultet va institutlar bor?",
                  "en": "Which faculties and institutes does SamSU have?"}},
    {"key": "rector", "title": {"uz": "Rektor", "en": "Rector"},
     "question": {"uz": "SamDU rektori kim va qabul vaqti qachon?",
                  "en": "Who is the rector of SamSU and what are the reception hours?"}},
    {"key": "grading", "title": {"uz": "Baholash", "en": "Grading"},
     "question": {"uz": "Talabalar bilimi qanday baholanadi?",
                  "en": "How are students' knowledge and performance graded?"}},
    {"key": "credit", "title": {"uz": "Kredit-modul va GPA", "en": "Credits and GPA"},
     "question": {"uz": "GPA qanday formula bilan hisoblanadi? Misol bilan tushuntiring.",
                  "en": "What is the GPA formula? Please explain with an example."}},
    {"key": "ai_faculty", "title": {"uz": "Sun'iy intellekt fakulteti", "en": "AI faculty"},
     "question": {"uz": "Sun'iy intellekt va raqamli texnologiyalar fakultetida qanday yo'nalishlar bor?",
                  "en": "Which programs does the Faculty of Artificial Intelligence and Digital Technologies offer?"}},
    {"key": "history", "title": {"uz": "Tarix", "en": "History"},
     "question": {"uz": "SamDU tarixi haqida qisqacha ma'lumot bering",
                  "en": "Give me a brief history of SamSU"}},
    {"key": "ai_lab", "title": {"uz": "AI laboratoriya", "en": "AI laboratory"},
     "question": {"uz": "SamDU sun'iy intellekt laboratoriyasi qanday loyihalar bilan shug'ullanadi?",
                  "en": "What projects does the SamSU artificial intelligence laboratory work on?"}},
]


def localized_suggestions(lang: str) -> list[dict]:
    lang = lang if lang in ("uz", "en") else "uz"
    return [{"key": s["key"], "title": s["title"][lang], "question": s["question"][lang]} for s in SUGGESTIONS]


def request_lang(body: dict | None = None) -> str | None:
    """Mijoz tanlagan til: JSON dagi "lang" yoki ?lang= ("uz" | "en")."""
    lang = (body or {}).get("lang") or request.args.get("lang")
    return lang if lang in ("uz", "en") else None



def error(code: str, message: str, status: int, **extra):
    body = {"status": "error", "code": code, "message": message}
    resp = jsonify(body)
    resp.status_code = status
    for k, v in extra.items():
        resp.headers[k] = str(v)
    return resp


def rate_limited(bucket: str, rule: tuple[int, int]):
    ok, retry_after = limiter.hit(f"{bucket}:{request.remote_addr}", *rule)
    if ok:
        return None
    return error("rate_limited", f"So'rovlar soni oshib ketdi. {retry_after} soniyadan so'ng qayta urinib ko'ring.",
                 429, **{"Retry-After": retry_after})


def json_body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@api.get("/health")
def health():
    kb = get_kb()
    return jsonify({"status": "ok", "knowledge_chunks": kb.size, "uptime_seconds": int(time.time() - STARTED_AT)})


@api.get("/suggestions")
def suggestions():
    return jsonify({"status": "success", "suggestions": localized_suggestions(request_lang() or "uz")})


@api.post("/chat")
def chat():
    if (limited := rate_limited("chat", RATE_LIMIT_CHAT)) is not None:
        return limited
    body = json_body()
    try:
        result = rag.answer(body.get("question", ""), body.get("history"), request_lang(body))
    except rag.ChatError as e:
        return error(e.code, e.message, e.http_status)
    return jsonify({"status": "success", **result})


@api.post("/chat/stream")
def chat_stream():
    if (limited := rate_limited("chat", RATE_LIMIT_CHAT)) is not None:
        return limited
    body = json_body()
    try:
        events = rag.answer_stream(body.get("question", ""), body.get("history"), request_lang(body))
    except rag.ChatError as e:
        return error(e.code, e.message, e.http_status)

    def sse():
        for ev in events:
            kind = ev.pop("type")
            yield f"event: {kind}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.post("/search")
def search():
    if (limited := rate_limited("search", RATE_LIMIT_SEARCH)) is not None:
        return limited
    body = json_body()
    try:
        result = rag.search(body.get("query", ""), body.get("top_k", 5))
    except rag.ChatError as e:
        return error(e.code, e.message, e.http_status)
    except (TypeError, ValueError):
        return error("invalid_request", "top_k butun son bo'lishi kerak.", 400)
    return jsonify({"status": "success", **result})


@api.post("/live/token")
def live_token():
    if (limited := rate_limited("live", RATE_LIMIT_LIVE_TOKEN)) is not None:
        return limited
    try:
        return jsonify({"status": "success", **create_live_token(request_lang(json_body()) or "uz")})
    except Exception as e:
        log.exception("Ovozli seans tokenini yaratib bo'lmadi: %s", e)
        msg = ("Voice assistant is temporarily unavailable. Please try again later." if request_lang(json_body()) == "en"
               else "Ovozli yordamchi vaqtincha mavjud emas. Iltimos, keyinroq urinib ko'ring.")
        return error("voice_unavailable", msg, 503)
