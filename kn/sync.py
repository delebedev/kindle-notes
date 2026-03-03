"""Sync orchestrator — local sources first, then notebook for remaining books."""

import click

from .db import DB
from .sources.local import sync_local_books
from .sources.notebook import sync_notebook_books


def sync_all(db: DB, asin_filter: str | None = None) -> None:
    """Run full sync: local sources first, then notebook for remaining books."""
    click.echo("Syncing local (DRM-free) books...", err=True)
    local_asins = sync_local_books(db, asin_filter)
    click.echo(f"Local sync done: {len(local_asins)} books\n", err=True)

    click.echo("Syncing notebook (DRM) books via Playwright...", err=True)
    sync_notebook_books(db, asin_filter, skip_asins=local_asins)
    click.echo("Notebook sync done.", err=True)
