"""
aggregate_final_results.py
===========================
Merges 4 model outputs into a single table with agreement tracking.

For each datapoint:
  - Collects labels from all 4 models
  - Computes agreement level (4/0, 3/1, 2/2, etc.)
  - Determines majority_label (for 3/1 and 4/0)
  - Flags 2/2 splits for judge LLM review (next step)

Output:
  data/processed/final_validation/aggregated_results.jsonl
  data/processed/final_validation/splits_for_judge.jsonl   (2/2 disagreements)
  data/processed/final_validation/summary.json              (descriptive stats)

Usage
-----
    python scripts/03_llm_classify/aggregate_final_results.py
    python scripts/03_llm_classify/aggregate_final_results.py --stats
"""

import argparse
import json
import sys
import time
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR     = PROJECT_ROOT / "data" / "final_validation_run_data"
DATAPOINTS   = DATA_DIR / "datapoints.jsonl"

MODEL_SUFFIXES = ["scout", "mistral", "gemma", "gpt"]
MODEL_LABELS   = {"scout": "Scout", "mistral": "Mistral", "gemma": "Gemma 4", "gpt": "GPT-Nano"}


def load_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def aggregate(stats_only=False):
    # Load datapoints
    dp_list = load_jsonl(DATAPOINTS)
    dp_map  = {r["id"]: r for r in dp_list}

    # Load model results
    model_results = {}
    for suffix in MODEL_SUFFIXES:
        rfile = DATA_DIR / f"results_{suffix}.jsonl"
        rows = load_jsonl(rfile)
        model_results[suffix] = {r["id"]: r for r in rows}

    # Count coverage
    for suffix in MODEL_SUFFIXES:
        coded = sum(1 for r in model_results[suffix].values() if r.get("status") == "coded")
        total = len(dp_map)
        print(f"  {MODEL_LABELS[suffix]:10s}: {coded}/{total} coded")

    # Build aggregated rows
    agg_rows   = []
    splits     = []
    agreement_counts = Counter()  # "4/0", "3/1", "2/2", etc.
    label_counts     = Counter()  # overall label distribution

    total_cost_by_model = {s: 0.0 for s in MODEL_SUFFIXES}
    total_time_by_model = {s: 0.0 for s in MODEL_SUFFIXES}
    total_tok_in_model  = {s: 0 for s in MODEL_SUFFIXES}
    total_tok_out_model = {s: 0 for s in MODEL_SUFFIXES}

    for dp_id, dp in dp_map.items():
        labels = {}
        model_data = {}
        for suffix in MODEL_SUFFIXES:
            r = model_results[suffix].get(dp_id)
            if r and r.get("status") == "coded":
                labels[suffix] = r["label"]
                model_data[suffix] = {
                    "label":      r["label"],
                    "confidence": r.get("confidence"),
                    "reasoning":  r.get("reasoning", "")[:200],
                }
                total_cost_by_model[suffix] += r.get("cost_usd", 0)
                total_tok_in_model[suffix]  += r.get("prompt_tokens", 0)
                total_tok_out_model[suffix] += r.get("completion_tokens", 0)

        n_coded = len(labels)
        if n_coded == 0:
            continue

        label_list = list(labels.values())
        c = Counter(label_list)
        most_common_label, most_common_count = c.most_common(1)[0]

        # Agreement string
        agree_str = f"{most_common_count}/{n_coded - most_common_count}"
        agreement_counts[agree_str] += 1
        label_counts[most_common_label] += 1

        # Determine final label
        if most_common_count > n_coded / 2:
            majority_label = most_common_label
        else:
            majority_label = None  # true split — needs judge

        row = {
            "id":              dp_id,
            "year":            dp["year"],
            "source_ngo":      dp["source_ngo"],
            "target_ngo":      dp["target_ngo"],
            "article_name":    dp["article_name"],
            "agreement":       agree_str,
            "majority_label":  majority_label,
            "labels":          labels,          # {model: label}
            "model_details":   model_data,      # {model: {label, confidence, reasoning}}
        }
        agg_rows.append(row)

        if majority_label is None:
            splits.append(row)

    # Summary stats
    summary = {
        "total_datapoints":     len(dp_map),
        "aggregated":           len(agg_rows),
        "agreement_distribution": dict(agreement_counts),
        "label_distribution":   dict(label_counts),
        "splits_for_judge":     len(splits),
        "cost_by_model":        {MODEL_LABELS[s]: round(v, 4) for s, v in total_cost_by_model.items()},
        "total_cost":           round(sum(total_cost_by_model.values()), 4),
        "tokens_in_by_model":   {MODEL_LABELS[s]: v for s, v in total_tok_in_model.items()},
        "tokens_out_by_model":  {MODEL_LABELS[s]: v for s, v in total_tok_out_model.items()},
    }

    print(f"\n  Agreement distribution:")
    for k in sorted(agreement_counts, reverse=True):
        pct = agreement_counts[k] / len(agg_rows) * 100 if agg_rows else 0
        print(f"    {k}: {agreement_counts[k]:>5}  ({pct:5.1f}%)")

    print(f"\n  Majority label distribution:")
    for k, v in sorted(label_counts.items(), key=lambda x: -x[1]):
        print(f"    {k:15s}: {v:>5}")

    print(f"\n  Splits (2/2) for judge: {len(splits)}")

    print(f"\n  Cost by model:")
    for s in MODEL_SUFFIXES:
        print(f"    {MODEL_LABELS[s]:10s}: ${total_cost_by_model[s]:.4f}")
    print(f"    {'TOTAL':10s}: ${sum(total_cost_by_model.values()):.4f}")

    if stats_only:
        return

    # Write outputs
    agg_file    = DATA_DIR / "aggregated_results.jsonl"
    splits_file = DATA_DIR / "splits_for_judge.jsonl"
    summary_file = DATA_DIR / "summary.json"

    with open(agg_file, "w", encoding="utf-8") as f:
        for r in agg_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(splits_file, "w", encoding="utf-8") as f:
        for r in splits:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n  Written:")
    print(f"    {agg_file.name}: {len(agg_rows)} rows")
    print(f"    {splits_file.name}: {len(splits)} rows")
    print(f"    {summary_file.name}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stats", action="store_true", help="Show stats only, don't write files")
    args = p.parse_args()
    aggregate(stats_only=args.stats)


if __name__ == "__main__":
    main()
