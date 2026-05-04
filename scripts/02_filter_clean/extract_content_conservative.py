"""
Conservative Content Extraction - Fixed Boilerplate Removal

PROBLEM: Greenpeace (and possibly other sites) put article content inside
<header>, <nav>, or other "boilerplate" elements. Aggressive removal causes
43% content loss on some pages.

SOLUTION: Only remove truly useless elements (script, style, iframe).
Keep everything else to preserve all article content.
"""
import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


from pathlib import Path
from bs4 import BeautifulSoup, UnicodeDammit
import re
import json
from typing import Optional
from multiprocessing import Pool, cpu_count
from functools import partial


def extract_text_conservative(html_bytes: bytes) -> Optional[str]:
    """
    Extract text with MINIMAL boilerplate removal

    Only removes:
    - <script> - JavaScript code (never useful)
    - <style> - CSS styles (never useful)
    - <iframe> - Embedded content (usually ads/widgets)

    KEEPS:
    - <nav>, <header>, <footer>, <aside> - May contain articles!
    - Everything else - Better to have extra text than miss content
    """

    try:
        # Use UnicodeDammit for robust encoding handling
        dammit = UnicodeDammit(html_bytes, is_html=True)
        if not dammit.unicode_markup:
            # Fallback to direct parsing
            soup = BeautifulSoup(html_bytes, 'html.parser')
        else:
            soup = BeautifulSoup(dammit.unicode_markup, 'html.parser')

        # ONLY remove truly useless elements
        for element in soup(['script', 'style', 'iframe']):
            element.decompose()

        # Get text
        text = soup.get_text(separator=' ', strip=True)

        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)

        return text

    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def process_single_file(html_file: Path, output_dir: Path) -> tuple:
    """Process a single HTML file (for parallel processing)"""
    try:
        # Read HTML
        with open(html_file, 'rb') as f:
            html_bytes = f.read()

        # Extract text
        text = extract_text_conservative(html_bytes)

        if text and len(text) > 50:
            # Save text
            text_file = output_dir / (html_file.stem + ".txt")
            with open(text_file, 'w', encoding='utf-8') as f:
                f.write(text)
            return ('success', html_file.name, len(text))
        else:
            return ('short', html_file.name, len(text) if text else 0)

    except Exception as e:
        return ('error', html_file.name, str(e))


def extract_all_datasets(raw_dir: Path, output_base: Path, workers: int = 1):
    """
    Re-extract ALL datasets with conservative method

    Args:
        raw_dir: data/raw directory
        output_base: data/interim/step1_content_extraction directory
        workers: Number of parallel workers (1 = no parallelism)
    """

    print("=" * 80)
    print("CONSERVATIVE CONTENT EXTRACTION")
    print("=" * 80)
    print("\nOnly removing: <script>, <style>, <iframe>")
    print("Keeping: <nav>, <header>, <footer>, <aside> (may contain articles)")
    print(f"Workers: {workers}\n")

    # Find all NGO directories
    ngo_dirs = [d for d in raw_dir.iterdir() if d.is_dir() and (d / "pages").exists()]

    print(f"Found {len(ngo_dirs)} NGO directories\n")

    total_files = 0
    total_extracted = 0
    total_errors = 0

    for ngo_dir in ngo_dirs:
        ngo_name = ngo_dir.name
        pages_dir = ngo_dir / "pages"
        html_files = list(pages_dir.glob("*.html"))

        if not html_files:
            continue

        print(f"\n{ngo_name}: {len(html_files)} files")
        print("-" * 40)

        # Create output directory
        output_ngo_dir = output_base / ngo_name
        output_dir = output_ngo_dir / "text"
        output_dir.mkdir(parents=True, exist_ok=True)

        extracted = 0
        errors = 0
        metadata_entries = []

        # Process files
        if workers > 1:
            # Parallel processing
            process_func = partial(process_single_file, output_dir=output_dir)
            with Pool(workers) as pool:
                results = pool.map(process_func, html_files)

            for status, filename, info in results:
                total_files += 1
                if status == 'success':
                    extracted += 1
                    total_extracted += 1
                    # Add to metadata
                    txt_filename = filename.replace('.html', '.txt')
                    metadata_entries.append({
                        'file': txt_filename,
                        'original_html': filename
                    })
                else:
                    errors += 1
                    total_errors += 1
                    if status == 'short':
                        print(f"  Skipped (too short): {filename} ({info} chars)")
                    else:
                        print(f"  ERROR {filename}: {info}")
        else:
            # Sequential processing
            for html_file in html_files:
                total_files += 1
                status, filename, info = process_single_file(html_file, output_dir)

                if status == 'success':
                    extracted += 1
                    total_extracted += 1
                    # Add to metadata
                    txt_filename = filename.replace('.html', '.txt')
                    metadata_entries.append({
                        'file': txt_filename,
                        'original_html': filename
                    })
                else:
                    errors += 1
                    total_errors += 1
                    if status == 'short':
                        print(f"  Skipped (too short): {filename} ({info} chars)")
                    else:
                        print(f"  ERROR {filename}: {info}")

                # Progress indicator
                if (extracted + errors) % 100 == 0:
                    print(f"  Progress: {extracted + errors}/{len(html_files)} files...")

        # Write metadata.jsonl
        metadata_file = output_ngo_dir / "metadata.jsonl"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            for entry in metadata_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')

        print(f"  OK: Extracted: {extracted} files")
        print(f"  OK: Created metadata.jsonl ({len(metadata_entries)} entries)")
        if errors > 0:
            print(f"  WARNING: Errors: {errors} files")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total files processed: {total_files}")
    print(f"Successfully extracted: {total_extracted}")
    print(f"Errors/skipped: {total_errors}")
    print(f"Success rate: {total_extracted/total_files*100:.1f}%")
    print(f"\nMetadata files created: {len(ngo_dirs)} NGOs")
    print(f"Format: {{ngo}}/metadata.jsonl (text -> HTML mapping)")
    print(f"\nReady for step 2 (keyword filtering)")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Extract content with conservative boilerplate removal')
    parser.add_argument('--raw', default='data/raw',
                       help='Raw HTML directory')
    parser.add_argument('--output', default='data/interim/step1_content_extraction',
                       help='Output directory')
    parser.add_argument('--workers', type=int, default=1,
                       help='Number of parallel workers (default: 1, use 8-12 for faster processing)')
    parser.add_argument('--test', action='store_true',
                       help='Test mode: only process one NGO')
    args = parser.parse_args()

    raw_dir = Path(args.raw)
    output_dir = Path(args.output)

    if not raw_dir.exists():
        print(f"ERROR: Raw directory not found: {raw_dir}")
        return

    if args.test:
        print("\n*** TEST MODE: Processing only Greenpeace CR ***\n")
        test_ngo = raw_dir / "Greenpeace CR"
        if test_ngo.exists():
            extract_all_datasets(raw_dir, output_dir, workers=args.workers)
        else:
            print("ERROR: Greenpeace CR directory not found")
        return

    # Confirm before processing all
    print(f"\nThis will re-extract ALL HTML files from {raw_dir}")
    print(f"Output to: {output_dir}")
    print(f"Using {args.workers} worker(s)")
    response = input("\nContinue? (yes/no): ")

    if response.lower() != 'yes':
        print("Cancelled")
        return

    extract_all_datasets(raw_dir, output_dir, workers=args.workers)


if __name__ == "__main__":
    main()
