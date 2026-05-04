"""
run_final_validation.py
========================
Final 4-model LLM validation run.

Models: Scout, Mistral, Gemma 4, GPT-5.4 Nano
Input:  data/processed/final_validation/datapoints.jsonl  (3086 rows, text stored once)
Output: data/processed/final_validation/results_{suffix}.jsonl per model
        (id + label/reasoning/confidence/model/tokens/cost/status — no input text)

Features:
  - Parallel 4-model execution via threads
  - Live dashboard with per-model progress bars
  - Full resume: coded rows skipped, ERROR rows retried
  - Cost/time tracking per model and total

Usage
-----
    python scripts/03_llm_classify/run_final_validation.py --status
    python scripts/03_llm_classify/run_final_validation.py --model scout
    python scripts/03_llm_classify/run_final_validation.py --all
    python scripts/03_llm_classify/run_final_validation.py --all --parallel
    python scripts/03_llm_classify/run_final_validation.py --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
import datetime
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR     = PROJECT_ROOT / "data" / "final_validation_run_data"
DATAPOINTS   = DATA_DIR / "datapoints.jsonl"
BACKUP_DIR   = DATA_DIR / "backups"

BACKUP_INTERVAL_SEC = 300   # every 5 minutes
BACKUP_KEEP         = 6     # keep last 6 backups (~30 min of history)


# ── Backup thread ─────────────────────────────────────────────────────────────
def _backup_worker(stop_event: threading.Event):
    """
    Background thread: copies all results_*.jsonl to backups/ every 5 minutes.
    Also runs once immediately on launch so the first backup exists right away.
    Keeps the last BACKUP_KEEP snapshots and deletes older ones.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    def do_backup():
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        result_files = sorted(DATA_DIR.glob("results_*.jsonl"))
        if not result_files:
            return
        snap_dir = BACKUP_DIR / ts
        snap_dir.mkdir(exist_ok=True)
        import shutil
        for f in result_files:
            shutil.copy2(f, snap_dir / f.name)
        # Prune old backups
        all_snaps = sorted(BACKUP_DIR.iterdir())
        for old in all_snaps[:-BACKUP_KEEP]:
            if old.is_dir():
                shutil.rmtree(old)

    # Immediate backup on launch
    do_backup()

    while not stop_event.wait(BACKUP_INTERVAL_SEC):
        do_backup()


def start_backup_thread() -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    t = threading.Thread(target=_backup_worker, args=(stop,), daemon=True, name="backup")
    t.start()
    return t, stop

# ── Model configs ─────────────────────────────────────────────────────────────
MODELS = {
    "scout": {
        "model_id":     "meta-llama/llama-4-scout",
        "suffix":       "scout",
        "input_price":  0.15,   # $/M tokens
        "output_price": 0.60,
        "cache_price":  0.015,
        "label":        "Scout",
    },
    "mistral": {
        "model_id":     "mistralai/mistral-small-2603",
        "suffix":       "mistral",
        "input_price":  0.10,
        "output_price": 0.30,
        "cache_price":  0.015,
        "label":        "Mistral",
    },
    "gemma": {
        "model_id":     "google/gemma-4-31b-it:nitro",
        "suffix":       "gemma",
        "input_price":  0.00,
        "output_price": 0.00,
        "cache_price":  0.00,
        "label":        "Gemma 4",
    },
    "gpt": {
        "model_id":     "openai/gpt-5.4-nano",
        "suffix":       "gpt",
        "input_price":  0.10,
        "output_price": 0.40,
        "cache_price":  0.025,
        "label":        "GPT-Nano",
    },
}

# ── OpenRouter config ─────────────────────────────────────────────────────────
OPENROUTER_URL    = "https://openrouter.ai/api/v1/chat/completions"
TEMPERATURE       = 0.1
MAX_TOKENS        = 2000
FREQUENCY_PENALTY = 0.4
SEED              = 42
TIMEOUT_SEC       = 120

# ── Prompt ────────────────────────────────────────────────────────────────────
# Imported from prompt_loader.py (same codebook as all previous runs)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompt_loader import FALLBACK_CODEBOOK, build_system_prompt, build_user_prompt

SYSTEM_PROMPT = build_system_prompt(FALLBACK_CODEBOOK)

# ── API key ───────────────────────────────────────────────────────────────────
def load_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return key
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key
    print("ERROR: OPENROUTER_API_KEY not found.")
    sys.exit(1)


# ── JSONL helpers ─────────────────────────────────────────────────────────────
def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  [warn] corrupt line {line_no} in {path.name}")
    return rows


def save_jsonl(rows: list[dict], path: Path):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── Load datapoints ──────────────────────────────────────────────────────────
def load_datapoints() -> dict[str, dict]:
    """Load datapoints.jsonl into {id: row_dict}."""
    rows = load_jsonl(DATAPOINTS)
    return {r["id"]: r for r in rows}


# ── API call ──────────────────────────────────────────────────────────────────
VALID_LABELS = {"collaboration", "co-mention", "wrong", "unsure"}
VALID_CONF   = {"high", "low"}


def call_openrouter(user_prompt: str, model: str, api_key: str) -> tuple[str, int, int, int]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://github.com/leriot/ngo-thesis",
        "X-Title":       "NGO Final Validation",
    }
    payload = {
        "model":             model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature":       TEMPERATURE,
        "max_tokens":        MAX_TOKENS,
        "frequency_penalty": FREQUENCY_PENALTY,
        "seed":              SEED,
        "response_format":   {"type": "json_object"},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = requests.post(OPENROUTER_URL, headers=headers, data=body, timeout=TIMEOUT_SEC)
    resp.raise_for_status()
    data = resp.json()

    usage  = data.get("usage", {})
    pt     = usage.get("prompt_tokens", 0)
    ct     = usage.get("completion_tokens", 0)
    cached = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
    content = data["choices"][0]["message"]["content"]
    if content is None:
        raise ValueError("Model returned null content")
    return content.strip(), pt, ct, cached


def parse_response(text: str) -> dict | None:
    # Strip <think> blocks (Qwen/Gemma reasoning)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    obj = None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            try:
                obj = json.loads(text[s:e+1])
            except json.JSONDecodeError:
                pass
    if obj:
        label      = str(obj.get("label", "")).strip().lower()
        reasoning  = str(obj.get("reasoning", "")).strip()
        confidence = str(obj.get("confidence", "high")).strip().lower()
        if label in VALID_LABELS:
            return {
                "label":      label,
                "reasoning":  reasoning,
                "confidence": confidence if confidence in VALID_CONF else "high",
            }
    return None


# ── Progress state (shared across threads) ────────────────────────────────────
class ModelProgress:
    def __init__(self, model_key: str, total: int):
        self.model_key     = model_key
        self.label         = MODELS[model_key]["label"]
        self.total         = total
        self.coded         = 0   # total coded including previous sessions (for display)
        self.session_coded = 0   # coded THIS session only (for rate/ETA calculation)
        self.errors        = 0
        self.cost          = 0.0
        self.tok_in        = 0
        self.tok_out       = 0
        self.start         = time.time()
        self.last_msg      = ""
        self.done          = False
        self.lock          = threading.Lock()


# ── Dashboard display ─────────────────────────────────────────────────────────
_DISPLAY_LOCK = threading.Lock()


def render_dashboard(progresses: list[ModelProgress], start_time: float):
    """Render a static dashboard. Uses ANSI cursor movement on Win10+."""
    lines = []
    lines.append("+" + "-"*68 + "+")
    lines.append("|  FINAL VALIDATION RUN - 4 Models x {:,} Datapoints{:>14}|".format(
        progresses[0].total if progresses else 0, ""))

    lines.append("+" + "-"*68 + "+")

    total_cost   = 0.0
    total_errors = 0
    for p in progresses:
        with p.lock:
            done         = p.coded
            session_done = p.session_coded   # only rows coded this session
            errs         = p.errors
            cost         = p.cost
            total        = p.total
            t_in         = p.tok_in
            t_out        = p.tok_out
            msg          = p.last_msg
            is_done      = p.done

        pct = done / total * 100 if total else 0
        bar_len  = 20
        filled   = int(bar_len * done / total) if total else 0
        bar      = "#" * filled + "." * (bar_len - filled)

        elapsed = time.time() - p.start
        remaining = total - done
        # Use only this-session throughput for ETA — avoids skew from resumed runs
        if session_done > 0 and not is_done:
            avg_sec = elapsed / session_done
            eta_str = f"ETA {remaining * avg_sec / 60:.0f}m"
        elif is_done:
            eta_str = f"done {elapsed/60:.0f}m"
        else:
            eta_str = "starting"

        lines.append("|  {:<8} [{}]  {:>4}/{:<4}  ({:5.1f}%)  {:>10}  ${:.3f}  |".format(
            p.label, bar, done, total, pct, eta_str, cost))

        total_cost   += cost
        total_errors += errs

    lines.append("+" + "-"*68 + "+")
    elapsed = time.time() - start_time
    lines.append("|  Total cost: ${:<8.3f}  Elapsed: {:<8}  Errors: {:<5}       |".format(
        total_cost, f"{elapsed/60:.1f}m", total_errors))
    lines.append("+" + "-"*68 + "+")

    # Add last iteration messages
    for p in progresses:
        with p.lock:
            msg = p.last_msg
        if msg:
            lines.append(f"  [{p.label:8s}] {msg}")

    with _DISPLAY_LOCK:
        # Move cursor up to overwrite previous dashboard
        n_lines = len(lines)
        sys.stdout.write(f"\033[{n_lines + 1}A\033[J")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()


# ── Single-model worker ──────────────────────────────────────────────────────
def run_model_worker(
    model_key:   str,
    datapoints:  dict[str, dict],
    api_key:     str,
    progress:    ModelProgress,
    force_recode: bool = False,
):
    cfg        = MODELS[model_key]
    suffix     = cfg["suffix"]
    model_id   = cfg["model_id"]
    in_price      = cfg["input_price"]
    out_price     = cfg["output_price"]
    cache_price   = cfg["cache_price"]
    request_delay = cfg.get("request_delay", 0.0)  # extra sleep between calls (free tiers)

    result_file = DATA_DIR / f"results_{suffix}.jsonl"

    # Load existing results (for resume)
    existing = {}
    if result_file.exists():
        for r in load_jsonl(result_file):
            existing[r["id"]] = r

    # Determine what needs coding
    all_ids = list(datapoints.keys())
    todo_ids = []
    already_coded = 0
    for dp_id in all_ids:
        if dp_id in existing:
            ex = existing[dp_id]
            if ex.get("status") == "coded" and not force_recode:
                already_coded += 1
                continue
            # ERROR or empty → retry
        todo_ids.append(dp_id)

    with progress.lock:
        progress.coded = already_coded

    if not todo_ids:
        with progress.lock:
            progress.done = True
            progress.last_msg = f"fully coded ({len(all_ids)} rows)"
        return

    for rank, dp_id in enumerate(todo_ids, 1):
        dp = datapoints[dp_id]
        user_prompt = build_user_prompt(dp)

        result = None
        pt, ct, cached = 0, 0, 0
        error_msg = ""

        for attempt in range(1, 4):
            try:
                raw, pt, ct, cached = call_openrouter(user_prompt, model_id, api_key)
                result = parse_response(raw)
                if result is None:
                    if attempt < 3:
                        time.sleep(2)
                        continue
                    error_msg = "parse-fail"
                else:
                    break
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else "?"
                body   = e.response.text[:120] if e.response else ""
                error_msg = f"http-{status}: {body}"
                sleep_sec = 20 if status == 429 else 5 * attempt
                if attempt < 3:
                    time.sleep(sleep_sec)
                # Last attempt: falls through with error_msg set
            except Exception as e:
                error_msg = str(e)[:120]
                if attempt < 3:
                    time.sleep(5)

        # Calculate cost
        in_cost     = (pt - cached) * in_price / 1_000_000
        cached_cost = cached * cache_price / 1_000_000
        out_cost    = ct * out_price / 1_000_000
        row_cost    = in_cost + cached_cost + out_cost

        if result:
            row_out = {
                "id":               dp_id,
                "status":           "coded",
                "label":            result["label"],
                "reasoning":        result["reasoning"],
                "confidence":       result["confidence"],
                "model":            model_id,
                "timestamp":        datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "prompt_tokens":    pt,
                "completion_tokens": ct,
                "cost_usd":         round(row_cost, 6),
            }
            msg = f"{result['label']:13s} {result['confidence']:4s} | {pt:4d}->{ct:3d} tok ${row_cost:.4f}  {dp['source_ngo'][:18]}->{dp['target_ngo'][:18]}"
        else:
            row_out = {
                "id":               dp_id,
                "status":           "ERROR",
                "label":            None,
                "reasoning":        error_msg,
                "confidence":       None,
                "model":            model_id,
                "timestamp":        datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "prompt_tokens":    pt,
                "completion_tokens": ct,
                "cost_usd":         round(row_cost, 6),
            }
            msg = f"ERROR: {error_msg[:60]}"

        existing[dp_id] = row_out

        # Write full results file after each row
        save_jsonl(list(existing.values()), result_file)

        with progress.lock:
            if result:
                progress.coded         += 1
                progress.session_coded += 1   # this session only — used for ETA rate
            else:
                progress.errors += 1
            progress.cost   += row_cost
            progress.tok_in += pt
            progress.tok_out += ct
            progress.last_msg = msg

        # Throttle for free-tier models
        if request_delay > 0:
            time.sleep(request_delay)

    with progress.lock:
        progress.done = True


# ── Status display ────────────────────────────────────────────────────────────
def print_status():
    if not DATAPOINTS.exists():
        print("datapoints.jsonl not found. Run build_final_validation_dataset.py first.")
        return

    dp = load_datapoints()
    total = len(dp)

    print(f"\n  FINAL VALIDATION STATUS")
    print(f"  Datapoints: {total:,}")
    print()

    all_results = {}
    for key, cfg in MODELS.items():
        rfile = DATA_DIR / f"results_{cfg['suffix']}.jsonl"
        rows = load_jsonl(rfile) if rfile.exists() else []
        coded  = sum(1 for r in rows if r.get("status") == "coded")
        errors = sum(1 for r in rows if r.get("status") == "ERROR")
        cost   = sum(r.get("cost_usd", 0) for r in rows)
        tok_in = sum(r.get("prompt_tokens", 0) for r in rows)
        tok_out = sum(r.get("completion_tokens", 0) for r in rows)
        remaining = total - coded

        all_results[key] = {r["id"]: r for r in rows if r.get("status") == "coded"}

        pct = coded / total * 100 if total else 0
        bar_len = 25
        filled  = int(bar_len * coded / total) if total else 0
        bar     = "#" * filled + "." * (bar_len - filled)

        # Estimate remaining cost
        if coded > 0:
            avg_cost = cost / coded
            est_remaining = avg_cost * remaining
        else:
            avg_in = 1050
            est_remaining = remaining * (avg_in * cfg["input_price"] + 150 * cfg["output_price"]) / 1e6

        status_line = "done" if coded == total else f"{errors} err" if errors else ""
        print(f"  {cfg['label']:10s} [{bar}]  {coded:>4}/{total}  ({pct:5.1f}%)  ${cost:.3f}  rem: ${est_remaining:.2f}  {status_line}")

    print()

    # Agreement summary (only for fully-coded models)
    coded_models = [k for k, v in all_results.items() if len(v) == total]
    if len(coded_models) >= 2:
        print(f"  Agreement ({len(coded_models)} models fully coded):")
        agree_counts = {4: 0, 3: 0, 2: 0, 1: 0}
        for dp_id in dp:
            labels = [all_results[m][dp_id]["label"] for m in coded_models if dp_id in all_results[m]]
            if not labels:
                continue
            from collections import Counter
            c = Counter(labels)
            max_agree = c.most_common(1)[0][1]
            agree_counts[min(max_agree, 4)] += 1
        for k in sorted(agree_counts, reverse=True):
            if agree_counts[k]:
                print(f"    {k}/{len(coded_models)} agreement: {agree_counts[k]:,} rows")
    print()

    # Total estimated cost for full run
    total_est = 0
    for key, cfg in MODELS.items():
        avg_in  = 1050
        avg_out = 150
        total_est += total * (avg_in * cfg["input_price"] + avg_out * cfg["output_price"]) / 1e6
    print(f"  Estimated total cost (all 4 models, {total:,} rows): ${total_est:.2f}")
    print()


# ── Dry run ───────────────────────────────────────────────────────────────────
def dry_run():
    dp = load_datapoints()
    total = len(dp)
    print(f"\n  DRY RUN — Final Validation")
    print(f"  Datapoints: {total:,}")
    print()

    # Verify all datapoints have valid data
    issues = 0
    for dp_id, r in dp.items():
        if not r.get("extracted_text", "").strip():
            print(f"  [EMPTY] {dp_id}: {r['year']}/{r['source_ngo']}/{r['article_name']}")
            issues += 1
        if r.get("extracted_text", "").startswith("["):
            # header-only text (warning/fallback) — should have been filtered
            header_end = r["extracted_text"].find("]")
            body = r["extracted_text"][header_end+1:].strip() if header_end != -1 else ""
            if len(body) < 50:
                print(f"  [SHORT] {dp_id}: only {len(body)} chars after header")
                issues += 1

    print(f"\n  Issues found: {issues}")
    if issues == 0:
        print("  All datapoints valid!")

    print(f"\n  Cost estimates per model (avg ~1050 in + 150 out tokens/row):")
    total_est = 0
    for key, cfg in MODELS.items():
        cost = total * (1050 * cfg["input_price"] + 150 * cfg["output_price"]) / 1e6
        total_est += cost
        print(f"    {cfg['label']:10s}: ${cost:.3f}  ({cfg['model_id']})")
    print(f"    {'TOTAL':10s}: ${total_est:.3f}")
    print(f"\n  Estimated time at 1.5s/call avg: {total * 1.5 / 60:.0f} min per model")
    print(f"  Parallel 4 models: ~{total * 1.5 / 60:.0f} min total wall time")
    print()


# ── Main entry ────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--model", choices=list(MODELS),
                   help="Run a single model")
    g.add_argument("--all", action="store_true",
                   help="Run all 4 models")
    g.add_argument("--status", action="store_true",
                   help="Show status and exit")
    g.add_argument("--dry-run", action="store_true",
                   help="Validate data and show cost estimates")

    p.add_argument("--parallel", action="store_true",
                   help="Run models in parallel threads (with --all)")
    p.add_argument("--force-recode", action="store_true",
                   help="Re-run already-coded rows")

    args = p.parse_args()

    if args.status:
        print_status()
        return
    if args.dry_run:
        dry_run()
        return

    if not DATAPOINTS.exists():
        print("ERROR: datapoints.jsonl not found. Run build_final_validation_dataset.py first.")
        sys.exit(1)

    api_key    = load_api_key()
    datapoints = load_datapoints()
    total      = len(datapoints)

    models_to_run = list(MODELS.keys()) if args.all else [args.model]

    # Enable ANSI escape on Windows
    if sys.platform == "win32":
        os.system("")

    # ── Start backup thread (runs for entire session, backs up every 5 min) ──
    backup_thread, backup_stop = start_backup_thread()
    print(f"  Backup thread started → backups/ (every {BACKUP_INTERVAL_SEC//60} min, keep last {BACKUP_KEEP})")

    if args.parallel and len(models_to_run) > 1:
        # ── Parallel mode ─────────────────────────────────────────────────
        start_time = time.time()
        progresses = [ModelProgress(k, total) for k in models_to_run]

        # Print blank lines for dashboard space
        dash_lines = len(progresses) + 7  # header + bars + footer + messages
        print("\n" * dash_lines)

        # Launch workers
        futures = {}
        with ThreadPoolExecutor(max_workers=len(models_to_run)) as executor:
            for i, model_key in enumerate(models_to_run):
                f = executor.submit(
                    run_model_worker, model_key, datapoints, api_key,
                    progresses[i], args.force_recode
                )
                futures[f] = model_key

            # Dashboard refresh loop
            all_done = False
            while not all_done:
                time.sleep(1.0)
                render_dashboard(progresses, start_time)
                all_done = all(p.done for p in progresses)

            # Final render
            render_dashboard(progresses, start_time)

        # Collect errors
        for f in futures:
            try:
                f.result()
            except Exception as e:
                print(f"\n  [FATAL] {futures[f]}: {e}")

        elapsed = time.time() - start_time
        total_cost = sum(p.cost for p in progresses)
        total_err  = sum(p.errors for p in progresses)
        print(f"\n  DONE  Elapsed: {elapsed/60:.1f}m  Cost: ${total_cost:.3f}  Errors: {total_err}")

    else:
        # ── Sequential mode ──────────────────────────────────────────────
        start_time = time.time()

        for model_key in models_to_run:
            cfg   = MODELS[model_key]
            total = len(datapoints)
            prog  = ModelProgress(model_key, total)

            print(f"\n  Starting {cfg['label']} ({cfg['model_id']})")
            print(f"  Output: results_{cfg['suffix']}.jsonl")
            print(f"  Pricing: ${cfg['input_price']:.3f}/M in  ${cfg['output_price']:.3f}/M out")
            print()

            # Print blank lines for single-model dashboard
            print("\n" * 8)

            run_model_worker(model_key, datapoints, api_key, prog, args.force_recode)

            # Print summary for this model
            print(f"\n  {cfg['label']}: {prog.coded} coded, {prog.errors} errors, ${prog.cost:.3f}")

    elapsed = time.time() - start_time
    print(f"\n  All done. Elapsed: {elapsed/60:.1f}m")

    # ── Stop backup thread cleanly ─────────────────────────────────────────
    backup_stop.set()
    backup_thread.join(timeout=5)


if __name__ == "__main__":
    main()