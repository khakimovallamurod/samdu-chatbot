"""Rasmiy saytlardan sahifalarni yig'ib, new-documents/ ga matn ko'rinishida saqlaydi.

Ishlatish:
    python web_scraper.py                       # ikkala sayt (standart limitlar bilan)
    python web_scraper.py ai-lab                # faqat https://ai-lab.sampc.uz/
    python web_scraper.py samdu --max-pages 300 # faqat https://www.samdu.uz/ (o'zbekcha sahifalar)

Keyin bazani yangilash: python ingest.py
"""
import re
import sys
import time
from collections import deque
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import DOCS_DIR

SITES = {
    "ai-lab": {"start": "https://ai-lab.sampc.uz/", "max_pages": 80, "path_filter": None},
    # samdu.uz juda katta — faqat o'zbekcha bo'limlar yig'iladi
    "samdu": {"start": "https://www.samdu.uz/uz", "max_pages": 250, "path_filter": re.compile(r"^/uz(/|$)")},
}

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SamDU-KB-Crawler/1.0"}
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|rar|docx?|xlsx?|pptx?|mp4|mp3|ico|css|js)$", re.I)
REQUEST_DELAY = 0.5  # saytga ortiqcha yuk tushmasligi uchun


def _clean(text: str) -> str:
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
    out, prev = [], None
    for l in lines:
        if len(l) < 2 or l == prev:
            continue
        out.append(l)
        prev = l
    return "\n".join(out)


def extract(html: bytes) -> tuple[str, str, BeautifulSoup]:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(strip=True) if soup.title else "").split("|")[0].strip()
    content = BeautifulSoup(html, "html.parser")
    for tag in content(["script", "style", "noscript", "nav", "footer", "header", "form", "svg", "iframe"]):
        tag.decompose()
    main = content.find("main") or content.find("article")
    text = _clean(main.get_text("\n")) if main else ""
    if len(text) < 300:  # ba'zi saytlarda asosiy matn <main> dan tashqarida
        text = _clean((content.body or content).get_text("\n"))
    return title, text, soup


def crawl(name: str, max_pages: int | None = None) -> None:
    site = SITES[name]
    start = site["start"]
    host = urlparse(start).netloc
    limit = max_pages or site["max_pages"]
    queue, seen, pages = deque([start]), {start}, []
    session = requests.Session()
    session.headers.update(HEADERS)

    while queue and len(pages) < limit:
        url = queue.popleft()
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type", ""):
                continue
        except requests.RequestException as e:
            print(f"  ✗ {url}: {e.__class__.__name__}")
            continue

        title, text, soup = extract(resp.content)
        if len(text) > 200:
            pages.append((url, title, text))
            print(f"  ✓ [{len(pages)}/{limit}] {url} ({len(text)} belgi)")

        for a in soup.find_all("a", href=True):
            link, _ = urldefrag(urljoin(url, a["href"]))
            parsed = urlparse(link)
            if parsed.netloc != host or parsed.scheme not in ("http", "https") or SKIP_EXT.search(parsed.path):
                continue
            if site["path_filter"] and not site["path_filter"].match(parsed.path):
                continue
            link = link.rstrip("/") or link
            if link not in seen:
                seen.add(link)
                queue.append(link)
        time.sleep(REQUEST_DELAY)

    if not pages:
        print(f"⚠️ {host}: hech qanday sahifa olinmadi")
        return

    # Bir xil matnli sahifalarni (masalan, til versiyalari) tashlab yuboramiz
    unique, seen_text = [], set()
    for url, title, text in pages:
        key = text[:500]
        if key not in seen_text:
            seen_text.add(key)
            unique.append((url, title, text))

    out_path = DOCS_DIR / f"web_{host.replace('.', '_').replace('-', '_')}.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        for url, title, text in unique:
            f.write(f"# {title or host} — {urlparse(url).path or '/'}\nURL: {url}\n{text}\n\n")
    print(f"✅ {len(unique)} sahifa → {out_path}")


if __name__ == "__main__":
    args = sys.argv[1:]
    max_pages = None
    if "--max-pages" in args:
        i = args.index("--max-pages")
        max_pages = int(args[i + 1])
        del args[i:i + 2]
    for site_name in (args or list(SITES)):
        print(f"\n🌐 {site_name}: {SITES[site_name]['start']}")
        crawl(site_name, max_pages)
