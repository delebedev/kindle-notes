"""kn — CLI tool to sync, browse, and search Kindle highlights."""

import json

import click

from .db import DB, parse_authors


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
        authors = parse_authors(b["authors"])
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
        raise click.ClickException(f"No book matching '{book}'")
    if len(matches) > 1:
        lines = [f"Ambiguous match for '{book}':"]
        for m in matches:
            lines.append(f"  {m['asin']}: {m['title']}")
        raise click.ClickException("\n".join(lines))
    b = matches[0]
    highlights = ctx.obj["db"].get_highlights(b["asin"])
    click.echo(f"{b['title']}")
    authors = parse_authors(b["authors"])
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
            raise click.ClickException(f"No book matching '{book}'")
        books = matches[:1]
    else:
        books = db.list_books()

    if as_json:
        output = []
        for b in books:
            highlights = db.get_highlights(b["asin"])
            output.append({
                "asin": b["asin"],
                "title": b["title"],
                "authors": parse_authors(b["authors"]),
                "highlights": [{"text": h["text"], "color": h["color"]} for h in highlights],
            })
        click.echo(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        for b in books:
            highlights = db.get_highlights(b["asin"])
            authors = parse_authors(b["authors"])
            click.echo(f"# {b['title']}")
            if authors:
                click.echo(f"*{', '.join(authors)}*\n")
            for h in highlights:
                click.echo(f"> {h['text']}\n")
