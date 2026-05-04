# Keyword Filter

Fast pre-filter that runs before the date filter so the slower
downstream stages only process pages that mention an NGO and a relation
cue.

## What it does

For each cleaned text file under
`data/interim/step1_content_extraction/{ngo}/text/`:

1. **NGO mention detection** — fuzzy match against every NGO name from
   `config/ngo_config.csv`, with patterns covering Czech declensions
   (e.g. `\bArnik[aáyěéuůouiíý]{0,3}\b` matches *Arnika, Arniky, Arnice,
   Arniku, Arnikou, …*).
2. **Relation keyword detection** — match against the collaboration cue
   list in `config/content_filter_keywords.yaml` (Czech and English).
3. **Scoring** — each page accumulates weighted points; pages above the
   configured threshold are kept, the rest are dropped.

## Public API

```python
from modules.keyword_filter.keyword_filter import KeywordFilter
```

The pipeline driver is
`scripts/02_filter_clean/01_extract_content.py`.

## Output

For each NGO, `data/interim/step2_keyword_filter/{ngo}/` contains:

- `text/*.txt` — pages that passed the filter (file names preserved)
- `excluded.jsonl` — one record per dropped page with the score and
  reason
- `filter_stats.json` — per-NGO summary counts

## Configuration

Keyword lists and weights live in
`config/content_filter_keywords.yaml`. Add or remove cues there rather
than in code.
