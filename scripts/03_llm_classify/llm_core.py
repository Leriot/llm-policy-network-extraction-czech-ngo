"""
llm_core.py
===========
Shared library for all LLM coding scripts in this project.
Import this instead of copy-pasting API logic.

Public API
----------
    from llm_core import (
        load_api_key, load_prompt, build_user_prompt, parse_response,
        call_openrouter, call_ollama, load_jsonl, save_jsonl, run_rows,
    )

run_rows() is the main coding loop — it handles retry, error counting,
per-row save, and progress printing. Pass a caller_fn that wraps either
call_openrouter or call_ollama with your model/key/seed baked in.
"""

import json
import os
import re
import sys
import time
import datetime
from pathlib import Path

import requests

# ── Project root (two levels up from this file) ────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── OpenRouter defaults (can be overridden per call) ──────────────────────────
OR_URL       = "https://openrouter.ai/api/v1/chat/completions"
OR_SEED      = 67
OR_TEMP      = 0.1
OR_MAX_TOK   = 800
OR_TIMEOUT   = 60

# ── Ollama defaults ────────────────────────────────────────────────────────────
OLLAMA_URL   = "http://localhost:{port}/api/chat"
OL_SEED      = 67
OL_TEMP      = 0.1
OL_MAX_TOK   = 800
OL_TIMEOUT   = 180
OL_PORT      = 11434

VALID_LABELS = {"collaboration", "co-mention", "wrong", "unsure"}
VALID_CONF   = {"high", "low"}


# ── API key ────────────────────────────────────────────────────────────────────

def load_api_key() -> str:
    """Load OPENROUTER_API_KEY from env or .env file."""
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
    print("ERROR: OPENROUTER_API_KEY not set in environment or .env file.")
    sys.exit(1)


# ── Prompt loader ──────────────────────────────────────────────────────────────

def load_prompt(prompt_file: Path) -> tuple[str, str]:
    """
    Parse a prompt .md file into (system_prompt, user_check_template).

    Expects sections delimited by "## SECTION_NAME" headings.
    user_check_template contains a {target_ngo} placeholder.
    """
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    raw = prompt_file.read_text(encoding="utf-8")

    def _section(tag: str) -> str:
        m = re.search(
            rf"^## {re.escape(tag)}\s*\n(.*?)(?=^## |\Z)",
            raw, re.MULTILINE | re.DOTALL,
        )
        return m.group(1).strip() if m else ""

    system_prompt = "\n\n".join(filter(None, [
        _section("SYSTEM_INTRO"),
        "## CODEBOOK\n\n" + _section("CODEBOOK") if _section("CODEBOOK") else "",
        "## EXAMPLES\n\n" + _section("EXAMPLES") if _section("EXAMPLES") else "",
        "## OUTPUT FORMAT\n\n" + _section("JSON_FORMAT") if _section("JSON_FORMAT") else "",
        "Respond with ONLY the JSON object — no markdown fences, no preamble, no text outside the brackets.",
    ]))

    user_check = _section("USER_CHECK")
    return system_prompt, user_check


def build_user_prompt(row: dict, user_check_template: str, text_field: str = "excerpt_text") -> str:
    """
    Build the per-row user prompt.

    text_field: key in row to use as the passage — "excerpt_text" (default)
                or "extracted_text" for old-style scraper excerpts.
    The passage is wrapped in <excerpt> tags regardless.
    """
    target_ngo = row.get("target_ngo", "")
    text       = (row.get(text_field) or row.get("excerpt_text") or row.get("extracted_text") or "").strip()
    # Strip [✓/⚠ ...] intercoder header lines if present
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            text = "\n".join(lines[i + 1:]).strip()
            break

    user_check = user_check_template.replace("{target_ngo}", target_ngo)
    return (
        f"SOURCE NGO (publisher): {row.get('source_ngo', '')}\n"
        f"TARGET NGO (to find):   {target_ngo}\n"
        f"Year: {row.get('year', '?')}\n"
        f"Keywords that triggered this pair: {row.get('relation_keywords', '')}\n\n"
        f"<excerpt>\n{text}\n</excerpt>\n\n"
        f"{user_check}"
    )


# ── Response parser ────────────────────────────────────────────────────────────

def parse_response(text: str) -> dict | None:
    """
    Parse the model's JSON response into {label, reasoning, confidence}.
    Returns None if unparseable (caller should retry).
    Strips Qwen <think>...</think> blocks automatically.
    """
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    obj  = None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            try:
                obj = json.loads(text[s:e + 1])
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


# ── API callers ────────────────────────────────────────────────────────────────

def call_openrouter(
    system_prompt: str,
    user_prompt:   str,
    model_id:      str,
    api_key:       str,
    *,
    seed:          int   = OR_SEED,
    temperature:   float = OR_TEMP,
    max_tokens:    int   = OR_MAX_TOK,
    timeout:       int   = OR_TIMEOUT,
    force_json:    bool  = True,
    referer:       str   = "https://github.com/leriot/ngo-thesis",
    title:         str   = "NGO Network Study",
) -> tuple[str, int, int]:
    """Returns (response_text, prompt_tokens, completion_tokens)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  referer,
        "X-Title":       title,
    }
    payload: dict = {
        "model":       model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "seed":        seed,
    }
    if force_json:
        payload["response_format"] = {"type": "json_object"}

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = requests.post(OR_URL, headers=headers, data=body, timeout=timeout)
    resp.raise_for_status()
    data    = resp.json()
    content = data["choices"][0]["message"]["content"]
    if content is None:
        raise ValueError("Model returned null content.")
    usage = data.get("usage", {})
    return content.strip(), usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def call_ollama(
    system_prompt: str,
    user_prompt:   str,
    model:         str,
    *,
    port:          int   = OL_PORT,
    seed:          int   = OL_SEED,
    temperature:   float = OL_TEMP,
    max_tokens:    int   = OL_MAX_TOK,
    timeout:       int   = OL_TIMEOUT,
) -> tuple[str, int, int]:
    """Returns (response_text, prompt_tokens, completion_tokens)."""
    url = OLLAMA_URL.format(port=port)
    payload = {
        "model":  model,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "seed":        seed,
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "format": "json",
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    content = data.get("message", {}).get("content", "")
    return content.strip(), data.get("prompt_eval_count", 0), data.get("eval_count", 0)


# ── JSONL helpers ──────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def save_jsonl(rows: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── Core coding loop ───────────────────────────────────────────────────────────

def run_rows(
    rows:         list[dict],
    todo:         list[tuple[int, dict]],   # [(row_index, row_dict), ...]
    caller_fn,                              # callable(system_prompt, user_prompt) → (text, pt, ct)
    system_prompt: str,
    user_check:   str,
    label_key:    str,                      # e.g. "label_mistral_r1"
    prefix:       str,                      # e.g. "mistral_r1" — used for reasoning/confidence keys
    out_path:     Path,
    text_field:   str  = "excerpt_text",    # which field to use as passage
    max_retries:  int  = 3,
    log          = None,                    # callable(msg) — defaults to print
) -> dict:
    """
    Core coding loop: iterate todo rows, call the model, parse, save.

    Keys written to each row:
      label_{prefix}       reasoning_{prefix}   confidence_{prefix}
      tokens_in_{prefix}   tokens_out_{prefix}  ts_{prefix}

    Returns a summary dict:
      {processed, errors, tokens_in, tokens_out, elapsed}
    """
    if log is None:
        log = print

    errors    = 0
    processed = 0
    total_in  = 0
    total_out = 0
    start     = time.time()

    reasoning_key   = f"reasoning_{prefix}"
    confidence_key  = f"confidence_{prefix}"
    tokens_in_key   = f"tokens_in_{prefix}"
    tokens_out_key  = f"tokens_out_{prefix}"
    ts_key          = f"ts_{prefix}"

    for rank, (row_idx, row) in enumerate(todo, 1):
        user_prompt = build_user_prompt(row, user_check, text_field=text_field)
        result = None
        pt = ct = 0

        for attempt in range(1, max_retries + 1):
            try:
                raw, pt, ct = caller_fn(system_prompt, user_prompt)
                result = parse_response(raw)
                if result is None:
                    log(f"[parse-fail] row {row_idx+1} attempt {attempt}/{max_retries} — retrying…")
                    if attempt < max_retries:
                        time.sleep(2)
                        continue
                    errors += 1
                    break
                else:
                    break
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else "?"
                body   = (e.response.text[:200] if e.response else "")
                log(f"[http-{status}] row {row_idx+1} attempt {attempt}/{max_retries}: {body}")
                if attempt < max_retries:
                    time.sleep(15 if status == 429 else 5 * attempt)
                else:
                    errors += 1
            except requests.exceptions.ConnectionError as e:
                log(f"[conn-err] row {row_idx+1} attempt {attempt}/{max_retries}: {e}")
                if attempt < max_retries:
                    time.sleep(5)
                else:
                    errors += 1
            except Exception as e:
                log(f"[error] row {row_idx+1} attempt {attempt}/{max_retries}: {e}")
                if attempt < max_retries:
                    time.sleep(5)
                else:
                    errors += 1

        if result is None:
            continue

        rows[row_idx][label_key]      = result["label"]
        rows[row_idx][reasoning_key]  = result["reasoning"]
        rows[row_idx][confidence_key] = result["confidence"]
        rows[row_idx][tokens_in_key]  = pt
        rows[row_idx][tokens_out_key] = ct
        rows[row_idx][ts_key]         = datetime.datetime.now(datetime.timezone.utc).isoformat()

        processed += 1
        total_in  += pt
        total_out += ct
        save_jsonl(rows, out_path)

        elapsed = time.time() - start
        rem     = (len(todo) - rank) * (elapsed / rank)
        lbl     = result["label"]
        ref     = row.get("original_scout_label") or row.get("human_majority") or "?"
        match   = "=" if lbl == ref else "X"
        log(
            f"  [{rank:2d}/{len(todo)}] {match} {lbl:13s} ref={ref:13s} "
            f"{pt}→{ct}tok  eta {rem/60:.1f}m  {row.get('target_ngo','')[:24]}"
        )

    elapsed = time.time() - start
    log(f"\n  done: {processed} coded  {errors} errors  "
        f"{total_in:,}in/{total_out:,}out tok  {elapsed/60:.1f}min\n")

    return {
        "processed":  processed,
        "errors":     errors,
        "tokens_in":  total_in,
        "tokens_out": total_out,
        "elapsed":    elapsed,
    }
