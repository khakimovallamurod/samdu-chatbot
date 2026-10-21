"""new-documents/*.txt fayllaridan vektor bazani (ChromaDB) noldan qayta quradi.

Ishlatish:
    python ingest.py

Eslatma: baza to'liq o'chirib qayta yaratiladi. Ishlab turgan serverni ingestdan
keyin qayta ishga tushiring.
"""
import hashlib
import re
import shutil
import sys
import time
from pathlib import Path

import chromadb
from google.genai import types

from config import (
    CHROMA_PATH,
    CHUNK_OVERLAP_CHARS,
    CHUNK_SIZE_CHARS,
    COLLECTION_NAME,
    DOCS_DIR,
    EMBED_BATCH_SIZE,
    EMBED_DIM,
    EMBED_MODEL,
    SOURCE_TITLES,
)
from utils import get_client

_SEPARATOR_LINE = re.compile(r"^\s*[=\-_*#~]{3,}\s*$")
_MD_HEADING = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$")
_URL_LINE = re.compile(r"^\s*(?:URL|=== MANBA):\s*(https?://\S+?)\s*(?:===)?\s*$", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")


def _clean_line(line: str) -> str:
    line = line.replace(" ", " ").replace("﻿", "")
    return re.sub(r"[ \t]+", " ", line).strip()


def _is_caps_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return 3 <= len(line) <= 90 and len(letters) >= 3 and all(c.isupper() for c in letters)


def _doc_title(fname: str, lines: list[str]) -> str:
    if fname in SOURCE_TITLES:
        return SOURCE_TITLES[fname]
    for line in lines[:25]:
        m = re.match(r"^(?:Nomi|Mavzu)\s*:\s*(.+)$", line)
        if m:
            return m.group(1).strip()[:120]
    for line in lines[:10]:
        m = _MD_HEADING.match(line)
        if m:
            return m.group(1).strip()[:120]
    return Path(fname).stem.replace("_", " ").replace("-", " ").strip().capitalize()


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    """Uzun paragrafni gaplar chegarasida, ustma-ust tushish bilan bo'laklaydi."""
    sentences = [s for s in _SENTENCE_END.split(text) if s]
    pieces, current = [], ""
    for sent in sentences:
        while len(sent) > size:  # gap ham juda uzun bo'lsa so'zlar bo'yicha kesamiz
            cut = sent.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            sentences_part, sent = sent[:cut], sent[cut:].lstrip()
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentences_part)
        if current and len(current) + len(sent) + 1 > size:
            pieces.append(current)
            tail = current[-overlap:]
            tail = tail[tail.find(" ") + 1:] if " " in tail else tail
            current = f"{tail} {sent}"
        else:
            current = f"{current} {sent}".strip()
    if current:
        pieces.append(current)
    return pieces


def chunk_document(fname: str, raw_text: str) -> list[dict]:
    """Hujjatni sarlavhalar (bo'limlar) tuzilishini saqlagan holda bo'laklaydi.

    Har bir bo'lak boshiga "Hujjat nomi | Bo'lim" sarlavhasi qo'shiladi — bu ham
    vektor, ham kalit so'z qidiruvi aniqligini sezilarli oshiradi.
    """
    lines = [_clean_line(l) for l in raw_text.splitlines()]
    title = _doc_title(fname, [l for l in lines if l])
    doc_url = ""
    section = ""
    chunks: list[dict] = []
    buffer: list[str] = []

    def flush():
        nonlocal buffer
        body = "\n".join(buffer).strip()
        buffer = []
        if len(body) < 40:
            return
        header = f"{title} | {section}" if section and section.lower() != title.lower() else title
        for piece in ([body] if len(body) <= CHUNK_SIZE_CHARS else _split_long(body, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS)):
            chunks.append({"text": f"{header}\n{piece}", "section": section, "url": doc_url})

    for line in lines:
        if not line or _SEPARATOR_LINE.match(line):
            continue
        url_match = _URL_LINE.match(line)
        if url_match:
            flush()
            doc_url = url_match.group(1)
            continue
        heading = _MD_HEADING.match(line)
        if heading or _is_caps_heading(line):
            flush()
            section = (heading.group(1) if heading else line).strip("*:= ")[:120]
            continue

        # Saytdan yig'ilgan sahifalar: bitta qator = bitta sahifa, boshida "Sarlavha . matn"
        if len(line) > 300 and 0 < line.find(" . ") < 120:
            flush()
            page_title, _, rest = line.partition(" . ")
            prev_section, section = section, page_title.strip()[:120]
            buffer = [rest]
            flush()
            section = prev_section
            continue

        if buffer and sum(len(b) + 1 for b in buffer) + len(line) > CHUNK_SIZE_CHARS:
            flush()
        buffer.append(line)
    flush()

    for c in chunks:
        c["title"] = title
        c["source"] = fname
    return chunks


def embed_documents(texts: list[str]) -> list[list[float]]:
    client = get_client()
    for attempt in range(5):
        try:
            resp = client.models.embed_content(
                model=EMBED_MODEL,
                # Har bir matn alohida Content bo'lishi shart, aks holda bitta vektor qaytadi
                contents=[types.Content(parts=[types.Part(text=t)]) for t in texts],
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=EMBED_DIM),
            )
            if len(resp.embeddings) != len(texts):
                raise ValueError(f"{len(texts)} ta matn uchun {len(resp.embeddings)} ta vektor qaytdi")
            return [e.values for e in resp.embeddings]
        except Exception as e:  # 429 / vaqtinchalik xatolar
            wait = min(60, 5 * 2 ** attempt)
            print(f"   ⚠️ Vektorlashda xato ({e.__class__.__name__}): {str(e)[:120]} — {wait}s kutiladi")
            time.sleep(wait)
    raise RuntimeError("Vektorlash 5 urinishdan keyin ham muvaffaqiyatsiz tugadi")


def ingest() -> None:
    files = sorted(p for p in DOCS_DIR.glob("*.txt") if p.is_file())
    if not files:
        print(f"⚠️ {DOCS_DIR} papkasida .txt fayllar topilmadi.")
        return

    # 1. Barcha hujjatlarni bo'laklash va takrorlarni olib tashlash
    all_chunks, seen = [], set()
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        chunks = chunk_document(path.name, text)
        unique = 0
        for c in chunks:
            key = hashlib.sha1(re.sub(r"\W+", "", c["text"].split("\n", 1)[-1].lower()).encode()).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            c["id"] = f"{path.stem}__{unique}"
            c["chunk_index"] = unique
            all_chunks.append(c)
            unique += 1
        print(f"📘 {path.name}: {len(chunks)} bo'lak ({unique} noyob)")
    print(f"\nJami noyob bo'laklar: {len(all_chunks)}")

    # 2. Eski bazani butunlay o'chirish va yangisini yaratish
    shutil.rmtree(CHROMA_PATH, ignore_errors=True)
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    print("🗑️  Eski baza o'chirildi, yangi kolleksiya yaratildi.\n")

    # 3. Vektorlash va saqlash
    started = time.time()
    for i in range(0, len(all_chunks), EMBED_BATCH_SIZE):
        batch = all_chunks[i:i + EMBED_BATCH_SIZE]
        embeddings = embed_documents([c["text"] for c in batch])
        collection.add(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            embeddings=embeddings,
            metadatas=[
                {"source": c["source"], "title": c["title"], "section": c["section"],
                 "url": c["url"], "chunk_index": c["chunk_index"]}
                for c in batch
            ],
        )
        print(f"   ✅ {min(i + EMBED_BATCH_SIZE, len(all_chunks))}/{len(all_chunks)}")

    print(f"\n🎉 Tayyor: {collection.count()} bo'lak {time.time() - started:.1f}s da saqlandi → {CHROMA_PATH}")


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        for p in sorted(DOCS_DIR.glob("*.txt")):
            cs = chunk_document(p.name, p.read_text(encoding="utf-8", errors="ignore"))
            sizes = [len(c["text"]) for c in cs] or [0]
            print(f"{p.name}: {len(cs)} bo'lak, o'rtacha {sum(sizes) // len(sizes)}, max {max(sizes)}")
            if cs:
                print("   ", cs[min(3, len(cs) - 1)]["text"][:220].replace("\n", " ⏎ "))
    else:
        ingest()
