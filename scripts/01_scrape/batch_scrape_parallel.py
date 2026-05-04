"""
Parallel Batch Scraper for Multiple NGOs
Scrapes multiple NGOs simultaneously using multiprocessing for maximum efficiency

Usage:
    # Run batch in parallel with 4 workers
    python scripts/batch_scrape_parallel.py --batch 1 --workers 4 --yes

    # Run all NGOs in parallel
    python scripts/batch_scrape_parallel.py --all --workers 6 --yes

    # Conservative mode (3 workers)
    python scripts/batch_scrape_parallel.py --batch 1 --workers 3 --yes
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
from pathlib import Path
from datetime import datetime
import pandas as pd
import logging
import json
from concurrent.futures import ProcessPoolExecutor, as_completed

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
        logging.FileHandler(f'data/logs/batch_parallel_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)


# Batch definitions
BATCHES = {
    1: ["Aliance pro energetickou sobestacnost", "Arnika", "Autoklub CR", "Beleco"],
    2: ["Calla - Sdruzeni pro zachranu prostredi", "Centrum pro dopravu a energetiku",
        "CI2", "Cesky svaz ochrancu prirody"],
    3: ["Ekologicky institut Veronica", "Extinction Rebellion [Posledni generace]",
        "Fakta o klimatu", "Frank Bold"],
    4: ["Fridays for Future", "Greenpeace CR", "Hnuti Duha", "Klimaticka koalice"],
    5: ["Limity jsme my", "Nesehnuti", "Zeleny kruh"]
}


def scrape_ngo_worker(ngo_row: pd.Series, max_pages: int = None):
    """
    Worker function to scrape a single NGO.
    Runs in separate process.
    """
    ngo_name = ngo_row['ngo_name']

    try:
        logger.info(f"[{ngo_name}] Starting scrape")

        # Create scraper for this process
        scraper = NGOScraper(config_path="config/scraping_rules.yaml")

        # Prepare seed URLs
        seed_urls = [{'url': ngo_row['url']}]

        # Run scrape
        start_time = time.time()
        stats = scraper.scrape_ngo(
            ngo_name=ngo_name,
            seed_urls=seed_urls,
            max_depth=int(ngo_row['depth_limit']),
            max_pages=max_pages
        )
        elapsed = time.time() - start_time

        logger.info(f"[{ngo_name}] Completed in {elapsed/60:.1f} min - "
                   f"Pages: {stats.get('storage_stats', {}).get('pages_saved', 0)}, "
                   f"Links: {stats.get('total_links', 0)}")

        return {
            'ngo_name': ngo_name,
            'status': 'success',
            'elapsed': elapsed,
            **stats
        }

    except Exception as e:
        logger.error(f"[{ngo_name}] Error: {e}", exc_info=True)
        return {
            'ngo_name': ngo_name,
            'status': 'error',
            'error': str(e)
        }


def main():
    parser = argparse.ArgumentParser(description='Parallel batch scrape multiple NGOs')

    # NGO selection
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true',
                       help='Scrape all NGOs in parallel')
    group.add_argument('--batch', type=int, choices=[1, 2, 3, 4, 5],
                       help='Scrape specific batch in parallel')
    group.add_argument('--ngos', nargs='+',
                       help='Scrape specific NGOs by name')

    # Parallel options
    parser.add_argument('--workers', type=int, default=4,
                        help='Number of parallel workers (default: 4, max recommended: 6)')
    parser.add_argument('--max-pages', type=int, default=None,
                        help='Maximum pages per NGO (default: unlimited)')
    parser.add_argument('--config', default='config/ngo_config.csv',
                        help='Path to NGO config file')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Skip confirmation prompt')

    args = parser.parse_args()

    # Validate workers
    if args.workers > 8:
        logger.warning(f"Workers limited to 8 (requested: {args.workers})")
        args.workers = 8

    # Load NGO configuration
    ngo_df = pd.read_csv(args.config)

    # Determine which NGOs to scrape
    if args.all:
        ngos_to_scrape = ngo_df['ngo_name'].tolist()
        mode = f"ALL NGOs ({len(ngos_to_scrape)} total)"
    elif args.batch:
        ngos_to_scrape = BATCHES[args.batch]
        mode = f"BATCH {args.batch} ({len(ngos_to_scrape)} NGOs)"
    else:
        ngos_to_scrape = args.ngos
        mode = f"SPECIFIC NGOs ({len(ngos_to_scrape)} selected)"

    # Filter DataFrame
    ngo_df = ngo_df[ngo_df['ngo_name'].isin(ngos_to_scrape)]

    if len(ngo_df) == 0:
        logger.error("No NGOs matched the selection criteria")
        return 1

    # Print summary
    print("\n" + "="*80)
    print("PARALLEL BATCH SCRAPING")
    print("="*80)
    print(f"\nMode: {mode}")
    print(f"Workers: {args.workers} parallel processes")
    print(f"Max pages per NGO: {args.max_pages if args.max_pages else 'Unlimited'}")
    print(f"\nNGOs to scrape:")
    for idx, row in ngo_df.iterrows():
        print(f"  {idx+1}. {row['ngo_name']}")

    # Estimate time
    if args.max_pages:
        est_time_per_ngo = (args.max_pages * 12) / 60
    else:
        est_time_per_ngo = 60  # 1 hour average

    # With parallel execution, time is divided by number of workers
    sequential_time = est_time_per_ngo * len(ngo_df)
    parallel_time = sequential_time / args.workers

    print(f"\nEstimated time:")
    print(f"  Sequential: {sequential_time:.1f} minutes ({sequential_time/60:.1f} hours)")
    print(f"  Parallel ({args.workers} workers): {parallel_time:.1f} minutes ({parallel_time/60:.1f} hours)")
    print(f"  Speedup: {args.workers}x faster")
    print("="*80)

    # Confirm
    if not args.yes:
        response = input("\nProceed with parallel scraping? [y/N]: ")
        if response.lower() != 'y':
            logger.info("Scraping cancelled by user")
            return 0

    # Run parallel scraping
    logger.info(f"\n{'='*80}")
    logger.info(f"Starting parallel scraping with {args.workers} workers")
    logger.info(f"{'='*80}\n")

    start_time_total = time.time()
    results = []

    # Use ProcessPoolExecutor for parallel execution
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        # Submit all tasks
        future_to_ngo = {
            executor.submit(scrape_ngo_worker, row, args.max_pages): row['ngo_name']
            for _, row in ngo_df.iterrows()
        }

        # Collect results as they complete
        for future in as_completed(future_to_ngo):
            ngo_name = future_to_ngo[future]
            try:
                result = future.result()
                results.append(result)

                status = "✓" if result.get('status') == 'success' else "✗"
                logger.info(f"{status} {ngo_name} finished")

            except Exception as e:
                logger.error(f"✗ {ngo_name} raised exception: {e}")
                results.append({
                    'ngo_name': ngo_name,
                    'status': 'error',
                    'error': str(e)
                })

    elapsed_total = time.time() - start_time_total

    # Summary
    print("\n\n" + "="*80)
    print("PARALLEL SCRAPING SUMMARY")
    print("="*80)
    print(f"\nTotal time: {elapsed_total/60:.1f} minutes ({elapsed_total/3600:.1f} hours)")
    print(f"NGOs processed: {len(results)}")
    print(f"Workers used: {args.workers}")

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

        print(f"\nSuccessful NGOs:")
        for r in successful:
            pages = r.get('storage_stats', {}).get('pages_saved', 0)
            links = r.get('total_links', 0)
            elapsed = r.get('elapsed', 0)
            print(f"  - {r['ngo_name']}: {pages} pages, {links} links in {elapsed/60:.1f} min")

    if failed:
        print(f"\nFailed NGOs:")
        for r in failed:
            print(f"  - {r['ngo_name']}: {r.get('error', 'Unknown error')}")

    # Database stats
    from modules.scraping.storage import URLDatabase
    db = URLDatabase()
    db_stats = db.get_stats()
    print(f"\nDatabase total: {db_stats['total_urls']} URLs")
    print(f"NGOs in database: {len(db_stats['by_ngo'])}")
    db.close()

    print("="*80)

    # Save results
    final_results_file = Path("data/logs") / f"batch_parallel_final_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(final_results_file, 'w', encoding='utf-8') as f:
        json.dump({
            'summary': {
                'total_time': elapsed_total,
                'workers': args.workers,
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
