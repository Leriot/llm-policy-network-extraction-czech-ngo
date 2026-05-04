"""
Step 5: Iterative Dataset Cleaning
===================================
Takes the Step 4 keyword-proximity-filtered dataset and applies source-specific
cleaning rules to remove boilerplate or navigation content that was falsely
triggering keyword or NGO matches.

This is an ITERATIVE process run during coding: each time a systematic false-positive
pattern is discovered for a particular source, a new rule is added here, and the
step5 dataset is regenerated before continuing to code.

Current rules
-------------
Greenpeace CR (Rule 1 — added March 2026)
    All article text is truncated at the first occurrence of "Související články"
    (Czech for "Related articles"). The section after this heading is website
    navigation/boilerplate listing related articles on the site — it is not part
    of the article body and was producing spurious NGO name and keyword hits during
    initial coding review.

Output structure
----------------
    data/interim/step5_iterative_cleaning/{year}/{org}/text/*.txt
    data/interim/step5_iterative_cleaning/{year}/_metadata/kept_files.jsonl

The metadata is re-validated after text cleaning: any target-NGO entry whose name
no longer appears in the cleaned article text is removed. Articles whose ALL target
NGOs are removed this way are dropped from the metadata entirely. This ensures that
the step5 metadata only contains proximity matches that survived boilerplate removal
(i.e. genuine article-body mentions, not website-widget false positives).

Usage
-----
    python scripts/step5_iterative_cleaning.py
    python scripts/step5_iterative_cleaning.py --force   # overwrite existing output
    python scripts/step5_iterative_cleaning.py --input data/interim/step4_keyword_proximity_filtering --output data/interim/step5_iterative_cleaning
"""
import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


import json
import re
import shutil
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# NGO name variants for post-cleaning metadata re-validation
# ---------------------------------------------------------------------------
# Maps the directory name (= source_ngo / target_ngo in metadata) to the list
# of name forms that may appear in article text (including Czech declensions).
# A target NGO is considered "present" if ANY variant appears in the cleaned text.
# Keep this in sync with _NGO_SHORT in prepare_intercoder_sample.py.

NGO_VARIANTS: dict[str, list[str]] = {
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


def _ngo_present(text_lower: str, ngo_dir: str) -> bool:
    """Return True if any name variant for `ngo_dir` appears in `text_lower`."""
    variants = NGO_VARIANTS.get(ngo_dir, [ngo_dir])
    return any(v.lower() in text_lower for v in variants)


# ---------------------------------------------------------------------------
# Cleaning rules
# ---------------------------------------------------------------------------
# Structure: dict[org_dir_name, list[callable(text: str) -> str]]
# Rules are applied in order; each receives the (possibly already-modified) text.

def _cut_at_marker(text: str, marker: str) -> str:
    """Return text truncated just before `marker` (first occurrence, case-sensitive)."""
    pos = text.find(marker)
    if pos == -1:
        return text
    return text[:pos].rstrip()


RULES: dict[str, list] = {
    # ── Greenpeace CR ─────────────────────────────────────────────────────────
    # Rule 1: strip "Related articles" navigation block.
    # The section starting with "Související články" is a website widget listing
    # other articles on the site. It frequently names other NGOs (as article
    # co-authors) and contains collaboration keywords — but these refer to OTHER
    # articles, not to the article body being coded. Truncating at this heading
    # removes the boilerplate while preserving the full article text.
    'Greenpeace CR': [
        lambda t: _cut_at_marker(t, 'Související články'),
    ],
    # ── Arnika ────────────────────────────────────────────────────────────────
    # Rule 1: strip the site footer / donate block that follows every article.
    # Arnika article pages share a footer that begins with the social-icon row
    # "youtube facebook linked instagram bsky" and continues with the donation
    # widget ("Podpořte Arniku v tom, co dělá …"), the staff sign-up form, the
    # campaign nav menu, and contact details. This block names other NGOs and
    # campaigns and was producing spurious co-mention/collaboration hits during
    # coding. Truncating at the social-icon row removes the footer while
    # preserving the article body and its closing hashtag list.
    'Arnika': [
        lambda t: _cut_at_marker(t, 'youtube facebook linked instagram bsky'),
    ],
}


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def apply_rules(text: str, org: str) -> tuple[str, bool]:
    """Apply all cleaning rules for `org`. Returns (cleaned_text, was_modified)."""
    rules = RULES.get(org, [])
    cleaned = text
    for rule in rules:
        cleaned = rule(cleaned)
    return cleaned, cleaned != text


def process(
    step4_dir: Path,
    step5_dir: Path,
    verbose: bool = True,
) -> dict:
    """
    Walk step4_dir, apply cleaning rules, write to step5_dir.
    Metadata (_metadata/) is copied unchanged — step5 does not re-run the
    proximity filter; it only cleans article text.

    Returns a stats dict.
    """
    stats = {
        'years': 0,
        'files_total': 0,
        'files_modified': 0,
        'chars_removed': 0,
        'meta_pairs_removed': 0,
        'meta_articles_dropped': 0,
        'by_org': {},
    }

    year_dirs = sorted(
        d for d in step4_dir.iterdir()
        if d.is_dir() and re.match(r'^\d{4}$', d.name)
    )

    for year_dir in year_dirs:
        stats['years'] += 1
        if verbose:
            print(f"\n{year_dir.name}:")

        # ── Pass 1: clean text files ──────────────────────────────────────────
        # Build a map filename -> cleaned_text for the metadata re-validation pass
        cleaned_texts: dict[str, dict[str, str]] = {}  # org_name -> filename -> text_lower

        for org_dir in sorted(year_dir.iterdir()):
            if not org_dir.is_dir() or org_dir.name == '_metadata':
                continue

            org_name = org_dir.name
            stats['by_org'].setdefault(
                org_name, {'files': 0, 'modified': 0, 'chars_removed': 0,
                           'pairs_removed': 0, 'articles_dropped': 0}
            )
            cleaned_texts[org_name] = {}

            text_src_dir = org_dir / 'text'
            if not text_src_dir.exists():
                continue

            text_dst_dir = step5_dir / year_dir.name / org_name / 'text'
            text_dst_dir.mkdir(parents=True, exist_ok=True)

            modified_count = 0
            txt_files = sorted(text_src_dir.glob('*.txt'))
            for txt_file in txt_files:
                stats['files_total'] += 1
                stats['by_org'][org_name]['files'] += 1

                text = txt_file.read_text(encoding='utf-8', errors='replace')
                cleaned, modified = apply_rules(text, org_name)

                dst_file = text_dst_dir / txt_file.name
                dst_file.write_text(cleaned, encoding='utf-8')
                cleaned_texts[org_name][txt_file.name] = cleaned.lower()

                if modified:
                    stats['files_modified'] += 1
                    stats['by_org'][org_name]['modified'] += 1
                    removed = len(text) - len(cleaned)
                    stats['chars_removed'] += removed
                    stats['by_org'][org_name]['chars_removed'] += removed
                    modified_count += 1

            if verbose:
                n = len(txt_files)
                tag = f" ({modified_count} trimmed)" if modified_count else ""
                print(f"  {org_name}: {n} files{tag}")

        # ── Pass 2: re-validate and rewrite metadata ──────────────────────────
        meta_src = year_dir / '_metadata' / 'kept_files.jsonl'
        meta_dst_dir = step5_dir / year_dir.name / '_metadata'
        meta_dst_dir.mkdir(parents=True, exist_ok=True)
        meta_dst = meta_dst_dir / 'kept_files.jsonl'

        if meta_src.exists():
            kept_rows = []
            pairs_removed = 0
            articles_dropped = 0

            with open(meta_src, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    src = row.get('source_ngo', '')
                    fname = row.get('filename', '')
                    targets = row.get('target_ngos', [])

                    text_lower = cleaned_texts.get(src, {}).get(fname, '')

                    # Keep only target NGOs whose name still appears in the
                    # cleaned article text.
                    if text_lower:
                        surviving = [t for t in targets if _ngo_present(text_lower, t)]
                        removed_n = len(targets) - len(surviving)
                    else:
                        # Text file not found — keep as-is (no cleaning happened)
                        surviving = targets
                        removed_n = 0

                    if removed_n:
                        pairs_removed += removed_n
                        stats['meta_pairs_removed'] += removed_n
                        stats['by_org'].setdefault(src, {}).setdefault('pairs_removed', 0)
                        stats['by_org'][src]['pairs_removed'] = (
                            stats['by_org'][src].get('pairs_removed', 0) + removed_n
                        )

                    if not surviving:
                        # All target NGOs were boilerplate — drop article entirely
                        articles_dropped += 1
                        stats['meta_articles_dropped'] += 1
                        stats['by_org'].setdefault(src, {}).setdefault('articles_dropped', 0)
                        stats['by_org'][src]['articles_dropped'] = (
                            stats['by_org'][src].get('articles_dropped', 0) + 1
                        )
                        continue

                    row['target_ngos'] = surviving
                    kept_rows.append(json.dumps(row, ensure_ascii=False))

            meta_dst.write_text('\n'.join(kept_rows) + '\n', encoding='utf-8')

            if verbose and (pairs_removed or articles_dropped):
                print(
                    f"  [metadata] {pairs_removed} target-NGO pairs removed, "
                    f"{articles_dropped} articles dropped"
                )
        else:
            # No metadata for this year — nothing to rewrite
            pass

    return stats


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Step 5: iterative text cleaning of the keyword-proximity dataset',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        '--input', default='data/interim/step4_keyword_proximity_filtering',
        help='Step 4 base directory (default: data/interim/step4_keyword_proximity_filtering)',
    )
    parser.add_argument(
        '--output', default='data/interim/step5_iterative_cleaning',
        help='Step 5 output directory (default: data/interim/step5_iterative_cleaning)',
    )
    parser.add_argument(
        '--force', action='store_true',
        help='Overwrite existing output directory',
    )
    args = parser.parse_args()

    step4_dir = Path(args.input)
    step5_dir = Path(args.output)

    if not step4_dir.exists():
        print(f"ERROR: Input directory not found: {step4_dir}", file=sys.stderr)
        sys.exit(1)

    if step5_dir.exists():
        if not args.force:
            print(f"ERROR: Output directory already exists: {step5_dir}", file=sys.stderr)
            print("Use --force to overwrite.", file=sys.stderr)
            sys.exit(1)
        shutil.rmtree(step5_dir)

    print("Step 5 — Iterative Dataset Cleaning")
    print(f"  Input:  {step4_dir}")
    print(f"  Output: {step5_dir}")
    print(f"\nActive cleaning rules:")
    for org, rules in RULES.items():
        print(f"  {org}: {len(rules)} rule(s)")

    stats = process(step4_dir, step5_dir, verbose=True)

    print(f"\n{'=' * 55}")
    print(f"Done.")
    print(f"  Years processed:          {stats['years']}")
    print(f"  Files processed:          {stats['files_total']}")
    print(f"  Files text-trimmed:       {stats['files_modified']}")
    print(f"  Characters removed:       {stats['chars_removed']:,}")
    print(f"  Metadata pairs removed:   {stats['meta_pairs_removed']}")
    print(f"  Metadata articles dropped:{stats['meta_articles_dropped']}")

    print(f"\nPer-organisation breakdown (affected only):")
    any_affected = False
    for org, s in sorted(stats['by_org'].items()):
        trimmed   = s.get('modified', 0)
        pairs_rm  = s.get('pairs_removed', 0)
        arts_drop = s.get('articles_dropped', 0)
        if trimmed or pairs_rm or arts_drop:
            any_affected = True
            n = s.get('files', 0)
            pct = 100 * trimmed / n if n else 0
            print(
                f"  {org}: {trimmed}/{n} files trimmed ({pct:.0f}%), "
                f"{s.get('chars_removed',0):,} chars removed, "
                f"{pairs_rm} meta pairs removed, {arts_drop} articles dropped"
            )
    if not any_affected:
        print("  (none)")


if __name__ == '__main__':
    main()
