# Dependency Audit

This file records the cleaned Python dependency decision for the final replication repository.

## Removed From `requirements.txt`

The following packages were removed because they are not imported by retained final scripts/modules or were tied to obsolete experiments:

- `pdfplumber`
- `pytesseract`
- `pdf2image`
- `Pillow`
- `httpx`
- `lxml`
- `tabulate`
- `python-dateutil`
- `python-magic`
- `xxhash`
- `coloredlogs`
- `jsonlines`
- `pytest`
- `pytest-cov`
- `responses`
- `jupyter`
- `notebook`
- `ipykernel`
- `matplotlib`
- `seaborn`
- `networkx`
- development-only `black`, `flake8`, and `mypy`

PDF/OCR processing was not used for the final retained dataset.

## Retained Runtime Dependencies

- `requests` and `urllib3` - scraper HTTP requests, retry handling, robots/sitemap retrieval.
- `beautifulsoup4` and `trafilatura` - HTML/text extraction.
- `chardet` - scraper encoding detection.
- `pyyaml` - YAML config loading.
- `pandas` - scraper CSV loading/export helpers.
- `flashtext` - fast NGO/keyword matching in filtering scripts.
- `tqdm` - scraper progress bars.
- `fuzzywuzzy` and `python-Levenshtein` - retained relationship validation helper.
- `openai` - LLM validation/tie-judge scripts.

## Optional / Not Required For Final Pipeline

- `gliner2` - the final pipeline does not use GLiNER. Module code in
  `modules/date_filter/`, `modules/scraping/content_extractor.py`, and
  `modules/relationship_extractor/` retains optional GLiNER fallback paths,
  but those paths are disabled by default and the import is wrapped in
  `try/except ImportError`. To re-enable the optional ML date layer:
  `pip install gliner2` and pass `--use-gliner` to
  `scripts/02_filter_clean/02_filter_by_date.py`.

## Config Files Kept

- `config/ngo_config.csv`
- `config/scraping_rules.yaml`
- `config/content_filter_keywords.yaml`
- `config/cleaning_config.yaml`

## Config Files Archived

The following were moved to `_archive_unused_20260503/config/unused_final_repo/` because retained final scripts do not require them:

- `config/extraction_config.yaml`
- `config/reduction_config.yaml`
- `config/ngo_config.yaml`

## Scraper Entry Points

Canonical retained scraper entry points:

- `scripts/01_scrape/batch_scrape.py`
- `scripts/01_scrape/batch_scrape_parallel.py`

The old `scripts/01_scrape/run_scraper.py` imported the archived `src` package and was moved to `_archive_unused_20260503/scripts/01_scrape/run_scraper_legacy_src_import.py`.
