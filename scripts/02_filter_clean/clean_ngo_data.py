#!/usr/bin/env python3
"""
Module 2: NGO Data Cleaning & Content Extraction
=================================================

Multi-stage pipeline for transforming raw HTML into clean text:
1. Template detection (global + section-specific boilerplate)
2. Content extraction (trafilatura + BeautifulSoup fallback)
3. Deduplication (shingling + Jaccard similarity)
4. Output (clean text + metadata)

Usage:
    # Analyze templates only
    python scripts/clean_ngo_data.py --ngo "Autoklub CR" --analyze-only

    # Clean one NGO
    python scripts/clean_ngo_data.py --ngo "Autoklub CR"

    # Clean all NGOs
    python scripts/clean_ngo_data.py --all

    # Skip deduplication
    python scripts/clean_ngo_data.py --all --no-dedup

    # Custom thresholds
    python scripts/clean_ngo_data.py --ngo "Arnika" --global-threshold 0.85

    # Parallel processing (NGO-level)
    python scripts/clean_ngo_data.py --all --workers 4

    # Fast extraction with more file workers (default: 8)
    python scripts/clean_ngo_data.py --ngo "Autoklub CR" --file-workers 16
"""
import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


import sys
import argparse
import logging
import json
import yaml
import time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import threading

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from modules.cleaning import TemplateDetector, ContentExtractor, ContentCleaner

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = "config/cleaning_config.yaml") -> dict:
    """Load cleaning configuration."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        logger.info(f"Loaded config from {config_path}")
        return config
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        raise


def find_ngos() -> list:
    """Find all NGOs with scraped data."""
    raw_path = Path("data/raw")
    if not raw_path.exists():
        return []
    return [d.name for d in raw_path.iterdir() if d.is_dir()]


def load_url_manifest(ngo_name: str) -> dict:
    """Load URL manifest for an NGO."""
    manifest_file = Path("data/raw") / ngo_name / "url_manifest.jsonl"

    if not manifest_file.exists():
        logger.warning(f"URL manifest not found for {ngo_name}")
        return {}

    manifest = {}
    try:
        with open(manifest_file, 'r', encoding='utf-8') as f:
            for line in f:
                entry = json.loads(line.strip())
                filename = entry.get('filename')  # Field is 'filename' not 'file'
                url = entry.get('url')
                if filename and url:
                    manifest[filename] = url
    except Exception as e:
        logger.error(f"Error loading manifest for {ngo_name}: {e}")

    return manifest


def process_ngo(ngo_name: str, config: dict, args: argparse.Namespace) -> dict:
    """
    Process one NGO through the full cleaning pipeline.

    Args:
        ngo_name: NGO name
        config: Configuration dict
        args: Command-line arguments

    Returns:
        Dict with processing statistics
    """
    start_time = time.time()
    logger.info(f"\n{'='*80}")
    logger.info(f"Processing: {ngo_name}")
    logger.info(f"{'='*80}")

    result = {
        'ngo_name': ngo_name,
        'success': False,
        'error': None,
        'stats': {}
    }

    try:
        # Paths
        raw_dir = Path("data/raw") / ngo_name
        pages_dir = raw_dir / "pages"  # HTML files are in pages/ subfolder
        cleaned_dir = Path("data/interim/step1_content_extraction") / ngo_name
        cleaned_dir.mkdir(parents=True, exist_ok=True)

        # --- STAGE 1: Template Detection ---
        logger.info(f"\n[Stage 1/4] Template Detection")

        detector = TemplateDetector(ngo_name, config)

        # Check if we should force re-analyze
        force_reanalyze = getattr(args, 'force_reanalyze', False)

        templates = detector.run(force_reanalyze=force_reanalyze)

        if args.analyze_only:
            logger.info(f"Template analysis complete for {ngo_name}")
            logger.info(f"  Global elements: {len(templates.get('global', {}).get('elements', []))}")
            logger.info(f"  Section groups: {len(templates.get('sections', {}))}")
            result['success'] = True
            result['stats'] = templates.get('stats', {})
            return result

        # --- STAGE 2: Content Extraction ---
        logger.info(f"\n[Stage 2/4] Content Extraction")

        extractor = ContentExtractor(config)
        manifest = load_url_manifest(ngo_name)

        if not manifest:
            logger.warning(f"No URL manifest found - using filenames as URLs")

        # Get all HTML files from pages/ subfolder
        html_files = list(pages_dir.glob('*.html'))
        total_files = len(html_files)

        if total_files == 0:
            logger.warning(f"No HTML files found for {ngo_name} in {pages_dir}")
            result['error'] = "No HTML files found"
            return result

        logger.info(f"Processing {total_files} HTML files...")

        # Extract content from all files using parallel processing
        extracted_data = []
        file_workers = min(getattr(args, 'file_workers', 8), 16)

        # Progress tracking
        progress_lock = threading.Lock()
        progress_counter = [0]  # Use list to allow mutation in nested function
        last_reported = [0]

        def extract_single_file(html_file):
            """Extract content from a single file."""
            url = manifest.get(html_file.name, f"file://{html_file.name}")
            result = extractor.extract_content(html_file, url, templates)

            # Update progress
            with progress_lock:
                progress_counter[0] += 1
                current = progress_counter[0]
                # Report every 100 files or at completion
                if current - last_reported[0] >= 100 or current == total_files:
                    logger.info(f"  Progress: {current}/{total_files} files ({100*current/total_files:.1f}%)")
                    last_reported[0] = current

            return result

        if file_workers > 1:
            logger.info(f"  Using {file_workers} parallel workers for extraction")
            with ThreadPoolExecutor(max_workers=file_workers) as executor:
                futures = [executor.submit(extract_single_file, f) for f in html_files]
                for future in as_completed(futures):
                    try:
                        extracted_data.append(future.result())
                    except Exception as e:
                        logger.error(f"  Extraction error: {e}")
                        extracted_data.append({'success': False, 'error': str(e)})
        else:
            # Sequential fallback
            for idx, html_file in enumerate(html_files, 1):
                if idx % 100 == 0 or idx == total_files:
                    logger.info(f"  Progress: {idx}/{total_files} files")
                url = manifest.get(html_file.name, f"file://{html_file.name}")
                extraction_result = extractor.extract_content(html_file, url, templates)
                extracted_data.append(extraction_result)

        # --- STAGE 3: Deduplication ---
        logger.info(f"\n[Stage 3/4] Deduplication")

        dedup_enabled = config['deduplication'].get('enabled', True) and not args.no_dedup

        if dedup_enabled:
            cleaner = ContentCleaner(ngo_name, config)

            for item in extracted_data:
                if item['success']:
                    cleaner.process_document(item['file'], item['text'])

            # Save duplicate mapping
            cleaner.save_duplicate_mapping()

            dedup_stats = cleaner.get_stats()
            logger.info(f"  Unique documents: {dedup_stats['unique_documents']}")
            logger.info(f"  Duplicates found: {dedup_stats['duplicate_documents']} "
                       f"({dedup_stats['deduplication_rate']:.1f}%)")

        else:
            logger.info("  Deduplication skipped")
            dedup_stats = {'deduplication_skipped': True}

        # --- STAGE 4: Save Outputs ---
        logger.info(f"\n[Stage 4/4] Saving Outputs")

        # Prepare output directory
        text_dir = cleaned_dir / "text"
        text_dir.mkdir(exist_ok=True)

        # Save clean text files
        saved_count = 0
        failed_count = 0

        for item in extracted_data:
            if item['success'] and item['text']:
                # Check if it's a duplicate (only save representative if keep_representative=True)
                if dedup_enabled and config['deduplication'].get('keep_representative', True):
                    is_dup, master = cleaner.is_duplicate(item['file'])
                    if is_dup:
                        continue  # Skip duplicates

                # Save text file
                text_filename = Path(item['file']).stem + '.txt'
                text_file = text_dir / text_filename

                try:
                    with open(text_file, 'w', encoding='utf-8') as f:
                        f.write(item['text'])
                    saved_count += 1
                except Exception as e:
                    logger.error(f"Error saving {text_filename}: {e}")
                    failed_count += 1
            else:
                failed_count += 1

        logger.info(f"  Saved {saved_count} clean text files")
        if failed_count > 0:
            logger.info(f"  Failed/skipped: {failed_count} files")

        # Save metadata
        if config['output'].get('save_metadata', True):
            metadata_file = cleaned_dir / "metadata.jsonl"

            try:
                with open(metadata_file, 'w', encoding='utf-8') as f:
                    for item in extracted_data:
                        if item['success']:
                            # Check if duplicate
                            is_dup = False
                            if dedup_enabled:
                                is_dup, _ = cleaner.is_duplicate(item['file'])

                            metadata = {
                                'file': Path(item['file']).stem + '.txt',
                                'original_html': item['file'],
                                'url': item['url'],
                                'word_count': item['word_count'],
                                'extraction_method': item['extraction_method'],
                                'is_duplicate': is_dup
                            }
                            f.write(json.dumps(metadata, ensure_ascii=False) + '\n')

                logger.info(f"  Metadata saved to {metadata_file}")

            except Exception as e:
                logger.error(f"Error saving metadata: {e}")

        # Compile final statistics
        elapsed = time.time() - start_time

        final_stats = {
            'total_html_files': total_files,
            'successful_extractions': sum(1 for item in extracted_data if item['success']),
            'failed_extractions': sum(1 for item in extracted_data if not item['success']),
            'text_files_saved': saved_count,
            'template_detection': templates.get('stats', {}),
            'extraction': extractor.get_stats(),
            'deduplication': dedup_stats,
            'processing_time_seconds': elapsed
        }

        logger.info(f"\n{'='*80}")
        logger.info(f"Processing complete for {ngo_name}")
        logger.info(f"  Time: {elapsed/60:.1f} minutes")
        logger.info(f"  Text files saved: {saved_count}/{total_files}")
        logger.info(f"{'='*80}")

        result['success'] = True
        result['stats'] = final_stats

    except Exception as e:
        logger.error(f"Error processing {ngo_name}: {e}", exc_info=True)
        result['error'] = str(e)

    return result


def main():
    parser = argparse.ArgumentParser(
        description='Clean NGO data - extract text from HTML with deduplication',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze templates only
  python scripts/clean_ngo_data.py --ngo "Autoklub CR" --analyze-only

  # Clean one NGO
  python scripts/clean_ngo_data.py --ngo "Autoklub CR"

  # Clean all NGOs
  python scripts/clean_ngo_data.py --all

  # Skip deduplication
  python scripts/clean_ngo_data.py --all --no-dedup

  # Custom thresholds
  python scripts/clean_ngo_data.py --ngo "Arnika" --global-threshold 0.85 --section-threshold 0.75

  # Parallel processing (NGO-level)
  python scripts/clean_ngo_data.py --all --workers 4

  # Fast file extraction (default 8 workers, max 16)
  python scripts/clean_ngo_data.py --ngo "Autoklub CR" --file-workers 16
        """
    )

    # NGO selection
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--ngo', type=str, help='Process specific NGO by name')
    group.add_argument('--all', action='store_true', help='Process all NGOs')

    # Processing options
    parser.add_argument('--analyze-only', action='store_true',
                       help='Only run template analysis (skip extraction)')
    parser.add_argument('--no-dedup', action='store_true',
                       help='Skip deduplication step')
    parser.add_argument('--force-reanalyze', action='store_true',
                       help='Force template re-analysis even if templates exist')

    # Threshold overrides
    parser.add_argument('--global-threshold', type=float,
                       help='Override global template threshold (default: 0.80)')
    parser.add_argument('--section-threshold', type=float,
                       help='Override section template threshold (default: 0.80)')

    # Config and output
    parser.add_argument('--config', default='config/cleaning_config.yaml',
                       help='Path to config file (default: config/cleaning_config.yaml)')

    # Parallel processing
    parser.add_argument('--workers', type=int, default=1,
                       help='Number of parallel workers for NGOs (default: 1, max: 8)')
    parser.add_argument('--file-workers', type=int, default=8,
                       help='Number of parallel workers for file extraction (default: 8, max: 16)')

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Override thresholds if specified
    if args.global_threshold is not None:
        config['template_detection']['global_threshold'] = args.global_threshold
        logger.info(f"Using custom global threshold: {args.global_threshold:.2%}")

    if args.section_threshold is not None:
        config['template_detection']['section_threshold'] = args.section_threshold
        logger.info(f"Using custom section threshold: {args.section_threshold:.2%}")

    # Determine which NGOs to process
    if args.all:
        ngos = find_ngos()
        if not ngos:
            logger.error("No NGOs found in data/raw/")
            return 1
        logger.info(f"Found {len(ngos)} NGOs: {', '.join(ngos)}")
    else:
        ngos = [args.ngo]

    # Process NGOs
    start_time_total = time.time()
    results = []

    if args.workers > 1:
        # Parallel processing
        max_workers = min(args.workers, 8)
        logger.info(f"\n{'='*80}")
        logger.info(f"Starting parallel processing with {max_workers} workers")
        logger.info(f"{'='*80}\n")

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(process_ngo, ngo, config, args): ngo
                for ngo in ngos
            }

            for future in as_completed(futures):
                ngo = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    status = "✓" if result['success'] else "✗"
                    logger.info(f"{status} {ngo} finished")
                except Exception as e:
                    logger.error(f"✗ {ngo} raised exception: {e}")
                    results.append({
                        'ngo_name': ngo,
                        'success': False,
                        'error': str(e)
                    })

    else:
        # Sequential processing
        for ngo in ngos:
            result = process_ngo(ngo, config, args)
            results.append(result)

    # Summary
    elapsed_total = time.time() - start_time_total

    print(f"\n\n{'='*80}")
    print("CLEANING SUMMARY")
    print(f"{'='*80}")
    print(f"Total time: {elapsed_total/60:.1f} minutes ({elapsed_total/3600:.1f} hours)")
    print(f"NGOs processed: {len(results)}")

    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]

    print(f"\nSuccessful: {len(successful)}")
    print(f"Failed: {len(failed)}")

    if successful:
        total_files = sum(r['stats'].get('text_files_saved', 0) for r in successful)
        print(f"\nTotal clean text files: {total_files}")

        print(f"\nSuccessful NGOs:")
        for r in successful:
            stats = r['stats']
            saved = stats.get('text_files_saved', 0)
            total = stats.get('total_html_files', 0)
            print(f"  - {r['ngo_name']}: {saved} files saved (from {total} HTML)")

    if failed:
        print(f"\nFailed NGOs:")
        for r in failed:
            print(f"  - {r['ngo_name']}: {r.get('error', 'Unknown error')}")

    # Save summary
    summary_file = Path("data/logs") / f"cleaning_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    summary_file.parent.mkdir(exist_ok=True)

    try:
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'total_time': elapsed_total,
                'ngos_processed': len(results),
                'successful': len(successful),
                'failed': len(failed),
                'config': config,
                'results': results
            }, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"\nSummary saved to: {summary_file}")

    except Exception as e:
        logger.error(f"Error saving summary: {e}")

    print(f"{'='*80}\n")

    return 0 if len(failed) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
