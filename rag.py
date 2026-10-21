"""Savolga bilim bazasi asosida javob berish (oddiy va oqimli rejimlar).

Server yuklamasini kamaytirish uchun:
  * salomlashish/minnatdorchilik/"kimsan" kabi xabarlarga model chaqirilmasdan javob beriladi;
  * bazada mos ma'lumot topilmasa, model chaqirilmaydi;
  * bir xil savollarga javob keshdan qaytadi;
  * bir vaqtning o'zida ishlaydigan generatsiyalar soni semafor bilan cheklangan.
"""
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator

from google.genai import types

from config import (
    ANSWER_CACHE_SIZE,
    ANSWER_CACHE_TTL,
    CHAT_MODEL,
    CHAT_THINKING_LEVEL,
    CHAT_THINKING_LEVEL_NUMERIC,
    GEN_MAX_OUTPUT_TOKENS,
    GEN_TEMPERATURE,
    GENERATION_QUEUE_TIMEOUT,
    HISTORY_TURNS,
    MAX_CONCURRENT_GENERATIONS,
    MAX_QUESTION_CHARS,
)
from knowledge import KnowledgeBase, get_kb
from prompts import ANSWER_LANGUAGE, LAB_NAME_EN, LAB_NAME_UZ, SYSTEM_PROMPT
from utils import TTLCache, get_client, normalize_query

log = logging.getLogger(__name__)

_answer_cache = TTLCache(ANSWER_CACHE_SIZE, ANSWER_CACHE_TTL)
_generation_slots = threading.BoundedSemaphore(MAX_CONCURRENT_GENERATIONS)


class ChatError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 500):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


# --- Til va tezkor javoblar ------------------------------------------------

_EN_WORDS = set("""
what who whom whose where when why how which is are was were be been do does did can could should would will
the a an of to in on at for from with about and or not my your our their his her its this that these those there
please tell me give show explain list hello hi hey thanks thank you university faculty faculties rector student
students admission apply requirements documents fee fees tuition dormitory scholarship grade grading exam score
""".split())
_UZ_MARKERS = re.compile(
    r"(o'|g'|o‘|g‘|ʻ|\b(va|bilan|uchun|haqida|qanday|qaysi|nima|kim|qachon|qayerda|nechta|qancha|bormi|kerak"
    r"|ber|bering|ayt|ayting|menga|iltimos|salom|rahmat|universitet|talaba|talabalar|rektor|qabul)\b"
    r"|\w+(ning|lar|lari|larni|dagi|ga|da|dan|ni|mi|chi)\b)", re.I)


def detect_lang(text: str, hint: str | None = None) -> str:
    """Savol tilini aniqlaydi. Aniq bo'lmasa, UI da tanlangan til (hint) ishlatiladi."""
    if re.search(r"[ўқғҳЎҚҒҲ]", text):
        return "uz_cyrl"
    if re.search(r"[а-яА-ЯёЁ]", text):
        return "ru"
    words = re.findall(r"[a-zA-Z']+", text.lower())
    en_score = sum(1 for w in words if w in _EN_WORDS)
    uz_score = len(_UZ_MARKERS.findall(text))
    if en_score > uz_score:
        return "en"
    if uz_score > en_score:
        return "uz"
    return "en" if hint == "en" else "uz"


# Formula, hisob-kitob va raqamli qiymatlar haqidagi savollar — model chuqurroq "o'ylaydi"
_NUMERIC_RE = re.compile(
    r"\d|formula|hisobla|hisoblan|gpa|ball|foiz|kredit|baho|shkala|necha|qancha|miqdor|to'lov|kontrakt"
    r"|calculat|compute|score|percent|credit|grade|how\s+much|how\s+many|fee|tuition", re.I)


def is_numeric_question(text: str) -> bool:
    return bool(_NUMERIC_RE.search(text))


MESSAGES = {
    "greeting": {
        "uz": "Assalomu alaykum! Men SamDU axborot yordamchisiman. Qabul, fakultetlar, rahbariyat, tartib-qoidalar va universitet hayoti bo'yicha savollaringizga javob beraman.",
        "uz_cyrl": "Ассалому алайкум! Мен СамДУ ахборот ёрдамчисиман. Қабул, факультетлар, раҳбарият ва университет ҳаёти бўйича саволларингизга жавоб бераман.",
        "ru": "Здравствуйте! Я информационный помощник СамГУ. Отвечу на вопросы о поступлении, факультетах, руководстве и правилах университета.",
        "en": "Hello! I'm the Samarkand State University (SamSU) assistant. Ask me about admission, faculties, leadership, rules and student life.",
    },
    "thanks": {
        "uz": "Arzimaydi! Yana savollaringiz bo'lsa, bemalol so'rang.",
        "uz_cyrl": "Арзимайди! Яна саволларингиз бўлса, бемалол сўранг.",
        "ru": "Пожалуйста! Если появятся ещё вопросы — спрашивайте.",
        "en": "You're welcome! Feel free to ask anything else about the university.",
    },
    "bye": {
        "uz": "Xayr! Omad tilayman. SamDU haqida savollar bo'lsa, qaytib keling.",
        "uz_cyrl": "Хайр! Омад тилайман.",
        "ru": "До свидания! Будем рады помочь снова.",
        "en": "Goodbye! Come back any time.",
    },
    "identity": {
        "uz": f"Men Sharof Rashidov nomidagi Samarqand davlat universitetining AI yordamchisiman. Meni {LAB_NAME_UZ} ishlab chiqqan. SamDU haqidagi savollaringizga javob beraman.",
        "uz_cyrl": "Мен Шароф Рашидов номидаги Самарқанд давлат университетининг AI ёрдамчисиман. Мени СамДУ Сунъий интеллект ва рақамли технологиялар лабораторияси ишлаб чиққан.",
        "ru": "Я AI-помощник Самаркандского государственного университета имени Шарофа Рашидова, разработанный Лабораторией искусственного интеллекта и цифровых технологий СамГУ.",
        "en": f"I'm the AI assistant of Sharof Rashidov Samarkand State University, developed by the {LAB_NAME_EN}. Ask me anything about the university.",
    },
    "not_found": {
        "uz": "Kechirasiz, bu savol bo'yicha menda aniq ma'lumot yo'q. Men faqat SamDU bilan bog'liq savollarga javob beraman. Batafsil ma'lumot uchun www.samdu.uz saytiga yoki +998 66 240 38 40 ishonch telefoniga murojaat qiling.",
        "uz_cyrl": "Кечирасиз, бу савол бўйича менда аниқ маълумот йўқ. Мен фақат СамДУ билан боғлиқ саволларга жавоб бераман. Батафсил: www.samdu.uz, +998 66 240 38 40.",
        "ru": "К сожалению, у меня нет точной информации по этому вопросу. Я отвечаю только на вопросы о СамГУ. Подробнее: www.samdu.uz, телефон доверия +998 66 240 38 40.",
        "en": "Sorry, I don't have reliable information on that. I can only answer questions about Samarkand State University. See www.samdu.uz or call +998 66 240 38 40.",
    },
    "error": {
        "uz": "Kechirasiz, vaqtinchalik nosozlik yuz berdi. Iltimos, birozdan so'ng qayta urinib ko'ring.",
        "uz_cyrl": "Кечирасиз, вақтинчалик носозлик юз берди. Илтимос, бироздан сўнг қайта уриниб кўринг.",
        "ru": "Извините, произошла временная ошибка. Пожалуйста, повторите попытку чуть позже.",
        "en": "Sorry, a temporary error occurred. Please try again shortly.",
    },
}

_SMALL_TALK = [
    ("greeting", re.compile(
        r"^(assalomu?\s*alay?kum|salom(\s+alaykum)?|hayrli\s+(kun|tong|kech)|hello|hi|hey|good\s+(morning|afternoon|evening)"
        r"|привет|здравствуй(те)?|добрый\s+(день|вечер)|ассалому\s+алайкум|салом)[\s!.,)]*$", re.I)),
    ("thanks", re.compile(
        r"^(katta\s+)?(rahmat|raxmat|tashakkur|thanks?|thank\s+you|спасибо|благодарю|раҳмат|рахмат)([\s,!.]+\S+){0,3}[\s!.)]*$", re.I)),
    ("bye", re.compile(r"^(xayr|hayr|ko'rishguncha|bye|goodbye|пока|до\s+свидания|хайр)[\s!.]*$", re.I)),
    ("identity", re.compile(
        r"(sen|siz)\s+kim(san|siz)|seni\s+kim|sizni\s+kim|kim\s+(yaratgan|yaratdi|ishlab\s+chiqqan)|qaysi\s+model"
        r"|\b(gemini|chatgpt|gpt|openai|google|api\s*key|api)\b|кто\s+ты|кто\s+вас|какая\s+модель|who\s+are\s+you"
        r"|who\s+(made|created|built|developed)\s+you|(what|which)\s+(model|technology|ai|llm)"
        r"|qanday\s+(texnologiya|model|sun'iy\s+intellekt)|nima\s+asosida\s+ishlaysan|\b(claude|llm|llama|deepseek)\b", re.I)),
]


def small_talk_reply(text: str, hint: str | None = None) -> str | None:
    clean = re.sub(r"[‘’ʼʻ`]", "'", text.strip())
    if len(clean) > 80:
        return None
    for kind, pattern in _SMALL_TALK:
        if pattern.search(clean):
            return MESSAGES[kind][detect_lang(clean, hint)]
    return None


# --- Tayyorlash ------------------------------------------------------------

@dataclass
class Prepared:
    question: str
    lang: str
    instant_answer: str | None = None
    sources: list = field(default_factory=list)
    contents: list = field(default_factory=list)
    cache_key: str | None = None
    cached: bool = False
    numeric: bool = False


def _clean_history(history) -> list[dict]:
    out = []
    if not isinstance(history, list):
        return out
    for item in history[-HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = str(item.get("content") or "").strip()[:1500]
        if role in ("user", "assistant", "model") and text:
            out.append({"role": "user" if role == "user" else "model", "content": text})
    return out


def prepare(question: str, history=None, lang: str | None = None) -> Prepared:
    q = (question or "").strip()
    if not q:
        raise ChatError("empty_question", "Savol bo'sh bo'lmasligi kerak.", 400)
    if len(q) > MAX_QUESTION_CHARS:
        raise ChatError("question_too_long", f"Savol {MAX_QUESTION_CHARS} belgidan oshmasligi kerak.", 400)

    hint = lang if lang in ("uz", "en") else None
    lang = detect_lang(q, hint)
    quick = small_talk_reply(q, hint)
    if quick:
        return Prepared(question=q, lang=lang, instant_answer=quick)

    hist = _clean_history(history)
    cache_key = None if hist else f"{lang}:{normalize_query(q)}"
    if cache_key:
        hit = _answer_cache.get(cache_key)
        if hit:
            return Prepared(question=q, lang=lang, instant_answer=hit["answer"], sources=hit["sources"], cached=True)

    # Qisqa davomiy savollar ("batafsilroq", "telefoni-chi?") uchun oldingi savolni ham qo'shib qidiramiz
    search_query = q
    if hist and len(q.split()) <= 6:
        last_user = next((h["content"] for h in reversed(hist) if h["role"] == "user"), "")
        search_query = f"{last_user[:300]} {q}"

    kb = get_kb()
    chunks = kb.search(search_query)
    if not chunks:
        return Prepared(question=q, lang=lang, instant_answer=MESSAGES["not_found"][lang])

    contents = [types.Content(role=h["role"], parts=[types.Part(text=h["content"])]) for h in hist]
    numeric = is_numeric_question(q)
    contents.append(types.Content(role="user", parts=[types.Part(text=(
        f"MA'LUMOTLAR:\n{KnowledgeBase.build_context(chunks)}\n\n"
        f"JAVOB TILI: {ANSWER_LANGUAGE[lang]}\n"
        + ("ESLATMA: savol formula/raqamli qiymatlarga oid — formulani aynan keltiring, belgilarni izohlang, "
           "raqamlar berilgan bo'lsa bosqichma-bosqich hisoblab aniq natija bering.\n" if numeric else "")
        + f"SAVOL: {q}"
    ))]))
    return Prepared(question=q, lang=lang, sources=KnowledgeBase.sources(chunks), contents=contents,
                    cache_key=cache_key, numeric=numeric)


def _gen_config(numeric: bool = False, level: str | None = None) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.1 if numeric else GEN_TEMPERATURE,
        max_output_tokens=GEN_MAX_OUTPUT_TOKENS,
        thinking_config=types.ThinkingConfig(
            thinking_level=level or (CHAT_THINKING_LEVEL_NUMERIC if numeric else CHAT_THINKING_LEVEL)),
    )


def _is_config_error(e: Exception) -> bool:
    """Model tanlangan thinking darajasini qo'llab-quvvatlamasa — standart daraja bilan qayta urinamiz."""
    msg = str(e).lower()
    return "thinking" in msg or "invalid_argument" in msg


def _acquire_slot():
    if not _generation_slots.acquire(timeout=GENERATION_QUEUE_TIMEOUT):
        raise ChatError("busy", "Server hozir band. Iltimos, bir necha soniyadan so'ng qayta urinib ko'ring.", 503)


def _remember(p: Prepared, answer: str):
    if p.cache_key and answer:
        _answer_cache.set(p.cache_key, {"answer": answer, "sources": p.sources})


# --- Ommaviy funksiyalar ---------------------------------------------------

def answer(question: str, history=None, lang: str | None = None) -> dict:
    """To'liq javobni bir martada qaytaradi."""
    started = time.perf_counter()
    p = prepare(question, history, lang)
    if p.instant_answer is not None:
        text = p.instant_answer
    else:
        _acquire_slot()
        try:
            try:
                resp = get_client().models.generate_content(
                    model=CHAT_MODEL, contents=p.contents, config=_gen_config(p.numeric))
            except Exception as e:
                if not (p.numeric and _is_config_error(e)):
                    raise
                resp = get_client().models.generate_content(
                    model=CHAT_MODEL, contents=p.contents, config=_gen_config(p.numeric, CHAT_THINKING_LEVEL))
            text = (resp.text or "").strip()
        except Exception as e:
            log.exception("Generatsiya xatosi: %s", e)
            raise ChatError("generation_failed", MESSAGES["error"][p.lang], 502)
        finally:
            _generation_slots.release()
        if not text:
            text = MESSAGES["not_found"][p.lang]
        else:
            _remember(p, text)
    return {
        "answer": text,
        "sources": p.sources,
        "cached": p.cached,
        "lang": p.lang,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


def answer_stream(question: str, history=None, lang: str | None = None) -> Iterator[dict]:
    """Javobni bo'laklab qaytaradi: {"type": "delta", "text"} ... {"type": "done", ...}.

    Validatsiya xatolari (ChatError) birinchi next() chaqiruvidan oldin ko'tariladi,
    shuning uchun API ularni oqim boshlanmasdan to'g'ri HTTP status bilan qaytara oladi.
    """
    started = time.perf_counter()
    p = prepare(question, history, lang)

    def generate():
        if p.instant_answer is not None:
            yield {"type": "delta", "text": p.instant_answer}
        else:
            _acquire_slot()
            parts = []
            try:
                try:
                    stream = get_client().models.generate_content_stream(
                        model=CHAT_MODEL, contents=p.contents, config=_gen_config(p.numeric))
                    first = next(stream, None)  # konfiguratsiya xatosi shu yerda chiqadi
                except Exception as e:
                    if not (p.numeric and _is_config_error(e)):
                        raise
                    stream = get_client().models.generate_content_stream(
                        model=CHAT_MODEL, contents=p.contents, config=_gen_config(p.numeric, CHAT_THINKING_LEVEL))
                    first = next(stream, None)
                if first is not None and first.text:
                    parts.append(first.text)
                    yield {"type": "delta", "text": first.text}
                for chunk in stream:
                    if chunk.text:
                        parts.append(chunk.text)
                        yield {"type": "delta", "text": chunk.text}
            except Exception as e:
                log.exception("Oqimli generatsiya xatosi: %s", e)
                yield {"type": "error", "code": "generation_failed", "message": MESSAGES["error"][p.lang]}
                return
            finally:
                _generation_slots.release()
            full = "".join(parts).strip()
            if not full:
                yield {"type": "delta", "text": MESSAGES["not_found"][p.lang]}
            else:
                _remember(p, full)
        yield {
            "type": "done",
            "sources": p.sources,
            "cached": p.cached,
            "lang": p.lang,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    return generate()


def search(query: str, top_k: int = 5) -> dict:
    """Ovozli yordamchi (va boshqa mijozlar) uchun faqat qidiruv — model chaqirilmaydi."""
    q = (query or "").strip()
    if not q:
        raise ChatError("empty_query", "Qidiruv so'rovi bo'sh bo'lmasligi kerak.", 400)
    chunks = get_kb().search(q[:500], top_k=max(1, min(int(top_k), 10)))
    return {
        "context": KnowledgeBase.build_context(chunks, max_chars=6000) if chunks else "",
        "found": bool(chunks),
        "sources": KnowledgeBase.sources(chunks),
    }


if __name__ == "__main__":
    print("SamDU yordamchisi (chiqish: exit)")
    while True:
        try:
            q = input("\nSavol: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if q.lower() in ("exit", "quit", "chiqish"):
            break
        try:
            for ev in answer_stream(q):
                if ev["type"] == "delta":
                    print(ev["text"], end="", flush=True)
                elif ev["type"] == "done":
                    print(f"\n[{ev['latency_ms']} ms] Manbalar: {', '.join(s['title'] for s in ev['sources'])}")
        except ChatError as e:
            print(f"Xato: {e.message}")
