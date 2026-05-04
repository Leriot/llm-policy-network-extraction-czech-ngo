"""
Reprocess CI2 – Step 3 Date Organisation
==========================================
CI2 individual article pages carry:
  <span class="time pubdate">d. m. yyyy</span>

Listing/archive pages also have this element but with multiple entries
representing listed articles. The strategy is:
  - If exactly ONE <span class="time pubdate"> is found → reliable article page,
    use that date.
  - If multiple pubdate spans exist → listing page, skip (→ other).

This mirrors the Frank Bold approach of discriminating article pages from
listing pages via structural signals.

Usage:
    python scripts/reprocess_ci2_dates.py [--dry-run]
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
NGO_NAME       = "CI2"
STEP2_DIR      = PROJECT_ROOT / "data" / "step2_keyword_filter" / NGO_NAME
STEP1_METADATA = PROJECT_ROOT / "data" / "step1_content_extraction" / NGO_NAME / "metadata.jsonl"
RAW_PAGES_DIR  = PROJECT_ROOT / "data" / "raw" / NGO_NAME / "pages"
STEP3_BASE     = PROJECT_ROOT / "data" / "interim" / "step3_date_filter"
META_OUT       = STEP3_BASE / "_metadata" / NGO_NAME

CZECH_MONTHS = {
    'ledna':1,'února':2,'března':3,'dubna':4,'května':5,'června':6,
    'července':7,'srpna':8,'září':9,'října':10,'listopadu':11,'prosince':12
}


def parse_czech_date(text: str) -> str | None:
    """Parse Czech date formats: d. m. yyyy or d. Month yyyy"""
    # Numeric: 6. 12. 2022
    m = re.search(r'(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})', text)
    if m:
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            datetime(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except ValueError:
            pass
    # Month name: 6. prosince 2022
    pat = r'(\d{1,2})\.\s+(' + '|'.join(CZECH_MONTHS) + r')\s+(\d{4})'
    m = re.search(pat, text, re.IGNORECASE)
    if m:
        try:
            d, mo, y = int(m.group(1)), CZECH_MONTHS[m.group(2).lower()], int(m.group(3))
            datetime(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except ValueError:
            pass
    return None


def extract_date(html: str) -> str | None:
    """
    Return ISO date from a single <span class="time pubdate">.
    If multiple pubdate spans exist (listing page), return None.
    """
    soup = BeautifulSoup(html, 'html.parser')
    pubdates = soup.find_all('span', class_='pubdate')
    if len(pubdates) != 1:
        return None  # listing page or no date
    return parse_czech_date(pubdates[0].get_text(strip=True))


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
    no_date = no_html = listing_skipped = 0

    for txt_file in text_files:
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
             "date_sources": {"CI2 <span class=pubdate> (single)": sum(by_year.values())}}
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
