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
    {"title": "Qabul", "question": "SamDUga qabul qilish tartibi qanday? Qanday hujjatlar kerak?"},
    {"title": "Fakultetlar", "question": "SamDUda qanday fakultet va institutlar bor?"},
    {"title": "Rektor", "question": "SamDU rektori kim va qabul vaqti qachon?"},
    {"title": "Baholash", "question": "Talabalar bilimi qanday baholanadi?"},
    {"title": "Kredit-modul", "question": "Kredit-modul tizimi va GPA nima?"},
    {"title": "Sun'iy intellekt fakulteti", "question": "Sun'iy intellekt va raqamli texnologiyalar fakultetida qanday yo'nalishlar bor?"},
    {"title": "Tarix", "question": "SamDU tarixi haqida qisqacha ma'lumot bering"},
    {"title": "AI laboratoriya", "question": "SamDU Sun'iy intellekt laboratoriyasi qanday loyihalar bilan shug'ullanadi?"},
]


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
    return jsonify({"status": "success", "suggestions": SUGGESTIONS})


@api.post("/chat")
def chat():
    if (limited := rate_limited("chat", RATE_LIMIT_CHAT)) is not None:
        return limited
    body = json_body()
    try:
        result = rag.answer(body.get("question", ""), body.get("history"))
    except rag.ChatError as e:
        return error(e.code, e.message, e.http_status)
    return jsonify({"status": "success", **result})


@api.post("/chat/stream")
def chat_stream():
    if (limited := rate_limited("chat", RATE_LIMIT_CHAT)) is not None:
        return limited
    body = json_body()
    try:
        events = rag.answer_stream(body.get("question", ""), body.get("history"))
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
        return jsonify({"status": "success", **create_live_token()})
    except Exception as e:
        log.exception("Ovozli seans tokenini yaratib bo'lmadi: %s", e)
        return error("voice_unavailable", "Ovozli yordamchi vaqtincha mavjud emas. Iltimos, keyinroq urinib ko'ring.", 503)
