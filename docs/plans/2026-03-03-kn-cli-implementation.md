# kn CLI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `kn` CLI tool to sync, browse, and search Kindle highlights with local SQLite cache.

**Architecture:** Click CLI with SQLite cache at `~/.config/kn/`. Two data sources: local KFX parsing (DRM-free PDOCs) and Playwright notebook scraping (DRM EBOKs). Existing `extract.py` code is refactored into `kn/sources/` modules.

**Tech Stack:** Python 3.12, Click, SQLite/FTS5, Playwright, kfxlib (vendored), BeautifulSoup, binarycookies

---

### Task 1: Project scaffolding and deps

**Files:**
- Create: `kn/__init__.py`
- Create: `kn/sources/__init__.py`
- Modify: `pyproject.toml`

**Step 1: Create package directories**

```bash
mkdir -p kn/sources
touch kn/__init__.py kn/sources/__init__.py
```

**Step 2: Update pyproject.toml**

```toml
[project]
name = "kindle-notes"
version = "0.1.0"
description = "CLI tool to sync, browse, and search Kindle highlights"
requires-python = ">=3.12"
dependencies = [
    "beautifulsoup4>=4.14.3",
    "binary-cookies-parser>=2.1.2",
    "click>=8.1",
    "lxml>=6.0.2",
    "pillow>=12.1.1",
    "playwright>=1.49",
    "pypdf>=6.7.5",
]

[project.scripts]
kn = "kn.cli:main"
```

**Step 3: Install deps and playwright browser**

```bash
uv add click playwright
uv run playwright install chromium
```

**Step 4: Verify**

```bash
uv run python -c "import click; import playwright; print('ok')"
```

Expected: `ok`

**Step 5: Commit**

```bash
git add kn/ pyproject.toml uv.lock
git commit -m "feat: scaffold kn package, add click + playwright deps"
```

---

### Task 2: Database layer (db.py)

**Files:**
- Create: `kn/db.py`
- Create: `tests/test_db.py`

**Step 1: Write failing tests**

```python
# tests/test_db.py
import json
from kn.db import DB


def test_create_schema(tmp_path):
    db = DB(tmp_path / "test.db")
    # tables should exist
    tables = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [t[0] for t in tables]
    assert "books" in names
    assert "highlights" in names


def test_upsert_book(tmp_path):
    db = DB(tmp_path / "test.db")
    db.upsert_book("B123", "Test Book", ["Author A"], "EBOK", "notebook")
    book = db.get_book("B123")
    assert book["title"] == "Test Book"
    assert json.loads(book["authors"]) == ["Author A"]
    # upsert again with new title
    db.upsert_book("B123", "Updated Title", ["Author A"], "EBOK", "notebook")
    book = db.get_book("B123")
    assert book["title"] == "Updated Title"


def test_upsert_highlights_dedup(tmp_path):
    db = DB(tmp_path / "test.db")
    db.upsert_book("B123", "Test", [], "PDOC", "local")
    db.upsert_highlight("B123", "hello world", "yellow", 100, 200, 1000)
    db.upsert_highlight("B123", "hello world", "yellow", 100, 200, 1000)
    count = db.count_highlights("B123")
    assert count == 1


def test_list_books(tmp_path):
    db = DB(tmp_path / "test.db")
    db.upsert_book("A1", "Book A", [], "PDOC", "local")
    db.upsert_book("A2", "Book B", [], "EBOK", "notebook")
    db.upsert_highlight("A1", "text1", "yellow", 10, 20, 1000)
    db.upsert_highlight("A1", "text2", "blue", 30, 40, 1001)
    db.upsert_highlight("A2", "text3", "yellow", 50, 60, 1002)
    books = db.list_books()
    assert len(books) == 2
    # books should have highlight_count
    counts = {b["asin"]: b["highlight_count"] for b in books}
    assert counts["A1"] == 2
    assert counts["A2"] == 1


def test_search_fts(tmp_path):
    db = DB(tmp_path / "test.db")
    db.upsert_book("A1", "Book A", [], "PDOC", "local")
    db.upsert_highlight("A1", "bounded context is important", "yellow", 10, 20, 1000)
    db.upsert_highlight("A1", "event driven architecture", "blue", 30, 40, 1001)
    results = db.search("bounded context")
    assert len(results) == 1
    assert "bounded context" in results[0]["text"]


def test_get_highlights(tmp_path):
    db = DB(tmp_path / "test.db")
    db.upsert_book("A1", "Book A", [], "PDOC", "local")
    db.upsert_highlight("A1", "first", "yellow", 10, 20, 1000)
    db.upsert_highlight("A1", "second", "blue", 30, 40, 1001)
    highlights = db.get_highlights("A1")
    assert len(highlights) == 2
    assert highlights[0]["text"] == "first"


def test_find_book_fuzzy(tmp_path):
    db = DB(tmp_path / "test.db")
    db.upsert_book("B1", "Build: An Unorthodox Guide", ["Tony Fadell"], "EBOK", "notebook")
    db.upsert_book("B2", "Building Event-Driven Microservices", ["Adam B"], "PDOC", "local")
    matches = db.find_book("build")
    assert len(matches) == 2
    matches = db.find_book("unorthodox")
    assert len(matches) == 1
    assert matches[0]["asin"] == "B1"
    # exact ASIN
    matches = db.find_book("B2")
    assert len(matches) == 1
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_db.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kn.db'`

**Step 3: Implement db.py**

```python
# kn/db.py
import json
import sqlite3
import time
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".config" / "kn" / "highlights.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    asin TEXT PRIMARY KEY,
    title TEXT,
    authors TEXT,
    content_type TEXT,
    source TEXT,
    last_synced INTEGER
);

CREATE TABLE IF NOT EXISTS highlights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asin TEXT REFERENCES books(asin),
    text TEXT,
    color TEXT,
    position_start INTEGER,
    position_end INTEGER,
    created_at INTEGER,
    synced_at INTEGER,
    UNIQUE(asin, position_start, position_end)
);

CREATE VIRTUAL TABLE IF NOT EXISTS highlights_fts USING fts5(
    text, content='highlights', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS highlights_ai AFTER INSERT ON highlights BEGIN
    INSERT INTO highlights_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS highlights_ad AFTER DELETE ON highlights BEGIN
    INSERT INTO highlights_fts(highlights_fts, rowid, text)
        VALUES('delete', old.id, old.text);
END;
"""


class DB:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def upsert_book(
        self, asin: str, title: str, authors: list[str],
        content_type: str, source: str,
    ) -> None:
        self.conn.execute(
            "INSERT INTO books (asin, title, authors, content_type, source, last_synced) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(asin) DO UPDATE SET "
            "title=excluded.title, authors=excluded.authors, "
            "content_type=excluded.content_type, source=excluded.source, "
            "last_synced=excluded.last_synced",
            (asin, title, json.dumps(authors), content_type, source, int(time.time())),
        )
        self.conn.commit()

    def get_book(self, asin: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM books WHERE asin = ?", (asin,)
        ).fetchone()
        return dict(row) if row else None

    def upsert_highlight(
        self, asin: str, text: str, color: str,
        position_start: int, position_end: int, created_at: int,
    ) -> None:
        self.conn.execute(
            "INSERT INTO highlights (asin, text, color, position_start, position_end, created_at, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(asin, position_start, position_end) DO UPDATE SET "
            "text=excluded.text, color=excluded.color, synced_at=excluded.synced_at",
            (asin, text, color, position_start, position_end, created_at, int(time.time())),
        )
        self.conn.commit()

    def count_highlights(self, asin: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM highlights WHERE asin = ?", (asin,)
        ).fetchone()
        return row[0]

    def list_books(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT b.*, COUNT(h.id) as highlight_count "
            "FROM books b LEFT JOIN highlights h ON b.asin = h.asin "
            "GROUP BY b.asin ORDER BY b.last_synced DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_highlights(self, asin: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM highlights WHERE asin = ? ORDER BY position_start",
            (asin,),
        ).fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT h.*, b.title, b.authors FROM highlights h "
            "JOIN highlights_fts fts ON h.id = fts.rowid "
            "JOIN books b ON h.asin = b.asin "
            "WHERE highlights_fts MATCH ? ORDER BY rank",
            (query,),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_book(self, query: str) -> list[dict]:
        # Try exact ASIN first
        row = self.conn.execute(
            "SELECT * FROM books WHERE asin = ?", (query,)
        ).fetchone()
        if row:
            return [dict(row)]
        # Fuzzy title match
        rows = self.conn.execute(
            "SELECT * FROM books WHERE title LIKE ? COLLATE NOCASE",
            (f"%{query}%",),
        ).fetchall()
        return [dict(r) for r in rows]
```

**Step 4: Add pytest dep and run tests**

```bash
uv add --dev pytest
uv run pytest tests/test_db.py -v
```

Expected: all 7 tests PASS

**Step 5: Commit**

```bash
git add kn/db.py tests/test_db.py pyproject.toml uv.lock
git commit -m "feat: add SQLite database layer with FTS search"
```

---

### Task 3: Local source (sources/local.py)

**Files:**
- Create: `kn/sources/local.py`

Refactor local KFX extraction code from `extract.py` into this module.

**Step 1: Create sources/local.py**

Move these functions from `extract.py`:
- `find_annotation_db()` → `find_annotation_db()`
- `find_azw8()` → `find_azw8()`
- `load_annotations_from_db()` → `load_annotations()`
- `load_book_sections()` → `load_book_sections()`
- `extract_text()` → `extract_text()`
- `get_book_metadata()` → `get_book_metadata()`

Add a high-level function:

```python
def sync_local_books(db: DB, asin_filter: str | None = None) -> list[str]:
    """Sync DRM-free books from local Kindle data. Returns list of synced ASINs."""
```

This function:
1. Reads Kindle's annotation DB
2. For each ASIN with a local azw8, parses KFX and extracts highlight text
3. Upserts book + highlights into our DB
4. Returns list of successfully synced ASINs

Keep the same constants: `KINDLE_CONTAINER`, `EBOOKS_DIR`, `KSDK_DIR`.

**Step 2: Verify against real data**

```bash
uv run python -c "
from kn.db import DB
from kn.sources.local import sync_local_books
from pathlib import Path
db = DB(Path('/tmp/kn-test.db'))
synced = sync_local_books(db)
print(f'Synced: {synced}')
for b in db.list_books():
    print(f'  {b[\"title\"][:50]}: {b[\"highlight_count\"]} highlights')
"
```

Expected: 2 PDOCs synced, 258 total highlights (144 + 114)

**Step 3: Commit**

```bash
git add kn/sources/local.py
git commit -m "feat: add local KFX source for DRM-free books"
```

---

### Task 4: Notebook source with Playwright (sources/notebook.py)

**Files:**
- Create: `kn/sources/notebook.py`

**Step 1: Create sources/notebook.py**

Two parts:
1. Cookie loading from `Cookies.binarycookies` (reuse from extract.py)
2. Playwright scraping with scroll-to-load-all

```python
AMAZON_DOMAIN = "amazon.co.uk"
COOKIES_PATH = Path.home() / "Library/Containers/com.amazon.Lassen/Data/Library/Cookies/Cookies.binarycookies"


def load_amazon_cookies() -> list[dict]:
    """Load cookies in Playwright-compatible format."""


def fetch_notebook_books(page) -> list[dict]:
    """Get book list from notebook main page. Page already navigated."""


def fetch_all_highlights(page, asin: str) -> list[dict]:
    """Navigate to book's notebook page, scroll until all highlights loaded, extract."""
    # Navigate to notebook?asin=X
    # Wait for #highlight elements
    # Scroll and wait until count stabilizes (no new elements for 2 seconds)
    # Extract text from all #highlight elements


def sync_notebook_books(db: DB, asin_filter: str | None = None, skip_asins: list[str] | None = None) -> None:
    """Sync DRM books via Playwright notebook scraping."""
    # 1. Load cookies
    # 2. Launch Playwright chromium, set cookies
    # 3. Navigate to notebook, get book list
    # 4. For each book (not in skip_asins): fetch all highlights, upsert
```

Key Playwright logic for scrolling:

```python
async def _scroll_until_loaded(page):
    prev_count = 0
    while True:
        count = await page.locator("#highlight").count()
        if count == prev_count:
            break
        prev_count = count
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)
```

Use sync Playwright API (not async) for simplicity with Click.

**Step 2: Verify against real data**

```bash
uv run python -c "
from kn.db import DB
from kn.sources.notebook import sync_notebook_books
from pathlib import Path
db = DB(Path('/tmp/kn-test-nb.db'))
sync_notebook_books(db, asin_filter='B0DPLNK9GN')
b = db.get_book('B0DPLNK9GN')
count = db.count_highlights('B0DPLNK9GN')
print(f'{b[\"title\"]}: {count} highlights')
assert count > 97, f'Expected >97, got {count}'
print('PASS: got more than 97 highlights via Playwright')
"
```

Expected: B0DPLNK9GN has 219 highlights (matching Kindle's local annotation DB count)

**Step 3: Commit**

```bash
git add kn/sources/notebook.py
git commit -m "feat: add Playwright notebook source for DRM books"
```

---

### Task 5: Sync orchestrator (sync.py)

**Files:**
- Create: `kn/sync.py`

**Step 1: Implement sync.py**

```python
def sync_all(db: DB, asin_filter: str | None = None) -> None:
    """Run full sync: local sources first, then notebook for remaining books."""
    # 1. Sync local (DRM-free) — returns list of synced ASINs
    local_asins = sync_local_books(db, asin_filter)
    # 2. Sync notebook (DRM) — skip already-synced local ASINs
    sync_notebook_books(db, asin_filter, skip_asins=local_asins)
```

Print progress: `click.echo(f"Synced {title}: {count} highlights")`

**Step 2: Verify full sync**

```bash
uv run python -c "
from kn.db import DB
from kn.sync import sync_all
from pathlib import Path
db = DB(Path('/tmp/kn-test-full.db'))
sync_all(db)
books = db.list_books()
print(f'Books: {len(books)}')
total = sum(b['highlight_count'] for b in books)
print(f'Total highlights: {total}')
assert len(books) == 5
assert total > 500
print('PASS')
"
```

Expected: 5 books, >500 total highlights

**Step 3: Verify re-sync produces no duplicates**

```bash
uv run python -c "
from kn.db import DB
from kn.sync import sync_all
from pathlib import Path
db = DB(Path('/tmp/kn-test-full.db'))
# Already synced above — sync again
books_before = db.list_books()
counts_before = {b['asin']: b['highlight_count'] for b in books_before}
sync_all(db)
books_after = db.list_books()
counts_after = {b['asin']: b['highlight_count'] for b in books_after}
assert counts_before == counts_after, f'Counts changed: {counts_before} -> {counts_after}'
print('PASS: re-sync produced no duplicates')
"
```

Expected: PASS

**Step 4: Commit**

```bash
git add kn/sync.py
git commit -m "feat: add sync orchestrator (local first, notebook fallback)"
```

---

### Task 6: CLI commands (cli.py)

**Files:**
- Create: `kn/cli.py`

**Step 1: Implement cli.py**

```python
# kn/cli.py
import json
import click
from .db import DB

@click.group()
@click.pass_context
def main(ctx):
    ctx.ensure_object(dict)
    ctx.obj["db"] = DB()

@main.command()
@click.option("--book", default=None, help="Sync single book by ASIN")
@click.pass_context
def sync(ctx, book):
    """Sync highlights from Kindle app."""
    from .sync import sync_all
    sync_all(ctx.obj["db"], asin_filter=book)

@main.command("list")
@click.pass_context
def list_books(ctx):
    """List all books with highlight counts."""
    books = ctx.obj["db"].list_books()
    for b in books:
        authors = json.loads(b["authors"]) if b["authors"] else []
        author_str = f" by {', '.join(authors)}" if authors else ""
        click.echo(f"  {b['title']}{author_str}")
        click.echo(f"    {b['asin']} | {b['content_type']} | {b['highlight_count']} highlights")

@main.command()
@click.argument("book")
@click.pass_context
def show(ctx, book):
    """Show highlights for a book (fuzzy title match or ASIN)."""
    matches = ctx.obj["db"].find_book(book)
    if not matches:
        click.echo(f"No book matching '{book}'", err=True)
        raise SystemExit(1)
    if len(matches) > 1:
        click.echo(f"Ambiguous match for '{book}':")
        for m in matches:
            click.echo(f"  {m['asin']}: {m['title']}")
        raise SystemExit(1)
    b = matches[0]
    highlights = ctx.obj["db"].get_highlights(b["asin"])
    click.echo(f"{b['title']}")
    authors = json.loads(b["authors"]) if b["authors"] else []
    if authors:
        click.echo(f"by {', '.join(authors)}")
    click.echo(f"{len(highlights)} highlights\n")
    for h in highlights:
        click.echo(f"  {h['text']}")
        click.echo(f"  -- [{h['color']}]\n")

@main.command()
@click.argument("query")
@click.pass_context
def search(ctx, query):
    """Full-text search across all highlights."""
    results = ctx.obj["db"].search(query)
    if not results:
        click.echo(f"No results for '{query}'")
        return
    click.echo(f"{len(results)} results:\n")
    for r in results:
        click.echo(f"  {r['text']}")
        click.echo(f"  -- {r['title']} [{r['color']}]\n")

@main.command()
@click.option("--json-out", "as_json", is_flag=True, help="Output as JSON")
@click.option("--book", default=None, help="Export single book")
@click.pass_context
def export(ctx, as_json, book):
    """Export highlights to stdout (markdown or JSON)."""
    db = ctx.obj["db"]
    if book:
        matches = db.find_book(book)
        if not matches:
            click.echo(f"No book matching '{book}'", err=True)
            raise SystemExit(1)
        books = matches[:1]
    else:
        books = db.list_books()

    if as_json:
        output = []
        for b in books:
            highlights = db.get_highlights(b["asin"])
            output.append({
                "asin": b["asin"], "title": b["title"],
                "authors": json.loads(b["authors"]) if b["authors"] else [],
                "highlights": [{"text": h["text"], "color": h["color"]} for h in highlights],
            })
        click.echo(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        for b in books:
            highlights = db.get_highlights(b["asin"])
            authors = json.loads(b["authors"]) if b["authors"] else []
            click.echo(f"# {b['title']}")
            if authors:
                click.echo(f"*{', '.join(authors)}*\n")
            for h in highlights:
                click.echo(f"> {h['text']}\n")
```

**Step 2: Verify all commands (requires prior sync)**

```bash
# Sync first
uv run kn sync

# List
uv run kn list

# Show (fuzzy match)
uv run kn show build

# Search
uv run kn search "bounded context"

# Export JSON
uv run kn export --json-out | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d)} books'); assert len(d) > 0"

# Export markdown
uv run kn export --book build | head -20
```

Expected:
- `list`: 5 books with counts
- `show build`: highlights from "Build: An Unorthodox Guide..."
- `search`: at least 1 result with "bounded context"
- `export --json-out`: valid JSON array with >0 entries
- `export --book`: markdown output with `#` heading

**Step 3: Commit**

```bash
git add kn/cli.py
git commit -m "feat: add CLI commands (sync, list, show, search, export)"
```

---

### Task 7: Clean up and finalize

**Files:**
- Modify: `pyproject.toml` (description)
- Delete: `extract.py` (superseded by kn package)

**Step 1: Remove old extract.py**

```bash
trash extract.py
```

**Step 2: Final end-to-end verification**

```bash
# Fresh DB
rm -rf ~/.config/kn/

# Full sync
uv run kn sync

# All commands work
uv run kn list
uv run kn show build
uv run kn search "microservice"
uv run kn export --json-out | python3 -c "import json,sys; d=json.load(sys.stdin); assert len(d)==5; print('5 books OK')"

# Re-sync is idempotent
uv run kn sync
```

**Step 3: Commit and push**

```bash
git add -A
git commit -m "chore: remove extract.py, finalize project"
git push
```
