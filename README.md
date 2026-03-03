# kn — Kindle Notes CLI

Extract, sync, and search your Kindle highlights from the command line.

Reads highlights from the Mac Kindle app (`com.amazon.Lassen`) using two methods:

- **Local KFX parsing** for DRM-free sideloaded books (PDOCs)
- **Playwright browser scraping** for DRM-protected store purchases (EBOKs)

All highlights are stored in a local SQLite database with full-text search.

## Installation

Requires Python 3.12+ and the Mac Kindle app.

```bash
# Clone and install
git clone https://github.com/delebedev/kindle-notes.git
cd kindle-notes
uv pip install -e .
```

Or run directly without installing:

```bash
uv run --directory ~/src/kindle-notes kn sync
```

### Playwright setup (required for store-bought books)

Playwright needs a Chromium browser to scrape highlights from DRM-protected books. Install it after installing the package:

```bash
uv run playwright install chromium
```

This downloads a Chromium binary (~150 MB). Without this step, `kn sync` will still work for DRM-free/sideloaded books but will fail when scraping store purchases.

## Quick start

```bash
# Sync all highlights from your Kindle app
kn sync

# List your books
kn list

# Search across all highlights
kn search "compound interest"
```

## Commands

### `kn sync`

Syncs highlights from the Kindle app into `~/.config/kn/highlights.db`.

- Parses local KFX files for DRM-free books (fast, no network)
- Scrapes Amazon notebook via Playwright for DRM books (slower, needs cookies)
- Deduplicates automatically — safe to re-run

```bash
kn sync              # sync all books
kn sync --book ASIN  # sync a single book
```

### `kn list`

Lists all synced books with highlight counts.

```
$ kn list
  Atomic Habits: The life-changing million-copy #1 bestseller
    B01N5AX61W | EBOK | 121 highlights
  AI Engineering: Building Applications with Foundation Models
    B0DPLNK9GN | EBOK | 219 highlights
```

### `kn show <book>`

Shows all highlights for a book. Accepts a fuzzy title match or exact ASIN.

```bash
kn show "atomic"     # fuzzy match
kn show B01N5AX61W   # exact ASIN
```

### `kn search <query>`

Full-text search across all highlights using SQLite FTS5.

```
$ kn search "marginal gains"
1 results:

  "the aggregation of marginal gains," which was the philosophy of
  searching for a tiny margin of improvement in everything you do.
  -- Atomic Habits [yellow]
```

### `kn export`

Export highlights to stdout as markdown or JSON.

```bash
kn export                    # all books, markdown
kn export --json-out         # all books, JSON
kn export --book "atomic"    # single book
```

## How it works

1. **Local annotations** — reads `ksdk_annotation_v1.db` from the Kindle app container for highlight positions
2. **KFX extraction** — for DRM-free books, parses `.azw8` files via [kfxlib](https://github.com/kluyg/calibre-kfx-input) to extract the actual highlighted text
3. **Notebook scraping** — for DRM books, uses Playwright to open `read.amazon.com/notebook`, click each book, and scroll to load all highlights
4. **Cookie auth** — reads `Cookies.binarycookies` from the Kindle app for Amazon authentication (no login needed)

## Configuration

Optional config file at `~/.config/kn/config.toml`:

```toml
# Amazon domain — change for your region (default: amazon.com)
# Options: amazon.com, amazon.co.uk, amazon.de, amazon.co.jp, etc.
amazon_domain = "amazon.com"
```

Can also be set via environment variable: `KN_AMAZON_DOMAIN=amazon.co.uk kn sync`

## Data

- Config & database: `~/.config/kn/`
- Kindle app data: `~/Library/Containers/com.amazon.Lassen/Data/`

## License

GPL v3 — kfxlib is vendored from [calibre-kfx-input](https://github.com/kluyg/calibre-kfx-input) under GPL v3.
