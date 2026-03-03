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
