import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default):
    """Muhit o'zgaruvchisini default qiymat turiga moslab o'qiydi."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    raw = raw.strip()
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return raw


# API kalit (faqat serverda saqlanadi, mijozga hech qachon yuborilmaydi)
GOOGLE_API_KEY = _env("GOOGLE_API_KEY", "")

# Modellar
CHAT_MODEL = _env("CHAT_MODEL", "gemini-3.5-flash")
CHAT_THINKING_LEVEL = _env("CHAT_THINKING_LEVEL", "minimal")
LIVE_MODEL = _env("LIVE_MODEL", "gemini-3.8-live")
LIVE_VOICE = _env("LIVE_VOICE", "Kore")
LIVE_LANGUAGE = _env("LIVE_LANGUAGE", "uz")   # ovozli javob tili (ISO 639-1)
EMBED_MODEL = _env("EMBED_MODEL", "gemini-embedding-2")
EMBED_DIM = _env("EMBED_DIM", 768)

# Ma'lumotlar va vektor baza
DOCS_DIR = BASE_DIR / "new-documents"
CHROMA_PATH = str(BASE_DIR / "chroma_db")
COLLECTION_NAME = "samdu_kb"

# Ingestion (matnni bo'laklash)
CHUNK_SIZE_CHARS = 1000
CHUNK_OVERLAP_CHARS = 150
EMBED_BATCH_SIZE = 100

# Qidiruv (gibrid: vektor + kalit so'z)
VECTOR_CANDIDATES = 20
KEYWORD_CANDIDATES = 20
TOP_K = 8
MAX_CHUNKS_PER_SOURCE = 3      # bitta katta hujjat butun kontekstni egallab olmasligi uchun
MAX_CONTEXT_CHARS = 10000
MAX_VECTOR_DISTANCE = _env("MAX_VECTOR_DISTANCE", 0.36)  # cosine masofa (kichik = yaqinroq)

# Generatsiya
GEN_TEMPERATURE = 0.2
GEN_MAX_OUTPUT_TOKENS = 1500
HISTORY_TURNS = 6            # mijoz yuborgan suhbat tarixidan oxirgi nechta xabar olinadi
MAX_QUESTION_CHARS = 1000

# Keshlash
ANSWER_CACHE_TTL = _env("ANSWER_CACHE_TTL", 1800)
ANSWER_CACHE_SIZE = 1000
EMBED_CACHE_TTL = 6 * 3600
EMBED_CACHE_SIZE = 3000

# Yuklamani cheklash
MAX_CONCURRENT_GENERATIONS = _env("MAX_CONCURRENT_GENERATIONS", 16)
GENERATION_QUEUE_TIMEOUT = 15   # soniya: navbat to'la bo'lsa shuncha kutiladi
RATE_LIMIT_CHAT = (_env("RATE_LIMIT_CHAT", 20), 60)        # (so'rov, soniya) har bir IP uchun
RATE_LIMIT_SEARCH = (_env("RATE_LIMIT_SEARCH", 60), 60)
RATE_LIMIT_LIVE_TOKEN = (_env("RATE_LIMIT_LIVE_TOKEN", 6), 60)

# Ovozli seans (vaqtinchalik token)
LIVE_TOKEN_TTL_MINUTES = 30        # seans davomida token amal qilish muddati
LIVE_SESSION_START_MINUTES = 2     # token olingach seansni boshlash uchun vaqt

# Server
TRUST_PROXY = _env("TRUST_PROXY", False)   # nginx ortida ishlasa true qiling
CORS_ORIGINS = _env("CORS_ORIGINS", "*")
ENABLE_API_DOCS = _env("ENABLE_API_DOCS", True)
PORT = _env("PORT", 8800)

# Tuzilgan (qo'lda tayyorlangan) hujjatlarga qidiruvda ozgina ustunlik beriladi;
# saytdan avtomatik yig'ilgan katta fayllar standart 1.0 vaznda qoladi.
SOURCE_WEIGHTS = {
    "samdu_universitet_RAG.txt": 1.3,
    "samdu_pasport.txt": 1.3,
    "samdu_rag_chatbot_kb.txt": 1.3,
    "samdu_rektor_RAG.txt": 1.3,
    "samdu_tarix_RAG.txt": 1.3,
    "deepseek_text_20260506_d73d3f.txt": 1.2,
    "samdu_baholash_rag_chatbot.txt": 1.2,
    "samdu_ichki_tartib_rag_chatbot.txt": 1.2,
    "samdu_odob_axloq_rag_chatbot.txt": 1.2,
    "kredit_modul_tizimi_RAG.txt": 1.2,
    "oliy_talim_qabul_nizom_RAG.txt": 1.2,
    "tyutorlik_rag_chatbot.txt": 1.2,
}

# Manbalarning foydalanuvchiga ko'rinadigan nomlari (fayl nomlari hech qachon ko'rsatilmaydi)
SOURCE_TITLES = {
    "deepseek_text_20260506_d73d3f.txt": "SamDU Ustavi",
    "Ichki_Tartib_Qoida.txt": "SamDU ichki tartib-qoidalari",
    "samdu_ichki_tartib_rag_chatbot.txt": "SamDU ichki tartib-qoidalari",
    "Odob_axloq.txt": "SamDU odob-axloq kodeksi",
    "samdu_odob_axloq_rag_chatbot.txt": "SamDU odob-axloq kodeksi",
    "itkt_samdu_rag_dataset.txt": "Sun'iy intellekt va raqamli texnologiyalar fakulteti",
    "kredit_modul_tizimi_RAG.txt": "Kredit-modul tizimi (VM qarori, 824-son)",
    "oliy_talim_qabul_nizom_RAG.txt": "Oliy ta'limga qabul nizomi (VM qarori, 578-son)",
    "rag_data_samdu_clean.txt": "samdu.uz rasmiy sayti",
    "rag_data_samdu_clean2v.txt": "samdu.uz rasmiy sayti",
    "samdu_baholash_rag_chatbot.txt": "SamDU baholash mezoni va tartibi",
    "samdu_pasport.txt": "SamDU pasporti",
    "samdu_rag_chatbot_kb.txt": "SamDU pasporti",
    "samdu_rektor_RAG.txt": "SamDU rektori",
    "samdu_tarix_RAG.txt": "SamDU tarixi",
    "samdu_universitet_RAG.txt": "SamDU haqida umumiy ma'lumot",
    "tyutorlik_rag_chatbot.txt": "Tyutorlik faoliyati (VM qarori, 656-son)",
    "web_ai_lab_sampc_uz.txt": "SamDU Sun'iy intellekt laboratoriyasi",
    "web_www_samdu_uz.txt": "samdu.uz rasmiy sayti",
}
