"""
Prepare Intercoder Reliability Sample (10% Stratified)
=======================================================
Reads step5_iterative_cleaning output across all years (Step 5 is the
cleaned version of step4_keyword_proximity_filtering, with source-specific
boilerplate removed), draws a proportional stratified 10% sample, and
produces a CSV ready to upload to the intercoder tool.

Sampling strategy:
  - Proportional to year size (preserves temporal distribution)
  - Within each year, random shuffle to avoid NGO ordering bias
  - Reproducible via --seed (default 42)

Output CSV format:
  Line 1  : #CONFIG{...}   ← auto-configures intercoder tool
  Line 2  : column headers
  Lines 3+: one row per (source_ngo, target_ngo_pair, article)
            NOTE: docs with multiple target NGOs produce one row
            per target NGO (each pair gets its own coding decision)

Usage:
    python scripts/prepare_intercoder_sample.py                          # 150 entries (default)
    python scripts/prepare_intercoder_sample.py --fixed 200              # exact count
    python scripts/prepare_intercoder_sample.py --fixed 0 --pct 0.10    # 10% instead of fixed
    python scripts/prepare_intercoder_sample.py --output coding/round1_sample.csv
    python scripts/prepare_intercoder_sample.py --year 2025              # single year
    python scripts/prepare_intercoder_sample.py --seed 99                # different random draw
    python scripts/prepare_intercoder_sample.py --input data/interim/step4_keyword_proximity_filtering  # bypass Step 5
"""

import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


import argparse
import csv
import json
import math
import random
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Codebook (embedded in #CONFIG, also displayed in intercoder tool UI)
# ---------------------------------------------------------------------------
CODEBOOK = """CODING GUIDE — Czech NGO Network Study
========================================

CONTEXT
You are reading an article published by the SOURCE NGO. The article contains
a mention of the TARGET NGO near a collaboration/relation keyword.

Your task: decide whether this article provides evidence of COLLABORATION,
CO-MENTION, is a FALSE POSITIVE (wrong), or is UNSURE.

──────────────────────────────────────────
CATEGORIES
──────────────────────────────────────────

📗 COLLABORATION
A CONCRETE JOINT ACTION is described that directly involves BOTH the source NGO
and the target NGO. In the NGO sector, collaboration appears as joint OUTPUTS or
STRUCTURES — not only explicit phrases like "worked together". Code as
COLLABORATION if ANY of the following apply:

  1. JOINT PUBLICATION — both listed as co-authors or co-issuers of a press
     release, study, report, or analysis.
     ▸ Czech press releases use the byline: "Tisková zpráva NGO1, NGO2, NGO3"
       All listed NGOs jointly issued it — any pair in the list = collaboration.
  2. CO-SIGNING — both listed as signatories of an open letter, manifesto,
     appeal, or legal complaint.
  3. CO-ORGANIZING — both listed as organizers of a demonstration, protest,
     event, or roundtable ("spolupořádaly organizace NGO1, NGO2...").
  4. STRUCTURAL MEMBERSHIP — one NGO is explicitly a member, board member, or
     named partner of the other (e.g. "sdružuje... Arnika, Greenpeace" or
     "členská organizace").
  5. RESOURCE SHARING — one NGO provides specific legal, expert, or financial
     support to the other's campaign or lawsuit.

Key test: Could you say "SOURCE NGO and TARGET NGO DID X together"?
If yes → COLLABORATION

⚠ IMPORTANT: The joint action must directly involve BOTH the source NGO and the
target NGO. If the source NGO only REPORTS ON a collaboration between the target
NGO and a third organization (source NGO is not a participant), that is
CO-MENTION, not collaboration.

📘 CO-MENTION
The two organizations appear in the same text but NO DIRECT JOINT ACTION
between them is described.
Examples:
  ✓ One NGO quotes or cites the other's position
  ✓ Both comment separately on the same issue/event
  ✓ One NGO mentions the other as a peer/ally without joint work
  ✓ Coalition membership mentioned but no specific joint action described
  ✓ Source NGO endorses target NGO's campaign (but doesn't participate)
  ✓ News article naming both without describing cooperation
  ✓ Source NGO reports on a collaboration between target NGO and a THIRD PARTY
    (the source NGO is not a participant in that collaboration)
Key test: Are they just MENTIONED TOGETHER without acting together directly?
If yes → CO-MENTION

📕 WRONG
The detected "NGO name" is NOT actually this organization.
The text match is a false positive — a common Czech word or name that
coincidentally matches an NGO acronym or short name.
Examples:
  ✗ "duha" meaning rainbow (not Hnutí Duha)
  ✗ "arnika" as a medicinal plant (not Arnika NGO)
  ✗ "zelená" as an adjective meaning green (not Zelený kruh)
  ✗ A person's surname that matches an NGO name
  ✗ A different organization with a similar name
If marking WRONG, use the Notes field to explain what the word actually means.

❓ UNSURE
Genuine ambiguity — you cannot determine from the available context
whether this is collaboration, co-mention, or a false positive.
Use this sparingly. Examples:
  ? Text is too short or truncated to judge
  ? The relationship implied is not clearly joint or separate
  ? You cannot tell if the NGO name is being used as a proper noun or common noun

──────────────────────────────────────────
DECISION TREE
──────────────────────────────────────────
1. Is the TARGET NGO name actually referring to that NGO?
   → No → WRONG
2. Is a concrete JOINT ACTION described that directly involves BOTH source AND target NGO?
   → Yes → COLLABORATION
3. Are the NGOs mentioned together without joint action?
   → Yes → CO-MENTION
4. Still unclear? → UNSURE

──────────────────────────────────────────
CONFIDENCE
──────────────────────────────────────────
HIGH  → The text makes the answer clear; you feel confident
LOW   → You had to make a judgment call; another coder might disagree

Use LOW confidence to flag borderline cases for discussion — these are
the most valuable cases for calibrating the codebook.

──────────────────────────────────────────
KEYBOARD SHORTCUTS (intercoder tool)
──────────────────────────────────────────
1 = collaboration   2 = co-mention   3 = wrong   4 = unsure
H = high confidence   L = low confidence
Ctrl+Enter = save & next
"""

CODING_PRESET = {
    'coding_question': (
        'How would you classify the relationship between the SOURCE NGO (publisher) '
        'and the TARGET NGO (mentioned) in this article?'
    ),
    'coding_options': ['collaboration', 'co-mention', 'wrong', 'unsure'],
    'has_confidence': True,
    'has_notes': True,
    'instructions': CODEBOOK,
}

# ---------------------------------------------------------------------------
# Text context extraction
# ---------------------------------------------------------------------------
CONTEXT_WINDOW = 500   # chars on each side of the anchor point
MAX_SEARCH_DIST = 1200  # max chars between NGO name and keyword to count as co-occurrence

# Short name variants for each NGO directory name, used for in-text search
_NGO_SHORT: dict[str, list[str]] = {
    'Arnika':                                ['Arnika', 'Arniky', 'Arnice'],
    'Calla - Sdruzeni pro zachranu prostredi': ['Calla', 'Cally', 'Calle'],
    'Zeleny kruh':                           ['Zelený kruh', 'Zeleny kruh', 'Zeleného kruhu', 'Zelenému kruhu'],
    'Hnuti Duha':                            ['Hnutí Duha', 'Hnuti Duha', 'Hnutí DUHA'],
    'Nesehnuti':                             ['Nesehnutí', 'NESEHNUTÍ', 'Nesehnuti'],
    'Greenpeace CR':                         ['Greenpeace'],
    'Cesky svaz ochrancu prirody':           ['ČSOP', 'Český svaz', 'Cesky svaz'],
    'Ekologicky institut Veronica':          ['Veronica', 'Veronika'],
    'Frank Bold':                            ['Frank Bold'],
    'Klimaticka koalice':                    ['Klimatická koalice', 'Klimaticka koalice', 'klimatické koalice'],
    'Glopolis':                              ['Glopolis'],
    'Beleco':                                ['Beleco'],
    'CI2':                                   ['CI2'],
    'Centrum pro dopravu a energetiku':      ['Centrum pro dopravu', 'CDE'],
    'Fakta o klimatu':                       ['Fakta o klimatu'],
    'Limity jsme my':                        ['Limity jsme my'],
    'Extinction Rebellion [Posledni generace]': ['Extinction Rebellion', 'Poslední generace'],
    'Aliance pro energetickou sobestacnost': ['Aliance pro energetickou', 'AES'],
    'Autoklub CR':                           ['Autoklub'],
}


def _find_all(text_lower: str, term: str) -> list[int]:
    """Return all start positions of term (case-insensitive) in text."""
    tl = term.lower()
    positions = []
    start = 0
    while True:
        pos = text_lower.find(tl, start)
        if pos == -1:
            break
        positions.append(pos)
        start = pos + 1
    return positions


def extract_context(text: str, target_ngo: str, keywords: list[str]) -> str:
    """
    Find ALL (target_ngo_mention, relation_keyword) pairs within MAX_SEARCH_DIST
    of each other in the text. Anchors the context window on the closest pair.

    Header line format (parsed by intercoder tool's _parse_context_header):
      Single hit:   [✓ NGO "Arniky" + keyword "koalice" at 45 chars — same sentence/paragraph]
      Multiple hits:[✓ 3 hits — NGO "Arniky" + keyword "koalice" at 45 chars | "Arniky"+"spolupráce" at 234 | "Arnika"+"koalice" at 589]
      NGO fallback: [⚠ Fallback: NGO "Arniky" found but no keyword nearby — showing NGO context]
      KW fallback:  [⚠ Fallback: keyword "koalice" found but NGO "Arnika" absent from text]
      Missing both: [⚠ MISSING BOTH: neither NGO nor keyword found in text — likely boilerplate hit removed by Step 5 cleaning]

    The NGO term in the header (e.g. "Arniky") is the actual matched form used in the
    text, which may be an inflected variant. The intercoder tool's JS highlighter uses
    this to correctly highlight Czech inflected forms.
    """
    if not text:
        return ''

    text_lower = text.lower()
    ngo_terms  = _NGO_SHORT.get(target_ngo, [target_ngo])

    # ── Collect ALL (dist, anchor, ngo_term, keyword) pairs ──────────────────
    all_pairs: list[tuple[int, int, str, str]] = []

    for ngo_term in ngo_terms:
        ngo_positions = _find_all(text_lower, ngo_term)
        for kw in keywords:
            kw_positions = _find_all(text_lower, kw.lower())
            for np in ngo_positions:
                for kp in kw_positions:
                    dist = abs(np - kp)
                    if dist <= MAX_SEARCH_DIST:
                        anchor = (np + kp) // 2
                        all_pairs.append((dist, anchor, ngo_term, kw))

    # Sort by distance (closest first), then deduplicate same (ngo_term, kw) combo
    all_pairs.sort(key=lambda x: x[0])
    seen: set[tuple[str, str]] = set()
    unique_pairs: list[tuple[int, int, str, str]] = []
    for dist, anchor, ngo_term, kw in all_pairs:
        key = (ngo_term.lower(), kw.lower())
        if key not in seen:
            seen.add(key)
            unique_pairs.append((dist, anchor, ngo_term, kw))

    # ── Fallback: try NGO-only or keyword-only if no pairs found ─────────────
    fallback = False
    best_anchor   = -1
    best_dist     = MAX_SEARCH_DIST + 1
    best_ngo_term = ''
    best_kw       = ''

    if unique_pairs:
        best_dist, best_anchor, best_ngo_term, best_kw = unique_pairs[0]
    else:
        fallback = True
        # Try to find the NGO name anywhere in the text
        for ngo_term in ngo_terms:
            pos = text_lower.find(ngo_term.lower())
            if pos != -1:
                best_anchor   = pos
                best_ngo_term = ngo_term
                break
        # Try to find any keyword if NGO wasn't found (or also find keyword)
        for kw in keywords:
            pos = text_lower.find(kw.lower())
            if pos != -1:
                if best_anchor == -1:
                    best_anchor = pos
                best_kw = kw
                break
        if best_anchor == -1:
            return (
                '[⚠ MISSING BOTH: neither NGO nor keyword found in text'
                ' — likely a boilerplate hit removed by Step 5 cleaning]\n\n'
                + text[:1000].strip()
            )

    # ── Extract context snippet around best anchor ───────────────────────────
    start = max(0, best_anchor - CONTEXT_WINDOW)
    end   = min(len(text), best_anchor + CONTEXT_WINDOW)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = '…' + snippet
    if end < len(text):
        snippet = snippet + '…'

    # ── Build header ─────────────────────────────────────────────────────────
    if fallback:
        if best_ngo_term and not best_kw:
            header = (
                f'[⚠ Fallback: NGO "{best_ngo_term}" found but no keyword nearby'
                f' — showing NGO context]'
            )
        elif best_kw and not best_ngo_term:
            header = (
                f'[⚠ Fallback: keyword "{best_kw}" found but NGO "{target_ngo}"'
                f' absent from text — mark WRONG if NGO was only in boilerplate]'
            )
        else:
            header = (
                f'[⚠ Fallback: NGO "{best_ngo_term or target_ngo}" and keyword'
                f' "{best_kw}" found separately but beyond proximity window]'
            )
    else:
        n = len(unique_pairs)

        def _level(d: int) -> str:
            if d == 0:    return 'same token'
            if d < 150:   return 'same sentence/paragraph'
            if d < 500:   return 'nearby paragraph'
            return 'distant — consider marking unsure'

        icon = '✓' if best_dist < 500 else '~'

        if n == 1:
            header = (
                f'[{icon} NGO "{best_ngo_term}" + keyword "{best_kw}"'
                f' at {best_dist} chars — {_level(best_dist)}]'
            )
        else:
            # Compact representation of all matches (up to 4 shown)
            parts = []
            for dist, _, ngo_t, kw in unique_pairs[:4]:
                parts.append(f'"{ngo_t}"·"{kw}" at {dist}ch')
            extra = f' (+{n - 4} more)' if n > 4 else ''
            hits_str = ' | '.join(parts) + extra
            header = (
                f'[{icon} {n} hits — NGO "{best_ngo_term}" + keyword "{best_kw}"'
                f' at {best_dist} chars | also: {hits_str}]'
            )

    return header + '\n\n' + snippet


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
def collect_all_docs(base_dir: Path, years: list[str]) -> dict[str, list[dict]]:
    """Return dict year -> list of doc dicts."""
    docs_by_year: dict[str, list[dict]] = {}
    for year in years:
        meta_file = base_dir / year / '_metadata' / 'kept_files.jsonl'
        if not meta_file.exists():
            print(f"  [warn] No metadata for year {year}, skipping", file=sys.stderr)
            continue
        year_docs = []
        with open(meta_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                # Expand multi-target docs to one entry per target NGO pair
                targets = row.get('target_ngos', [])
                if not targets:
                    targets = ['(unknown)']
                for target in targets:
                    year_docs.append({
                        'year': row['year'],
                        'source_ngo': row['source_ngo'],
                        'target_ngo': target,
                        'filename': row['filename'],
                        'relation_keywords': row.get('relation_keywords', []),
                    })
        docs_by_year[year] = year_docs
        print(f"  {year}: {len(year_docs)} pairs ({len({d['filename'] for d in year_docs})} unique docs)")
    return docs_by_year


def stratified_sample(docs_by_year: dict, pct: float = 0.10, fixed: int = 0,
                      seed: int = 42) -> list[dict]:
    """Proportional stratified sample across years."""
    rng = random.Random(seed)
    total = sum(len(v) for v in docs_by_year.values())
    target_n = fixed if fixed > 0 else max(1, round(total * pct))

    print(f"\nTotal pairs: {total}  →  Target sample: {target_n} ({pct*100:.0f}%)")

    sample = []
    for year, docs in sorted(docs_by_year.items()):
        # Proportional allocation (at least 1 per year)
        year_n = max(1, round(len(docs) / total * target_n))
        shuffled = docs[:]
        rng.shuffle(shuffled)
        picked = shuffled[:min(year_n, len(shuffled))]
        sample.extend(picked)
        print(f"  {year}: {len(docs)} pairs → sampled {len(picked)}")

    # Trim or pad to exact target if fixed count requested
    if fixed > 0 and len(sample) != fixed:
        rng.shuffle(sample)
        sample = sample[:fixed]

    print(f"\nFinal sample: {len(sample)} rows")
    return sample


# ---------------------------------------------------------------------------
# Load text files and build output rows
# ---------------------------------------------------------------------------
def build_rows(sample: list[dict], base_dir: Path) -> list[dict]:
    rows = []
    missing = 0
    for entry in sample:
        year = entry['year']
        source_ngo = entry['source_ngo']
        filename = entry['filename']
        txt_path = base_dir / year / source_ngo / 'text' / filename
        text = ''
        if txt_path.exists():
            try:
                text = txt_path.read_text(encoding='utf-8', errors='replace')
            except Exception as e:
                print(f"  [warn] Could not read {txt_path}: {e}", file=sys.stderr)
        else:
            missing += 1

        context = extract_context(text, entry['target_ngo'], entry['relation_keywords'])

        # Build a readable article name: strip leading numeric prefix (e.g. "00236_")
        # and replace underscores/hyphens with spaces
        stem = filename.replace('.txt', '')
        # Remove leading digits+underscore prefix like "00236_" or "01_002_133_"
        stem = re.sub(r'^[\d_]+', '', stem)
        article_name = stem.replace('-', ' ').replace('_', ' ').strip() or filename

        rows.append({
            'year': year,
            'source_ngo': source_ngo,
            'target_ngo': entry['target_ngo'],
            'article_name': article_name,
            'article_url': '',
            'relation_keywords': ', '.join(entry['relation_keywords']),
            'extracted_text': context,
        })

    if missing:
        print(f"  [warn] {missing} text files not found", file=sys.stderr)
    return rows


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------
def write_csv(rows: list[dict], output_path: Path, preset: dict):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    config_json = '#CONFIG' + json.dumps({
        'coding_question': preset['coding_question'],
        'coding_options':  preset['coding_options'],
        'has_confidence':  preset['has_confidence'],
        'has_notes':       preset['has_notes'],
        'instructions':    preset['instructions'],
    }, ensure_ascii=False)

    fieldnames = ['year', 'source_ngo', 'target_ngo', 'article_name',
                  'article_url', 'relation_keywords', 'extracted_text']

    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        # Write #CONFIG as a single properly-quoted CSV cell so Excel/Calc
        # don't split the JSON on commas into multiple columns.
        writer_cfg = csv.writer(f)
        writer_cfg.writerow([config_json])
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✓ Written {len(rows)} rows → {output_path}")
    print(f"  Upload this file to the intercoder tool.")
    print(f"  Coding options: {', '.join(preset['coding_options'])}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description='Prepare stratified intercoder reliability sample',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        '--input', default='data/interim/step5_iterative_cleaning',
        help='Base directory of cleaned dataset (default: data/interim/step5_iterative_cleaning; use data/interim/step4_keyword_proximity_filtering to bypass Step 5)',
    )
    parser.add_argument(
        '--output', default='data/intercoder_sample/round1_coding_sample.csv',
        help='Output CSV path',
    )
    parser.add_argument(
        '--pct', type=float, default=0.10,
        help='Fraction to sample per year (default: 0.10 = 10%%)',
    )
    parser.add_argument(
        '--fixed', type=int, default=150,
        help='Fixed total sample size (default: 150; set to 0 to use --pct instead)',
    )
    parser.add_argument(
        '--seed', type=int, default=42,
        help='Random seed for reproducibility (default: 42)',
    )
    parser.add_argument(
        '--year', default='all',
        help='Specific year or "all" (default: all)',
    )
    args = parser.parse_args()

    base_dir = Path(args.input)
    if not base_dir.exists():
        print(f"ERROR: Input directory not found: {base_dir}", file=sys.stderr)
        sys.exit(1)

    # Determine years
    if args.year == 'all':
        years = sorted(d.name for d in base_dir.iterdir()
                       if d.is_dir() and re.match(r'^\d{4}$', d.name))
    else:
        years = [args.year]

    print(f"Collecting docs from: {base_dir}")
    print(f"Years: {', '.join(years)}\n")

    docs_by_year = collect_all_docs(base_dir, years)
    if not docs_by_year:
        print("ERROR: No documents found.", file=sys.stderr)
        sys.exit(1)

    sample = stratified_sample(docs_by_year, pct=args.pct, fixed=args.fixed, seed=args.seed)
    rows = build_rows(sample, base_dir)
    write_csv(rows, Path(args.output), CODING_PRESET)


if __name__ == '__main__':
    main()
