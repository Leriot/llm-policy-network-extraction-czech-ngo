"""
build_final_validation_dataset.py
==================================
Consolidates per-year full_dataset JSONL files into a single
data/processed/final_validation/datapoints.jsonl for the final 4-model run.

Each row stores: id, year, source_ngo, target_ngo, article_name,
relation_keywords, extracted_text (1000-char proximity window).

Model result files (results_*.jsonl) reference rows by id only —
no text duplication.

Usage
-----
    python scripts/03_llm_classify/build_final_validation_dataset.py
    python scripts/03_llm_classify/build_final_validation_dataset.py --force
    python scripts/03_llm_classify/build_final_validation_dataset.py --stats
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FULL_DATASET = PROJECT_ROOT / "data" / "full_dataset"
OUTPUT_DIR   = PROJECT_ROOT / "data" / "final_validation_run_data"
OUTPUT_FILE  = OUTPUT_DIR / "datapoints.jsonl"


def build(force=False, stats_only=False):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if OUTPUT_FILE.exists() and not force and not stats_only:
        n = sum(1 for line in OUTPUT_FILE.open(encoding="utf-8") if line.strip())
        print(f"[skip] {OUTPUT_FILE.name} already exists ({n} rows). Use --force.")
        return

    # Collect all base pairs (not suffixed model files)
    rows = []
    for year in range(2016, 2026):
        path = FULL_DATASET / f"{year}_pairs.jsonl"
        if not path.exists():
            print(f"  [warn] {path.name} not found — skipping")
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                rows.append({
                    "id":                r["id"],
                    "year":              r["year"],
                    "source_ngo":        r["source_ngo"],
                    "target_ngo":        r["target_ngo"],
                    "article_name":      r["article_name"],
                    "relation_keywords": r.get("relation_keywords", ""),
                    "extracted_text":    r.get("extracted_text", ""),
                })

    # Validate — check for duplicates
    ids = [r["id"] for r in rows]
    dupes = len(ids) - len(set(ids))
    if dupes:
        print(f"  WARNING: {dupes} duplicate IDs found!")

    # Check for empty extracted texts
    empty = sum(1 for r in rows if not r["extracted_text"].strip())
    warnings_with = sum(1 for r in rows if r["extracted_text"].startswith("["))

    if stats_only:
        print(f"Total datapoints: {len(rows)}")
        print(f"  Years: 2016–2025")
        print(f"  Duplicate IDs: {dupes}")
        print(f"  Empty extracted_text: {empty}")
        print(f"  Rows with [header]: {warnings_with}")
        by_year = {}
        for r in rows:
            by_year.setdefault(r["year"], 0)
            by_year[r["year"]] += 1
        for y in sorted(by_year):
            print(f"    {y}: {by_year[y]} pairs")
        # Avg text length
        lens = [len(r["extracted_text"]) for r in rows if r["extracted_text"]]
        if lens:
            avg = sum(lens) / len(lens)
            print(f"  Avg extracted_text length: {avg:.0f} chars ({avg/4:.0f} tokens est)")
        return

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Written: {OUTPUT_FILE}")
    print(f"  {len(rows)} datapoints, {dupes} dupes, {empty} empty texts")
    by_year = {}
    for r in rows:
        by_year.setdefault(r["year"], 0)
        by_year[r["year"]] += 1
    for y in sorted(by_year):
        print(f"    {y}: {by_year[y]}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true")
    p.add_argument("--stats", action="store_true")
    args = p.parse_args()
    build(force=args.force, stats_only=args.stats)


if __name__ == "__main__":
    main()
