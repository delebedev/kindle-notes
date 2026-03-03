#!/usr/bin/env python3
"""Extract Kindle highlights from local Mac Kindle app data.

Two extraction methods:
  1. Local KFX parsing — for DRM-free books (sideloaded PDOCs)
  2. Amazon notebook API — for DRM-protected store purchases (EBOK)

Usage:
    uv run python extract.py [--json] [--book ASIN]
"""
import json
import logging
import sqlite3
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from kfxlib import yj_book
from kfxlib.utilities import KFXDRMError

logging.basicConfig(level=logging.WARNING)

KINDLE_CONTAINER = Path.home() / "Library/Containers/com.amazon.Lassen/Data"
EBOOKS_DIR = KINDLE_CONTAINER / "Library/eBooks"
KSDK_DIR = KINDLE_CONTAINER / "Library/KSDK"
COOKIES_PATH = KINDLE_CONTAINER / "Library/Cookies/Cookies.binarycookies"

# Amazon domain — adjust if your account uses .com instead of .co.uk
AMAZON_DOMAIN = "amazon.co.uk"


@dataclass
class BookResult:
    asin: str
    title: str
    authors: list[str]
    content_type: str
    source: str  # "local" or "notebook"
    highlights: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cookie loading
# ---------------------------------------------------------------------------

def load_amazon_cookies() -> dict[str, str]:
    """Extract Amazon cookies from the Kindle app's binary cookie store."""
    import binarycookies

    if not COOKIES_PATH.exists():
        return {}
    with open(COOKIES_PATH, "rb") as f:
        jar = binarycookies.load(f)
    cookies = {}
    for c in jar:
        if "amazon" in c.url:
            cookies[c.name] = c.value
    return cookies


# ---------------------------------------------------------------------------
# Notebook API (for DRM books)
# ---------------------------------------------------------------------------

def fetch_notebook_books(cookies: dict[str, str]) -> list[dict]:
    """Fetch book list from Amazon notebook."""
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request(f"https://read.{AMAZON_DOMAIN}/notebook")
    req.add_header("Cookie", cookie_str)
    req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")

    resp = urllib.request.urlopen(req)
    soup = BeautifulSoup(resp.read().decode("utf-8"), "lxml")

    books = []
    for el in soup.select(".kp-notebook-library-each-book"):
        asin = el.get("id", "")
        title_el = el.select_one(".kp-notebook-searchable")
        author_el = el.select_one(".kp-notebook-searchable + span")
        books.append({
            "asin": asin,
            "title": title_el.text.strip() if title_el else "Unknown",
            "authors": [author_el.text.strip()] if author_el else [],
        })
    return books


def _notebook_request(url: str, cookies: dict[str, str]) -> BeautifulSoup:
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request(url)
    req.add_header("Cookie", cookie_str)
    req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
    resp = urllib.request.urlopen(req)
    return BeautifulSoup(resp.read().decode("utf-8"), "lxml")


def fetch_notebook_highlights(asin: str, cookies: dict[str, str]) -> list[dict]:
    """Fetch highlights for a book from Amazon notebook.

    Note: the notebook page only returns the first ~97 highlights.
    Amazon's pagination requires JS execution that we can't replicate here.
    """
    url = f"https://read.{AMAZON_DOMAIN}/notebook?asin={asin}&contentLimitState=&"
    soup = _notebook_request(url, cookies)

    highlights = []
    for el in soup.select("#highlight"):
        text = el.get_text(strip=True)
        if text:
            highlights.append({"text": text, "color": "yellow"})
    return highlights


# ---------------------------------------------------------------------------
# Local KFX parsing (for DRM-free books)
# ---------------------------------------------------------------------------

def find_annotation_db() -> Path:
    for p in KSDK_DIR.iterdir():
        db = p / "ksdk_annotation_v1.db"
        if db.exists():
            return db
    raise FileNotFoundError(f"No annotation DB found in {KSDK_DIR}")


def find_azw8(asin: str) -> Path | None:
    asin_dir = EBOOKS_DIR / asin
    if not asin_dir.exists():
        return None
    for f in asin_dir.rglob("*.azw8"):
        return f
    return None


def load_annotations_from_db(
    db_path: Path, asin_filter: str | None = None
) -> dict[str, list[dict]]:
    """Load highlights grouped by ASIN from the local annotation DB."""
    db = sqlite3.connect(str(db_path))
    rows = db.execute(
        "SELECT serialized_payload FROM server_view "
        "WHERE json_extract(serialized_payload, '$.type') = 'HIGHLIGHT'"
    ).fetchall()
    db.close()

    by_asin: dict[str, list[dict]] = {}
    for (payload_str,) in rows:
        ann = json.loads(payload_str)
        bd = ann["book_data"]
        asin = bd["asin"]
        if asin_filter and asin != asin_filter:
            continue

        meta = json.loads(ann.get("json_metadata", "{}"))
        entry = {
            "asin": asin,
            "content_type": bd["contentType"],
            "start": ann["start_position"]["shortPosition"],
            "end": ann["end_position"]["shortPosition"],
            "color": meta.get("mchl_color", "yellow"),
        }
        by_asin.setdefault(asin, []).append(entry)

    for v in by_asin.values():
        v.sort(key=lambda h: h["start"])
    return by_asin


def load_book_sections(azw8_path: Path) -> list[dict]:
    book = yj_book.YJ_Book(str(azw8_path))
    content = book.convert_to_json_content()
    data = json.loads(content.decode("utf-8"))

    sections = sorted(
        [e for e in data.get("data", []) if e.get("type") == 1],
        key=lambda x: x["position"],
    )
    for i, sec in enumerate(sections[:-1]):
        sec["length"] = sections[i + 1]["position"] - sec["position"]
    if sections:
        sections[-1]["length"] = len(sections[-1]["content"])
    return sections


def extract_text(sections: list[dict], start: int, end: int) -> str:
    parts = []
    idx = 0
    while idx < len(sections) - 1 and sections[idx + 1]["position"] <= start:
        idx += 1
    while idx < len(sections) and sections[idx]["position"] < end:
        sec = sections[idx]
        sec_start = sec["position"]
        sec_end = sec_start + sec["length"]
        s = max(start, sec_start) - sec_start
        e = min(end + 1, sec_end) - sec_start
        if e > s:
            parts.append(sec["content"][s:e])
        idx += 1
    return "".join(parts).replace("\n", " ").strip()


def get_book_metadata(azw8_path: Path) -> tuple[str, list[str]]:
    try:
        book = yj_book.YJ_Book(str(azw8_path))
        meta = book.get_metadata()
        return meta.title or azw8_path.stem, meta.authors or []
    except Exception:
        return azw8_path.stem, []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def print_book(result: BookResult) -> None:
    print(f"\n{'='*70}")
    print(f"{result.title}")
    if result.authors:
        print(f"by {', '.join(result.authors)}")
    print(
        f"ASIN: {result.asin} | {result.content_type} | "
        f"{len(result.highlights)} highlights | source: {result.source}"
    )
    print(f"{'='*70}")
    for h in result.highlights:
        print(f"\n  {h['text']}")
        print(f"  -- [{h.get('color', 'yellow')}]")


def main():
    output_json = "--json" in sys.argv
    asin_filter = None
    if "--book" in sys.argv:
        idx = sys.argv.index("--book")
        asin_filter = sys.argv[idx + 1]

    db_path = find_annotation_db()
    by_asin = load_annotations_from_db(db_path, asin_filter)

    cookies = load_amazon_cookies()
    has_cookies = bool(cookies)

    # Pre-fetch notebook book list for metadata of DRM books
    notebook_books: dict[str, dict] = {}
    if has_cookies:
        try:
            for b in fetch_notebook_books(cookies):
                notebook_books[b["asin"]] = b
        except Exception as e:
            print(f"Warning: could not fetch notebook: {e}", file=sys.stderr)

    results: list[BookResult] = []
    drm_asins: list[str] = []

    # Process each book's annotations
    for asin, annotations in by_asin.items():
        azw8 = find_azw8(asin)
        content_type = annotations[0]["content_type"]

        # Try local KFX extraction first
        if azw8:
            try:
                sections = load_book_sections(azw8)
                title, authors = get_book_metadata(azw8)
                highlights = []
                for ann in annotations:
                    text = extract_text(sections, ann["start"], ann["end"])
                    highlights.append({"text": text, "color": ann["color"]})
                result = BookResult(
                    asin=asin, title=title, authors=authors,
                    content_type=content_type, source="local",
                    highlights=highlights,
                )
                results.append(result)
                if not output_json:
                    print_book(result)
                continue
            except KFXDRMError:
                drm_asins.append(asin)
            except Exception as e:
                print(f"[{asin}] local parse error: {e}", file=sys.stderr)
                drm_asins.append(asin)
        else:
            drm_asins.append(asin)

    # Fall back to notebook API for DRM/missing books
    for asin in drm_asins:
        if not has_cookies:
            print(
                f"[{asin}] DRM protected, no cookies available — skipping",
                file=sys.stderr,
            )
            continue

        nb = notebook_books.get(asin)
        if not nb:
            print(f"[{asin}] not found in notebook — skipping", file=sys.stderr)
            continue

        try:
            highlights = fetch_notebook_highlights(asin, cookies)
        except Exception as e:
            print(f"[{asin}] notebook fetch error: {e}", file=sys.stderr)
            continue

        result = BookResult(
            asin=asin, title=nb["title"], authors=nb["authors"],
            content_type="EBOK", source="notebook",
            highlights=highlights,
        )
        results.append(result)
        if not output_json:
            print_book(result)

    if output_json:
        print(json.dumps(
            [
                {
                    "asin": r.asin,
                    "title": r.title,
                    "authors": r.authors,
                    "content_type": r.content_type,
                    "source": r.source,
                    "highlights": r.highlights,
                }
                for r in results
            ],
            indent=2,
            ensure_ascii=False,
        ))


if __name__ == "__main__":
    main()
