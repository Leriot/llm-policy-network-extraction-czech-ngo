r"""
Reprocess Ekologicky institut Veronica – Step 3 Date Organisation
==================================================================
Veronica article pages carry a visible Czech-language publication line:
  Vloženo: d. m. yyyy
  (or variants: Vloženo: dd. mm. yyyy)

This appears in the body text of individual articles. The dc.datesubmitted
metadata tag present on all pages is a CMS placeholder (2000-01-01) and is
deliberately ignored.

Strategy:
  - Search the full page text for the pattern "Vloženo:\s*d+. m+. yyyy"
  - If exactly one unambiguous date is found → use it.
  - Multiple matches or no match → other.

Usage:
    python scripts/reprocess_veronica_dates.py [--dry-run]
"""

import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


import json, re, shutil, argparse, logging
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ROOT   = Path(__file__).parent.parent
NGO_NAME       = "Ekologicky institut Veronica"
STEP2_DIR      = PROJECT_ROOT / "data" / "step2_keyword_filter" / NGO_NAME
STEP1_METADATA = PROJECT_ROOT / "data" / "step1_content_extraction" / NGO_NAME / "metadata.jsonl"
RAW_PAGES_DIR  = PROJECT_ROOT / "data" / "raw" / NGO_NAME / "pages"
STEP3_BASE     = PROJECT_ROOT / "data" / "interim" / "step3_date_filter"
META_OUT       = STEP3_BASE / "_metadata" / NGO_NAME

# Pattern: "Publikováno:" followed by Czech date d. m. yyyy
# (optionally followed by ", autor/ka: ..." which we ignore)
VLOZENO_RE = re.compile(
    r'Publikov[aá]no\s*:\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})',
    re.IGNORECASE
)


def extract_date(html: str) -> str | None:
    """
    Search page text for 'Vloženo: d. m. yyyy'.
    Returns ISO date if exactly one unambiguous match; None otherwise.
    """
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(separator=' ')
    matches = VLOZENO_RE.findall(text)
    if not matches:
        return None
    # Deduplicate
    unique = list(dict.fromkeys(matches))
    if len(unique) != 1:
        # Multiple different dates on the page → likely a listing view
        return None
    day, month, year = int(unique[0][0]), int(unique[0][1]), int(unique[0][2])
    try:
        datetime(year, month, day)
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return None


def load_metadata_map() -> dict:
    mapping = {}
    with open(STEP1_METADATA, 'r', encoding='utf-8') as f:
        for line in f:
            e = json.loads(line)
            mapping[e['file']] = e['original_html']
    return mapping


def clear_existing(dry_run: bool) -> int:
    removed = 0
    for year_dir in STEP3_BASE.iterdir():
        if not year_dir.is_dir() or year_dir.name.startswith('_'):
            continue
        td = year_dir / NGO_NAME / "text"
        if td.exists():
            files = list(td.glob("*.txt"))
            if files:
                logger.info(f"  Removing {len(files)} from {year_dir.name}/{NGO_NAME}/text/")
                if not dry_run:
                    for f in files:
                        f.unlink()
            removed += len(files)
    return removed


def run(dry_run=False):
    logger.info("=" * 65)
    logger.info(f"{NGO_NAME} – Step 3 Date Reprocessing")
    if dry_run:
        logger.info("  DRY RUN")
    logger.info("=" * 65)

    metadata_map = load_metadata_map()
    text_files = sorted((STEP2_DIR / "text").glob("*.txt"))
    logger.info(f"Metadata entries: {len(metadata_map)}, step2 files: {len(text_files)}")

    removed = clear_existing(dry_run)
    logger.info(f"Cleared {removed} existing step3 files")

    if not dry_run:
        for y in range(2016, 2026):
            (STEP3_BASE / str(y) / NGO_NAME / "text").mkdir(parents=True, exist_ok=True)
        (STEP3_BASE / "other" / NGO_NAME / "text").mkdir(parents=True, exist_ok=True)

    by_year = {str(y): 0 for y in range(2016, 2026)}
    no_date = no_html = 0

    for i, txt_file in enumerate(text_files):
        if i % 500 == 0:
            logger.info(f"  Progress: {i}/{len(text_files)}")
        fname = txt_file.name
        if fname not in metadata_map:
            dest = STEP3_BASE / "other" / NGO_NAME / "text" / fname
            if not dry_run: shutil.copy2(txt_file, dest)
            no_html += 1
            continue

        html_path = RAW_PAGES_DIR / metadata_map[fname]
        if not html_path.exists():
            dest = STEP3_BASE / "other" / NGO_NAME / "text" / fname
            if not dry_run: shutil.copy2(txt_file, dest)
            no_html += 1
            continue

        html = html_path.read_text(encoding='utf-8', errors='replace')
        pub_date = extract_date(html)

        if pub_date and pub_date[:4] in by_year:
            dest = STEP3_BASE / pub_date[:4] / NGO_NAME / "text" / fname
            by_year[pub_date[:4]] += 1
        else:
            dest = STEP3_BASE / "other" / NGO_NAME / "text" / fname
            no_date += 1

        if not dry_run:
            shutil.copy2(txt_file, dest)

    stats = {"total_files": len(text_files), "by_year": by_year,
             "no_date": no_date, "no_html": no_html,
             "date_sources": {"Veronica Vloženo: text pattern": sum(by_year.values())}}
    if not dry_run:
        META_OUT.mkdir(parents=True, exist_ok=True)
        with open(META_OUT / "date_organization_stats.json", 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)

    logger.info("\nRESULTS:")
    for y, c in sorted(by_year.items()):
        if c: logger.info(f"  {y}: {c}")
    logger.info(f"  other: {no_date}  |  no_html: {no_html}")
    logger.info(f"  total dated: {sum(by_year.values())} / {len(text_files)}")
    if dry_run:
        logger.info("  (DRY RUN – nothing written)")
    logger.info("=" * 65)
    return stats


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--dry-run', action='store_true')
    run(dry_run=p.parse_args().dry_run)
