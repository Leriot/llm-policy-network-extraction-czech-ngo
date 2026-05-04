# Zenodo Data Deposit Plan

This repository is intended to keep code and documentation on GitHub while depositing the reproducibility data on Zenodo.

## GitHub Contents

- Python and R pipeline scripts.
- Configuration files.
- Documentation and methodology notes.
- Prompt/codebook files.
- Small public test fixtures and synthetic COMPON-format data.
- Final figures, tables, and compact model outputs, unless later moved fully into Zenodo.

## Zenodo Contents

Deposit the reproducibility data as a versioned Zenodo record:

- `data/raw/`
- `data/interim/`
- `data/processed/full_dataset/`
- `data/processed/final_validation/`
- `data/processed/network/`
- `data/processed/validation_history/`
- `data/processed/provenance/`
- optional copy of `outputs/`

Do not deposit restricted COMPON raw files or real COMPON matrices unless the data owner explicitly permits it.

## Recommended Workflow

1. Finalize the GitHub repository without large data committed.
2. Create a GitHub release tag, for example `v1.0.0`.
3. Link the GitHub repository to Zenodo so the release is archived.
4. Upload the data archive to Zenodo as the companion dataset record.
5. Add the minted DOI to `README.md`.
6. Cite both the GitHub release DOI and the Zenodo data DOI in thesis replication notes.

## Restore Layout

After downloading the Zenodo archive, extract it into the repository root. The restored local tree should place files back under:

```text
data/raw/
data/interim/
data/processed/
```

The scripts assume those paths unless environment variables are used for local restricted inputs.
