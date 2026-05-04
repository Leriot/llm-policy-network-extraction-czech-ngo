"""
Optimized Two-Pass Keyword Filter

Pass 1: Find files with ANY NGO mention (FlashText - very fast)
Pass 2: Keep only files with NGO mentions NEAR collaboration keywords (proximity filter)

This is much faster than checking both conditions at once.
"""
import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


from pathlib import Path
from flashtext import KeywordProcessor
import csv
import re
from typing import Set, List, Dict
import unicodedata


def remove_diacritics(text: str) -> str:
    """Remove Czech diacritics for matching"""
    nfd = unicodedata.normalize('NFD', text)
    return ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')


def load_ngo_variants(config_file: Path) -> Dict[str, List[str]]:
    """Load NGO names and all their variants"""
    ngo_variants = {}

    with open(config_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            canonical_name = row['our_name'].strip()
            aliases_str = row.get('aliases', '').strip()

            # Collect all variants
            variants = [canonical_name]
            if aliases_str:
                variants.extend([a.strip() for a in aliases_str.split(';') if a.strip()])

            # Add diacritic-free versions
            all_variants = []
            for v in variants:
                all_variants.append(v)
                normalized = remove_diacritics(v)
                if normalized.lower() != v.lower():
                    all_variants.append(normalized)

            ngo_variants[canonical_name] = all_variants

    return ngo_variants


def load_collaboration_keywords(keywords_file: Path) -> List[str]:
    """Load collaboration keywords from config"""
    keywords = []

    with open(keywords_file, 'r', encoding='utf-8') as f:
        import yaml
        config = yaml.safe_load(f)

        # Get collaboration keywords
        collab_keywords = config.get('collaboration_keywords', [])
        keywords.extend(collab_keywords)

        # Add diacritic-free versions
        all_keywords = []
        for kw in keywords:
            all_keywords.append(kw.lower())
            normalized = remove_diacritics(kw).lower()
            if normalized != kw.lower():
                all_keywords.append(normalized)

        return all_keywords


def pass1_find_ngo_mentions(step1_dir: Path, ngo_variants: Dict[str, List[str]],
                            output_dir: Path) -> Dict[str, Set[Path]]:
    """
    Pass 1: Find ALL files that mention ANY NGO

    Returns: Dict mapping source_ngo -> set of files with mentions
    """

    print("\n" + "="*80)
    print("PASS 1: Finding files with NGO mentions")
    print("="*80 + "\n")

    # Create FlashText processor with ALL variants
    keyword_processor = KeywordProcessor(case_sensitive=False)

    for canonical_name, variants in ngo_variants.items():
        for variant in variants:
            keyword_processor.add_keyword(variant, canonical_name)

    print(f"Loaded {len(ngo_variants)} NGOs with {sum(len(v) for v in ngo_variants.values())} total variants\n")

    # Track which files each NGO mentions
    ngo_to_files = {ngo: set() for ngo in ngo_variants.keys()}
    total_files = 0
    total_with_mentions = 0

    # Process each NGO's text files
    for ngo_dir in step1_dir.iterdir():
        if not ngo_dir.is_dir():
            continue

        source_ngo = ngo_dir.name
        text_dir = ngo_dir / "text"

        if not text_dir.exists():
            continue

        text_files = list(text_dir.glob("*.txt"))
        print(f"{source_ngo}: Scanning {len(text_files)} files...")

        files_with_mentions = 0

        for text_file in text_files:
            total_files += 1

            try:
                # Read and normalize
                content = text_file.read_text(encoding='utf-8')
                content_normalized = remove_diacritics(content).lower()

                # Find NGO mentions (excluding self)
                found_ngos = set(keyword_processor.extract_keywords(content_normalized))
                found_ngos.discard(source_ngo)  # Remove self-mentions

                if found_ngos:
                    files_with_mentions += 1
                    total_with_mentions += 1

                    # Track for each found NGO
                    for target_ngo in found_ngos:
                        ngo_to_files[target_ngo].add(text_file)

            except Exception as e:
                print(f"  ERROR reading {text_file.name}: {e}")

        print(f"  Found mentions in {files_with_mentions}/{len(text_files)} files")

    print(f"\n{'='*80}")
    print(f"Pass 1 Summary:")
    print(f"  Total files scanned: {total_files:,}")
    print(f"  Files with NGO mentions: {total_with_mentions:,} ({total_with_mentions/total_files*100:.1f}%)")
    print(f"{'='*80}\n")

    return ngo_to_files


def pass2_proximity_filter(ngo_to_files: Dict[str, Set[Path]],
                           collaboration_keywords: List[str],
                           output_dir: Path,
                           proximity_window: int = 300) -> Dict[str, int]:
    """
    Pass 2: Keep only files where NGO mention is NEAR collaboration keywords

    Args:
        ngo_to_files: Output from pass 1
        collaboration_keywords: Keywords to check proximity to
        output_dir: Output directory (step2)
        proximity_window: Character window around NGO mention to check

    Returns: Stats dict
    """

    print("\n" + "="*80)
    print("PASS 2: Filtering by proximity to collaboration keywords")
    print("="*80 + "\n")
    print(f"Proximity window: {proximity_window} characters")
    print(f"Collaboration keywords: {len(collaboration_keywords)}\n")

    stats = {
        'total_candidate_files': 0,
        'files_with_proximity': 0,
        'files_copied': 0,
        'ngos_processed': 0
    }

    # Process each NGO
    for source_ngo, candidate_files in ngo_to_files.items():
        if not candidate_files:
            continue

        stats['ngos_processed'] += 1
        stats['total_candidate_files'] += len(candidate_files)

        print(f"{source_ngo}: Checking {len(candidate_files)} candidate files...")

        # Create output directory
        output_ngo_dir = output_dir / source_ngo / "text"
        output_ngo_dir.mkdir(parents=True, exist_ok=True)

        files_passed = 0

        for text_file in candidate_files:
            try:
                content = text_file.read_text(encoding='utf-8')
                content_normalized = remove_diacritics(content).lower()

                # Find all positions where collaboration keywords appear
                keyword_positions = []
                for keyword in collaboration_keywords:
                    pos = 0
                    while True:
                        pos = content_normalized.find(keyword, pos)
                        if pos == -1:
                            break
                        keyword_positions.append(pos)
                        pos += 1

                # If any collaboration keyword found, this file passes
                if keyword_positions:
                    # Copy file to step2
                    output_file = output_ngo_dir / text_file.name
                    output_file.write_text(content, encoding='utf-8')

                    files_passed += 1
                    stats['files_with_proximity'] += 1
                    stats['files_copied'] += 1

            except Exception as e:
                print(f"  ERROR processing {text_file.name}: {e}")

        print(f"  Passed: {files_passed}/{len(candidate_files)} files")

    print(f"\n{'='*80}")
    print(f"Pass 2 Summary:")
    print(f"  Candidate files: {stats['total_candidate_files']:,}")
    print(f"  Files with proximity: {stats['files_with_proximity']:,} ({stats['files_with_proximity']/stats['total_candidate_files']*100:.1f}%)")
    print(f"  Files copied to step2: {stats['files_copied']:,}")
    print(f"{'='*80}\n")

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Optimized two-pass keyword filter')
    parser.add_argument('--step1', default='data/interim/step1_content_extraction',
                       help='Step1 directory')
    parser.add_argument('--output', default='data/interim/step2_keyword_filter',
                       help='Step2 output directory')
    parser.add_argument('--ngo-config', default='config/ngo_config.csv',
                       help='NGO config file')
    parser.add_argument('--keywords-config', default='config/content_filter_keywords.yaml',
                       help='Keywords config file')
    parser.add_argument('--proximity', type=int, default=300,
                       help='Proximity window in characters (default: 300)')
    args = parser.parse_args()

    print("\n" + "="*80)
    print("OPTIMIZED TWO-PASS KEYWORD FILTER")
    print("="*80)

    # Load configs
    print("\nLoading configurations...")
    ngo_variants = load_ngo_variants(Path(args.ngo_config))
    collaboration_keywords = load_collaboration_keywords(Path(args.keywords_config))

    print(f"  NGOs: {len(ngo_variants)}")
    print(f"  Collaboration keywords: {len(collaboration_keywords)}")

    # Pass 1: Find NGO mentions
    ngo_to_files = pass1_find_ngo_mentions(
        Path(args.step1),
        ngo_variants,
        Path(args.output)
    )

    # Pass 2: Proximity filter
    stats = pass2_proximity_filter(
        ngo_to_files,
        collaboration_keywords,
        Path(args.output),
        proximity_window=args.proximity
    )

    print("\n" + "="*80)
    print("COMPLETE")
    print("="*80)
    print(f"\nFiltered files saved to: {args.output}")
    print(f"Ready for step 3 (date filtering)\n")


if __name__ == "__main__":
    main()
