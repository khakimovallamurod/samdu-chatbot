"""Bilim bazasidan gibrid qidiruv: vektor (ChromaDB) + kalit so'z (BM25), RRF bilan birlashtiriladi.

Kalit so'z indeksi xotirada saqlanadi (~1 MB matn), shuning uchun ism, raqam va
atamalar (masalan, "Nazarov", "GPA", "824-son") bo'yicha qidiruv bir zumda va aniq ishlaydi.
Savol vektorlari keshlanadi — takroriy savollar API ga murojaat qilmaydi.
"""
import logging
import math
import threading
from collections import Counter, defaultdict

import chromadb
from google.genai import types

from config import (
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBED_CACHE_SIZE,
    EMBED_CACHE_TTL,
    EMBED_DIM,
    EMBED_MODEL,
    KEYWORD_CANDIDATES,
    MAX_CHUNKS_PER_SOURCE,
    MAX_CONTEXT_CHARS,
    MAX_VECTOR_DISTANCE,
    SOURCE_TITLES,
    SOURCE_WEIGHTS,
    TOP_K,
    VECTOR_CANDIDATES,
)
from utils import TTLCache, get_client, normalize_query, tokenize

log = logging.getLogger(__name__)

RRF_K = 60


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.doc_len: list[int] = []
        for idx, doc in enumerate(docs):
            tokens = tokenize(doc)
            self.doc_len.append(len(tokens))
            for tok, tf in Counter(tokens).items():
                self.postings[tok].append((idx, tf))
        n = len(docs) or 1
        self.avgdl = (sum(self.doc_len) / n) or 1
        self.idf = {t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def search(self, query: str, limit: int) -> list[tuple[int, float]]:
        scores: dict[int, float] = defaultdict(float)
        for tok in set(tokenize(query)):
            idf = self.idf.get(tok)
            if idf is None:
                continue
            for idx, tf in self.postings[tok]:
                norm = self.k1 * (1 - self.b + self.b * self.doc_len[idx] / self.avgdl)
                scores[idx] += idf * tf * (self.k1 + 1) / (tf + norm)
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]


class KnowledgeBase:
    def __init__(self):
        self._lock = threading.Lock()
        self._embed_cache = TTLCache(EMBED_CACHE_SIZE, EMBED_CACHE_TTL)
        self.load()

    def load(self):
        """Kolleksiya va kalit so'z indeksini (qayta) yuklaydi."""
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = client.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
        data = collection.get(include=["documents", "metadatas"])
        ids, docs, metas = data["ids"], data["documents"], data["metadatas"]
        bm25 = BM25(docs)
        with self._lock:
            self.collection = collection
            self.ids, self.docs, self.metas = ids, docs, metas
            self.id_to_idx = {doc_id: i for i, doc_id in enumerate(ids)}
            self.bm25 = bm25
        self._embed_cache.clear()
        log.info("Bilim bazasi yuklandi: %d bo'lak", len(ids))

    @property
    def size(self) -> int:
        return len(self.ids)

    def embed_query(self, text: str) -> list[float]:
        key = normalize_query(text)
        cached = self._embed_cache.get(key)
        if cached is not None:
            return cached
        resp = get_client().models.embed_content(
            model=EMBED_MODEL,
            contents=text,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY", output_dimensionality=EMBED_DIM),
        )
        vector = resp.embeddings[0].values
        self._embed_cache.set(key, vector)
        return vector

    def search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        """Eng mos bo'laklarni qaytaradi: [{text, title, section, url, score}]."""
        if not self.ids:
            return []

        fused: dict[int, float] = defaultdict(float)
        vector_ok = False

        # 1) Vektor qidiruv (semantik o'xshashlik, boshqa tillardagi savollar uchun ham)
        try:
            res = self.collection.query(
                query_embeddings=[self.embed_query(query)],
                n_results=min(VECTOR_CANDIDATES, self.size),
                include=["distances"],
            )
            for rank, (doc_id, dist) in enumerate(zip(res["ids"][0], res["distances"][0])):
                if dist <= MAX_VECTOR_DISTANCE and doc_id in self.id_to_idx:
                    fused[self.id_to_idx[doc_id]] += 1 / (RRF_K + rank)
                    vector_ok = True
        except Exception as e:
            # Vektor xizmati ishlamasa ham kalit so'z qidiruvi bilan javob beramiz
            log.warning("Vektor qidiruvda xato: %s", e)

        # 2) Kalit so'z qidiruvi (BM25)
        keyword_hits = self.bm25.search(query, KEYWORD_CANDIDATES)
        top_bm25 = keyword_hits[0][1] if keyword_hits else 0
        for rank, (idx, score) in enumerate(keyword_hits):
            # Vektor hech narsa topmagan bo'lsa, zaif kalit so'z mosliklarini e'tiborsiz qoldiramiz
            if not vector_ok and score < max(4.0, top_bm25 * 0.5):
                continue
            fused[idx] += 1 / (RRF_K + rank)

        for idx in fused:
            fused[idx] *= SOURCE_WEIGHTS.get(self.metas[idx].get("source", ""), 1.0)

        # Xilma-xillik: bitta manbadan ko'pi bilan MAX_CHUNKS_PER_SOURCE ta bo'lak
        ranked, per_source = [], defaultdict(int)
        for idx, score in sorted(fused.items(), key=lambda x: x[1], reverse=True):
            title = self.metas[idx].get("title", "")
            if per_source[title] >= MAX_CHUNKS_PER_SOURCE:
                continue
            per_source[title] += 1
            ranked.append((idx, score))
            if len(ranked) >= top_k:
                break
        return [
            {
                "text": self.docs[idx],
                # Joriy nom config dan olinadi — nom o'zgarsa bazani qayta qurish shart emas
                "title": SOURCE_TITLES.get(self.metas[idx].get("source", ""), self.metas[idx].get("title", "")),
                "section": self.metas[idx].get("section", ""),
                "url": self.metas[idx].get("url", ""),
                "score": round(score, 5),
            }
            for idx, score in ranked
        ]

    @staticmethod
    def build_context(chunks: list[dict], max_chars: int = MAX_CONTEXT_CHARS) -> str:
        blocks, total = [], 0
        for i, c in enumerate(chunks, 1):
            block = f"[{i}] {c['text'].strip()}"
            if total + len(block) > max_chars:
                break
            blocks.append(block)
            total += len(block)
        return "\n\n".join(blocks)

    @staticmethod
    def sources(chunks: list[dict]) -> list[dict]:
        """Foydalanuvchiga ko'rsatiladigan manbalar (fayl nomlarisiz, takrorlarsiz)."""
        seen, out = set(), []
        for c in chunks[:4]:  # faqat eng mos bo'laklar manbalari
            if c["title"] and c["title"] not in seen:
                seen.add(c["title"])
                out.append({"title": c["title"], "url": c["url"] or None})
        return out[:3]


_kb = None
_kb_lock = threading.Lock()


def get_kb() -> KnowledgeBase:
    global _kb
    if _kb is None:
        with _kb_lock:
            if _kb is None:
                _kb = KnowledgeBase()
    return _kb
