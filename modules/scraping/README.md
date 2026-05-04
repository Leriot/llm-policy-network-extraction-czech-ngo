# Scraping

Collects raw web content (HTML pages, hyperlinks) from NGO websites
into `data/raw/{ngo}/`.

## Features

- Parallel scraping with a configurable worker pool
- Sitemap discovery and date-aware URL prioritisation
- `robots.txt` compliance
- Session tracking with checkpoint/resume (per-NGO SQLite session DB)
- Rate limiting (configurable per-domain delay)
- Hyperlink graph capture for downstream link analysis

## Public API

```python
from modules.scraping.scraper import NGOScraper
from modules.scraping.content_extractor import ContentExtractor
```

The pipeline drivers are:

- `scripts/01_scrape/batch_scrape.py` — sequential, one NGO at a time
- `scripts/01_scrape/batch_scrape_parallel.py` — parallel across NGOs

## Inputs

- `config/ngo_config.csv` — one row per NGO: name, aliases, scrape URL,
  depth limit
- `config/scraping_rules.yaml` — global crawl settings (worker count,
  rate limit, max depth, optional date filter)

## Output

For each NGO, `data/raw/{ngo}/` contains:

- `pages/*.html` — raw scraped HTML pages
- `documents/` — non-HTML downloads (PDFs etc.)
- `links.json` — captured hyperlink graph
- `session.db` — scrape session state (checkpoint / resume)
