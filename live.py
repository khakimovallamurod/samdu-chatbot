"""Ovozli (real vaqt) suhbat uchun bir martalik vaqtinchalik token yaratish.

Arxitektura (server yuklamasi minimal):
  1. Mijoz (brauzer yoki mobil ilova) POST /api/v1/live/token chaqiradi.
  2. Server bir martalik, qisqa muddatli token qaytaradi. Asosiy kalit serverdan chiqmaydi.
     Tokenga model, ovoz, tizim ko'rsatmasi va funksiyalar qulflangan — mijoz ularni o'zgartira olmaydi.
  3. Mijoz ovozli WebSocket seansiga to'g'ridan-to'g'ri ulanadi: audio oqimi serverimiz orqali o'tmaydi.
  4. Model SamDU haqida ma'lumot kerak bo'lsa `search_samdu` funksiyasini chaqiradi; mijoz
     POST /api/v1/search orqali bilim bazasidan matn olib, natijani seansga qaytaradi.
"""
import datetime as dt

from google import genai
from google.genai import types

from config import (
    GOOGLE_API_KEY,
    LIVE_LANGUAGE,
    LIVE_MODEL,
    LIVE_SESSION_START_MINUTES,
    LIVE_TOKEN_TTL_MINUTES,
    LIVE_VOICE,
)
from prompts import VOICE_SYSTEM_PROMPT

LIVE_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContentConstrained"
)

SEARCH_TOOL = {
    "name": "search_samdu",
    "description": (
        "Samarqand davlat universiteti (SamDU) rasmiy ma'lumotlar bazasidan qidiradi: rahbariyat, xodimlar, "
        "fakultetlar, kafedralar, qabul, baholash, kredit-modul tizimi, ichki tartib, odob-axloq, tyutorlik, "
        "tarix, Sun'iy intellekt laboratoriyasi. SamDU haqidagi har qanday aniq savolda chaqiring."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Qidiruv so'rovi o'zbek tilida (lotin yozuvida), foydalanuvchi savolining aniq mazmuni.",
            }
        },
        "required": ["query"],
    },
}

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=GOOGLE_API_KEY, http_options={"api_version": "v1alpha"})
    return _client


def _live_config() -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=VOICE_SYSTEM_PROMPT,
        temperature=0.3,  # past harorat — javob o'rtasida boshqa tilga o'tib ketmaslik uchun
        # Javob nutqi o'zbek tilida sintez qilinadi
        speech_config=types.SpeechConfig(
            language_code=LIVE_LANGUAGE,
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=LIVE_VOICE)),
        ),
        # Foydalanuvchi nutqi o'zbekcha (yoki ruscha) deb taniladi — shovqin boshqa til so'ziga aylanib ketmasligi uchun
        input_audio_transcription=types.AudioTranscriptionConfig(language_codes=["uz-UZ", "ru-RU"]),
        # Nutqni aniqlash: fon shovqiniga kamroq sezgir, gap tugashini biroz uzoqroq kutadi
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                prefix_padding_ms=300,
                silence_duration_ms=800,
            )
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(language_codes=["uz-UZ"]),
        tools=[types.Tool(function_declarations=[SEARCH_TOOL])],
        context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
    )


def create_live_token() -> dict:
    now = dt.datetime.now(tz=dt.timezone.utc)
    expires = now + dt.timedelta(minutes=LIVE_TOKEN_TTL_MINUTES)
    start_deadline = now + dt.timedelta(minutes=LIVE_SESSION_START_MINUTES)
    token = _get_client().auth_tokens.create(
        config=types.CreateAuthTokenConfig(
            uses=1,
            expire_time=expires,
            new_session_expire_time=start_deadline,
            live_connect_constraints=types.LiveConnectConstraints(model=LIVE_MODEL, config=_live_config()),
            http_options={"api_version": "v1alpha"},
        )
    )
    return {
        "token": token.name,
        "websocket_url": f"{LIVE_WS_URL}?access_token={token.name}",
        "expires_at": expires.isoformat(),
        "session_start_deadline": start_deadline.isoformat(),
        "setup": {"setup": {"model": f"models/{LIVE_MODEL}"}},
        "audio": {
            "input": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1, "mime_type": "audio/pcm;rate=16000"},
            "output": {"encoding": "pcm_s16le", "sample_rate": 24000, "channels": 1},
        },
        "tool": {"name": SEARCH_TOOL["name"], "endpoint": "/api/v1/search"},
    }
