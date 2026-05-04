"""Build final directed edge lists and yearly matrices from LLM validation.

Inputs:
    data/processed/final_validation/aggregated_results.jsonl
    data/processed/final_validation/judged_ties.jsonl
    data/processed/network/ngo_codes.csv

Outputs:
    data/processed/network/edge_list_directed_by_year.csv
    data/processed/network/edge_list_directed_total.csv
    data/processed/network/matrices/{collab,comention}_{year}_directed.csv
    data/processed/network/matrices/{collab,comention}_total_directed.csv
"""
from __future__ import annotations

import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import csv
import json
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VALIDATION_DIR = PROJECT_ROOT / "data" / "processed" / "final_validation"
NETWORK_DIR = PROJECT_ROOT / "data" / "processed" / "network"
MATRIX_DIR = NETWORK_DIR / "matrices"
YEARS = [str(y) for y in range(2016, 2026)]
SIGNAL_LABELS = {"collaboration", "co-mention"}


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_codes(path: Path) -> tuple[list[str], dict[str, str]]:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    names = [row["ngo_name"] for row in rows]
    codes = {row["ngo_name"]: row["code"] for row in rows}
    return names, codes


def final_labels() -> list[dict]:
    judged = {
        row["id"]: row.get("judge_label")
        for row in load_jsonl(VALIDATION_DIR / "judged_ties.jsonl")
        if row.get("judge_label")
    }

    labeled = []
    for row in load_jsonl(VALIDATION_DIR / "aggregated_results.jsonl"):
        label = judged.get(row["id"]) or row.get("majority_label")
        if label not in SIGNAL_LABELS:
            continue
        labeled.append(
            {
                "id": row["id"],
                "year": str(row["year"]),
                "source_ngo": row["source_ngo"],
                "target_ngo": row["target_ngo"],
                "label": label,
            }
        )
    return labeled


def write_matrix(path: Path, names: list[str], codes: dict[str, str], active_edges: set[tuple[str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    code_order = [codes[name] for name in names]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([""] + code_order)
        for src in names:
            row = [codes[src]]
            for tgt in names:
                row.append(0 if src == tgt else int((src, tgt) in active_edges))
            writer.writerow(row)


def main() -> None:
    names, codes = load_codes(NETWORK_DIR / "ngo_codes.csv")
    rows = final_labels()

    by_year_pair: dict[tuple[str, str, str], dict[str, int]] = defaultdict(
        lambda: {"collaboration": 0, "co-mention": 0}
    )
    for row in rows:
        key = (row["source_ngo"], row["target_ngo"], row["year"])
        by_year_pair[key][row["label"]] += 1

    yearly_rows = []
    total_pair: dict[tuple[str, str], dict[str, object]] = defaultdict(
        lambda: {"years": set(), "collaboration": 0, "co-mention": 0}
    )

    for (src, tgt, year), counts in sorted(by_year_pair.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
        collab = counts["collaboration"]
        coment = counts["co-mention"]
        if collab + coment == 0:
            continue
        yearly_rows.append(
            {
                "source_ngo": src,
                "source_code": codes[src],
                "target_ngo": tgt,
                "target_code": codes[tgt],
                "year": year,
                "collab_evidence": collab,
                "comention_evidence": coment,
                "total_evidence": collab + coment,
                "has_collaboration": int(collab > 0),
            }
        )
        total_pair[(src, tgt)]["years"].add(year)
        total_pair[(src, tgt)]["collaboration"] += collab
        total_pair[(src, tgt)]["co-mention"] += coment

    NETWORK_DIR.mkdir(parents=True, exist_ok=True)
    with (NETWORK_DIR / "edge_list_directed_by_year.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "source_ngo",
            "source_code",
            "target_ngo",
            "target_code",
            "year",
            "collab_evidence",
            "comention_evidence",
            "total_evidence",
            "has_collaboration",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(yearly_rows)

    total_rows = []
    for (src, tgt), counts in sorted(total_pair.items()):
        collab = int(counts["collaboration"])
        coment = int(counts["co-mention"])
        years = sorted(counts["years"])
        total_rows.append(
            {
                "source_ngo": src,
                "source_code": codes[src],
                "target_ngo": tgt,
                "target_code": codes[tgt],
                "years_active": ";".join(years),
                "n_years": len(years),
                "collab_evidence": collab,
                "comention_evidence": coment,
                "total_evidence": collab + coment,
                "has_collaboration": int(collab > 0),
            }
        )

    with (NETWORK_DIR / "edge_list_directed_total.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "source_ngo",
            "source_code",
            "target_ngo",
            "target_code",
            "years_active",
            "n_years",
            "collab_evidence",
            "comention_evidence",
            "total_evidence",
            "has_collaboration",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(total_rows)

    for year in YEARS:
        collab_edges = {
            (row["source_ngo"], row["target_ngo"])
            for row in yearly_rows
            if row["year"] == year and int(row["collab_evidence"]) > 0
        }
        coment_edges = {
            (row["source_ngo"], row["target_ngo"])
            for row in yearly_rows
            if row["year"] == year and int(row["comention_evidence"]) > 0
        }
        write_matrix(MATRIX_DIR / f"collab_{year}_directed.csv", names, codes, collab_edges)
        write_matrix(MATRIX_DIR / f"comention_{year}_directed.csv", names, codes, coment_edges)

    write_matrix(
        MATRIX_DIR / "collab_total_directed.csv",
        names,
        codes,
        {(row["source_ngo"], row["target_ngo"]) for row in total_rows if int(row["collab_evidence"]) > 0},
    )
    write_matrix(
        MATRIX_DIR / "comention_total_directed.csv",
        names,
        codes,
        {(row["source_ngo"], row["target_ngo"]) for row in total_rows if int(row["comention_evidence"]) > 0},
    )

    print(f"Wrote {len(yearly_rows)} yearly rows and {len(total_rows)} total directed pairs.")


if __name__ == "__main__":
    main()
