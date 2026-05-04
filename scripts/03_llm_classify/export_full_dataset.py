"""
export_full_dataset.py
======================
Converts the per-year JSONL files produced by the full-dataset coding run
into various output formats suitable for analysis.

Formats
-------
    csv       — single flat CSV, one row per (source_ngo, target_ngo, article)
    edges     — network edges CSV: source_ngo, target_ngo, year, weight
                (weight = fraction of articles labelled 'collaboration')
    summary   — per-year / per-NGO-pair summary table (CSV)
    parquet   — columnar format for fast pandas loading (requires pyarrow)

Usage
-----
    # Export all years to a flat CSV
    python scripts/03_llm_classify/export_full_dataset.py --format csv

    # Export edge list (network data)
    python scripts/03_llm_classify/export_full_dataset.py --format edges

    # Export only coded rows, specific years
    python scripts/03_llm_classify/export_full_dataset.py \\
        --format csv --years 2019 2020 2021 --coded-only

    # All formats at once
    python scripts/03_llm_classify/export_full_dataset.py --format all
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_DIR  = PROJECT_ROOT / "data" / "full_dataset"
EXPORTS_DIR  = PROJECT_ROOT / "data" / "full_dataset" / "exports"

YEARS = [str(y) for y in range(2016, 2026)]


def load_all_jsonl(years: list[str], coded_only: bool = False) -> list[dict]:
    rows = []
    for year in years:
        path = DATASET_DIR / f"{year}_pairs.jsonl"
        if not path.exists():
            print(f"  [skip] {year}: {path.name} not found", file=sys.stderr)
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if coded_only and row.get("llm_label") is None:
                    continue
                rows.append(row)
    return rows


# ── Export formats ────────────────────────────────────────────────────────────

def export_csv(rows: list[dict], out_path: Path):
    """Flat CSV — one row per candidate pair."""
    fieldnames = [
        "id", "year", "source_ngo", "target_ngo", "article_name",
        "llm_label", "llm_confidence", "llm_reasoning",
        "llm_model", "llm_timestamp", "llm_cost_usd",
        "llm_prompt_tokens", "llm_completion_tokens",
    ]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ CSV:     {out_path}  ({len(rows):,} rows)")


def export_edges(rows: list[dict], out_path: Path):
    """
    Network edge list.  One row per (source_ngo, target_ngo, year) tuple.

    Columns:
        source_ngo, target_ngo, year,
        n_articles       — total articles with this pair
        n_collab         — articles labelled 'collaboration'
        n_comention      — articles labelled 'co-mention'
        collab_rate      — n_collab / n_articles
        edge_weight      — same as collab_rate (convenient alias)
        has_edge         — 1 if n_collab > 0, else 0
    """
    # Group by (source, target, year)
    key_stats: dict[tuple, dict] = defaultdict(lambda: {
        "n_articles": 0, "n_collab": 0, "n_comention": 0, "n_wrong": 0, "n_unsure": 0
    })
    for row in rows:
        k = (row["source_ngo"], row["target_ngo"], row["year"])
        s = key_stats[k]
        s["n_articles"] += 1
        label = row.get("llm_label") or ""
        if label == "collaboration":
            s["n_collab"] += 1
        elif label == "co-mention":
            s["n_comention"] += 1
        elif label == "wrong":
            s["n_wrong"] += 1
        elif label == "unsure":
            s["n_unsure"] += 1

    fieldnames = [
        "source_ngo", "target_ngo", "year",
        "n_articles", "n_collab", "n_comention", "n_wrong", "n_unsure",
        "collab_rate", "edge_weight", "has_edge",
    ]
    edge_rows = []
    for (src, tgt, yr), s in sorted(key_stats.items()):
        rate = s["n_collab"] / s["n_articles"] if s["n_articles"] > 0 else 0.0
        edge_rows.append({
            "source_ngo":  src,
            "target_ngo":  tgt,
            "year":        yr,
            **s,
            "collab_rate": round(rate, 4),
            "edge_weight": round(rate, 4),
            "has_edge":    1 if s["n_collab"] > 0 else 0,
        })

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(edge_rows)
    n_edges = sum(1 for r in edge_rows if r["has_edge"])
    print(f"  ✓ Edges:   {out_path}  ({len(edge_rows):,} pairs, {n_edges} with ≥1 collaboration)")


def export_summary(rows: list[dict], out_path: Path):
    """Per-year label distribution summary."""
    by_year: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "collaboration": 0, "co-mention": 0, "wrong": 0, "unsure": 0, "uncoded": 0
    })
    for row in rows:
        yr  = row.get("year", "?")
        lbl = row.get("llm_label") or "uncoded"
        by_year[yr]["total"] += 1
        by_year[yr][lbl]     += 1

    fieldnames = ["year", "total", "coded", "collaboration", "co-mention",
                  "wrong", "unsure", "uncoded", "collab_rate"]
    summary_rows = []
    for yr in sorted(by_year.keys()):
        s    = by_year[yr]
        coded = s["total"] - s["uncoded"]
        rate  = s["collaboration"] / coded if coded > 0 else 0.0
        summary_rows.append({
            "year":          yr,
            "total":         s["total"],
            "coded":         coded,
            "collaboration": s["collaboration"],
            "co-mention":    s["co-mention"],
            "wrong":         s["wrong"],
            "unsure":        s["unsure"],
            "uncoded":       s["uncoded"],
            "collab_rate":   round(rate, 4),
        })

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    total = sum(r["total"] for r in summary_rows)
    coded = sum(r["coded"] for r in summary_rows)
    collabs = sum(r["collaboration"] for r in summary_rows)
    print(f"  ✓ Summary: {out_path}  "
          f"({total:,} total | {coded:,} coded | {collabs:,} collaboration)")


def export_parquet(rows: list[dict], out_path: Path):
    """Parquet format (fast columnar — for large datasets and pandas analysis)."""
    try:
        import pandas as pd
    except ImportError:
        print("  [skip] Parquet: pandas not installed (pip install pandas pyarrow)")
        return

    df = pd.DataFrame(rows)
    # Drop extracted_text column from parquet (large; keep in JSONL)
    if "extracted_text" in df.columns:
        df = df.drop(columns=["extracted_text"])
    df.to_parquet(out_path, index=False)
    print(f"  ✓ Parquet: {out_path}  ({len(df):,} rows, {df.memory_usage(deep=True).sum()/1024:.0f} KB)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Export full-dataset JSONL results to CSV / edge list / parquet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--format", default="csv",
        choices=["csv", "edges", "summary", "parquet", "all"],
        help="Output format (default: csv)",
    )
    parser.add_argument(
        "--years", nargs="+", default=YEARS,
        help="Years to include (default: all 2016–2025)",
    )
    parser.add_argument(
        "--coded-only", action="store_true",
        help="Only include rows that have been coded by the LLM",
    )
    parser.add_argument(
        "--out-dir", default=str(EXPORTS_DIR),
        help=f"Output directory (default: {EXPORTS_DIR})",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nLoading JSONL from {DATASET_DIR}…")
    rows = load_all_jsonl(args.years, coded_only=args.coded_only)
    coded = sum(1 for r in rows if r.get("llm_label") is not None)
    print(f"  Loaded {len(rows):,} rows ({coded:,} coded)\n")

    if not rows:
        print("  No data found. Run build_full_dataset.py then run_full_dataset_openrouter.py first.")
        return

    suffix_coded = "_coded" if args.coded_only else "_all"
    years_tag    = "_".join(args.years) if len(args.years) < 10 else "all_years"

    do_csv     = args.format in ("csv",     "all")
    do_edges   = args.format in ("edges",   "all")
    do_summary = args.format in ("summary", "all")
    do_parquet = args.format in ("parquet", "all")

    if do_csv:
        export_csv(rows, out_dir / f"full_dataset_{years_tag}{suffix_coded}.csv")
    if do_edges:
        export_edges(rows, out_dir / f"edge_list_{years_tag}{suffix_coded}.csv")
    if do_summary:
        export_summary(rows, out_dir / f"summary_{years_tag}{suffix_coded}.csv")
    if do_parquet:
        export_parquet(rows, out_dir / f"full_dataset_{years_tag}{suffix_coded}.parquet")

    print(f"\nExports written to: {out_dir}")


if __name__ == "__main__":
    main()
