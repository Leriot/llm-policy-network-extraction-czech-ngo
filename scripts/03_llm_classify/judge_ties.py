import argparse
import os
import sys
import json
import random
from collections import Counter
from pathlib import Path
from openai import OpenAI

# Force UTF-8 for Windows console
sys.stdout.reconfigure(encoding='utf-8')

MAX_OUTPUT_TOKENS = 8000   # thinking tokens + JSON output
THINKING_BUDGET   = 5000   # tokens Claude can use for internal reasoning

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
DATA_DIR     = PROJECT_ROOT / "data" / "final_validation_run_data"

PROMPT_FILE      = SCRIPT_DIR / "judge_prompt.md"
DATAPOINTS_FILE  = DATA_DIR / "datapoints.jsonl"
SPLITS_FILE      = DATA_DIR / "splits_for_judge.jsonl"
AGGREGATED_FILE  = DATA_DIR / "aggregated_results.jsonl"
OUTPUT_FILE      = DATA_DIR / "judged_ties.jsonl"
VALIDATION_FILE  = DATA_DIR / "judged_validation.jsonl"

MODEL = "anthropic/claude-sonnet-4-6"


# ── API key ────────────────────────────────────────────────────────────────────
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
    print("ERROR: OPENROUTER_API_KEY not found in environment or .env")
    sys.exit(1)


# ── Prompt ─────────────────────────────────────────────────────────────────────
def load_prompt() -> str:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"judge_prompt.md not found at {PROMPT_FILE}")
    return PROMPT_FILE.read_text(encoding="utf-8")


# ── Text helpers ───────────────────────────────────────────────────────────────
def sanitize_text(text: str) -> str:
    """Replace non-Latin/Czech characters (e.g. Cyrillic) with spaces."""
    import unicodedata
    cleaned = []
    for ch in text:
        cat = unicodedata.category(ch)
        cp  = ord(ch)
        if cp < 0x0500 or cat in ('Po', 'Pd', 'Ps', 'Pe', 'Zs'):
            cleaned.append(ch)
        else:
            cleaned.append(' ')
    return ''.join(cleaned)


def parse_response(text: str | None):
    import re
    if not text:
        return None
    # Strip thinking blocks from Claude extended thinking and Qwen <think> tags
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"<think>.*?</think>",      "", text, flags=re.DOTALL).strip()
    if not text:
        return None
    obj = None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            try:
                obj = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return obj


# ── Data loaders ───────────────────────────────────────────────────────────────
def load_datapoints() -> dict:
    """Load datapoints.jsonl → dict[id -> extracted_text].
    This is the canonical 1,000-char proximity window each model was sent."""
    data = {}
    with open(DATAPOINTS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                data[rec['id']] = rec.get('extracted_text', '')
    return data


def load_splits(datapoints: dict) -> list:
    """Load splits_for_judge.jsonl and attach extracted_text from datapoints."""
    splits = []
    missing_text = 0
    with open(SPLITS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rec['extracted_text'] = datapoints.get(rec['id'], '')
            if not rec['extracted_text']:
                missing_text += 1
            splits.append(rec)
    if missing_text:
        print(f"WARNING: {missing_text} split rows had no extracted_text in datapoints.jsonl")
    return splits


def load_existing_results(path: Path) -> dict:
    """Load already-judged rows; keyed by id. Only rows with a judge_label count."""
    results = {}
    if not path.exists():
        return results
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get('judge_label'):
                    results[rec['id']] = rec
            except json.JSONDecodeError:
                pass
    return results


# ── Validation sample ──────────────────────────────────────────────────────────
def load_validation_sample(datapoints: dict, n_unanimous: int = 9,
                            n_majority: int = 9, seed: int = 42) -> list:
    """Sample unanimous (4/0) and majority (3/1) cases from aggregated_results.jsonl
    to validate judge quality against already-known answers."""
    random.seed(seed)
    unanimous, majority = [], []

    with open(AGGREGATED_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            agreement = rec.get('agreement', '')
            if agreement == '4/0':
                rec['consensus_label'] = rec['majority_label']
                rec['consensus_type']  = '4/0'
                rec['extracted_text']  = datapoints.get(rec['id'], '')
                unanimous.append(rec)
            elif agreement == '3/1':
                rec['consensus_label'] = rec['majority_label']
                rec['consensus_type']  = '3/1'
                rec['extracted_text']  = datapoints.get(rec['id'], '')
                majority.append(rec)

    sample_u = random.sample(unanimous, min(n_unanimous, len(unanimous)))
    sample_m = random.sample(majority,  min(n_majority,  len(majority)))
    print(f"  Validation pool: {len(unanimous)} unanimous (4/0), {len(majority)} majority (3/1)")
    print(f"  Sampling {len(sample_u)} + {len(sample_m)} = {len(sample_u)+len(sample_m)} cases")
    return sample_u + sample_m


# ── User message builder ───────────────────────────────────────────────────────
def build_user_message(case: dict) -> str:
    """Build the user-turn message for a single case.

    Uses extracted_text from datapoints.jsonl — the exact same 1,000-char
    proximity window that Scout, Mistral, Gemma and GPT-Nano each received.
    Raters are anonymous (Rater 1–4) matching the prompt framing.
    """
    model_details = case.get('model_details', {})
    rater_lines = ""
    for i, (model, details) in enumerate(model_details.items(), 1):
        lbl = (details.get('label') or '?').upper()
        rsn = (details.get('reasoning') or '').replace('\n', ' ').strip()
        rater_lines += (
            f"Rater {i} Label: {lbl}\n"
            f"Rater {i} Reasoning: {rsn}\n\n"
        )

    excerpt = sanitize_text(case.get('extracted_text', ''))

    return (
        f"SOURCE NGO: {case['source_ngo']}\n"
        f"TARGET NGO: {case['target_ngo']}\n\n"
        f"<excerpt>\n{excerpt}\n</excerpt>\n\n"
        f"<reasonings>\n{rater_lines}</reasonings>\n\n"
        f"Evaluate the raters, declare the definitive label, "
        f"and state your reasoning in JSON."
    )


# ── Core judging loop ──────────────────────────────────────────────────────────
def run_judge(cases_to_judge: list, output_file: Path,
              system_prompt: str, client: OpenAI,
              mode_label: str = 'disputed', limit: int = 0):

    already_judged = load_existing_results(output_file)
    print(f"Already judged : {len(already_judged)}")

    to_judge = [c for c in cases_to_judge if c['id'] not in already_judged]
    skipped  = [c for c in cases_to_judge if c['id'] in already_judged]
    print(f"Skipping (done): {len(skipped)}")
    if limit > 0 and len(to_judge) > limit:
        print(f"--limit {limit}: capping run to {limit} cases")
        to_judge = to_judge[:limit]
    print(f"To judge now   : {len(to_judge)}\n")

    if not to_judge:
        print(f"All {mode_label} cases already judged. Nothing to do.")
        print(f"Output: {output_file}")
        _print_summary(list(already_judged.values()), output_file)
        return

    new_results = []

    for rank, case in enumerate(to_judge, 1):
        labels_dict = case.get('labels', {}) or case.get('model_details', {})
        if isinstance(next(iter(labels_dict.values()), None), dict):
            label_summary = " | ".join(
                f"{m}={d.get('label','?')}" for m, d in labels_dict.items()
            )
        else:
            label_summary = " | ".join(f"{m}={v}" for m, v in labels_dict.items())

        print(f"[{rank}/{len(to_judge)}] {case['source_ngo']} → {case['target_ngo']}")
        print(f"  Labels : {label_summary}")

        user_msg = build_user_message(case)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_msg},
        ]

        parsed     = None
        last_error = None
        raw_content = None

        for attempt in range(1, 4):
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    temperature=1,          # required when thinking is enabled
                    max_tokens=MAX_OUTPUT_TOKENS,
                    extra_headers={
                        "HTTP-Referer": "https://github.com/leriot",
                        "X-Title": "NGO Network Thesis - Judge LLM",
                    },
                    extra_body={
                        "thinking": {
                            "type": "enabled",
                            "budget_tokens": THINKING_BUDGET,
                        }
                    },
                )

                if not response.choices:
                    raise ValueError(f"Empty choices on attempt {attempt}")

                raw_content = response.choices[0].message.content
                parsed = parse_response(raw_content)

                if parsed:
                    break
                else:
                    print(f"  -> Parse failed attempt {attempt}/3, raw: {str(raw_content)[:100]}")

            except Exception as inner_e:
                last_error = inner_e
                print(f"  -> API attempt {attempt}/3 failed: {inner_e}")
                if attempt < 3:
                    import time
                    time.sleep(10 * attempt)

        if not parsed and last_error:
            print(f"  -> All attempts failed, skipping row. Error: {last_error}\n")
            continue   # don't append — will retry on next run

        if parsed:
            case['judge_label']      = parsed.get('label')
            case['judge_reasoning']  = parsed.get('reasoning')
            case['judge_confidence'] = parsed.get('confidence')
            print(f"  -> Judge: {str(case['judge_label']).upper()} [{case['judge_confidence']}]")
            print(f"     {case['judge_reasoning']}\n")
        else:
            print(f"  -> Failed to parse JSON response:\n{str(raw_content)[:200]}\n")
            continue

        new_results.append(case)

        # Write incrementally so progress survives interruption
        with open(output_file, 'w', encoding='utf-8') as f:
            for res in list(already_judged.values()) + new_results:
                f.write(json.dumps(res, ensure_ascii=False) + '\n')

    all_results = list(already_judged.values()) + new_results
    print(f"\nDone. Total in output: {len(all_results)}  "
          f"({len(already_judged)} existing + {len(new_results)} new)")
    _print_summary(all_results, output_file)


def _print_summary(results: list, output_file: Path):
    label_counts: Counter = Counter()
    confidence_counts: Counter = Counter()
    for res in results:
        lbl  = res.get('judge_label')  or 'not_judged'
        conf = res.get('judge_confidence') or 'unknown'
        label_counts[lbl] += 1
        confidence_counts[conf] += 1

    print(f"\n  Judge label distribution ({output_file.name}):")
    for lbl, cnt in label_counts.most_common():
        print(f"    {lbl:15s}: {cnt}")
    print(f"\n  Confidence distribution:")
    for conf, cnt in confidence_counts.most_common():
        print(f"    {conf:8s}: {cnt}")

    # Validation accuracy (only if consensus_label is present)
    if any('consensus_label' in r for r in results):
        correct = sum(
            1 for r in results
            if r.get('judge_label') == r.get('consensus_label')
        )
        total = sum(1 for r in results if r.get('consensus_label'))
        if total:
            print(f"\n  Validation accuracy: {correct}/{total} = {correct/total*100:.1f}%")


# ── Status ─────────────────────────────────────────────────────────────────────
def print_status():
    splits_total = sum(1 for _ in open(SPLITS_FILE, encoding='utf-8') if _.strip())
    judged       = load_existing_results(OUTPUT_FILE)
    val_judged   = load_existing_results(VALIDATION_FILE)
    print(f"Splits to judge : {splits_total}")
    print(f"Judged (main)   : {len(judged)}")
    print(f"Judged (valid.) : {len(val_judged)}")
    print(f"Remaining       : {splits_total - len(judged)}")
    if judged:
        _print_summary(list(judged.values()), OUTPUT_FILE)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=f'Judge disputed LLM tie cases via {MODEL}')
    ap.add_argument('--force', action='store_true',
                    help='Delete existing output and re-judge all cases from scratch')
    ap.add_argument('--validation', action='store_true',
                    help='Sample 9 unanimous (4/0) + 9 majority (3/1) cases for judge quality check')
    ap.add_argument('--status', action='store_true',
                    help='Print progress stats and exit')
    ap.add_argument('--limit', type=int, default=0,
                    help='Process only N cases (0 = all). Useful for test runs.')
    args = ap.parse_args()

    if args.status:
        print_status()
        sys.exit(0)

    active_file = VALIDATION_FILE if args.validation else OUTPUT_FILE

    if args.force and active_file.exists():
        print(f'--force: deleting {active_file.name} and re-running all cases...')
        active_file.unlink()

    api_key     = load_api_key()
    client      = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    system_prompt = load_prompt()
    datapoints  = load_datapoints()

    if args.validation:
        print("\n── VALIDATION MODE: sampling unanimous and majority-vote cases ──")
        cases = load_validation_sample(datapoints)
        run_judge(cases, active_file, system_prompt, client,
                  mode_label='validation', limit=args.limit)
    else:
        splits = load_splits(datapoints)
        print(f"Total splits to judge: {len(splits)}")
        run_judge(splits, active_file, system_prompt, client,
                  mode_label='disputed', limit=args.limit)
