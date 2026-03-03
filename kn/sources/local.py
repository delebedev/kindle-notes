"""Local KFX source — sync DRM-free books from Kindle app data."""

import json
import sqlite3
import sys
import time
from pathlib import Path

# kfxlib is vendored at repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import click  # noqa: E402

from kfxlib import yj_book  # noqa: E402
from kfxlib.utilities import KFXDRMError  # noqa: E402
from kn.db import DB  # noqa: E402

KINDLE_CONTAINER = Path.home() / "Library/Containers/com.amazon.Lassen/Data"
EBOOKS_DIR = KINDLE_CONTAINER / "Library/eBooks"
KSDK_DIR = KINDLE_CONTAINER / "Library/KSDK"


def find_annotation_db() -> Path:
    """Locate the Kindle annotation SQLite DB."""
    for p in KSDK_DIR.iterdir():
        db = p / "ksdk_annotation_v1.db"
        if db.exists():
            return db
    raise FileNotFoundError(f"No annotation DB found in {KSDK_DIR}")


def find_azw8(asin: str) -> Path | None:
    """Find the .azw8 KFX file for a given ASIN."""
    asin_dir = EBOOKS_DIR / asin
    if not asin_dir.exists():
        return None
    for f in asin_dir.rglob("*.azw8"):
        return f
    return None


def load_annotations(
    db_path: Path, asin_filter: str | None = None
) -> dict[str, list[dict]]:
    """Load highlights grouped by ASIN from the local annotation DB."""
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT serialized_payload FROM server_view "
        "WHERE json_extract(serialized_payload, '$.type') = 'HIGHLIGHT'"
    ).fetchall()
    conn.close()

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
            "last_modified": ann.get("last_modified", 0),
        }
        by_asin.setdefault(asin, []).append(entry)

    for v in by_asin.values():
        v.sort(key=lambda h: h["start"])
    return by_asin


def load_book_sections(azw8_path: Path) -> list[dict]:
    """Parse KFX and return sorted content sections with position info."""
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
    """Extract highlight text spanning start..end across content sections."""
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
    """Extract title and authors from KFX metadata."""
    try:
        book = yj_book.YJ_Book(str(azw8_path))
        meta = book.get_metadata()
        return meta.title or azw8_path.stem, meta.authors or []
    except Exception:
        return azw8_path.stem, []


def sync_local_books(db: DB, asin_filter: str | None = None) -> list[str]:
    """Sync DRM-free books from local Kindle data. Returns list of synced ASINs."""
    db_path = find_annotation_db()
    by_asin = load_annotations(db_path, asin_filter)
    synced: list[str] = []

    for asin, annotations in by_asin.items():
        azw8 = find_azw8(asin)
        if not azw8:
            continue

        content_type = annotations[0]["content_type"]
        try:
            sections = load_book_sections(azw8)
            title, authors = get_book_metadata(azw8)
        except KFXDRMError:
            continue
        except Exception as e:
            click.echo(f"[{asin}] local parse error: {e}", err=True)
            continue

        db.upsert_book(
            asin=asin,
            title=title,
            authors=authors,
            content_type=content_type,
            source="local",
        )

        count = 0
        for ann in annotations:
            try:
                text = extract_text(sections, ann["start"], ann["end"])
                db.upsert_highlight(
                    asin=asin,
                    text=text,
                    color=ann["color"],
                    position_start=ann["start"],
                    position_end=ann["end"],
                    created_at=ann.get("last_modified", int(time.time())),
                )
                count += 1
            except Exception as e:
                click.echo(f"[{asin}] highlight error: {e}", err=True)

        synced.append(asin)
        click.echo(f"  {title[:50]}: {count} highlights", err=True)

    return synced
