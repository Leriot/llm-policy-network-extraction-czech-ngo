# Cleaning

Content extraction and deduplication for the scraped HTML corpus.

## What it does

Transforms raw HTML pages under `data/raw/{ngo}/` into clean text under
`data/interim/step1_content_extraction/{ngo}/text/` by:

1. **Multi-level template detection** — finds boilerplate elements that
   appear on most pages of a site (global templates) and on most pages
   within a URL section (section templates), and removes them before
   text extraction.
2. **Content extraction** — uses
   [trafilatura](https://trafilatura.readthedocs.io/) as the primary
   extractor, with a BeautifulSoup fallback for pages where trafilatura
   returns nothing.
3. **Deduplication** — 3-word shingling + Jaccard similarity (threshold
   0.85) to keep one representative per near-duplicate cluster.

## Public API

```python
from modules.cleaning.template_detector import TemplateDetector
from modules.cleaning.content_cleaner import ContentCleaner
```

The pipeline driver is `scripts/02_filter_clean/clean_ngo_data.py`.

## Output

For each NGO, `data/interim/step1_content_extraction/{ngo}/` contains:

- `text/*.txt` — cleaned article text, one file per page
- `metadata.jsonl` — per-NGO scrape statistics (single JSON object)
- `templates.json` — detected boilerplate template signatures
- `duplicates.json` — near-duplicate clusters and their representatives

## Configuration

Boilerplate thresholds and extraction options live in
`config/cleaning_config.yaml`.
