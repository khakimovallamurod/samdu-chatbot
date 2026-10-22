"""API ni begona skript va botlardan himoyalash.

Veb sahifa ochilganda brauzerga imzolangan HttpOnly cookie beriladi (JS uni o'qiy olmaydi,
boshqa saytlar yubora olmaydi — SameSite=Strict). API faqat shu cookie yoki mobil ilova
kaliti (X-API-Key) bilan ishlaydi; curl/skript bilan to'g'ridan-to'g'ri chaqirib bo'lmaydi.
Limitlar IP va sessiya bo'yicha alohida hisoblanadi.
"""
import hashlib
import hmac
import secrets

from flask import request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import CLIENT_API_KEYS, GOOGLE_API_KEY, SECRET_KEY, SESSION_TTL

COOKIE_NAME = "samdu_sid"

# SECRET_KEY berilmasa API kalitdan hosil qilinadi — barcha gunicorn workerlarida bir xil bo'lishi uchun
_secret = SECRET_KEY or hashlib.sha256(b"samdu-session:" + GOOGLE_API_KEY.encode()).hexdigest()
_serializer = URLSafeTimedSerializer(_secret, salt="samdu-web-session")
_api_keys = [k.strip() for k in CLIENT_API_KEYS.split(",") if k.strip()]


def issue_session(resp):
    """Sahifa javobiga yangi sessiya cookie sini qo'shadi (mavjud bo'lsa ID saqlanadi)."""
    sid = session_id() or secrets.token_urlsafe(16)
    resp.set_cookie(COOKIE_NAME, _serializer.dumps(sid), max_age=SESSION_TTL, httponly=True,
                    secure=request.is_secure, samesite="Strict", path="/")
    return resp


def session_id() -> str | None:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        return _serializer.loads(raw, max_age=SESSION_TTL)
    except (BadSignature, SignatureExpired):
        return None


def client_identity() -> str | None:
    """So'rov kimdan: "web:<sid>" | "app:<kalit xeshi>" | None (ruxsatsiz)."""
    key = request.headers.get("X-API-Key", "")
    if key:
        for k in _api_keys:
            if hmac.compare_digest(key, k):
                return "app:" + hashlib.sha256(k.encode()).hexdigest()[:12]
        return None
    sid = session_id()
    return f"web:{sid}" if sid else None
