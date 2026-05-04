"""
Relationship Extractor using GLiNER 2

Extracts COMPON-compliant relationships from Czech NGO texts.
"""

import re
import logging
from typing import List, Dict, Tuple, Set
from pathlib import Path

logger = logging.getLogger(__name__)

# Chunking parameters
RELATIONSHIP_CHUNK_SIZE = 3000  # ~750 tokens, enough for sentence context
RELATIONSHIP_OVERLAP = 1000     # Higher overlap to catch cross-boundary relationships

# COMPON Relationship Schema
RELATIONSHIP_SCHEMA = {
    "collaboration_ties": [
        "actor1::str::First organization or NGO name (specific, not generic)",
        "actor2::str::Second organization or NGO name (specific, not generic)",
        "relation_type::str::Type of collaboration (partnership, consortium, joint_project, coalition, memorandum)",
        "context::str::Full sentence containing both actors and their relationship"
    ],
    "information_exchange": [
        "actor1::str::First organization name",
        "actor2::str::Second organization name",
        "exchange_type::str::Type of information exchange (consultation, coordination, dialogue, workshop, conference)",
        "context::str::Full sentence describing the exchange"
    ],
    "funding_ties": [
        "funder::str::Organization providing funding (specific name)",
        "recipient::str::Organization receiving funding (specific name)",
        "funding_type::str::Type of funding (grant, donation, subsidy, project_funding)",
        "context::str::Full sentence describing the funding relationship",
        "amount::str::Amount with currency if mentioned"
    ]
}


class RelationshipExtractor:
    """Extract COMPON relationships using GLiNER 2 local model"""

    def __init__(self, model_name: str = "fastino/gliner2-large-v1", threshold: float = 0.6):
        """
        Initialize relationship extractor.

        Args:
            model_name: GLiNER 2 model name
            threshold: Confidence threshold for extractions (default 0.6 for relationships)
        """
        self.model_name = model_name
        self.threshold = threshold
        self._model = None

        logger.info(f"Relationship extractor initialized (model: {model_name}, threshold: {threshold})")

    def load_model(self):
        """Load GLiNER 2 model (lazy loading)"""
        if self._model is None:
            try:
                from gliner2 import GLiNER2
                import os
                import sys
                import io
                from contextlib import redirect_stdout, redirect_stderr

                logger.info(f"Loading GLiNER 2 model: {self.model_name}")
                logger.info("  (This may take a few minutes on first run...)")

                # Disable progress bars to reduce console output issues on Windows
                os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
                os.environ['TRANSFORMERS_VERBOSITY'] = 'error'

                # Suppress stdout/stderr during model loading to avoid encoding issues
                # GLiNER2 prints emojis that Windows console can't handle
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self._model = GLiNER2.from_pretrained(self.model_name)

                logger.info("  Model loaded successfully")
            except ImportError:
                raise ImportError(
                    "GLiNER 2 not installed. Install with: pip install gliner2"
                )
            except Exception as e:
                raise RuntimeError(f"Failed to load GLiNER 2 model: {e}")

    def chunk_text_by_sentences(self, text: str) -> List[Tuple[str, int]]:
        """
        Split text into chunks at sentence boundaries for better relationship capture.

        Args:
            text: Full text to chunk

        Returns:
            List of (chunk_text, start_offset) tuples
        """
        # Split on Czech sentence boundaries (.!? followed by whitespace)
        sentences = re.split(r'([.!?]\s+)', text)

        chunks = []
        current_chunk = ""
        current_offset = 0
        chunk_start_offset = 0

        for i, part in enumerate(sentences):
            if len(current_chunk) + len(part) > RELATIONSHIP_CHUNK_SIZE:
                if current_chunk:
                    chunks.append((current_chunk.strip(), chunk_start_offset))

                    # Start new chunk with overlap
                    overlap_start = max(0, len(current_chunk) - RELATIONSHIP_OVERLAP)
                    current_chunk = current_chunk[overlap_start:]
                    chunk_start_offset = current_offset - len(current_chunk)

            current_chunk += part
            current_offset += len(part)

        # Add final chunk
        if current_chunk.strip():
            chunks.append((current_chunk.strip(), chunk_start_offset))

        return chunks

    def extract_from_text(self, text: str, source_file: str = "") -> Dict[str, List[Dict]]:
        """
        Extract all relationship types from text.

        Args:
            text: Document text
            source_file: Optional source file identifier

        Returns:
            {
                'collaboration': [...],
                'information_exchange': [...],
                'funding': [...]
            }
        """
        # Ensure model is loaded
        self.load_model()

        # Chunk text
        chunks = self.chunk_text_by_sentences(text)

        logger.debug(f"Processing {len(chunks)} chunks from {source_file or 'text'}")

        all_relationships = {
            'collaboration': [],
            'information_exchange': [],
            'funding': []
        }

        for chunk_idx, (chunk_text, chunk_offset) in enumerate(chunks):
            # Extract each relationship type
            for schema_name, schema_fields in RELATIONSHIP_SCHEMA.items():
                try:
                    # Use extract_json for structured extraction
                    # Based on GLiNER2 docs: model.extract_json(text, schema, threshold=...)
                    result = self._model.extract_json(
                        chunk_text,
                        {schema_name: schema_fields},
                        threshold=self.threshold
                    )

                    # Process results
                    if result and schema_name in result:
                        relationships = result[schema_name]

                        # Add metadata to each relationship
                        for rel in relationships:
                            rel['chunk_offset'] = chunk_offset
                            rel['chunk_index'] = chunk_idx
                            rel['source_file'] = source_file
                            rel['compon_type'] = self._map_to_compon_type(schema_name)

                            # Map to standard format
                            if schema_name == 'collaboration_ties':
                                all_relationships['collaboration'].append(rel)
                            elif schema_name == 'information_exchange':
                                all_relationships['information_exchange'].append(rel)
                            elif schema_name == 'funding_ties':
                                all_relationships['funding'].append(rel)

                except Exception as e:
                    logger.warning(f"Error extracting {schema_name} from chunk {chunk_idx}: {e}")
                    continue

        # Deduplicate across chunks
        all_relationships = self._deduplicate_relationships(all_relationships)

        return all_relationships

    def _map_to_compon_type(self, schema_name: str) -> int:
        """Map schema name to COMPON Tie Type"""
        mapping = {
            'collaboration_ties': 1,      # Collaboration
            'information_exchange': 2,    # Information Exchange
            'funding_ties': 3             # Resource Exchange (Funding)
        }
        return mapping.get(schema_name, 0)

    def _deduplicate_relationships(self, relationships: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
        """
        Remove duplicate relationships found across chunk boundaries.

        Two relationships are duplicates if:
        1. Same actors (normalized)
        2. Same relationship type
        3. Similar context (>80% overlap)
        """
        for rel_type in relationships:
            if not relationships[rel_type]:
                continue

            # Simple deduplication: keep unique (actor1, actor2, type) pairs
            seen = set()
            unique_rels = []

            for rel in relationships[rel_type]:
                try:
                    # Get actor names, handling None values
                    if rel_type == 'funding':
                        funder = rel.get('funder') or ''
                        recipient = rel.get('recipient') or ''
                        funding_type = rel.get('funding_type') or ''

                        key = (
                            funder.lower().strip() if isinstance(funder, str) else '',
                            recipient.lower().strip() if isinstance(recipient, str) else '',
                            funding_type
                        )
                    else:
                        actor1 = rel.get('actor1') or ''
                        actor2 = rel.get('actor2') or ''
                        rel_subtype = rel.get('relation_type') or rel.get('exchange_type') or ''

                        actor1_clean = actor1.lower().strip() if isinstance(actor1, str) else ''
                        actor2_clean = actor2.lower().strip() if isinstance(actor2, str) else ''

                        # Sort to make undirected
                        actors = tuple(sorted([actor1_clean, actor2_clean]))
                        key = (*actors, rel_subtype if isinstance(rel_subtype, str) else '')

                    # Only keep if both actors are non-empty
                    if key[0] and key[1] and key not in seen:
                        seen.add(key)
                        unique_rels.append(rel)
                except Exception as e:
                    logger.warning(f"Error deduplicating relationship: {e}, rel={rel}")
                    continue

            relationships[rel_type] = unique_rels

        return relationships

    def extract_from_file(self, file_path: Path) -> Dict[str, List[Dict]]:
        """
        Extract relationships from a text file.

        Args:
            file_path: Path to text file

        Returns:
            Dictionary of relationships by type
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()

            return self.extract_from_text(text, source_file=file_path.name)

        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            return {
                'collaboration': [],
                'information_exchange': [],
                'funding': []
            }
