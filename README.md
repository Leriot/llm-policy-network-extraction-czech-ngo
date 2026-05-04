# Czech NGO Collaboration Network Thesis Repository

Replication repository for a master's thesis on reconstructing Czech environmental NGO collaboration networks from public web data and comparing them to COMPON survey data.

## What This Reproduces

This repo preserves the final pipeline used to:

1. retain the full scraped public NGO web corpus,
2. extract and filter article text,
3. build source-target NGO candidate pairs,
4. classify collaboration evidence with LLM validation,
5. construct directed yearly network edge lists and matrices, and
6. run network comparison, QAP/MRQAP/CUG, and ERGM analyses in R.

## License

MIT — see [`LICENSE`](LICENSE). Use this code and documentation for
anything you like. See [`NOTICE`](NOTICE) for the boundary between
MIT-licensed code and the COMPON-derived figures and tables in
`outputs/`, which are research outputs published under the author's
COMPON data-use agreement rather than under MIT.

## Data Availability

The GitHub repository contains code, configuration, documentation, small test fixtures, and final thesis artifacts. The full data deposit is archived separately on Zenodo and cited with its DOI.

See `docs/dependency_audit.md` for the runtime dependency audit and `docs/data_deposit_zenodo.md` for the data deposit plan.

Recommended Zenodo deposit contents:

- `data/raw/` - final retained public raw corpus.
- `data/interim/` - retained pipeline steps from extraction through final boilerplate-cleaned text.
- `data/processed/full_dataset/` - per-year candidate pair JSONL files.
- `data/processed/final_validation/` - final validation inputs, model outputs, agreement aggregation, and judged ties.
- `data/processed/network/` - final directed edge lists, node codes, yearly matrices, and R input matrices.
- `data/processed/validation_history/` - older validation/pilot outputs retained for manual review.
- `data/processed/provenance/` - scraper/session metadata.

After downloading the Zenodo archive, extract it into the repository root so those paths exist locally.

Zenodo DOI: `https://doi.org/10.5281/zenodo.20024166`

## Data Excluded

Real COMPON raw data and matrices are not included in GitHub or the public Zenodo deposit because they are restricted/proprietary. The repo includes `data/external/compon_synthetic/collab_2025_compon_synthetic.csv`, a randomized matrix with the same 19-node format for testing R scripts.

To rerun the real COMPON comparison, provide your local restricted matrix path:

```bash
set COMPON_MATRIX_PATH=C:\path\to\collab_2025_compon.csv
```

or for extracting the COMPON subset from the restricted Excel file:

```bash
set COMPON_COLLABORATION_XLSX=C:\path\to\CZ2025_COLLABORATION_NET.xlsx
```

## Quick Start (Sanity Check)

A fresh clone can verify the cleaning logic against a 50-document sample
slice (`data/sample/pipeline_test/`) without needing the full Zenodo
data, R, or any LLM API key:

```bash
python -m venv .venv
. .venv/Scripts/activate           # PowerShell: . .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/run_sample_pipeline.py
```

Expect `result : PASS` (50/50 step5 outputs match the snapshot).

## Pipeline Order

```bash
python scripts/01_scrape/batch_scrape_parallel.py --all --workers 6 --yes
python scripts/02_filter_clean/01_extract_content.py
python scripts/02_filter_clean/02_filter_by_date.py --all --start-date 2016-01-01 --end-date 2025-12-31
python scripts/02_filter_clean/03_split_by_year.py --all
# Per-NGO date fix-ups for four sources whose dates the generic filter misses:
python scripts/02_filter_clean/date_fixups/reprocess_ci2_dates.py
python scripts/02_filter_clean/date_fixups/reprocess_frank_bold_dates.py
python scripts/02_filter_clean/date_fixups/reprocess_klimaticka_koalice_dates.py
python scripts/02_filter_clean/date_fixups/reprocess_veronica_dates.py
python scripts/02_filter_clean/04_filter_ngo_proximity.py
python scripts/02_filter_clean/05_iterative_boilerplate_cleaning.py
python scripts/03_llm_classify/build_full_dataset.py
python scripts/03_llm_classify/build_final_validation_dataset.py
python scripts/03_llm_classify/run_final_validation.py --all --parallel
python scripts/03_llm_classify/aggregate_final_results.py
python scripts/03_llm_classify/judge_ties.py
python scripts/04_network_build/01_build_directed_network_outputs.py
```

Then run the R analysis scripts:

```bash
Rscript scripts/04_network_build/03_merge_raw_comention_collab_matrices.R
Rscript scripts/05_analysis_r/02_network_comparison_qap_cug.R
Rscript scripts/05_analysis_r/03_ergm_models.R
```

## Final Outputs

- Network edge lists and matrices: `data/processed/network/`
- Figures: `outputs/figures/`
- Thesis tables: `outputs/tables/`
- Network comparison report: `outputs/reports/network_comparison_report.txt`
- ERGM results and diagnostics: `outputs/model_results/ergm/`
