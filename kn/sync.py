"""Sync orchestrator — local sources first, then notebook for remaining books."""

import sys

from .db import DB
from .sources.local import sync_local_books
from .sources.notebook import sync_notebook_books


def sync_all(db: DB, asin_filter: str | None = None) -> None:
    """Run full sync: local sources first, then notebook for remaining books."""
    print("Syncing local (DRM-free) books...", file=sys.stderr)
    local_asins = sync_local_books(db, asin_filter)
    print(f"Local sync done: {len(local_asins)} books\n", file=sys.stderr)

    print("Syncing notebook (DRM) books via Playwright...", file=sys.stderr)
    sync_notebook_books(db, asin_filter, skip_asins=local_asins)
    print("Notebook sync done.", file=sys.stderr)
