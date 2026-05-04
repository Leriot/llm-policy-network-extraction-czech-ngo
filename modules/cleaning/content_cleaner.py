"""
Content Cleaner - Deduplication and Post-Processing
====================================================

Handles deduplication of extracted content using shingling + Jaccard similarity.
Adapted from scripts/filter_content.py for the new Module 2 architecture.
"""

import json
import logging
import string
from pathlib import Path
from typing import Dict, Set, List, Tuple, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class ContentCleaner:
    """
    Handles content deduplication and final cleaning.
    """

    def __init__(self, ngo_name: str, config: Dict):
        """
        Initialize content cleaner.

        Args:
            ngo_name: Name of the NGO
            config: Configuration dict from cleaning_config.yaml
        """
        self.ngo_name = ngo_name
        self.config = config

        # Deduplication settings
        self.similarity_threshold = config['deduplication'].get('similarity_threshold', 0.85)
        self.shingle_size = config['deduplication'].get('shingle_size', 3)
        self.keep_representative = config['deduplication'].get('keep_representative', True)

        # Track unique documents
        self.unique_docs: Dict[str, Set[Tuple]] = {}  # filename -> shingles

        # Duplicate clusters
        self.duplicate_clusters: Dict[str, List[str]] = defaultdict(list)  # master -> duplicates

        # Paths
        self.cleaned_dir = Path("data/interim/step1_content_extraction") / ngo_name
        self.duplicates_file = self.cleaned_dir / "duplicates.json"

        # Statistics
        self.stats = {
            'total_documents': 0,
            'unique_documents': 0,
            'duplicate_documents': 0,
            'duplicate_clusters': 0
        }

    def get_shingles(self, text: str, k: Optional[int] = None) -> Set[Tuple]:
        """
        Create k-word shingles for deduplication.

        Args:
            text: Input text
            k: Shingle size (default: from config)

        Returns:
            Set of k-word tuples
        """
        if k is None:
            k = self.shingle_size

        # Remove punctuation and lowercase
        translator = str.maketrans('', '', string.punctuation)
        clean_tokens = text.translate(translator).lower().split()

        if len(clean_tokens) < k:
            # If text is shorter than shingle size, use all words as one shingle
            return set([tuple(clean_tokens)]) if clean_tokens else set()

        # Create k-word shingles
        shingles = set(
            tuple(clean_tokens[i:i+k])
            for i in range(len(clean_tokens) - k + 1)
        )

        return shingles

    def calculate_jaccard_similarity(self, set_a: Set, set_b: Set) -> float:
        """
        Calculate Jaccard similarity between two sets.

        Args:
            set_a: First set
            set_b: Second set

        Returns:
            Similarity score (0.0 to 1.0)
        """
        if not set_a and not set_b:
            return 0.0

        intersection = len(set_a.intersection(set_b))
        union = len(set_a.union(set_b))

        return intersection / union if union > 0 else 0.0

    def find_duplicate(self, current_shingles: Set[Tuple],
                      filename: str) -> Tuple[bool, Optional[str]]:
        """
        Check if current document is a duplicate of existing documents.

        Args:
            current_shingles: Shingles of current document
            filename: Filename of current document

        Returns:
            Tuple of (is_duplicate, master_filename)
        """
        if not current_shingles:
            return False, None

        for master_filename, master_shingles in self.unique_docs.items():
            similarity = self.calculate_jaccard_similarity(current_shingles, master_shingles)

            if similarity >= self.similarity_threshold:
                return True, master_filename

        return False, None

    def process_document(self, filename: str, text: str) -> Tuple[bool, Optional[str]]:
        """
        Process a document for deduplication.

        Args:
            filename: Document filename
            text: Document text content

        Returns:
            Tuple of (is_unique, master_filename_if_duplicate)
        """
        self.stats['total_documents'] += 1

        # Generate shingles
        shingles = self.get_shingles(text)

        if not shingles:
            logger.debug(f"No shingles generated for {filename} (empty or too short)")
            return True, None  # Consider empty docs as unique

        # Check for duplicates
        is_duplicate, master_filename = self.find_duplicate(shingles, filename)

        if is_duplicate:
            # Document is a duplicate
            self.stats['duplicate_documents'] += 1
            self.duplicate_clusters[master_filename].append(filename)
            logger.debug(f"Duplicate found: {filename} → {master_filename} "
                        f"(similarity ≥{self.similarity_threshold:.2%})")
            return False, master_filename

        else:
            # Document is unique
            self.unique_docs[filename] = shingles
            self.stats['unique_documents'] += 1
            return True, None

    def save_duplicate_mapping(self):
        """Save duplicate cluster mapping to JSON file."""
        if not self.duplicate_clusters:
            logger.info("No duplicates found - no mapping file created")
            return

        # Convert to more readable format
        mapping = {
            'ngo_name': self.ngo_name,
            'similarity_threshold': self.similarity_threshold,
            'shingle_size': self.shingle_size,
            'clusters': []
        }

        for master, duplicates in self.duplicate_clusters.items():
            mapping['clusters'].append({
                'representative': master,
                'duplicates': duplicates,
                'duplicate_count': len(duplicates)
            })

        self.stats['duplicate_clusters'] = len(self.duplicate_clusters)

        try:
            with open(self.duplicates_file, 'w', encoding='utf-8') as f:
                json.dump(mapping, f, indent=2, ensure_ascii=False)

            logger.info(f"Duplicate mapping saved to {self.duplicates_file}")
            logger.info(f"  {self.stats['duplicate_clusters']} clusters with "
                       f"{self.stats['duplicate_documents']} total duplicates")

        except Exception as e:
            logger.error(f"Error saving duplicate mapping: {e}")

    def load_duplicate_mapping(self) -> Optional[Dict]:
        """
        Load duplicate mapping from JSON file.

        Returns:
            Duplicate mapping dict or None if not found
        """
        if not self.duplicates_file.exists():
            return None

        try:
            with open(self.duplicates_file, 'r', encoding='utf-8') as f:
                mapping = json.load(f)

            logger.info(f"Loaded duplicate mapping from {self.duplicates_file}")
            return mapping

        except Exception as e:
            logger.error(f"Error loading duplicate mapping: {e}")
            return None

    def is_duplicate(self, filename: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a filename is in the duplicate list.

        Args:
            filename: Filename to check

        Returns:
            Tuple of (is_duplicate, master_filename)
        """
        for master, duplicates in self.duplicate_clusters.items():
            if filename in duplicates:
                return True, master

        return False, None

    def get_stats(self) -> Dict:
        """Get deduplication statistics."""
        return {
            **self.stats,
            'deduplication_rate': (self.stats['duplicate_documents'] / self.stats['total_documents'] * 100)
            if self.stats['total_documents'] > 0 else 0
        }

    def reset(self):
        """Reset deduplication state (for processing a new NGO)."""
        self.unique_docs = {}
        self.duplicate_clusters = defaultdict(list)
        self.stats = {
            'total_documents': 0,
            'unique_documents': 0,
            'duplicate_documents': 0,
            'duplicate_clusters': 0
        }
