"""
Batch Scraper for Multiple NGOs
Scrapes multiple NGOs sequentially with progress tracking and error handling

Usage:
    # Scrape all NGOs (no page limit)
    python scripts/batch_scrape.py --all

    # Scrape specific NGOs
    python scripts/batch_scrape.py --ngos "Arnika" "Hnutí Duha" "Calla"

    # Scrape with page limit (for testing)
    python scripts/batch_scrape.py --all --max-pages 100

    # Scrape in batches
    python scripts/batch_scrape.py --batch 1  # First 5 NGOs
    python scripts/batch_scrape.py --batch 2  # Next 5 NGOs
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
import time
import re
from pathlib import Path
from datetime import datetime
import pandas as pd
import logging
import json

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from modules.scraping import NGOScraper

# Configure logging
Path("data/logs").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f'data/logs/batch_scrape_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)


# Batch definitions for 19 NGOs (4-5 NGOs per batch for manageable chunks)
BATCHES = {
    1: ["Aliance pro energetickou sobestacnost", "Arnika", "Autoklub CR", "Beleco"],
    2: ["Calla - Sdruzeni pro zachranu prostredi", "Centrum pro dopravu a energetiku",
        "CI2", "Cesky svaz ochrancu prirody"],
    3: ["Ekologicky institut Veronica", "Extinction Rebellion [Posledni generace]",
        "Fakta o klimatu", "Frank Bold"],
    4: ["Fridays for Future", "Greenpeace CR", "Hnuti Duha", "Klimaticka koalice"],
    5: ["Limity jsme my", "Nesehnuti", "Zeleny kruh"]
}


def load_ngo_config(config_file: str = "config/ngo_config.csv") -> pd.DataFrame:
    """Load NGO configuration."""
    try:
        df = pd.read_csv(config_file)
        logger.info(f"Loaded {len(df)} NGOs from {config_file}")
        return df
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        raise


def setup_ngo_logger(ngo_name: str) -> logging.Logger:
    """
    Set up a dedicated logger for an NGO with its own file.
    This allows tracking progress per NGO in parallel execution.

    Args:
        ngo_name: Name of the NGO

    Returns:
        Logger instance
    """
    # Sanitize NGO name for filename
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', ngo_name)

    # Create NGO-specific logger
    ngo_logger = logging.getLogger(f"ngo.{safe_name}")
    ngo_logger.setLevel(logging.INFO)
    ngo_logger.propagate = False  # Don't propagate to root logger

    # Clear any existing handlers
    ngo_logger.handlers.clear()

    # Add file handler for this NGO
    log_file = Path(f'data/logs/{safe_name}_progress.log')
    log_file.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    )
    ngo_logger.addHandler(file_handler)

    # Also add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        logging.Formatter(f'[{safe_name}] %(asctime)s - %(message)s')
    )
    ngo_logger.addHandler(console_handler)

    return ngo_logger


def scrape_ngo(scraper: NGOScraper, ngo_row: pd.Series, max_pages: int = None) -> dict:
    """
    Scrape a single NGO with dedicated logging.

    Args:
        scraper: NGOScraper instance
        ngo_row: Row from NGO config DataFrame
        max_pages: Maximum pages to scrape (None = unlimited)

    Returns:
        Dictionary with scraping statistics
    """
    ngo_name = ngo_row['ngo_name']
    url = ngo_row['url']
    depth_limit = int(ngo_row['depth_limit'])

    # Set up dedicated logger for this NGO
    ngo_logger = setup_ngo_logger(ngo_name)

    ngo_logger.info(f"{'='*80}")
    ngo_logger.info(f"Starting scrape: {ngo_name}")
    ngo_logger.info(f"URL: {url}")
    ngo_logger.info(f"Max Depth: {depth_limit}")
    ngo_logger.info(f"Max Pages: {max_pages if max_pages else 'Unlimited'}")
    ngo_logger.info(f"Progress can be monitored at: data/raw/{ngo_name}/scraping_progress.txt")
    ngo_logger.info(f"{'='*80}")

    try:
        start_time = time.time()

        # Prepare seed URLs
        seed_urls = [{'url': url}]

        # Run scrape
        stats = scraper.scrape_ngo(
            ngo_name=ngo_name,
            seed_urls=seed_urls,
            max_depth=depth_limit,
            max_pages=max_pages
        )

        elapsed = time.time() - start_time
        stats['elapsed_time'] = elapsed
        stats['status'] = 'success'

        ngo_logger.info(f"")
        ngo_logger.info(f"✓ {ngo_name} completed successfully in {elapsed/60:.1f} minutes")
        ngo_logger.info(f"  Pages: {stats.get('storage_stats', {}).get('pages_saved', 0)}")
        ngo_logger.info(f"  Links: {stats.get('total_links', 0)}")
        ngo_logger.info(f"  Skipped (in DB): {stats.get('skipped_urls', 0)}")

        return stats

    except KeyboardInterrupt:
        ngo_logger.warning(f"⚠ {ngo_name} interrupted by user")
        raise

    except Exception as e:
        ngo_logger.error(f"✗ {ngo_name} failed: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'ngo_name': ngo_name
        }


def main():
    parser = argparse.ArgumentParser(description='Batch scrape multiple NGOs')

    # NGO selection
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true',
                       help='Scrape all NGOs')
    group.add_argument('--batch', type=int, choices=[1, 2, 3, 4, 5],
                       help='Scrape specific batch (1-5, ~4 NGOs each)')
    group.add_argument('--ngos', nargs='+',
                       help='Scrape specific NGOs by name')

    # Scraping options
    parser.add_argument('--max-pages', type=int, default=None,
                        help='Maximum pages per NGO (default: unlimited)')
    parser.add_argument('--config', default='config/ngo_config.csv',
                        help='Path to NGO config file')
    parser.add_argument('--skip-completed', action='store_true',
                        help='Skip NGOs that already have data in database')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Skip confirmation prompt')

    args = parser.parse_args()

    # Load NGO configuration
    ngo_df = load_ngo_config(args.config)

    # Determine which NGOs to scrape
    if args.all:
        ngos_to_scrape = ngo_df['ngo_name'].tolist()
        logger.info(f"Mode: ALL NGOs ({len(ngos_to_scrape)} total)")
    elif args.batch:
        ngos_to_scrape = BATCHES[args.batch]
        logger.info(f"Mode: BATCH {args.batch} ({len(ngos_to_scrape)} NGOs)")
    else:
        ngos_to_scrape = args.ngos
        logger.info(f"Mode: SPECIFIC NGOs ({len(ngos_to_scrape)} selected)")

    # Filter DataFrame
    ngo_df = ngo_df[ngo_df['ngo_name'].isin(ngos_to_scrape)]

    if len(ngo_df) == 0:
        logger.error("No NGOs matched the selection criteria")
        return 1

    # Print summary
    print("\n" + "="*80)
    print("BATCH SCRAPING PLAN")
    print("="*80)
    print(f"\nNGOs to scrape: {len(ngo_df)}")
    for idx, row in ngo_df.iterrows():
        print(f"  {idx+1}. {row['ngo_name']}")
    print(f"\nMax pages per NGO: {args.max_pages if args.max_pages else 'Unlimited'}")
    print(f"Resume mode: Enabled (database-tracked)")

    # Estimate time
    if args.max_pages:
        est_time_per_ngo = (args.max_pages * 12) / 60  # ~12s per page average
    else:
        est_time_per_ngo = 60  # Assume 1 hour average for unlimited
    total_est_time = est_time_per_ngo * len(ngo_df)

    print(f"\nEstimated time: {total_est_time:.1f} minutes ({total_est_time/60:.1f} hours)")
    print("="*80)

    # Confirm (unless --yes flag is used)
    if not args.yes:
        response = input("\nProceed with scraping? [y/N]: ")
        if response.lower() != 'y':
            logger.info("Scraping cancelled by user")
            return 0

    # Initialize scraper (shared across all NGOs for database persistence)
    scraper = NGOScraper(config_path="config/scraping_rules.yaml")

    # Track results
    results = []
    start_time_total = time.time()

    try:
        for idx, (_, ngo_row) in enumerate(ngo_df.iterrows(), 1):
            ngo_name = ngo_row['ngo_name']

            # Skip if requested and NGO already has data
            if args.skip_completed:
                visited_count = scraper.url_db.get_visited_count(ngo_name)
                if visited_count > 0:
                    logger.info(f"\n⊘ Skipping {ngo_name} (already has {visited_count} URLs in database)")
                    continue

            print(f"\n\n{'='*80}")
            print(f"NGO {idx}/{len(ngo_df)}: {ngo_name}")
            print(f"{'='*80}\n")

            # Scrape
            stats = scrape_ngo(scraper, ngo_row, max_pages=args.max_pages)
            results.append({
                'ngo_name': ngo_name,
                **stats
            })

            # Save intermediate results
            results_file = Path("data/logs") / f"batch_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    except KeyboardInterrupt:
        logger.warning("\n\n⚠ Batch scraping interrupted by user")

    finally:
        # Final summary
        elapsed_total = time.time() - start_time_total

        print("\n\n" + "="*80)
        print("BATCH SCRAPING SUMMARY")
        print("="*80)
        print(f"\nTotal time: {elapsed_total/60:.1f} minutes ({elapsed_total/3600:.1f} hours)")
        print(f"NGOs processed: {len(results)}/{len(ngo_df)}")

        successful = [r for r in results if r.get('status') == 'success']
        failed = [r for r in results if r.get('status') == 'error']

        print(f"\nSuccessful: {len(successful)}")
        print(f"Failed: {len(failed)}")

        if successful:
            total_pages = sum(r.get('storage_stats', {}).get('pages_saved', 0) for r in successful)
            total_links = sum(r.get('total_links', 0) for r in successful)
            total_skipped = sum(r.get('skipped_urls', 0) for r in successful)

            print(f"\nTotal pages saved: {total_pages}")
            print(f"Total links extracted: {total_links}")
            print(f"Total URLs skipped (in DB): {total_skipped}")

        if failed:
            print(f"\nFailed NGOs:")
            for r in failed:
                print(f"  - {r['ngo_name']}: {r.get('error', 'Unknown error')}")

        # Database stats
        db_stats = scraper.url_db.get_stats()
        print(f"\nDatabase total: {db_stats['total_urls']} URLs")
        print(f"NGOs in database: {len(db_stats['by_ngo'])}")

        print("="*80)

        # Save final results
        final_results_file = Path("data/logs") / f"batch_final_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(final_results_file, 'w', encoding='utf-8') as f:
            json.dump({
                'summary': {
                    'total_time': elapsed_total,
                    'ngos_processed': len(results),
                    'successful': len(successful),
                    'failed': len(failed),
                    'total_pages': total_pages if successful else 0,
                    'total_links': total_links if successful else 0,
                    'database_stats': db_stats
                },
                'results': results
            }, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"\nResults saved to: {final_results_file}")

    return 0 if len(failed) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
