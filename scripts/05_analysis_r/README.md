# 05 Analysis R

R scripts for final network comparison and model outputs.

- `01_extract_compon_subset.R` extracts a 19-NGO COMPON subset from a local restricted Excel file.
- `02_network_comparison_qap_cug.R` runs network descriptives, QAP/MRQAP, CUG tests, and figure/table exports.
- `03_ergm_models.R` runs ERGM models and diagnostics.
- `04_reciprocity_permutation_check.R` runs the reciprocity permutation check.

By default, COMPON-dependent scripts use `data/external/compon_synthetic/collab_2025_compon_synthetic.csv`. Set `COMPON_MATRIX_PATH` to a local restricted matrix to reproduce real thesis comparisons.
