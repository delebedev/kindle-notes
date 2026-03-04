"""CLI tests using Click's CliRunner."""

import json

from click.testing import CliRunner

from kn.cli import main
from kn.db import DB


def _seed_db(db: DB):
    """Seed a DB with sample data for CLI tests."""
    db.upsert_book("B001", "Atomic Habits", ["James Clear"], "EBOK", "notebook")
    db.upsert_book("B002", "Deep Work", ["Cal Newport"], "PDOC", "local")
    db.upsert_highlight("B001", "small changes compound over time", "yellow", 10, 50, 1000)
    db.upsert_highlight(
        "B001", "habits are the compound interest of self-improvement", "blue", 60, 120, 1001,
    )
    db.upsert_highlight("B002", "deep work is the ability to focus", "yellow", 5, 40, 1002)


def test_list_books(tmp_path):
    db = DB(tmp_path / "test.db")
    _seed_db(db)

    runner = CliRunner()
    result = runner.invoke(main, ["list"], obj={"db": db})
    assert result.exit_code == 0
    assert "Atomic Habits" in result.output
    assert "Deep Work" in result.output
    assert "2 highlights" in result.output


def test_show_book(tmp_path):
    db = DB(tmp_path / "test.db")
    _seed_db(db)

    runner = CliRunner()
    result = runner.invoke(main, ["show", "atomic"], obj={"db": db})
    assert result.exit_code == 0
    assert "Atomic Habits" in result.output
    assert "compound interest" in result.output


def test_show_limit(tmp_path):
    db = DB(tmp_path / "test.db")
    _seed_db(db)

    runner = CliRunner()
    result = runner.invoke(main, ["show", "atomic", "--limit", "1"], obj={"db": db})
    assert result.exit_code == 0
    assert "1 of 2 highlights" in result.output
    assert "small changes" in result.output
    assert "compound interest" not in result.output


def test_show_offset(tmp_path):
    db = DB(tmp_path / "test.db")
    _seed_db(db)

    runner = CliRunner()
    result = runner.invoke(
        main, ["show", "atomic", "--limit", "1", "--offset", "1"], obj={"db": db},
    )
    assert result.exit_code == 0
    assert "1 of 2 highlights" in result.output
    assert "compound interest" in result.output
    assert "small changes" not in result.output


def test_show_no_match(tmp_path):
    db = DB(tmp_path / "test.db")
    _seed_db(db)

    runner = CliRunner()
    result = runner.invoke(main, ["show", "nonexistent"], obj={"db": db})
    assert result.exit_code != 0
    assert "No book matching" in result.output


def test_search(tmp_path):
    db = DB(tmp_path / "test.db")
    _seed_db(db)

    runner = CliRunner()
    result = runner.invoke(main, ["search", "compound"], obj={"db": db})
    assert result.exit_code == 0
    assert "compound" in result.output


def test_search_no_results(tmp_path):
    db = DB(tmp_path / "test.db")
    _seed_db(db)

    runner = CliRunner()
    result = runner.invoke(main, ["search", "quantum"], obj={"db": db})
    assert result.exit_code == 0
    assert "No results" in result.output


def test_search_invalid_query(tmp_path):
    db = DB(tmp_path / "test.db")
    _seed_db(db)

    runner = CliRunner()
    result = runner.invoke(main, ["search", "OR AND"], obj={"db": db})
    assert result.exit_code != 0
    assert "Invalid search query" in result.output


def test_export_markdown(tmp_path):
    db = DB(tmp_path / "test.db")
    _seed_db(db)

    runner = CliRunner()
    result = runner.invoke(main, ["export"], obj={"db": db})
    assert result.exit_code == 0
    assert "# Atomic Habits" in result.output
    assert "# Deep Work" in result.output
    assert "> small changes" in result.output


def test_export_json(tmp_path):
    db = DB(tmp_path / "test.db")
    _seed_db(db)

    runner = CliRunner()
    result = runner.invoke(main, ["export", "--json-out"], obj={"db": db})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    asins = {b["asin"] for b in data}
    assert "B001" in asins


def test_export_single_book(tmp_path):
    db = DB(tmp_path / "test.db")
    _seed_db(db)

    runner = CliRunner()
    result = runner.invoke(main, ["export", "--book", "atomic"], obj={"db": db})
    assert result.exit_code == 0
    assert "# Atomic Habits" in result.output
    assert "Deep Work" not in result.output
