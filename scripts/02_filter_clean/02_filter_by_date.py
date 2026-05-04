"""
Filter Step 2 (Keyword Filtered) Data by Date

Maps filtered text files back to their original HTML files,
extracts publication dates, and filters by date range.

Usage:
    # Filter all NGOs
    python scripts/filter_step2_by_date.py --all --start-date "2017-01-01" --end-date "2025-12-31"

    # Filter single NGO
    python scripts/filter_step2_by_date.py --ngo "Arnika" --start-date "2017-01-01" --end-date "2025-12-31"

    # Optional: enable GLiNER ML date extraction (requires `pip install gliner2`,
    # not used in the final pipeline)
    python scripts/02_filter_clean/02_filter_by_date.py --all --start-date "2017-01-01" --end-date "2025-12-31" --use-gliner
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


def filter_ngo_by_date(
    ngo_name: str,
    step2_dir: Path,
    step1_dir: Path,
    raw_dir: Path,
    output_dir: Path,
    date_filter: DateFilter
) -> Dict:
    """
    Filter one NGO's data by date.

    Args:
        ngo_name: NGO name
        step2_dir: data/interim/step2_keyword_filter/{ngo}
        step1_dir: data/interim/step1_content_extraction/{ngo} (for metadata)
        raw_dir: data/raw/{ngo} (for HTML files)
        output_dir: data/interim/step3_date_filter/{ngo}
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
            'kept': 0,
            'excluded': 0,
            'no_html': 0,
            'no_date': 0,
            'out_of_range': 0
        }

    text_files = list(step2_text_dir.glob("*.txt"))

    stats = {
        'total_files': len(text_files),
        'kept': 0,
        'excluded': 0,
        'no_html': 0,
        'no_date': 0,
        'out_of_range': 0,
        'date_sources': {}
    }

    # Output directory
    output_text_dir = output_dir / "text"
    output_text_dir.mkdir(parents=True, exist_ok=True)

    # Track results
    results = []

    for i, txt_file in enumerate(text_files, 1):
        if i % 100 == 0:
            logger.info(f"  Processed {i}/{len(text_files)} files...")

        txt_filename = txt_file.name

        # Get corresponding HTML file
        if txt_filename not in file_to_html:
            logger.warning(f"No metadata for {txt_filename}")
            stats['no_html'] += 1
            stats['excluded'] += 1
            continue

        html_filename = file_to_html[txt_filename]
        html_path = raw_dir / "pages" / html_filename

        if not html_path.exists():
            logger.warning(f"HTML file not found: {html_path}")
            stats['no_html'] += 1
            stats['excluded'] += 1
            continue

        # Read HTML
        try:
            with open(html_path, 'r', encoding='utf-8', errors='replace') as f:
                html_content = f.read()
        except Exception as e:
            logger.error(f"Error reading {html_path}: {e}")
            stats['no_html'] += 1
            stats['excluded'] += 1
            continue

        # Extract date
        date_result = date_filter.extract_date(html_content, str(html_path))
        pub_date = date_result['date']
        source = date_result['source']

        # Check if in range
        keep = False
        reason = None

        if pub_date:
            stats['date_sources'][source] = stats['date_sources'].get(source, 0) + 1

            if date_filter._is_in_date_range(pub_date):
                keep = True
            else:
                stats['out_of_range'] += 1
                reason = f"Date out of range: {pub_date}"
        else:
            stats['no_date'] += 1
            reason = "No date found"

        # Keep or exclude
        if keep:
            stats['kept'] += 1

            # Copy text file to output
            shutil.copy(txt_file, output_text_dir / txt_filename)

            results.append({
                'file': txt_filename,
                'date': pub_date,
                'source': source,
                'kept': True
            })
        else:
            stats['excluded'] += 1

            results.append({
                'file': txt_filename,
                'date': pub_date,
                'source': source,
                'kept': False,
                'reason': reason
            })

    # Save results
    results_file = output_dir / "date_filter_results.jsonl"
    with open(results_file, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + '\n')

    # Save stats
    stats_file = output_dir / "date_filter_stats.json"
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    logger.info(f"Date filtering complete: {stats['kept']}/{stats['total_files']} pages kept")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Filter step2 keyword-filtered data by publication date',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Filter all NGOs (2017-2025)
  python scripts/filter_step2_by_date.py --all --start-date "2017-01-01" --end-date "2025-12-31"

  # Filter single NGO
  python scripts/filter_step2_by_date.py --ngo "Arnika" --start-date "2017-01-01" --end-date "2025-12-31"

  # Optional: enable GLiNER (requires gliner2; not used in the final pipeline)
  python scripts/02_filter_clean/02_filter_by_date.py --all --start-date "2017-01-01" --end-date "2025-12-31" --use-gliner
        """
    )

    # NGO selection
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--ngo', type=str, help='Process specific NGO by name')
    group.add_argument('--all', action='store_true', help='Process all NGOs')

    # Date range
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')

    # Options
    parser.add_argument('--use-gliner', action='store_true',
                       help='Enable optional GLiNER ML date extraction (requires gliner2; not used in final pipeline)')
    parser.add_argument('--preload-gliner', action='store_true',
                       help='Pre-load GLiNER model before processing (only with --use-gliner)')

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

    # Initialize date filter
    date_filter = DateFilter(
        start_date=args.start_date,
        end_date=args.end_date,
        use_gliner=args.use_gliner
    )

    # Pre-load GLiNER if requested
    if args.preload_gliner and args.use_gliner:
        logger.info("Pre-loading GLiNER model...")
        date_filter.preload_gliner_model()

    # Process each NGO
    overall_stats = {
        'total_files': 0,
        'kept': 0,
        'excluded': 0,
        'no_html': 0,
        'no_date': 0,
        'out_of_range': 0,
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
        output_ngo_dir = Path(f"data/interim/step3_date_filter/{ngo}")

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
            stats = filter_ngo_by_date(
                ngo,
                step2_ngo_dir,
                step1_ngo_dir,
                raw_ngo_dir,
                output_ngo_dir,
                date_filter
            )

            # Update overall stats
            overall_stats['total_files'] += stats['total_files']
            overall_stats['kept'] += stats['kept']
            overall_stats['excluded'] += stats['excluded']
            overall_stats['no_html'] += stats['no_html']
            overall_stats['no_date'] += stats['no_date']
            overall_stats['out_of_range'] += stats['out_of_range']
            overall_stats['ngos_processed'] += 1

            for source, count in stats['date_sources'].items():
                overall_stats['date_sources'][source] = \
                    overall_stats['date_sources'].get(source, 0) + count

            # Display results
            print(f"\nResults:")
            print(f"  Total files: {stats['total_files']}")
            print(f"  Kept: {stats['kept']} ({stats['kept']/stats['total_files']*100:.1f}%)")
            print(f"  Excluded: {stats['excluded']} ({stats['excluded']/stats['total_files']*100:.1f}%)")
            print(f"    - No HTML: {stats['no_html']}")
            print(f"    - No date: {stats['no_date']}")
            print(f"    - Out of range: {stats['out_of_range']}")

            if stats['date_sources']:
                print(f"\n  Date sources:")
                for source, count in sorted(stats['date_sources'].items(),
                                           key=lambda x: x[1], reverse=True):
                    print(f"    {source}: {count}")

            print(f"\n  Output saved to: {output_ngo_dir}")

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
        print(f"Kept: {overall_stats['kept']} " +
              f"({overall_stats['kept']/overall_stats['total_files']*100:.1f}%)")
        print(f"Excluded: {overall_stats['excluded']} " +
              f"({overall_stats['excluded']/overall_stats['total_files']*100:.1f}%)")
        print(f"  - No HTML: {overall_stats['no_html']}")
        print(f"  - No date: {overall_stats['no_date']}")
        print(f"  - Out of range: {overall_stats['out_of_range']}")

        if overall_stats['date_sources']:
            print(f"\nDate sources:")
            for source, count in sorted(overall_stats['date_sources'].items(),
                                       key=lambda x: x[1], reverse=True):
                print(f"  {source}: {count}")

        print(f"{'='*80}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
