# kn — Kindle Notes CLI

## Overview

CLI tool to sync, browse, and search Kindle highlights from the Mac Kindle app (com.amazon.Lassen). Two data sources: local KFX parsing for DRM-free sideloaded books, Playwright-based notebook scraping for DRM store purchases.

## Data Model

SQLite at `~/.config/kn/highlights.db`:

```sql
books (
    asin TEXT PRIMARY KEY,
    title TEXT,
    authors TEXT,          -- JSON array
    content_type TEXT,     -- EBOK | PDOC
    source TEXT,           -- local | notebook
    last_synced INTEGER    -- unix timestamp
)

highlights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asin TEXT REFERENCES books(asin),
    text TEXT,
    color TEXT,            -- yellow | blue | pink | orange
    position_start INTEGER,
    position_end INTEGER,
    created_at INTEGER,    -- from Kindle's last_modified
    synced_at INTEGER,
    UNIQUE(asin, position_start, position_end)
)
```

FTS via SQLite fts5 virtual table on `highlights.text`.

## CLI Commands

```
kn sync              # sync all books
kn sync --book ASIN  # sync single book
kn list              # list books with highlight counts
kn show <book>       # highlights for a book (fuzzy title match)
kn search <query>    # FTS across all highlights
kn export            # markdown to stdout
kn export --json     # JSON to stdout
kn export --book X   # single book
```

## Sync Logic

1. Read Kindle's local annotation DB for `last_modified` timestamps
2. Compare against `highlights.synced_at` — skip unchanged
3. PDOC: parse KFX locally via kfxlib, extract text at positions
4. EBOK: Playwright opens notebook page, scrolls to load all, scrapes
5. Upsert into SQLite — dedup via unique constraint

Playwright: headless Chromium, cookies from Kindle app's Cookies.binarycookies, scroll until no new #highlight elements.

## Module Layout

```
kindle-notes/
  kfxlib/              # vendored (GPL v3)
  kn/
    __init__.py
    cli.py             # click commands
    db.py              # SQLite schema, queries, FTS
    sync.py            # orchestrates sync
    sources/
      __init__.py
      local.py         # KFX parsing + local annotation DB
      notebook.py      # Playwright notebook scraping + cookies
  pyproject.toml       # [project.scripts] kn = "kn.cli:main"
```

## Verification

| Step | Verification |
|------|-------------|
| db.py | Create DB, insert, query, FTS — unit test |
| sources/local.py | Assert 258 highlights from 2 PDOCs |
| sources/notebook.py | Playwright scrape 1 EBOK, assert >97 highlights |
| sync.py | Full sync + re-sync, no duplicates |
| CLI commands | `kn list` shows 5 books, `kn search` returns hits |
| Export | JSON output validates as array with entries |

## Decisions

- CLI name: `kn`
- Config dir: `~/.config/kn/`
- Amazon domain: `amazon.co.uk` (hardcoded for now)
- Playwright required (not optional) — user wants all highlights
- Export to stdout only (JSON/markdown) — no direct Obsidian write
- Click for CLI framework
- Approach A: flat module layout, no plugin system
