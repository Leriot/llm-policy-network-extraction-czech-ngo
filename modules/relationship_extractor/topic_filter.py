"""
Topic Filter using GLiNER 2

Filters texts by topic relevance before relationship extraction.
Reduces false positives from unrelated content (promotions, admin pages, etc.)
"""

import logging
from typing import List, Dict, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# Relevant topics for Czech NGO climate policy network research
RELEVANT_TOPICS = [
    "climate_change",
    "environmental_policy",
    "sustainability",
    "renewable_energy",
    "carbon_emissions",
    "biodiversity",
    "nature_conservation",
    "air_quality",
    "water_protection",
    "waste_management",
    "circular_economy",
    "green_transition",
    "environmental_justice",
    "climate_activism",
    "energy_transition",
    "environmental_legislation",
    "pollution_control",
    "ecosystem_protection",
    "climate_policy",
    "environmental_advocacy"
]

# GLiNER schema for topic extraction
TOPIC_SCHEMA = {
    "document_topics": [
        "primary_topic::str::Main topic of the document from this list: climate change, environmental policy, sustainability, renewable energy, biodiversity, nature conservation, pollution, waste management, energy, or other",
        "relevance_score::str::How relevant is this document to environmental or climate issues (high, medium, low)",
        "key_themes::str::List of key environmental themes mentioned (comma-separated)"
    ]
}


class TopicFilter:
    """Filter texts by topic relevance using GLiNER 2"""

    def __init__(
        self,
        model_name: str = "fastino/gliner2-large-v1",
        threshold: float = 0.5,
        relevant_topics: List[str] = None
    ):
        """
        Initialize topic filter.

        Args:
            model_name: GLiNER 2 model name
            threshold: Confidence threshold for topic extraction
            relevant_topics: List of relevant topic keywords
        """
        self.model_name = model_name
        self.threshold = threshold
        self.relevant_topics = relevant_topics or RELEVANT_TOPICS
        self._model = None

        logger.info(f"Topic filter initialized with {len(self.relevant_topics)} relevant topics")

    def load_model(self):
        """Load GLiNER 2 model (lazy loading)"""
        if self._model is None:
            try:
                from gliner2 import GLiNER2
                import os
                import sys
                import io
                from contextlib import redirect_stdout, redirect_stderr

                logger.info(f"Loading GLiNER 2 model for topic filtering: {self.model_name}")

                os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
                os.environ['TRANSFORMERS_VERBOSITY'] = 'error'

                # Suppress stdout/stderr during model loading
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self._model = GLiNER2.from_pretrained(self.model_name)

                logger.info("  Topic filter model loaded successfully")
            except ImportError:
                raise ImportError("GLiNER 2 not installed. Install with: pip install gliner2")
            except Exception as e:
                raise RuntimeError(f"Failed to load GLiNER 2 model: {e}")

    def is_relevant(self, text: str, min_confidence: float = 0.3) -> Tuple[bool, Dict]:
        """
        Check if text is relevant to environmental/climate topics.

        Args:
            text: Document text to check
            min_confidence: Minimum confidence for relevance

        Returns:
            (is_relevant: bool, topic_info: dict)
        """
        self.load_model()

        # Take first 1000 characters for topic detection
        # (topic usually clear from beginning)
        sample = text[:1000]

        try:
            # Extract topics
            result = self._model.extract_json(
                sample,
                TOPIC_SCHEMA,
                threshold=self.threshold
            )

            if result and 'document_topics' in result:
                topics = result['document_topics']

                if not topics:
                    return False, {'reason': 'No topics extracted'}

                topic_info = topics[0] if isinstance(topics, list) else topics

                # Check relevance (handle None values)
                primary_topic = (topic_info.get('primary_topic') or '').lower()
                relevance = (topic_info.get('relevance_score') or '').lower()
                key_themes = (topic_info.get('key_themes') or '').lower()

                # Check if any relevant topic keywords match
                topic_text = f"{primary_topic} {key_themes}".lower()
                matches = [
                    topic for topic in self.relevant_topics
                    if topic.replace('_', ' ') in topic_text
                    or topic.replace('_', '') in topic_text.replace(' ', '')
                ]

                is_relevant = (
                    len(matches) > 0
                    or relevance in ['high', 'medium']
                    or any(keyword in topic_text for keyword in [
                        'climate', 'environment', 'sustain', 'energy',
                        'biodiversity', 'conservation', 'pollution',
                        'waste', 'carbon', 'green', 'ecology'
                    ])
                )

                return is_relevant, {
                    'primary_topic': primary_topic,
                    'relevance_score': relevance,
                    'key_themes': key_themes,
                    'matched_topics': matches
                }

            return False, {'reason': 'Extraction failed'}

        except Exception as e:
            logger.warning(f"Topic extraction error: {e}")
            # If extraction fails, assume relevant (don't filter out)
            return True, {'reason': 'Error - assuming relevant', 'error': str(e)}

    def filter_files(
        self,
        file_paths: List[Path],
        min_confidence: float = 0.3
    ) -> Tuple[List[Path], List[Dict]]:
        """
        Filter list of files by topic relevance.

        Args:
            file_paths: List of text files to check
            min_confidence: Minimum confidence for relevance

        Returns:
            (relevant_files: List[Path], filter_results: List[Dict])
        """
        relevant_files = []
        filter_results = []

        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()

                is_relevant, topic_info = self.is_relevant(text, min_confidence)

                result = {
                    'file': str(file_path),
                    'is_relevant': is_relevant,
                    'topic_info': topic_info
                }

                filter_results.append(result)

                if is_relevant:
                    relevant_files.append(file_path)
                else:
                    logger.debug(f"Filtered out (irrelevant): {file_path.name}")

            except Exception as e:
                logger.warning(f"Error reading {file_path}: {e}")
                # Include file if we can't read it (don't lose data on errors)
                relevant_files.append(file_path)
                filter_results.append({
                    'file': str(file_path),
                    'is_relevant': True,
                    'topic_info': {'reason': 'Error - included by default', 'error': str(e)}
                })

        if len(file_paths) > 0:
            logger.info(
                f"Topic filtering: {len(relevant_files)}/{len(file_paths)} files relevant " +
                f"({100*len(relevant_files)/len(file_paths):.1f}%)"
            )
        else:
            logger.info("Topic filtering: No files to process")

        return relevant_files, filter_results
