"""
Filter Step 2 Data by Year (Multi-Year Organization)

Organizes filtered text files by publication year (2016-2025) and "other" for undated content.

Usage:
    # Filter all NGOs into year-based folders
    python scripts/filter_step2_by_year.py --all

    # Filter single NGO
    python scripts/filter_step2_by_year.py --ngo "Arnika"

    # With GLiNER (slower but more accurate)
    python scripts/filter_step2_by_year.py --all --use-gliner
"""
import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


import argparse
import sys
import json
import shutil
import logging
from pathlib import Path
from typing import Dict, List
from datetime import datetime

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from modules.date_filter import DateFilter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def filter_ngo_by_year(
    ngo_name: str,
    step2_dir: Path,
    step1_dir: Path,
    raw_dir: Path,
    output_base_dir: Path,
    date_filter: DateFilter
) -> Dict:
    """
    Filter one NGO's data by year, organizing into year-based folders.

    Args:
        ngo_name: NGO name
        step2_dir: data/interim/step2_keyword_filter/{ngo}
        step1_dir: data/interim/step1_content_extraction/{ngo} (for metadata)
        raw_dir: data/raw/{ngo} (for HTML files)
        output_base_dir: data/interim/step3_date_filter (base directory, not NGO-specific)
        date_filter: DateFilter instance

    Returns:
        Statistics dict
    """
    # Load metadata mapping (file -> url -> html)
    metadata_file = step1_dir / "metadata.jsonl"
    if not metadata_file.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_file}")

    # Build filename -> html mapping
    file_to_html = {}
    with open(metadata_file, 'r', encoding='utf-8') as f:
        for line in f:
            entry = json.loads(line)
            txt_file = entry['file']
            html_file = entry['original_html']
            file_to_html[txt_file] = html_file

    logger.info(f"Loaded {len(file_to_html)} metadata entries for {ngo_name}")

    # Get filtered text files from step2
    step2_text_dir = step2_dir / "text"
    if not step2_text_dir.exists():
        logger.warning(f"No text directory found: {step2_text_dir}")
        return {
            'total_files': 0,
            'by_year': {},
            'no_date': 0,
            'no_html': 0
        }

    text_files = list(step2_text_dir.glob("*.txt"))

    # Initialize stats
    stats = {
        'total_files': len(text_files),
        'by_year': {str(year): 0 for year in range(2016, 2026)},  # 2016-2025
        'no_date': 0,
        'no_html': 0,
        'date_sources': {}
    }

    # Create year directories + "other" with NGO subdirectories
    # Structure: year/{ngo}/text/
    year_dirs = {}
    for year in range(2016, 2026):
        year_dir = output_base_dir / str(year) / ngo_name / "text"
        year_dir.mkdir(parents=True, exist_ok=True)
        year_dirs[str(year)] = year_dir

    # Create "other" directory for undated content
    other_dir = output_base_dir / "other" / ngo_name / "text"
    other_dir.mkdir(parents=True, exist_ok=True)

    # Track all results for analysis
    results = []

    for i, txt_file in enumerate(text_files, 1):
        if i % 100 == 0:
            logger.info(f"  Processed {i}/{len(text_files)} files...")

        txt_filename = txt_file.name

        # Get corresponding HTML file
        if txt_filename not in file_to_html:
            logger.warning(f"No metadata for {txt_filename}")
            stats['no_html'] += 1
            # Copy to "other" - can't extract date without HTML
            shutil.copy(txt_file, other_dir / txt_filename)
            results.append({
                'file': txt_filename,
                'year': 'other',
                'reason': 'No metadata mapping'
            })
            continue

        html_filename = file_to_html[txt_filename]
        html_path = raw_dir / "pages" / html_filename

        if not html_path.exists():
            logger.warning(f"HTML file not found: {html_path}")
            stats['no_html'] += 1
            # Copy to "other"
            shutil.copy(txt_file, other_dir / txt_filename)
            results.append({
                'file': txt_filename,
                'year': 'other',
                'reason': 'HTML not found'
            })
            continue

        # Read HTML
        try:
            with open(html_path, 'r', encoding='utf-8', errors='replace') as f:
                html_content = f.read()
        except Exception as e:
            logger.error(f"Error reading {html_path}: {e}")
            stats['no_html'] += 1
            shutil.copy(txt_file, other_dir / txt_filename)
            results.append({
                'file': txt_filename,
                'year': 'other',
                'reason': f'Read error: {e}'
            })
            continue

        # Extract date
        date_result = date_filter.extract_date(html_content, str(html_path))
        pub_date = date_result['date']
        source = date_result['source']

        if pub_date:
            # Extract year
            try:
                year = pub_date[:4]  # YYYY from YYYY-MM-DD

                # Check if year is in our range (2016-2025)
                if year in stats['by_year']:
                    # Copy to year folder
                    shutil.copy(txt_file, year_dirs[year] / txt_filename)
                    stats['by_year'][year] += 1
                    stats['date_sources'][source] = stats['date_sources'].get(source, 0) + 1

                    results.append({
                        'file': txt_filename,
                        'year': year,
                        'date': pub_date,
                        'source': source
                    })
                else:
                    # Out of range year - put in "other"
                    shutil.copy(txt_file, other_dir / txt_filename)
                    stats['no_date'] += 1

                    results.append({
                        'file': txt_filename,
                        'year': 'other',
                        'date': pub_date,
                        'reason': f'Year {year} out of range (2016-2025)'
                    })
            except (ValueError, IndexError) as e:
                # Invalid date format
                shutil.copy(txt_file, other_dir / txt_filename)
                stats['no_date'] += 1

                results.append({
                    'file': txt_filename,
                    'year': 'other',
                    'date': pub_date,
                    'reason': f'Invalid date format: {e}'
                })
        else:
            # No date found - put in "other"
            shutil.copy(txt_file, other_dir / txt_filename)
            stats['no_date'] += 1

            results.append({
                'file': txt_filename,
                'year': 'other',
                'reason': 'No date found'
            })

    # Save results and stats to NGO directory at base level
    ngo_metadata_dir = output_base_dir / "_metadata" / ngo_name
    ngo_metadata_dir.mkdir(parents=True, exist_ok=True)

    results_file = ngo_metadata_dir / "date_organization_results.jsonl"
    with open(results_file, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + '\n')

    # Save stats
    stats_file = ngo_metadata_dir / "date_organization_stats.json"
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    total_dated = sum(stats['by_year'].values())
    logger.info(f"Date organization complete: {total_dated}/{stats['total_files']} pages dated, " +
                f"{stats['no_date']} in 'other'")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Organize step2 keyword-filtered data by publication year',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Organize all NGOs by year (2016-2025)
  python scripts/filter_step2_by_year.py --all

  # Organize single NGO
  python scripts/filter_step2_by_year.py --ngo "Arnika"

  # Use GLiNER (slower but more accurate)
  python scripts/filter_step2_by_year.py --all --use-gliner
        """
    )

    # NGO selection
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--ngo', type=str, help='Process specific NGO by name')
    group.add_argument('--all', action='store_true', help='Process all NGOs')

    # Options
    parser.add_argument('--use-gliner', action='store_true',
                       help='Enable GLiNER ML model (slower but more accurate)')
    parser.add_argument('--preload-gliner', action='store_true',
                       help='Pre-load GLiNER model before processing')

    args = parser.parse_args()

    # Determine NGOs to process
    if args.all:
        step2_dir = Path("data/interim/step2_keyword_filter")
        if not step2_dir.exists():
            logger.error(f"Step2 directory not found: {step2_dir}")
            return 1

        ngos = [d.name for d in step2_dir.iterdir() if d.is_dir()]
        if not ngos:
            logger.error("No NGOs found in data/interim/step2_keyword_filter/")
            return 1

        logger.info(f"Found {len(ngos)} NGOs to process")
    else:
        ngos = [args.ngo]

    # Initialize date filter (no date range - we organize by year)
    date_filter = DateFilter(
        start_date="2016-01-01",
        end_date="2025-12-31",
        use_gliner=args.use_gliner
    )

    # Pre-load GLiNER if requested
    if args.preload_gliner and args.use_gliner:
        logger.info("Pre-loading GLiNER model...")
        date_filter.preload_gliner_model()

    # Process each NGO
    overall_stats = {
        'total_files': 0,
        'by_year': {str(year): 0 for year in range(2016, 2026)},
        'no_date': 0,
        'no_html': 0,
        'ngos_processed': 0,
        'date_sources': {}
    }

    for ngo in ngos:
        print(f"\n{'='*80}")
        print(f"Processing: {ngo}")
        print(f"{'='*80}")

        step2_ngo_dir = Path(f"data/interim/step2_keyword_filter/{ngo}")
        step1_ngo_dir = Path(f"data/interim/step1_content_extraction/{ngo}")
        raw_ngo_dir = Path(f"data/raw/{ngo}")
        output_base_dir = Path("data/interim/step3_date_filter")

        # Check directories exist
        if not step2_ngo_dir.exists():
            logger.warning(f"Skipping {ngo}: step2 directory not found")
            continue

        if not step1_ngo_dir.exists():
            logger.warning(f"Skipping {ngo}: step1 directory not found (need metadata)")
            continue

        if not raw_ngo_dir.exists():
            logger.warning(f"Skipping {ngo}: raw directory not found (need HTML files)")
            continue

        try:
            # Filter
            stats = filter_ngo_by_year(
                ngo,
                step2_ngo_dir,
                step1_ngo_dir,
                raw_ngo_dir,
                output_base_dir,
                date_filter
            )

            # Update overall stats
            overall_stats['total_files'] += stats['total_files']
            overall_stats['no_date'] += stats['no_date']
            overall_stats['no_html'] += stats['no_html']
            overall_stats['ngos_processed'] += 1

            for year in stats['by_year']:
                overall_stats['by_year'][year] += stats['by_year'][year]

            for source, count in stats['date_sources'].items():
                overall_stats['date_sources'][source] = \
                    overall_stats['date_sources'].get(source, 0) + count

            # Display results
            total_dated = sum(stats['by_year'].values())
            print(f"\nResults:")
            print(f"  Total files: {stats['total_files']}")
            print(f"  Dated: {total_dated} ({total_dated/stats['total_files']*100:.1f}%)")
            print(f"  Other (no date/errors): {stats['no_date']} ({stats['no_date']/stats['total_files']*100:.1f}%)")

            print(f"\n  Distribution by year:")
            for year in range(2016, 2026):
                count = stats['by_year'][str(year)]
                if count > 0:
                    print(f"    {year}: {count} files")

            if stats['date_sources']:
                print(f"\n  Date sources:")
                for source, count in sorted(stats['date_sources'].items(),
                                           key=lambda x: x[1], reverse=True):
                    print(f"    {source}: {count}")

            print(f"\n  Output structure: data/interim/step3_date_filter/{{year}}/{ngo}/text/")

        except Exception as e:
            logger.error(f"Error processing {ngo}: {e}", exc_info=True)
            continue

    # Overall summary
    if overall_stats['ngos_processed'] > 1:
        print(f"\n{'='*80}")
        print("OVERALL SUMMARY")
        print(f"{'='*80}")
        print(f"NGOs processed: {overall_stats['ngos_processed']}")
        print(f"Total files: {overall_stats['total_files']}")

        total_dated = sum(overall_stats['by_year'].values())
        print(f"Dated: {total_dated} ({total_dated/overall_stats['total_files']*100:.1f}%)")
        print(f"Other (no date): {overall_stats['no_date']} ({overall_stats['no_date']/overall_stats['total_files']*100:.1f}%)")

        print(f"\nDistribution by year:")
        for year in range(2016, 2026):
            count = overall_stats['by_year'][str(year)]
            print(f"  {year}: {count} files ({count/overall_stats['total_files']*100:.1f}%)")

        print(f"\nOther: {overall_stats['no_date']} files ({overall_stats['no_date']/overall_stats['total_files']*100:.1f}%)")

        if overall_stats['date_sources']:
            print(f"\nDate sources:")
            for source, count in sorted(overall_stats['date_sources'].items(),
                                       key=lambda x: x[1], reverse=True):
                print(f"  {source}: {count} ({count/total_dated*100:.1f}%)")

        print(f"{'='*80}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
