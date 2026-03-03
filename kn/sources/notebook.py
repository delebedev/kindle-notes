"""Playwright-based notebook source — sync DRM books via browser scraping.

Clicks each book in the sidebar, then scrolls to trigger AJAX loading
of all highlights (initial load shows ~97-147, scroll loads the rest).
"""

import sys
import time
from pathlib import Path

import binarycookies
from playwright.sync_api import sync_playwright

from kn.db import DB

AMAZON_DOMAIN = "amazon.co.uk"
COOKIES_PATH = (
    Path.home()
    / "Library/Containers/com.amazon.Lassen/Data/Library/Cookies/Cookies.binarycookies"
)


def load_amazon_cookies() -> list[dict]:
    """Load cookies from Kindle app in Playwright-compatible format."""
    if not COOKIES_PATH.exists():
        return []
    with open(COOKIES_PATH, "rb") as f:
        jar = binarycookies.load(f)
    cookies = []
    for c in jar:
        if "amazon" in c.url:
            cookies.append({
                "name": c.name,
                "value": c.value,
                "domain": f".{AMAZON_DOMAIN}",
                "path": "/",
            })
    return cookies


def fetch_notebook_books(page) -> list[dict]:
    """Get book list from notebook main page. Page already navigated."""
    page.wait_for_selector(".kp-notebook-library-each-book", timeout=15000)
    books = []
    for el in page.query_selector_all(".kp-notebook-library-each-book"):
        asin = el.get_attribute("id") or ""
        title_el = el.query_selector(".kp-notebook-searchable")
        author_el = el.query_selector(".kp-notebook-searchable + span")
        books.append({
            "asin": asin,
            "title": title_el.inner_text().strip() if title_el else "Unknown",
            "authors": [author_el.inner_text().strip()] if author_el else [],
        })
    return books


def fetch_all_highlights(page, asin: str) -> list[dict]:
    """Fetch all highlights by clicking book in sidebar then scrolling.

    The notebook page loads ~97-147 highlights on click, then lazy-loads
    the rest via AJAX on scroll. We click the book, then scroll until
    the highlight count stabilizes.
    """
    book_el = page.locator(f"#{asin}")
    if book_el.count() == 0:
        return []
    book_el.click()
    page.wait_for_timeout(3000)

    try:
        page.wait_for_selector("#highlight", timeout=10000)
    except Exception:
        return []

    prev_count = 0
    stable_rounds = 0
    while stable_rounds < 3:
        count = page.locator("#highlight").count()
        if count != prev_count:
            stable_rounds = 0
            print(f"    loaded: {count} highlights", file=sys.stderr)
        else:
            stable_rounds += 1
        prev_count = count
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

    highlights = []
    for el in page.query_selector_all("#highlight"):
        text = el.inner_text().strip()
        if text:
            highlights.append({"text": text, "color": "yellow"})
    return highlights


def sync_notebook_books(
    db: DB,
    asin_filter: str | None = None,
    skip_asins: list[str] | None = None,
) -> None:
    """Sync DRM books via Playwright notebook scraping."""
    skip = set(skip_asins or [])

    cookies = load_amazon_cookies()
    if not cookies:
        print(
            "Warning: no Amazon cookies found — cannot scrape notebook",
            file=sys.stderr,
        )
        return

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()

        # Navigate to notebook and get book list
        page.goto(
            f"https://read.{AMAZON_DOMAIN}/notebook",
            wait_until="networkidle",
        )
        books = fetch_notebook_books(page)
        print(f"Found {len(books)} books in notebook", file=sys.stderr)

        # Filter to requested ASIN if specified
        if asin_filter:
            books = [b for b in books if b["asin"] == asin_filter]

        for book in books:
            asin = book["asin"]
            if asin in skip:
                continue

            try:
                print(f"  Scraping: {book['title'][:60]}...", file=sys.stderr)
                highlights = fetch_all_highlights(page, asin)

                db.upsert_book(
                    asin=asin,
                    title=book["title"],
                    authors=book["authors"],
                    content_type="EBOK",
                    source="notebook",
                )

                for i, h in enumerate(highlights):
                    db.upsert_highlight(
                        asin=asin,
                        text=h["text"],
                        color=h["color"],
                        position_start=i,
                        position_end=i,
                        created_at=int(time.time()),
                    )

                print(
                    f"  {book['title'][:50]}: {len(highlights)} highlights",
                    file=sys.stderr,
                )
            except Exception as e:
                print(
                    f"  [{asin}] notebook error: {e}",
                    file=sys.stderr,
                )

        browser.close()
