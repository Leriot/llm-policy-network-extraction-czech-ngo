"""
Generate metadata.jsonl for step1_content_extraction

Creates metadata.jsonl mapping text files to their original HTML files.
This is required by filter_step2_by_year.py to extract publication dates.

Format:
    {"file": "00001_page.txt", "original_html": "00001_page.html"}

Uses url_manifest.jsonl from raw/ to get HTML filenames.
"""
import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


from pathlib import Path
import json


def generate_metadata_for_ngo(ngo_dir: Path, step1_dir: Path) -> dict:
    """
    Generate metadata.jsonl for one NGO

    Args:
        ngo_dir: data/raw/{ngo} directory
        step1_dir: data/interim/step1_content_extraction/{ngo} directory

    Returns:
        Stats dict
    """
    ngo_name = ngo_dir.name

    # Read url_manifest.jsonl to get HTML filenames
    url_manifest = ngo_dir / "url_manifest.jsonl"
    if not url_manifest.exists():
        return {'error': 'No url_manifest.jsonl found'}

    # Build mapping: HTML filename -> exists
    html_files = {}
    with open(url_manifest, 'r', encoding='utf-8') as f:
        for line in f:
            entry = json.loads(line)
            html_file = entry['filename']
            html_files[html_file] = True

    # Check which text files exist in step1
    text_dir = step1_dir / "text"
    if not text_dir.exists():
        return {'error': 'No text directory in step1'}

    text_files = list(text_dir.glob("*.txt"))

    # Create metadata entries
    metadata_entries = []
    matched = 0
    unmatched = 0

    for text_file in text_files:
        txt_name = text_file.name

        # Convert .txt to .html
        html_name = txt_name.replace('.txt', '.html')

        # Verify HTML exists
        if html_name in html_files:
            metadata_entries.append({
                'file': txt_name,
                'original_html': html_name
            })
            matched += 1
        else:
            # Check if HTML actually exists on disk
            html_path = ngo_dir / "pages" / html_name
            if html_path.exists():
                metadata_entries.append({
                    'file': txt_name,
                    'original_html': html_name
                })
                matched += 1
            else:
                unmatched += 1
                print(f"  WARNING: {ngo_name} - No HTML for {txt_name}")

    # Write metadata.jsonl
    metadata_file = step1_dir / "metadata.jsonl"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        for entry in metadata_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    return {
        'ngo': ngo_name,
        'text_files': len(text_files),
        'matched': matched,
        'unmatched': unmatched,
        'metadata_file': str(metadata_file)
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Generate metadata.jsonl for step1')
    parser.add_argument('--raw', default='data/raw',
                       help='Raw HTML directory')
    parser.add_argument('--step1', default='data/interim/step1_content_extraction',
                       help='Step1 directory')
    args = parser.parse_args()

    raw_dir = Path(args.raw)
    step1_dir = Path(args.step1)

    if not raw_dir.exists():
        print(f"ERROR: {raw_dir} not found")
        return 1

    if not step1_dir.exists():
        print(f"ERROR: {step1_dir} not found")
        return 1

    print("="*80)
    print("GENERATING METADATA.JSONL FOR STEP1")
    print("="*80)
    print()

    # Find all NGO directories in step1
    ngo_dirs = [d for d in step1_dir.iterdir() if d.is_dir()]

    print(f"Found {len(ngo_dirs)} NGO directories in step1\n")

    results = []

    for step1_ngo_dir in sorted(ngo_dirs):
        ngo_name = step1_ngo_dir.name
        raw_ngo_dir = raw_dir / ngo_name

        if not raw_ngo_dir.exists():
            print(f"SKIP {ngo_name}: No corresponding raw/ directory")
            continue

        print(f"{ngo_name}:")

        result = generate_metadata_for_ngo(raw_ngo_dir, step1_ngo_dir)

        if 'error' in result:
            print(f"  ERROR: {result['error']}")
        else:
            print(f"  OK: Created metadata.jsonl")
            print(f"    Text files: {result['text_files']}")
            print(f"    Matched: {result['matched']}")
            if result['unmatched'] > 0:
                print(f"    WARNING: Unmatched: {result['unmatched']}")
            results.append(result)

        print()

    # Summary
    print("="*80)
    print("SUMMARY")
    print("="*80)

    total_ngos = len(results)
    total_files = sum(r['text_files'] for r in results)
    total_matched = sum(r['matched'] for r in results)
    total_unmatched = sum(r['unmatched'] for r in results)

    print(f"NGOs processed: {total_ngos}")
    print(f"Total text files: {total_files}")
    print(f"Matched (have HTML): {total_matched} ({total_matched/total_files*100:.1f}%)")

    if total_unmatched > 0:
        print(f"Unmatched (no HTML): {total_unmatched} ({total_unmatched/total_files*100:.1f}%)")
        print("\nWARNING: Some text files don't have corresponding HTML files.")
        print("   These will be placed in 'other' folder during date filtering.")
    else:
        print("\nOK: All text files have corresponding HTML files!")

    print("\nMetadata files created in:")
    print("  data/interim/step1_content_extraction/{ngo}/metadata.jsonl")
    print("\nReady for step 3 (date filtering)")
    print()

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
