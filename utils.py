"""Umumiy yordamchi vositalar: kesh, rate limiter, matn normalizatsiyasi."""
import re
import threading
import time
from collections import OrderedDict, deque

from google import genai

from config import GOOGLE_API_KEY

_client = None
_client_lock = threading.Lock()


def get_client() -> genai.Client:
    """Butun jarayon uchun yagona API mijozi (ulanishlar qayta ishlatiladi)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = genai.Client(api_key=GOOGLE_API_KEY)
    return _client


class TTLCache:
    """Thread-safe LRU + TTL kesh."""

    def __init__(self, maxsize: int, ttl: int):
        self.maxsize = maxsize
        self.ttl = ttl
        self._data: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, expires = item
            if expires < time.monotonic():
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key, value):
        with self._lock:
            self._data[key] = (value, time.monotonic() + self.ttl)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self):
        with self._lock:
            self._data.clear()


class RateLimiter:
    """Har bir kalit (IP + endpoint) uchun sirpanuvchi oyna asosidagi cheklov."""

    def __init__(self):
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """(ruxsat_berildimi, necha soniyadan keyin qayta urinish mumkin)."""
        now = time.monotonic()
        with self._lock:
            if now - self._last_cleanup > 300:
                self._cleanup(now)
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(q[0] + window - now) + 1)
            q.append(now)
            return True, 0

    def _cleanup(self, now: float):
        self._last_cleanup = now
        for key in [k for k, q in self._hits.items() if not q or q[-1] < now - 3600]:
            del self._hits[key]


# --- Matn normalizatsiyasi -------------------------------------------------

_APOSTROPHES = re.compile(r"[‘’ʼʻ`´']")

_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
}


def to_latin(text: str) -> str:
    """O'zbek kirill yozuvini lotinga o'giradi (kalit so'z qidiruvi uchun)."""
    return "".join(_CYR_TO_LAT.get(ch, ch) for ch in text.lower())


def normalize_query(text: str) -> str:
    """Kesh kaliti uchun savolni bir xil ko'rinishga keltiradi."""
    text = _APOSTROPHES.sub("'", text.lower())
    text = re.sub(r"[^\w\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_TOKEN_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = {
    "va", "bilan", "uchun", "ham", "bu", "shu", "u", "bir", "esa", "yoki", "lekin",
    "haqida", "qanday", "qaysi", "nima", "kim", "qachon", "qayerda", "nechta", "necha",
    "bo'yicha", "ma'lumot", "ber", "bering", "aytib", "ayting", "menga", "iltimos",
    "ro'yxati", "ro'yxat", "ro'yxatini", "kerak", "mumkin", "bormi", "qanaqa",
    "the", "of", "and", "is", "what", "who", "how", "in", "a", "an",
}


def tokenize(text: str) -> list[str]:
    """BM25 uchun tokenlar: lotinlashtirish, apostroflarni birxillashtirish, oddiy stemming.

    O'zbek tili agglyutinativ ("rektor", "rektori", "rektorining"), shuning uchun
    uzun so'zlarning faqat dastlabki 6 harfi olinadi.
    """
    text = _APOSTROPHES.sub("'", to_latin(text))
    tokens = []
    for tok in _TOKEN_RE.findall(text):
        tok = tok.strip("'")
        if len(tok) < 2 or tok in _STOPWORDS:
            continue
        tokens.append(tok[:6])
    return tokens
