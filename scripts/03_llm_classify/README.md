# 03 LLM Classify

Builds final candidate-pair JSONL files, runs multi-model validation, aggregates agreement, and adjudicates split decisions.

Core order:

1. `build_full_dataset.py`
2. `build_final_validation_dataset.py`
3. `run_final_validation.py`
4. `aggregate_final_results.py`
5. `judge_ties.py`
6. `export_full_dataset.py` if flat exports are needed

Standalone helper:

- `prepare_intercoder_sample.py` draws a proportional stratified
  sample (default 150 entries) from the step5 cleaned dataset and
  writes a CSV ready to load into the intercoder reliability tool.
  Reads `data/interim/step5_iterative_cleaning/` by default; pass
  `--input data/interim/step4_keyword_proximity_filtering` to bypass
  the boilerplate-cleaning step.
