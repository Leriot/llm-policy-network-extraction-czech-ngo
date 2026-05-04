"""
Copy metadata from raw to step1

The conservative extraction doesn't create metadata files,
but filter_step2_by_year needs them for date filtering.
This script copies metadata from data/raw to data/interim/step1_content_extraction.
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
import shutil


def copy_metadata_files():
    """Copy metadata.json from raw to step1 as metadata.jsonl"""

    raw_dir = Path("data/raw")
    step1_dir = Path("data/interim/step1_content_extraction")

    if not raw_dir.exists():
        print(f"ERROR: {raw_dir} not found")
        return

    if not step1_dir.exists():
        print(f"ERROR: {step1_dir} not found")
        return

    print("Copying metadata files from raw to step1...\n")

    copied = 0
    missing = 0

    for ngo_dir in step1_dir.iterdir():
        if not ngo_dir.is_dir():
            continue

        ngo_name = ngo_dir.name
        raw_metadata = raw_dir / ngo_name / "metadata.json"
        step1_metadata = ngo_dir / "metadata.jsonl"

        if raw_metadata.exists():
            # Copy as jsonl (same format, different extension)
            shutil.copy2(raw_metadata, step1_metadata)
            copied += 1
            print(f"✓ {ngo_name}")
        else:
            missing += 1
            print(f"✗ {ngo_name} - no metadata in raw")

    print(f"\n{'='*60}")
    print(f"Copied: {copied}")
    print(f"Missing: {missing}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    copy_metadata_files()
