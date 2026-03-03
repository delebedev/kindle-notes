"""SQLite database layer with FTS5 full-text search for highlights."""

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


def parse_authors(raw: str | None) -> list[str]:
    """Parse JSON-encoded authors string from DB."""
    if not raw:
        return []
    return json.loads(raw)


class DB:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def upsert_book(
        self,
        asin: str,
        title: str,
        authors: list[str],
        content_type: str,
        source: str,
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
        self,
        asin: str,
        text: str,
        color: str,
        position_start: int,
        position_end: int,
        created_at: int,
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
