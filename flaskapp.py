"""SamDU AI yordamchi — Flask ilova.

Ishga tushirish:
    Ishlab chiqish:  python flaskapp.py
    Production:      gunicorn -w 2 -k gthread --threads 16 --timeout 120 -b 0.0.0.0:8800 flaskapp:app
"""
import logging
import threading

from flask import Flask, abort, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

import rag
from api import SUGGESTIONS, api, rate_limited
from api_docs import OPENAPI_SPEC
from config import CORS_ORIGINS, ENABLE_API_DOCS, PORT, RATE_LIMIT_CHAT, TRUST_PROXY
from knowledge import get_kb

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = Flask(__name__)
app.json.ensure_ascii = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600  # statik fayllar brauzerda keshlanadi
if TRUST_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.register_blueprint(api)
get_kb()  # bilim bazasini birinchi so'rovdan oldin xotiraga yuklaymiz


def _warmup():
    """API ulanishini oldindan ochib qo'yamiz — birinchi foydalanuvchi kutib qolmasin."""
    try:
        get_kb().embed_query("SamDU")
    except Exception as e:
        logging.warning("Warm-up muvaffaqiyatsiz: %s", e)


threading.Thread(target=_warmup, daemon=True).start()


@app.after_request
def add_headers(resp):
    if request.path.startswith("/api/"):
        resp.headers["Access-Control-Allow-Origin"] = CORS_ORIGINS
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Max-Age"] = "86400"
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    return resp


@app.before_request
def cors_preflight():
    if request.method == "OPTIONS" and request.path.startswith("/api/"):
        return app.make_default_options_response()


@app.errorhandler(HTTPException)
def http_error(e: HTTPException):
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "code": e.name.lower().replace(" ", "_"), "message": e.description}), e.code
    return e


@app.errorhandler(Exception)
def unhandled_error(e: Exception):
    logging.exception("Kutilmagan xato: %s", e)
    return jsonify({"status": "error", "code": "internal_error",
                    "message": "Kechirasiz, vaqtinchalik nosozlik yuz berdi."}), 500


_ICON = ('<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">'
         '<path stroke-linecap="round" stroke-linejoin="round" d="{}"/></svg>')
_ICON_PATHS = {
    "Qabul": "M4.26 10.147a60.438 60.438 0 0 0-.491 6.347A48.62 48.62 0 0 1 12 20.904a48.62 48.62 0 0 1 8.232-4.41 60.46 60.46 0 0 0-.491-6.347m-15.482 0a50.636 50.636 0 0 0-2.658-.813A59.906 59.906 0 0 1 12 3.493a59.903 59.903 0 0 1 10.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.717 50.717 0 0 1 12 13.489a50.702 50.702 0 0 1 7.74-3.342",
    "Fakultetlar": "M12 21v-8.25M15.75 21v-8.25M8.25 21v-8.25M3 9l9-6 9 6m-1.5 12V10.332A48.36 48.36 0 0 0 12 9.75c-2.551 0-5.056.2-7.5.582V21M3 21h18M12 6.75h.008v.008H12V6.75Z",
    "Rektor": "M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z",
    "Baholash": "M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z",
    "Kredit-modul": "M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25",
    "Sun'iy intellekt fakulteti": "M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 0 0 2.25-2.25V6.75a2.25 2.25 0 0 0-2.25-2.25H6.75A2.25 2.25 0 0 0 4.5 6.75v10.5a2.25 2.25 0 0 0 2.25 2.25Zm.75-12h9v9h-9v-9Z",
    "Tarix": "M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
    "AI laboratoriya": "M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23-.693L5 14.5m14.8.8 1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5",
}
WEB_SUGGESTIONS = [{**s, "icon": _ICON.format(_ICON_PATHS.get(s["title"], _ICON_PATHS["Tarix"]))} for s in SUGGESTIONS]


@app.get("/")
def home():
    return render_template("index.html", suggestions=WEB_SUGGESTIONS)


@app.get("/api/openapi.json")
def openapi_json():
    if not ENABLE_API_DOCS:
        abort(404)
    return jsonify(OPENAPI_SPEC)


@app.get("/api/docs")
def api_docs():
    if not ENABLE_API_DOCS:
        abort(404)
    return render_template("api_docs.html")


@app.post("/ask")
def ask_legacy():
    """Eski mijozlar uchun moslik: {"question": "..."} → {"status", "answer", "sources"}."""
    if (limited := rate_limited("chat", RATE_LIMIT_CHAT)) is not None:
        return limited
    payload = request.get_json(silent=True) or {}
    try:
        result = rag.answer(payload.get("question", ""))
    except rag.ChatError as e:
        return jsonify({"status": "error", "answer": e.message}), e.http_status
    return jsonify({"status": "success", "answer": result["answer"], "sources": result["sources"]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
