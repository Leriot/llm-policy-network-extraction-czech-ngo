"""
build_full_dataset.py
=====================
Scans data/interim/step6_final_boilerplate_cleaned/ and builds per-year JSONL
input files for the full LLM coding run.

Each line in the output JSONL is one (source_ngo, target_ngo, article) pair
with an extracted context excerpt — the same fields the LLM runner needs.
Running this is step 1; the actual LLM coding is done by run_full_dataset_openrouter.py.

Output: data/processed/full_dataset/{year}_pairs.jsonl

Usage
-----
    python scripts/03_llm_classify/build_full_dataset.py          # all years
    python scripts/03_llm_classify/build_full_dataset.py --year 2020
    python scripts/03_llm_classify/build_full_dataset.py --dry-run  # count only
    python scripts/03_llm_classify/build_full_dataset.py --stats    # summary table
"""

import argparse
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

# ── Project root ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STEP6_DIR    = PROJECT_ROOT / "data" / "step6_final_boilerplate_cleaned"
OUTPUT_DIR   = PROJECT_ROOT / "data" / "full_dataset"

# ── NGO regex patterns (from filter_step4_ngo_collab.py, applied to step6) ────
# Canonical directory name → regex that matches the NGO in Czech text
import re as _re

NGO_PATTERNS = [
    ('Arnika',                                  r'\bArnik[aáyiíeě]\w*'),
    ('Autoklub CR',                             r'\bAutoklub\w*'),
    ('Beleco',                                  r'\bBelec\w*'),
    ('Calla - Sdruzeni pro zachranu prostredi', r'\bCall[aáyiíeě]\w*'),
    ('Centrum pro dopravu a energetiku',        r'\bCDE\b|\bCentrum\s+pro\s+dopravu\b'),
    ('Cesky svaz ochrancu prirody',
        r'\bČSOP\b|\bCSOP\b'
        r'|\bČesk[éýéhoémuém]\w*\s+svaz[ua]?\s+ochránc\w+'
        r'|\bsvaz[ua]?\s+ochránc\w+\s+př[íi]rod\w+'),
    ('CI2',                                     r'\bCI2\b'),
    ('Ekologicky institut Veronica',            r'\bVeronik\w+'),
    ('Extinction Rebellion [Posledni generace]',
        r'\bExtinction\s+Rebellion\b|\bPosledn[íi]\s+generac\w+'),
    ('Fakta o klimatu',                         r'\bFakt[aáůech]+\s+o\s+klimat\w+'),
    ('Frank Bold',                              r'\bFrank\s+Bold\b'),
    ('Fridays for Future',                      r'\bFFF\b|\bFridays\s+for\s+Future\b'),
    ('Greenpeace CR',                           r'\bGreenpeace\b'),
    ('Hnuti Duha',
        r'\bHnut[íi]\s+Duh\w+'
        r'|\bHnut[íi]\s+DUHA\b'),
    ('Klimaticka koalice',                      r'\bKlimatick\w+\s+[Kk]oalic\w+'),
    ('Limity jsme my',                          r'\bLimit[yu]\s+jsme\b'),
    ('Nesehnuti',                               r'\bNesehnut\w+'),
    ('Zeleny kruh',
        r'\bZelen[éýéhoémuém]\w*\s+[Kk]ruh\w*'
        r'|\bZelen[éý]\s+[Kk]ruh\b'),
]

_COMPILED = [(d, _re.compile(p, _re.IGNORECASE)) for d, p in NGO_PATTERNS]

# Short name variants used for context window extraction
_NGO_SHORT: dict[str, list[str]] = {
    'Arnika':                                ['Arnika', 'Arniky', 'Arnice', 'Arniku'],
    'Calla - Sdruzeni pro zachranu prostredi': ['Calla', 'Cally', 'Calle', 'Callou'],
    'Zeleny kruh':                           ['Zelený kruh', 'Zeleny kruh', 'Zeleného kruhu', 'Zelenému kruhu'],
    'Hnuti Duha':                            ['Hnutí Duha', 'Hnuti Duha', 'Hnutí DUHA', 'hnutí Duha'],
    'Nesehnuti':                             ['Nesehnutí', 'NESEHNUTÍ', 'Nesehnuti', 'nesehnutí'],
    'Greenpeace CR':                         ['Greenpeace'],
    'Cesky svaz ochrancu prirody':           ['ČSOP', 'CSOP', 'Český svaz', 'Cesky svaz'],
    'Ekologicky institut Veronica':          ['Veronica', 'Veronika', 'Veronikou', 'Veroniky'],
    'Frank Bold':                            ['Frank Bold'],
    'Klimaticka koalice':                    ['Klimatická koalice', 'Klimaticka koalice',
                                              'klimatické koalice', 'klimatické koalici'],
    'Beleco':                                ['Beleco'],
    'CI2':                                   ['CI2'],
    'Centrum pro dopravu a energetiku':      ['Centrum pro dopravu', 'CDE'],
    'Fakta o klimatu':                       ['Fakta o klimatu', 'Fakta o klimatu'],
    'Limity jsme my':                        ['Limity jsme my'],
    'Extinction Rebellion [Posledni generace]': ['Extinction Rebellion', 'Poslední generace',
                                                 'Posledni generace'],
    'Autoklub CR':                           ['Autoklub'],
    'Fridays for Future':                    ['Fridays for Future', 'FFF'],
}

# ── Context extraction constants ──────────────────────────────────────────────
CONTEXT_WINDOW  = 1000   # chars on each side of anchor point (doubled for better LLM context)
MAX_SEARCH_DIST = 1200   # max chars between NGO name and keyword to count

# Relation keywords used to anchor the context window
RELATION_KEYWORDS = [
    'spolupracovali', 'spolupracuje', 'spolupráci', 'spolupráce', 'spolupracovat',
    'společně', 'společná', 'společné', 'společnou', 'společného',
    'partneři', 'partnerů', 'partnerství', 'partnerská',
    'koalice', 'koalici', 'koaliční',
    'platforma', 'platformy',
    'sdružení', 'sdružuje', 'sdružovat',
    'síť', 'sítě', 'sítí',
    'členů', 'člen', 'členská', 'členské',
    'projekt', 'projektu', 'projektů',
    'iniciativa', 'iniciativy',
    'spolupořádaly', 'spolupořádali', 'spolupořádá',
    'expert', 'experti', 'expertní',
    'podpořili', 'podpořila', 'podpora',
    'signatáři', 'podepsané', 'podepsal', 'podepsali',
]


def find_other_ngos(text: str, source_dir: str) -> list[str]:
    """Return canonical NGO names found in text (excluding source NGO)."""
    found = []
    for dirname, pat in _COMPILED:
        if dirname == source_dir:
            continue
        if pat.search(text):
            found.append(dirname)
    return found


def _find_all(text_lower: str, term: str) -> list[int]:
    """All start positions of term (case-insensitive) in text."""
    tl = term.lower()
    positions, start = [], 0
    while True:
        pos = text_lower.find(tl, start)
        if pos == -1:
            break
        positions.append(pos)
        start = pos + 1
    return positions


def extract_context(text: str, target_ngo: str, keywords: list[str]) -> str:
    """
    Extract a ~1000-char context window around the closest (NGO, keyword) pair.
    Returns header line + snippet, same format as prepare_intercoder_sample.py.
    """
    if not text:
        return ''

    text_lower = text.lower()
    ngo_terms  = _NGO_SHORT.get(target_ngo, [target_ngo])

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

    all_pairs.sort(key=lambda x: x[0])
    seen: set[tuple[str, str]] = set()
    unique_pairs = []
    for dist, anchor, ngo_term, kw in all_pairs:
        key = (ngo_term.lower(), kw.lower())
        if key not in seen:
            seen.add(key)
            unique_pairs.append((dist, anchor, ngo_term, kw))

    fallback = False
    best_anchor = best_dist = -1
    best_ngo_term = best_kw = ''

    if unique_pairs:
        best_dist, best_anchor, best_ngo_term, best_kw = unique_pairs[0]
    else:
        fallback = True
        for ngo_term in ngo_terms:
            pos = text_lower.find(ngo_term.lower())
            if pos != -1:
                best_anchor = pos
                best_ngo_term = ngo_term
                break
        for kw in keywords:
            pos = text_lower.find(kw.lower())
            if pos != -1:
                if best_anchor == -1:
                    best_anchor = pos
                best_kw = kw
                break
        if best_anchor == -1:
            return (
                '[⚠ MISSING BOTH: neither NGO nor keyword found — likely boilerplate]\n\n'
                + text[:1000].strip()
            )

    start   = max(0, best_anchor - CONTEXT_WINDOW)
    end     = min(len(text), best_anchor + CONTEXT_WINDOW)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = '…' + snippet
    if end < len(text):
        snippet = snippet + '…'

    if fallback:
        if best_ngo_term and not best_kw:
            header = f'[⚠ Fallback: NGO "{best_ngo_term}" found but no keyword nearby]'
        elif best_kw and not best_ngo_term:
            header = f'[⚠ Fallback: keyword "{best_kw}" found but NGO "{target_ngo}" absent]'
        else:
            header = f'[⚠ Fallback: NGO "{best_ngo_term}" and keyword "{best_kw}" beyond proximity window]'
    else:
        def _level(d: int) -> str:
            if d < 150:  return 'same sentence/paragraph'
            if d < 500:  return 'nearby paragraph'
            return 'distant'

        icon = '✓' if best_dist < 500 else '~'
        n = len(unique_pairs)
        if n == 1:
            header = (
                f'[{icon} NGO "{best_ngo_term}" + keyword "{best_kw}"'
                f' at {best_dist} chars — {_level(best_dist)}]'
            )
        else:
            parts = [f'"{ngo_t}"·"{kw}" at {dist}ch'
                     for dist, _, ngo_t, kw in unique_pairs[:4]]
            extra = f' (+{n - 4} more)' if n > 4 else ''
            hits_str = ' | '.join(parts) + extra
            header = (
                f'[{icon} {n} hits — NGO "{best_ngo_term}" + keyword "{best_kw}"'
                f' at {best_dist} chars | also: {hits_str}]'
            )

    return header + '\n\n' + snippet


# ── Main builder ──────────────────────────────────────────────────────────────

def build_year(year: str, dry_run: bool = False, force: bool = False) -> dict:
    """
    Process one year of step6 data.
    Returns stats dict: {year, articles_scanned, pairs_found, ngos_seen}.
    """
    year_dir = STEP6_DIR / year
    if not year_dir.exists():
        print(f"  [skip] {year}: no step6 directory found")
        return {}

    out_path = OUTPUT_DIR / f"{year}_pairs.jsonl"

    if out_path.exists() and not force:
        existing_count = sum(1 for _ in out_path.open(encoding='utf-8') if _.strip())
        print(f"  [skip] {year}: already built ({existing_count} pairs). Use --force to rebuild.")
        return {'year': year, 'pairs_found': existing_count, 'skipped': True}

    ngo_dirs = sorted(
        d.name for d in year_dir.iterdir()
        if d.is_dir() and d.name != '_metadata'
    )

    articles_scanned = 0
    pairs_found = 0
    ngos_seen = set()
    rows = []

    for source_ngo in ngo_dirs:
        text_dir = year_dir / source_ngo / 'text'
        if not text_dir.exists():
            continue

        for txt_file in sorted(text_dir.iterdir()):
            if not txt_file.suffix == '.txt':
                continue

            articles_scanned += 1
            try:
                text = txt_file.read_text(encoding='utf-8', errors='replace')
            except Exception as e:
                print(f"  [warn] Cannot read {txt_file}: {e}", file=sys.stderr)
                continue

            target_ngos = find_other_ngos(text, source_ngo)
            if not target_ngos:
                continue

            for target_ngo in target_ngos:
                context = extract_context(text, target_ngo, RELATION_KEYWORDS)

                # Skip pairs where NGO and keyword never appear close together —
                # these are proximity false positives (keyword in one paragraph, NGO in another).
                # Only [✓ ...] and [~ ...] headers indicate genuine proximity.
                if context.startswith("[⚠"):
                    continue

                ngos_seen.add(target_ngo)

                # Build deterministic ID
                pair_id = f"{year}__{source_ngo}__{txt_file.name}__{target_ngo}"

                row = {
                    'id':                pair_id,
                    'year':              year,
                    'source_ngo':        source_ngo,
                    'target_ngo':        target_ngo,
                    'article_name':      txt_file.name,
                    'relation_keywords': ', '.join(RELATION_KEYWORDS[:6]),  # compact
                    'extracted_text':    context,
                    # LLM result fields — populated by run_full_dataset_openrouter.py
                    'llm_label':         None,
                    'llm_reasoning':     None,
                    'llm_confidence':    None,
                    'llm_model':         None,
                    'llm_timestamp':     None,
                    'llm_prompt_tokens': None,
                    'llm_completion_tokens': None,
                    'llm_cost_usd':      None,
                }
                rows.append(row)
                pairs_found += 1

    if not dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
        print(f"  {year}: {articles_scanned} articles → {pairs_found} pairs "
              f"({len(ngos_seen)} unique target NGOs)  →  {out_path.name}")
    else:
        print(f"  {year}: {articles_scanned} articles → {pairs_found} pairs "
              f"[DRY RUN — not written]")

    return {
        'year':             year,
        'articles_scanned': articles_scanned,
        'pairs_found':      pairs_found,
        'ngos_seen':        len(ngos_seen),
    }


def print_stats(all_stats: list[dict]):
    """Print a summary table."""
    total_articles = sum(s.get('articles_scanned', 0) for s in all_stats)
    total_pairs    = sum(s.get('pairs_found', 0) for s in all_stats)
    print()
    print("╔══════╦═══════════╦════════════╦══════════════╗")
    print("║ Year ║ Articles  ║ Pairs      ║ Status       ║")
    print("╠══════╬═══════════╬════════════╬══════════════╣")
    for s in all_stats:
        if not s:
            continue
        skipped = s.get('skipped', False)
        status = 'existing' if skipped else 'built'
        print(f"║ {s['year']} ║ {s.get('articles_scanned', '?'):>9} ║ "
              f"{s.get('pairs_found', '?'):>10} ║ {status:<12} ║")
    print("╠══════╬═══════════╬════════════╬══════════════╣")
    print(f"║ ALL  ║ {total_articles:>9} ║ {total_pairs:>10} ║{'':14}║")
    print("╚══════╩═══════════╩════════════╩══════════════╝")
    print()
    # Cost estimate
    avg_input_tok  = 550    # typical per call (system prompt ~300 + excerpt ~250)
    avg_output_tok = 150
    mistral_cost   = (avg_input_tok * 0.15 + avg_output_tok * 0.60) / 1_000_000
    scout_cost     = (avg_input_tok * 0.08 + avg_output_tok * 0.30) / 1_000_000
    print(f"  Estimated total pairs:           {total_pairs:,}")
    print(f"  Mistral Small cost estimate:     ${total_pairs * mistral_cost:.2f}  "
          f"({avg_input_tok} in / {avg_output_tok} out tok avg × ${mistral_cost*1e6:.2f}/M)")
    print(f"  Llama 4 Scout cost estimate:     ${total_pairs * scout_cost:.2f}  "
          f"(DeepInfra fp8)")
    print(f"  OpenRouter time estimate:        ~{total_pairs * 1.5 / 3600:.1f}h  "
          f"(1.5 sec/call avg)")
    print(f"  Local Qwen time estimate:        ~{total_pairs * 12 / 3600:.0f}h  "
          f"(~12 sec/call on CPU)")
    print()


def main():
    parser = argparse.ArgumentParser(
        description='Build per-year JSONL input for the full LLM coding run',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--year',    help='Only build a single year (e.g. 2020)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Count pairs only, do not write any files')
    parser.add_argument('--force',   action='store_true',
                        help='Rebuild even if output already exists')
    parser.add_argument('--stats',   action='store_true',
                        help='Print summary table without rebuilding')
    args = parser.parse_args()

    if args.year:
        years = [args.year]
    else:
        years = [str(y) for y in range(2016, 2026)]

    print(f"\nScanning step6 → building full-dataset JSONL pairs")
    print(f"Input:  {STEP6_DIR}")
    print(f"Output: {OUTPUT_DIR}\n")

    all_stats = []
    for year in years:
        stat = build_year(year, dry_run=args.dry_run, force=args.force)
        if stat:
            all_stats.append(stat)

    print_stats(all_stats)


if __name__ == '__main__':
    main()
