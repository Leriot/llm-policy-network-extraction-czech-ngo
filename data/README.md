# Data Directory

## `raw/`

Final retained public raw corpus. This includes the full scraped NGO web dataset. It is intentionally not treated as an obsolete cache, but it is excluded from GitHub and should be restored locally from the Zenodo data deposit.

## `interim/`

Retained stepwise pipeline outputs:

- `step1_content_extraction/` - text extracted from raw HTML/PDF inputs.
- `step2_keyword_filter/` - keyword-filtered candidate content.
- `step3_date_filter/` - temporally filtered content.
- `step4_keyword_proximity_filtering/` - candidate files with NGO/proximity evidence.
- `step5_iterative_cleaning/` - cleaned candidate text.
- `step6_final_boilerplate_cleaned/` - final cleaned text consumed by LLM dataset construction.

These folders are excluded from GitHub and should be restored from Zenodo when reproducing the full pipeline without rerunning every upstream step.

## `processed/`

Final analysis-ready data:

- `full_dataset/` - per-year source-target candidate pair JSONL files.
- `final_validation/` - final LLM validation inputs, model outputs, agreement aggregation, and judged ties.
- `network/` - final node codes, directed edge lists, yearly matrices, total matrices, and R input matrices.
- `validation_history/` - older validation/pilot outputs retained for manual review.
- `provenance/` - scraper/session metadata retained for reproducibility.

These processed datasets are excluded from GitHub and should be deposited on Zenodo with the raw and interim data.

## `external/`

External or non-public inputs. Real COMPON data is excluded. `compon_synthetic/` contains a randomized COMPON-format matrix so R scripts can be smoke-tested without proprietary data.

## `sample/`

Reserved for smaller public samples that can be committed directly to GitHub. The full corpus belongs in the Zenodo deposit.
