# Sample Data

This folder contains small public fixtures for repository smoke tests and orientation. It is not a replacement for the full Zenodo data deposit.

Contents:

- `raw/Aliance_pro_energetickou_sobestacnost/pages/` - two retained raw HTML pages copied from the final public corpus.
- `processed/network/ngo_codes.csv` - 19-node code table used by network matrix scripts.
- `processed/network/matrices/collab_2025_directed.csv` - one final directed collaboration matrix for shape/order checks.

The full raw, interim, processed, validation, and network datasets are excluded from GitHub and should be restored from Zenodo.

## `pipeline_test/`

A 50-document slice of the real pipeline, kept small enough to commit to GitHub. It lets a fresh clone verify the cleaning scripts still reproduce the published outputs without needing the full Zenodo dataset, R, or any LLM API key.

### Layout

```
pipeline_test/
  picks.tsv                                - manifest: year<TAB>ngo<TAB>filename
  input_step3/{year}/{ngo}/text/*.txt      - 50 docs as they leave the date split
  expected_step4/{year}/{ngo}/text/*.txt   - same 50 docs after NGO/proximity filter
  expected_step5/{year}/{ngo}/text/*.txt   - same 50 docs after iterative cleaning
```

The slice spans 10 years (2016-2025) and 10 NGOs.

### Run

```bash
python scripts/run_sample_pipeline.py
```

This copies `input_step3/` into a temporary `_work/` tree, runs `scripts/02_filter_clean/04_filter_ngo_proximity.py` and `scripts/02_filter_clean/05_iterative_boilerplate_cleaning.py` against it, and diffs each produced file byte-for-byte against the expected snapshot. Pass criterion: at least 90% of the step5 outputs match. The intermediate step4 comparison is reported as informational only because the on-disk step4 snapshot was taken from a later iteration of the rules and will not match the freshly-produced intermediate exactly.

### What it does not cover

- Live scraping (`scripts/01_scrape/`).
- Step 1-3 (content extraction, keyword filter, date split). These scripts hardcode `data/interim/...` paths in places and depend on the per-NGO `metadata.jsonl` mapping that lives outside this slice.
- The LLM validation pipeline in `scripts/03_llm_classify/`.
- The R network analysis in `scripts/05_analysis_r/`.
