"""new-documents/*.txt fayllaridan vektor baza (ChromaDB) yaratish.

Ishlatish:
    python ingest.py                 # bazani noldan to'liq qayta qurish (barcha fayllar)
    python ingest.py --add           # faqat bazada hali yo'q YANGI fayllarni qo'shish (tejamkor)
    python ingest.py --add fayl.txt  # ko'rsatilgan fayl(lar)ni qayta indekslash (o'zgartirilgan bo'lsa)
    python ingest.py --dry-run       # API chaqirmasdan bo'laklashni ko'rish

Ingestdan keyin ishlab turgan serverni qayta ishga tushiring.
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
_URL_LINE = re.compile(r"^\s*(?:URL|MANBA|=== MANBA):\s*(https?://\S+?)\s*(?:===)?\s*$", re.IGNORECASE)
# Huquqiy hujjatlar tuzilishi: "3-bob. ...", "12-modda. ...", "...qaroriga 1-ILOVA"
_BOB_LINE = re.compile(r"^\d+-bob\.\s*\S.*$", re.IGNORECASE)
_MODDA_LINE = re.compile(r"^\d+-modda\.\s*\S.*$", re.IGNORECASE)
_ANNEX_LINE = re.compile(r"\b\d+-ILOVA\s*$")
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
    part = ""   # ilova / nizom nomi
    bob = ""    # joriy bob
    expect_part_title = False  # "N-ILOVA" dan keyingi katta harfli qator — ilova nomi
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
            if chunks or doc_url:  # yangi sahifa (saytdan yig'ilgan fayllar) — oldingi qismni yopamiz
                flush()
            doc_url = url_match.group(1)  # hujjat boshidagi MANBA birinchi bo'lakka ham tegishli
            continue
        if len(line) < 200 and _ANNEX_LINE.search(line):
            flush()
            part, bob = line[:120], ""
            section = part
            expect_part_title = True
            continue
        if expect_part_title:
            expect_part_title = False
            if line.isupper() and len(line) < 400:
                flush()
                part, bob = line[:110], ""
                section = part
                continue
        if len(line) < 200 and _BOB_LINE.match(line):
            flush()
            bob = line[:120]
            section = f"{part[:60]} — {bob}" if part else bob
            continue
        if len(line) < 250 and _MODDA_LINE.match(line):
            flush()
            section = f"{bob} — {line[:120]}" if bob else line[:120]
            continue
        heading = _MD_HEADING.match(line)
        if heading or (_is_caps_heading(line) and len(line) <= 90) or (line.isupper() and line.endswith("NIZOM")):
            flush()
            section = (heading.group(1) if heading else line).strip("*:= ")[:120]
            if line.isupper() and line.endswith("NIZOM"):
                part, bob = section, ""
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
            key = _body_hash(c["text"])
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


def _body_hash(text: str) -> str:
    return hashlib.sha1(re.sub(r"\W+", "", text.split("\n", 1)[-1].lower()).encode()).hexdigest()


def ingest_add(names: list[str]) -> None:
    """Bazani o'chirmasdan faqat yangi (yoki ko'rsatilgan) fayllarni qo'shadi.

    Embedding faqat shu fayllar uchun hisoblanadi — butun bazani qayta qurishga qaraganda ancha tejamkor.
    """
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    existing = collection.get(include=["metadatas", "documents"])
    indexed = {m.get("source") for m in existing["metadatas"]}

    if names:
        paths = [DOCS_DIR / n for n in names]
        missing = [str(p) for p in paths if not p.is_file()]
        if missing:
            print(f"❌ Topilmadi: {', '.join(missing)}")
            return
    else:
        paths = sorted(p for p in DOCS_DIR.glob("*.txt") if p.name not in indexed)
    if not paths:
        print("✅ Yangi fayl yo'q — baza dolzarb.")
        return

    # Qayta indekslanadigan fayllarning eski bo'laklarini o'chiramiz
    for p in paths:
        if p.name in indexed:
            collection.delete(where={"source": p.name})
            print(f"🗑️  {p.name}: eski bo'laklar o'chirildi")

    # Boshqa fayllardagi bir xil matnlar takrorlanmasin
    current = collection.get(include=["documents"])
    seen = {_body_hash(d) for d in current["documents"]}
    new_chunks = []
    for p in paths:
        chunks = chunk_document(p.name, p.read_text(encoding="utf-8", errors="ignore"))
        unique = 0
        for c in chunks:
            key = _body_hash(c["text"])
            if key in seen:
                continue
            seen.add(key)
            c["id"] = f"{p.stem}__{unique}"
            c["chunk_index"] = unique
            new_chunks.append(c)
            unique += 1
        print(f"📘 {p.name}: {len(chunks)} bo'lak ({unique} noyob)")

    started = time.time()
    for i in range(0, len(new_chunks), EMBED_BATCH_SIZE):
        batch = new_chunks[i:i + EMBED_BATCH_SIZE]
        embeddings = embed_documents([c["text"] for c in batch])
        collection.add(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            embeddings=embeddings,
            metadatas=[{"source": c["source"], "title": c["title"], "section": c["section"],
                        "url": c["url"], "chunk_index": c["chunk_index"]} for c in batch],
        )
        print(f"   ✅ {min(i + EMBED_BATCH_SIZE, len(new_chunks))}/{len(new_chunks)}")
    print(f"\n🎉 Qo'shildi: {len(new_chunks)} bo'lak ({time.time() - started:.1f}s). Bazada jami: {collection.count()}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--dry-run" in args:
        names = [a for a in args if not a.startswith("--")]
        for p in ([DOCS_DIR / n for n in names] if names else sorted(DOCS_DIR.glob("*.txt"))):
            cs = chunk_document(p.name, p.read_text(encoding="utf-8", errors="ignore"))
            sizes = [len(c["text"]) for c in cs] or [0]
            print(f"{p.name}: {len(cs)} bo'lak, o'rtacha {sum(sizes) // len(sizes)}, max {max(sizes)}")
            if cs:
                print("   ", cs[min(3, len(cs) - 1)]["text"][:220].replace("\n", " ⏎ "))
    elif "--add" in args:
        ingest_add([a for a in args if not a.startswith("--")])
    else:
        ingest()
