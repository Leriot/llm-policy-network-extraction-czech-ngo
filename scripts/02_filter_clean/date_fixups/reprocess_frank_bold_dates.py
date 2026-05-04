"""
Reprocess Frank Bold – Step 3 Date Organisation
=================================================
Frank Bold's news/article pages use <time datetime="YYYY-MM-DD"> inside
<div class="content"><div class="meta"> as their publication date.
Static/listing pages also have <time> elements but inside <div class="col-center">
(sidebar), not <div class="content">.

The generic date-filter module skipped <time> elements on pages without an
<article> HTML5 tag (all Frank Bold pages), which caused 1173 files to end up
in data/interim/step3_date_filter/other/ with no year assigned.

This script:
  1. Removes existing Frank Bold entries from step3 year folders AND other/
  2. Re-reads each Frank Bold step2 text file, finds its raw HTML, extracts the
     publication date via the first <time datetime="..."> inside a grandparent
     with class "content"
  3. Copies the text file into the correct step3/{year}/Frank Bold/text/ folder
  4. Updates the date_organization_stats.json for Frank Bold

Usage:
    python scripts/reprocess_frank_bold_dates.py [--dry-run]
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
import argparse
import logging
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ROOT   = Path(__file__).parent.parent
STEP2_DIR      = PROJECT_ROOT / "data" / "step2_keyword_filter" / "Frank Bold"
STEP1_METADATA = PROJECT_ROOT / "data" / "step1_content_extraction" / "Frank Bold" / "metadata.jsonl"
RAW_PAGES_DIR  = PROJECT_ROOT / "data" / "raw" / "Frank Bold" / "pages"
STEP3_BASE     = PROJECT_ROOT / "data" / "interim" / "step3_date_filter"
META_OUT       = STEP3_BASE / "_metadata" / "Frank Bold"
NGO_NAME       = "Frank Bold"


def extract_frank_bold_date(html: str) -> str | None:
    """
    Extract publication date from a Frank Bold HTML page.

    Uses the first <time datetime="..."> element whose grandparent element
    has class "content" (the main article content area).
    Static/listing pages have <time> elements only in grandparent "col-center"
    or "item" (sidebar) — those are deliberately ignored.

    Returns ISO date string "YYYY-MM-DD" or None.
    """
    soup = BeautifulSoup(html, 'html.parser')
    for time_elem in soup.find_all('time'):
        dt = time_elem.get('datetime', '').strip()
        if not dt:
            continue
        parent     = time_elem.parent
        grandparent = parent.parent if parent else None
        if grandparent is None:
            continue
        gp_classes = grandparent.get('class', [])
        if 'content' in gp_classes:
            # Validate ISO date format
            m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', dt)
            if m:
                try:
                    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    datetime(year, month, day)          # validate
                    return f"{year:04d}-{month:02d}-{day:02d}"
                except ValueError:
                    pass
    return None


def load_metadata_map() -> dict:
    """Returns {txt_filename: html_filename} from step1 metadata."""
    mapping = {}
    with open(STEP1_METADATA, 'r', encoding='utf-8') as f:
        for line in f:
            entry = json.loads(line)
            mapping[entry['file']] = entry['original_html']
    return mapping


def clear_existing_frank_bold(dry_run: bool) -> int:
    """Remove all existing Frank Bold text files from step3 (all years + other)."""
    removed = 0
    for year_dir in STEP3_BASE.iterdir():
        if not year_dir.is_dir() or year_dir.name.startswith('_'):
            continue
        ngo_text_dir = year_dir / NGO_NAME / "text"
        if ngo_text_dir.exists():
            files = list(ngo_text_dir.glob("*.txt"))
            if files:
                logger.info(f"  Removing {len(files)} files from {year_dir.name}/Frank Bold/text/")
                if not dry_run:
                    for f in files:
                        f.unlink()
            removed += len(files)
    return removed


def run(dry_run: bool = False):
    logger.info("=" * 65)
    logger.info("FRANK BOLD – Step 3 Date Reprocessing")
    if dry_run:
        logger.info("  (DRY RUN – no files will be written)")
    logger.info("=" * 65)

    # Load metadata mapping
    metadata_map = load_metadata_map()
    logger.info(f"Loaded {len(metadata_map)} metadata entries")

    # Get step2 text files
    step2_text_dir = STEP2_DIR / "text"
    text_files = sorted(step2_text_dir.glob("*.txt"))
    logger.info(f"Step2 text files to process: {len(text_files)}")

    # Clear existing step3 Frank Bold data
    removed = clear_existing_frank_bold(dry_run)
    logger.info(f"Cleared {removed} existing step3 Frank Bold files")

    # Ensure year + other directories exist
    if not dry_run:
        for year in range(2016, 2026):
            (STEP3_BASE / str(year) / NGO_NAME / "text").mkdir(parents=True, exist_ok=True)
        (STEP3_BASE / "other" / NGO_NAME / "text").mkdir(parents=True, exist_ok=True)

    # Stats
    by_year  = {str(y): 0 for y in range(2016, 2026)}
    no_date  = 0
    no_html  = 0
    date_sources = {"Frank Bold <time> in content div": 0}
    results  = []

    for txt_file in text_files:
        fname = txt_file.name

        if fname not in metadata_map:
            logger.warning(f"  No metadata for {fname} – copying to other/")
            dest = STEP3_BASE / "other" / NGO_NAME / "text" / fname
            if not dry_run:
                shutil.copy2(txt_file, dest)
            no_html += 1
            results.append({'file': fname, 'year': 'other', 'reason': 'No metadata'})
            continue

        html_fname = metadata_map[fname]
        html_path  = RAW_PAGES_DIR / html_fname

        if not html_path.exists():
            logger.warning(f"  HTML not found: {html_fname} – copying to other/")
            dest = STEP3_BASE / "other" / NGO_NAME / "text" / fname
            if not dry_run:
                shutil.copy2(txt_file, dest)
            no_html += 1
            results.append({'file': fname, 'year': 'other', 'reason': 'HTML missing'})
            continue

        html_content = html_path.read_text(encoding='utf-8', errors='replace')
        pub_date = extract_frank_bold_date(html_content)

        if pub_date:
            year = pub_date[:4]
            if year in by_year:
                dest = STEP3_BASE / str(year) / NGO_NAME / "text" / fname
                by_year[year] += 1
                date_sources["Frank Bold <time> in content div"] += 1
            else:
                dest = STEP3_BASE / "other" / NGO_NAME / "text" / fname
                no_date += 1
            if not dry_run:
                shutil.copy2(txt_file, dest)
            results.append({'file': fname, 'year': year if year in by_year else 'other',
                             'date': pub_date})
        else:
            dest = STEP3_BASE / "other" / NGO_NAME / "text" / fname
            if not dry_run:
                shutil.copy2(txt_file, dest)
            no_date += 1
            results.append({'file': fname, 'year': 'other', 'reason': 'No date found'})

    # Write updated stats
    stats = {
        "total_files": len(text_files),
        "by_year": by_year,
        "no_date": no_date,
        "no_html": no_html,
        "date_sources": date_sources,
    }
    if not dry_run:
        META_OUT.mkdir(parents=True, exist_ok=True)
        with open(META_OUT / "date_organization_stats.json", 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        with open(META_OUT / "date_results.jsonl", 'w', encoding='utf-8') as f:
            for row in results:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')

    # Summary
    logger.info("\n" + "=" * 65)
    logger.info("RESULTS")
    logger.info("=" * 65)
    total_dated = sum(by_year.values())
    for year, count in sorted(by_year.items()):
        if count:
            logger.info(f"  {year}: {count}")
    logger.info(f"  other (no date): {no_date}")
    logger.info(f"  no HTML found : {no_html}")
    logger.info(f"  ─────────────────")
    logger.info(f"  Total input   : {len(text_files)}")
    logger.info(f"  Total dated   : {total_dated}")
    logger.info(f"  ─────────────────")
    if dry_run:
        logger.info("  (DRY RUN – nothing written)")
    else:
        logger.info("  Step3 updated. Now run step4 for Frank Bold:")
        logger.info("    python scripts/filter_step4_ngo_collab.py --ngo 'Frank Bold'")
    logger.info("=" * 65)

    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Reprocess Frank Bold step3 dates using <time> in content div'
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would happen without writing any files')
    args = parser.parse_args()
    run(dry_run=args.dry_run)
