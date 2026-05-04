"""
Step 4 – NGO Co-occurrence Filter
==================================
Filters step3 documents to those that contain BOTH:
  1. A mention of at least one OTHER NGO from the core list
  2. At least one collaboration/relation keyword from content_filter_keywords.yaml

NGO detection uses regex patterns per NGO to handle Czech declensions
(e.g. Arnika/Arniky/Arnice, Calla/Cally/Calle). The canonical name for
self-exclusion is matched exactly against the source directory name.

Output structure mirrors step3:
  data/interim/step4_keyword_proximity_filtering/{year}/{ngo}/text/{file}.txt

A JSONL metadata file per year records which NGOs and keywords matched.

Usage:
    python scripts/filter_step4_ngo_collab.py              # all years
    python scripts/filter_step4_ngo_collab.py --year 2025  # single year
    python scripts/filter_step4_ngo_collab.py --year other # undated docs
    python scripts/filter_step4_ngo_collab.py --ngo "Arnika"
    python scripts/filter_step4_ngo_collab.py --dry-run
"""
import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


import re
import sys
import json
import csv
import shutil
import logging
import argparse
from pathlib import Path
from collections import defaultdict

import yaml
from flashtext import KeywordProcessor

# ── Project root ──────────────────────────────────────────────────────────────
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ── NGO regex patterns ─────────────────────────────────────────────────────────
# Each entry: (directory_name_exact, regex_pattern)
# directory_name_exact MUST match the folder name in step3/{year}/ exactly —
# this is used to skip self-mentions when scanning a source NGO's own docs.
# Patterns handle common Czech declension suffixes for each NGO name.

NGO_PATTERNS = [
    ('Aliance pro energetickou sobestacnost',
        r'\bAliES\b'),
    ('Arnika',
        r'\bArnik[aáyiíeě]\w*'),            # Arnika, Arniky, Arnice, Arnikou…
    ('Autoklub CR',
        r'\bAutoklub\w*'),
    ('Beleco',
        r'\bBelec\w*'),
    ('Calla - Sdruzeni pro zachranu prostredi',
        r'\bCall[aáyiíeě]\w*'),             # Calla, Cally, Calle, Callou…
    ('Centrum pro dopravu a energetiku',
        r'\bCDE\b|\bCentrum\s+pro\s+dopravu\b'),
    ('Cesky svaz ochrancu prirody',
        r'\bČSOP\b|\bCSOP\b'
        r'|\bČesk[éýéhoémuém]\w*\s+svaz[ua]?\s+ochránc\w+'
        r'|\bsvaz[ua]?\s+ochránc\w+\s+př[íi]rod\w+'),
    ('CI2',
        r'\bCI2\b'),
    ('Ekologicky institut Veronica',
        r'\bVeronik\w+'),                   # Veronica, Veronice, Veroniky…
    ('Extinction Rebellion [Posledni generace]',
        r'\bExtinction\s+Rebellion\b|\bPosledn[íi]\s+generac\w+'),
    ('Fakta o klimatu',
        r'\bFakt[aáůech]+\s+o\s+klimat\w+'),
    ('Frank Bold',
        r'\bFrank\s+Bold\b'),
    ('Fridays for Future',
        r'\bFFF\b|\bFridays\s+for\s+Future\b'),
    ('Greenpeace CR',
        r'\bGreenpeace\b'),
    ('Hnuti Duha',
        r'\bHnut[íi]\s+Duh\w+'              # requires "Hnutí" to avoid false "rainbow"
        r'|\bHnut[íi]\s+DUHA\b'),
    ('Klimaticka koalice',
        r'\bKlimatick\w+\s+[Kk]oalic\w+'),  # Klimatická koalice, koalici, koalice…
    ('Limity jsme my',
        r'\bLimit[yu]\s+jsme\b'),
    ('Nesehnuti',
        r'\bNesehnut\w+'),
    ('Zeleny kruh',
        r'\bZelen[éýéhoémuém]\w*\s+[Kk]ruh\w*'  # Zelený/Zeleného/Zelenému kruh/kruhu…
        r'|\bZelen[éý]\s+[Kk]ruh\b'),
]

# Compile all patterns once
_COMPILED = [(d, re.compile(p, re.IGNORECASE)) for d, p in NGO_PATTERNS]


def find_other_ngos(text: str, source_dir: str) -> list[str]:
    """
    Return list of canonical NGO directory names found in text,
    excluding the source NGO itself.
    """
    found = []
    for dirname, pat in _COMPILED:
        if dirname == source_dir:
            continue
        if pat.search(text):
            found.append(dirname)
    return found


# ── Relation keyword loader (FlashText) ───────────────────────────────────────

def load_relation_keywords(config_path: Path) -> list[str]:
    """
    Returns all keyword variations from the 'relations' section of
    content_filter_keywords.yaml (roots + explicit variations).
    """
    with open(config_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    terms = []
    for entry in cfg.get('keywords', {}).get('relations', []):
        root = entry.get('root', '').strip()
        if root:
            terms.append(root)
        for var in entry.get('variations', []):
            var = var.strip()
            if var:
                terms.append(var)

    # Deduplicate, longest first so substring matches don't shadow longer terms
    seen = set()
    unique = []
    for t in sorted(terms, key=len, reverse=True):
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            unique.append(t)

    logger.info(f"Loaded {len(unique)} relation keyword terms")
    return unique


def build_keyword_processor(relation_terms: list[str]) -> KeywordProcessor:
    proc = KeywordProcessor(case_sensitive=False)
    for term in relation_terms:
        proc.add_keyword(term, term)
    return proc


# ── Core check ────────────────────────────────────────────────────────────────

def check_document(text: str, source_ngo: str,
                   rel_proc: KeywordProcessor) -> dict | None:
    """
    Returns match dict if the document passes both filters, else None.
    """
    other_ngos = find_other_ngos(text, source_ngo)
    if not other_ngos:
        return None

    found_relations = list(set(rel_proc.extract_keywords(text)))
    if not found_relations:
        return None

    return {
        'target_ngos': sorted(other_ngos),
        'relation_keywords': sorted(found_relations),
    }


# ── Per-year filter ────────────────────────────────────────────────────────────

def filter_year(
    input_year_dir: Path,
    output_year_dir: Path,
    rel_proc: KeywordProcessor,
    ngo_filter: str | None,
    dry_run: bool,
) -> dict:
    """Process one year folder. Returns stats dict."""
    year = input_year_dir.name

    ngo_dirs = sorted(d.name for d in input_year_dir.iterdir() if d.is_dir())
    if ngo_filter:
        ngo_dirs = [n for n in ngo_dirs if ngo_filter.lower() in n.lower()]

    stats = defaultdict(int)
    per_ngo_stats = {}
    metadata_rows = []

    for source_ngo in ngo_dirs:
        text_dir = input_year_dir / source_ngo / 'text'
        if not text_dir.exists():
            continue

        files = sorted(text_dir.glob('*.txt'))
        kept = skipped_no_ngo = skipped_no_rel = 0

        for txt_file in files:
            stats['total_files'] += 1
            try:
                text = txt_file.read_text(encoding='utf-8', errors='replace')
            except Exception as e:
                logger.warning(f"  Could not read {txt_file.name}: {e}")
                stats['read_errors'] += 1
                continue

            match = check_document(text, source_ngo, rel_proc)

            if match is None:
                if not find_other_ngos(text, source_ngo):
                    skipped_no_ngo += 1
                    stats['skipped_no_ngo'] += 1
                else:
                    skipped_no_rel += 1
                    stats['skipped_no_relation'] += 1
                continue

            stats['kept_files'] += 1
            kept += 1

            dest_dir = output_year_dir / source_ngo / 'text'
            if not dry_run:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(txt_file, dest_dir / txt_file.name)

            metadata_rows.append({
                'year': year,
                'source_ngo': source_ngo,
                'filename': txt_file.name,
                'target_ngos': match['target_ngos'],
                'relation_keywords': match['relation_keywords'],
            })

        if files:
            pct = f"{100*kept/len(files):.1f}%"
            logger.info(
                f"  [{year}] {source_ngo}: {kept}/{len(files)} kept ({pct}) "
                f"| no-NGO: {skipped_no_ngo}, no-rel: {skipped_no_rel}"
            )
        per_ngo_stats[source_ngo] = {
            'total': len(files), 'kept': kept,
            'skipped_no_ngo': skipped_no_ngo,
            'skipped_no_relation': skipped_no_rel,
        }

    # Write per-year metadata
    if not dry_run and metadata_rows:
        meta_dir = output_year_dir / '_metadata'
        meta_dir.mkdir(parents=True, exist_ok=True)
        with open(meta_dir / 'kept_files.jsonl', 'w', encoding='utf-8') as f:
            for row in metadata_rows:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
        with open(meta_dir / 'summary.json', 'w', encoding='utf-8') as f:
            json.dump({'year': year, 'totals': dict(stats),
                       'per_ngo': per_ngo_stats},
                      f, ensure_ascii=False, indent=2)

    return dict(stats)


# ── Pipeline runner ────────────────────────────────────────────────────────────

def run_filter(
    step3_dir: Path,
    output_dir: Path,
    keyword_config: Path,
    year: str = 'all',
    ngo_filter: str | None = None,
    dry_run: bool = False,
    include_other: bool = False,
):
    # Determine which year folders to process
    def is_dated_year(name: str) -> bool:
        return name.isdigit() and len(name) == 4

    all_year_dirs = sorted(
        d for d in step3_dir.iterdir()
        if d.is_dir() and not d.name.startswith('_')
        and (is_dated_year(d.name) or (include_other and d.name == 'other'))
    )
    if year == 'all':
        year_dirs = all_year_dirs
    else:
        target = step3_dir / year
        if not target.exists():
            logger.error(f"Year folder not found: {target}")
            sys.exit(1)
        year_dirs = [target]

    print(f"\n{'='*70}")
    print("STEP 4 – NGO CO-OCCURRENCE FILTER")
    print(f"  Input  : {step3_dir}")
    print(f"  Years  : {', '.join(d.name for d in year_dirs)}")
    print(f"  Output : {output_dir}")
    print(f"  Mode   : {'DRY RUN' if dry_run else 'WRITE'}")
    print(f"{'='*70}\n")

    relation_terms = load_relation_keywords(keyword_config)
    rel_proc = build_keyword_processor(relation_terms)

    grand = defaultdict(int)
    year_totals = {}

    for year_dir in year_dirs:
        yr = year_dir.name
        print(f"\n── {yr} {'─'*50}")
        stats = filter_year(
            input_year_dir  = year_dir,
            output_year_dir = output_dir / yr,
            rel_proc        = rel_proc,
            ngo_filter      = ngo_filter,
            dry_run         = dry_run,
        )
        for k, v in stats.items():
            grand[k] += v
        kept  = stats.get('kept_files', 0)
        total = stats.get('total_files', 0)
        pct   = f"{100*kept/total:.1f}%" if total else "n/a"
        year_totals[yr] = {'total': total, 'kept': kept}
        print(f"  {yr}: {kept} / {total} kept ({pct})")

    # ── Grand summary ──────────────────────────────────────────────────────
    total = grand['total_files']
    kept  = grand['kept_files']
    print(f"\n{'='*70}")
    print("OVERALL SUMMARY")
    print(f"{'='*70}")
    print(f"  {'Year':<8} {'Kept':>6} / {'Total':>7}  {'%':>6}")
    print(f"  {'-'*35}")
    for yr, t in year_totals.items():
        pct = f"{100*t['kept']/t['total']:.1f}%" if t['total'] else 'n/a'
        print(f"  {yr:<8} {t['kept']:>6} / {t['total']:>7}  {pct:>6}")
    print(f"  {'─'*35}")
    pct_all = f"{100*kept/total:.1f}%" if total else 'n/a'
    print(f"  {'ALL':<8} {kept:>6} / {total:>7}  {pct_all:>6}")
    print(f"\n  Dropped – no NGO    : {grand['skipped_no_ngo']}")
    print(f"  Dropped – no rel kw : {grand['skipped_no_relation']}")
    if dry_run:
        print("\n  (DRY RUN — no files written)")
    else:
        print(f"\n  Output : {output_dir}/{{year}}/{{ngo}}/text/")
    print(f"{'='*70}\n")

    return kept


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Step 4: filter step3 docs to those with NGO mention + relation keyword'
    )
    parser.add_argument('--year', default='all',
                        help='Year to process (2016-2025 / other / all). Default: all dated years')
    parser.add_argument('--include-other', action='store_true',
                        help='Also process the "other" (undated) folder — slow, 17k docs')
    parser.add_argument('--ngo', default=None,
                        help='Process only NGOs whose dir name contains this string')
    parser.add_argument('--dry-run', action='store_true',
                        help='Report counts without writing files')
    parser.add_argument('--input',  default='data/interim/step3_date_filter')
    parser.add_argument('--output', default='data/interim/step4_keyword_proximity_filtering')
    args = parser.parse_args()

    run_filter(
        step3_dir     = project_root / args.input,
        output_dir    = project_root / args.output,
        keyword_config= project_root / 'config' / 'content_filter_keywords.yaml',
        year          = args.year,
        ngo_filter    = args.ngo,
        dry_run       = args.dry_run,
        include_other = args.include_other,
    )
