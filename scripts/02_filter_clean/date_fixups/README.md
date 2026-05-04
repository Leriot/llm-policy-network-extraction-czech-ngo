# Per-NGO Date Fix-ups

Four NGOs ship publication dates in formats that the generic step-3 date
filter (`02_filter_by_date.py` / `03_split_by_year.py`) misses, leaving
their pages stuck under `data/interim/step3_date_filter/other/` with no
year assigned. These scripts re-parse the raw HTML for those NGOs using
site-specific cues and move the pages into the correct
`data/interim/step3_date_filter/{year}/{ngo}/` folder.

| Script                                | NGO                                | Date cue parsed |
| ------------------------------------- | ---------------------------------- | --------------- |
| `reprocess_ci2_dates.py`              | CI2                                | site-specific   |
| `reprocess_frank_bold_dates.py`       | Frank Bold                         | `<time>` tag inside the article div |
| `reprocess_klimaticka_koalice_dates.py` | Klimatická koalice               | site-specific   |
| `reprocess_veronica_dates.py`         | Ekologický institut Veronica       | "Vloženo: d. m. yyyy" line in article body (CMS `dc.datesubmitted` is a 2000-01-01 placeholder and is ignored) |

Each script supports `--dry-run` so you can preview the moves before they
happen. They are idempotent: re-running on an already-organised tree is a
no-op.

Run after `02_filter_by_date.py` / `03_split_by_year.py` and before
`04_filter_ngo_proximity.py`.
