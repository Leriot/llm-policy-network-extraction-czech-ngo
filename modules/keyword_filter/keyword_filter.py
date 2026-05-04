"""
Keyword Filter - Collaboration Relevance Scoring

Filters pages by:
1. NGO mentions (with Czech declension fuzzy matching)
2. Collaboration keywords (partnership, cooperation, etc.)
3. Topic relevance (climate, energy, etc.)

Scoring system with weighted categories ensures only collaboration-relevant
pages proceed to expensive date filtering and GLiNER actor extraction.
"""

import re
import yaml
import csv
import json
import shutil
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class KeywordFilter:
    """
    Filters documents by collaboration-relevant keywords and NGO mentions.

    Uses weighted keyword scoring with Czech language declension support.
    """

    def __init__(self, config_path: str, ngo_config_path: str):
        """
        Initialize keyword filter.

        Args:
            config_path: Path to content_filter_keywords.yaml
            ngo_config_path: Path to ngo_config.csv
        """
        self.config = self._load_config(config_path)
        self.ngo_patterns = self._build_ngo_patterns(ngo_config_path)
        self.keyword_patterns = self._build_keyword_patterns()

        logger.info(f"Keyword filter initialized with {len(self.ngo_patterns)} NGO patterns")

    def _load_config(self, path: str) -> dict:
        """Load YAML configuration."""
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _build_ngo_patterns(self, csv_path: str) -> Dict[str, List[str]]:
        """
        Build regex patterns for NGO names with Czech declension support.

        Czech nouns decline by case (nominative, genitive, dative, etc.),
        so "Arnika" can appear as "Arniky", "Arniku", "Arnice", etc.

        Returns:
            Dict mapping NGO name to list of regex patterns
        """
        patterns = {}

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ngo_name = row['ngo_name']
                aliases_str = row.get('aliases', '')

                # Parse aliases (comma-separated)
                aliases = [a.strip() for a in aliases_str.split(',') if a.strip()]

                # Build patterns for main name and aliases
                all_names = [ngo_name] + aliases
                ngo_patterns = []

                for name in all_names:
                    # Skip empty names
                    if not name:
                        continue

                    # Extract root (remove common suffixes for Czech declensions)
                    root = self._extract_root_for_declension(name)

                    # Czech declension pattern
                    # Matches variations like: Arnika, Arniky, Arniku, Arnice, Arnikou
                    pattern = rf'\b{re.escape(root)}[aáyěéuůouiíý]{{0,3}}\b'
                    ngo_patterns.append(pattern)

                    # Also match full name exactly (for compound names)
                    if ' ' in name:  # Multi-word names
                        pattern_exact = rf'\b{re.escape(name)}\b'
                        ngo_patterns.append(pattern_exact)

                patterns[ngo_name] = ngo_patterns

        return patterns

    def _extract_root_for_declension(self, word: str) -> str:
        """
        Extract root from Czech word for declension matching.

        Examples:
            Arnika → Arnik (matches Arnika, Arniky, Arniku, Arnice, Arnikou)
            Veronica → Veronic (matches Veronica, Veronikou, Veronice)
            spolupráce → spoluprác (matches spolupráce, spolupráci, spolupráců)

        Args:
            word: Czech word

        Returns:
            Root suitable for declension regex
        """
        # Don't modify short words
        if len(word) <= 4:
            return word

        # For compound words (with spaces), only process last word
        if ' ' in word:
            parts = word.split()
            last_word = parts[-1]
            root_last = self._extract_root_for_declension(last_word)
            parts[-1] = root_last
            return ' '.join(parts)

        # Common Czech suffixes to remove
        # Order matters - try longer suffixes first
        suffixes_to_try = [
            'ství', 'ství', 'ová', 'ice', 'ika', 'ovi', 'oví',
            'ce', 'ka', 'ie', 'ia', 'ta', 'da', 'na',
            'a', 'e', 'i', 'y', 'ě', 'í', 'ý', 'á', 'é', 'ů', 'u', 'o'
        ]

        for suffix in suffixes_to_try:
            if word.lower().endswith(suffix):
                potential_root = word[:-len(suffix)]
                # Make sure root is at least 3 characters
                if len(potential_root) >= 3:
                    return potential_root

        return word

    def _build_keyword_patterns(self) -> Dict[str, List[Tuple[str, int]]]:
        """
        Build regex patterns from keywords config with weights.

        Returns:
            Dict mapping category to list of (pattern, weight) tuples
        """
        patterns = {}

        for category, keywords in self.config['keywords'].items():
            category_patterns = []

            for kw in keywords:
                root = kw['root']
                weight = kw['weight']

                # Build flexible pattern for Czech declensions
                # Example: spoluprác → matches spolupráce, spolupracovat, spolupracující
                # Allow up to 15 additional characters after root
                pattern = rf'\b{re.escape(root)}[a-záčďéěíňóřšťůúýž]{{0,15}}\b'

                category_patterns.append((pattern, weight))

            patterns[category] = category_patterns

        return patterns

    def score_document(self, text: str) -> Dict:
        """
        Score document by keyword relevance.

        Scoring system:
        - NGO mentions: 5 points each (highest priority)
        - Collaboration keywords: 1-3 points (from config)
        - Density: score per 100 words

        Args:
            text: Document text (cleaned)

        Returns:
            Dict with score, density, category breakdowns, and NGO mentions
        """
        words = text.split()
        word_count = len(words)

        scores = {
            'total': 0,
            'density': 0,
            'categories': {},
            'ngo_mentions': {},
            'ngo_mention_count': 0,
            'word_count': word_count
        }

        # Score NGO mentions (highest priority - weight 5)
        for ngo_name, patterns in self.ngo_patterns.items():
            mention_count = 0

            for pattern in patterns:
                try:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    mention_count += len(matches)
                except re.error as e:
                    logger.warning(f"Invalid regex pattern for {ngo_name}: {pattern} - {e}")
                    continue

            if mention_count > 0:
                scores['ngo_mentions'][ngo_name] = mention_count
                scores['ngo_mention_count'] += mention_count
                scores['total'] += mention_count * 5  # Weight: 5 per NGO mention

        # Score keywords by category (from config)
        for category, patterns in self.keyword_patterns.items():
            category_score = 0

            for pattern, weight in patterns:
                try:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    category_score += len(matches) * weight
                except re.error as e:
                    logger.warning(f"Invalid regex pattern in {category}: {pattern} - {e}")
                    continue

            scores['categories'][category] = category_score
            scores['total'] += category_score

        # Calculate density (score per 100 words)
        if word_count > 0:
            scores['density'] = scores['total'] / (word_count / 100)
        else:
            scores['density'] = 0

        return scores

    def should_keep(self, text: str) -> Tuple[bool, Dict]:
        """
        Determine if document should be kept based on keyword relevance.

        Criteria (ALL must pass):
        1. Total score >= min_raw_score
        2. Density >= min_density_score
        3. NGO mentions >= min_organization_mentions (from config)

        Args:
            text: Document text

        Returns:
            (keep: bool, scores: dict)
        """
        scores = self.score_document(text)

        thresholds = self.config['filtering']

        # Must pass ALL criteria
        keep = (
            scores['total'] >= thresholds['min_raw_score'] and
            scores['density'] >= thresholds['min_density_score'] and
            scores['ngo_mention_count'] >= thresholds.get('min_organization_mentions', 0)
        )

        return keep, scores

    def filter_dataset(self, input_dir: Path, output_dir: Path) -> Dict:
        """
        Filter entire dataset by keywords.

        Args:
            input_dir: data/cleaned/{ngo}/ (contains text/ subdirectory)
            output_dir: data/keyword_filtered/{ngo}/

        Returns:
            Statistics dict
        """
        input_text_dir = input_dir / "text"
        output_text_dir = output_dir / "text"
        output_text_dir.mkdir(parents=True, exist_ok=True)

        if not input_text_dir.exists():
            raise ValueError(f"Input text directory not found: {input_text_dir}")

        stats = {
            'total_files': 0,
            'kept': 0,
            'excluded': 0,
            'avg_score_kept': 0,
            'avg_score_excluded': 0,
            'ngo_mentions': {},
            'category_distribution': {}
        }

        kept_scores = []
        excluded_scores = []
        excluded_files = []

        logger.info(f"Processing files from {input_text_dir}")

        # Process all text files
        text_files = list(input_text_dir.glob("*.txt"))
        stats['total_files'] = len(text_files)

        for i, text_file in enumerate(text_files, 1):
            if i % 100 == 0:
                logger.info(f"  Processed {i}/{len(text_files)} files...")

            # Read text
            try:
                with open(text_file, 'r', encoding='utf-8') as f:
                    text = f.read()
            except Exception as e:
                logger.error(f"Error reading {text_file}: {e}")
                continue

            # Score and filter
            keep, scores = self.should_keep(text)

            if keep:
                stats['kept'] += 1
                kept_scores.append(scores['total'])

                # Copy to output
                shutil.copy(text_file, output_text_dir / text_file.name)

                # Track NGO mentions
                for ngo, count in scores['ngo_mentions'].items():
                    stats['ngo_mentions'][ngo] = stats['ngo_mentions'].get(ngo, 0) + count

                # Track category distribution
                for category, score in scores['categories'].items():
                    stats['category_distribution'][category] = \
                        stats['category_distribution'].get(category, 0) + score
            else:
                stats['excluded'] += 1
                excluded_scores.append(scores['total'])

                # Log excluded file
                excluded_files.append({
                    'file': text_file.name,
                    'score': scores['total'],
                    'density': scores['density'],
                    'ngo_mentions': scores['ngo_mention_count'],
                    'reason': self._get_exclusion_reason(scores)
                })

        # Calculate averages
        if kept_scores:
            stats['avg_score_kept'] = sum(kept_scores) / len(kept_scores)
        if excluded_scores:
            stats['avg_score_excluded'] = sum(excluded_scores) / len(excluded_scores)

        # Save statistics
        stats_file = output_dir / "filter_stats.json"
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)

        # Save excluded list (for debugging)
        excluded_file = output_dir / "excluded.jsonl"
        with open(excluded_file, 'w', encoding='utf-8') as f:
            for entry in excluded_files:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')

        logger.info(f"Filtering complete: {stats['kept']}/{stats['total_files']} pages kept")

        return stats

    def _get_exclusion_reason(self, scores: Dict) -> str:
        """Determine why document was excluded."""
        thresholds = self.config['filtering']

        reasons = []

        if scores['total'] < thresholds['min_raw_score']:
            reasons.append(f"Low score ({scores['total']} < {thresholds['min_raw_score']})")

        if scores['density'] < thresholds['min_density_score']:
            reasons.append(f"Low density ({scores['density']:.2f} < {thresholds['min_density_score']})")

        min_ngo = thresholds.get('min_organization_mentions', 0)
        if scores['ngo_mention_count'] < min_ngo:
            reasons.append(f"Insufficient NGO mentions ({scores['ngo_mention_count']} < {min_ngo})")

        return "; ".join(reasons) if reasons else "Unknown"
