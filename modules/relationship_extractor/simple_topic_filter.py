"""
Simple keyword-based topic filter

More reliable than GLiNER-based topic extraction for filtering irrelevant documents.
"""

import logging
from typing import List, Tuple, Dict
from pathlib import Path

logger = logging.getLogger(__name__)

# Environmental/climate keywords (Czech + English)
RELEVANT_KEYWORDS = [
    # English
    'climate', 'environmental', 'environment', 'sustainability', 'sustainable',
    'renewable', 'energy', 'carbon', 'emission', 'pollution', 'conservation',
    'biodiversity', 'ecosystem', 'nature', 'green', 'ecology', 'ecological',
    'waste', 'recycling', 'water', 'air quality', 'forest', 'wildlife',
    'protected area', 'natura', 'habitat', 'species',

    # Czech
    'klima', 'životn', 'prostřed', 'udržitel', 'obnovitel', 'energie',
    'uhlík', 'emise', 'znečišt', 'ochrana', 'biodiverzit', 'ekosystém',
    'příroda', 'ekolog', 'odpad', 'recyklac', 'voda', 'kvalita ovzduš',
    'les', 'volně žijíc', 'chráněn', 'natura', 'habitatów', 'druh'
]

# Irrelevant keywords (strong indicators of non-research content)
IRRELEVANT_KEYWORDS = [
    # Commercial/promotional
    'discount', 'slevy', 'sleva', 'akce', 'nabídka', 'benefit', 'benefity',
    'členská karta', 'membership', 'special offer', 'promo', 'shopping',

    # Administrative
    'archive', 'archiv', 'dokumenty', 'formul', 'kontakt', 'o nás',
    'about us', 'contact', 'adresa', 'address', 'telefon', 'phone'
]


class SimpleTopicFilter:
    """Simple keyword-based topic filter"""

    def __init__(
        self,
        relevant_keywords: List[str] = None,
        irrelevant_keywords: List[str] = None,
        min_relevant_matches: int = 2,
        sample_size: int = 1000
    ):
        """
        Initialize simple topic filter.

        Args:
            relevant_keywords: Keywords indicating relevant content
            irrelevant_keywords: Keywords indicating irrelevant content
            min_relevant_matches: Minimum relevant keyword matches required
            sample_size: Number of characters to sample from beginning
        """
        self.relevant_keywords = relevant_keywords or RELEVANT_KEYWORDS
        self.irrelevant_keywords = irrelevant_keywords or IRRELEVANT_KEYWORDS
        self.min_relevant_matches = min_relevant_matches
        self.sample_size = sample_size

        logger.info(
            f"Simple topic filter initialized: {len(self.relevant_keywords)} relevant keywords, " +
            f"{len(self.irrelevant_keywords)} irrelevant keywords"
        )

    def is_relevant(self, text: str) -> Tuple[bool, Dict]:
        """
        Check if text is relevant based on keyword matching.

        Args:
            text: Document text

        Returns:
            (is_relevant: bool, info: dict)
        """
        # Sample from beginning (topics usually clear early)
        sample = text[:self.sample_size].lower()

        # Count relevant keyword matches
        relevant_matches = []
        for keyword in self.relevant_keywords:
            if keyword.lower() in sample:
                relevant_matches.append(keyword)

        # Count irrelevant keyword matches
        irrelevant_matches = []
        for keyword in self.irrelevant_keywords:
            if keyword.lower() in sample:
                irrelevant_matches.append(keyword)

        # Decision logic:
        # - If strong irrelevant signals and few relevant -> irrelevant
        # - If sufficient relevant signals -> relevant
        # - Otherwise -> relevant (err on side of inclusion)

        if len(irrelevant_matches) >= 3 and len(relevant_matches) < self.min_relevant_matches:
            is_relevant = False
            reason = f"Strong irrelevant signals: {', '.join(irrelevant_matches[:3])}"
        elif len(relevant_matches) >= self.min_relevant_matches:
            is_relevant = True
            reason = f"Relevant keywords found: {', '.join(relevant_matches[:5])}"
        elif len(relevant_matches) > 0:
            # Some relevant keywords but less than minimum
            # Still include (benefit of doubt)
            is_relevant = True
            reason = f"Some relevant keywords: {', '.join(relevant_matches)}"
        else:
            # No clear signals - include by default
            is_relevant = True
            reason = "No clear signals - including by default"

        return is_relevant, {
            'relevant_matches': relevant_matches[:10],
            'irrelevant_matches': irrelevant_matches[:10],
            'num_relevant': len(relevant_matches),
            'num_irrelevant': len(irrelevant_matches),
            'reason': reason
        }

    def filter_files(
        self,
        file_paths: List[Path]
    ) -> Tuple[List[Path], List[Dict]]:
        """
        Filter list of files by topic relevance.

        Args:
            file_paths: List of text files to check

        Returns:
            (relevant_files: List[Path], filter_results: List[Dict])
        """
        if not file_paths:
            logger.info("No files to filter")
            return [], []

        relevant_files = []
        filter_results = []

        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()

                is_relevant, info = self.is_relevant(text)

                result = {
                    'file': str(file_path),
                    'is_relevant': is_relevant,
                    'info': info
                }

                filter_results.append(result)

                if is_relevant:
                    relevant_files.append(file_path)
                else:
                    logger.debug(f"Filtered out: {file_path.name} - {info['reason']}")

            except Exception as e:
                logger.warning(f"Error reading {file_path}: {e}")
                # Include on error (don't lose data)
                relevant_files.append(file_path)
                filter_results.append({
                    'file': str(file_path),
                    'is_relevant': True,
                    'info': {'reason': f'Error - included: {e}'}
                })

        logger.info(
            f"Topic filtering: {len(relevant_files)}/{len(file_paths)} files relevant " +
            f"({100*len(relevant_files)/len(file_paths):.1f}%)"
        )

        return relevant_files, filter_results
