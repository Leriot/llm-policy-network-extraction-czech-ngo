"""
Relationship Validator

Validates extracted relationships against core NGO list.
"""

import re
import logging
from typing import List, Dict, Tuple, Set
from pathlib import Path

try:
    from fuzzywuzzy import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False
    logging.warning("fuzzywuzzy not available, using exact matching only")

logger = logging.getLogger(__name__)


class RelationshipValidator:
    """Validate extracted relationships against core NGO list"""

    def __init__(self, core_ngo_list: List[str], fuzzy_threshold: int = 85):
        """
        Initialize validator.

        Args:
            core_ngo_list: List of core NGO names from config
            fuzzy_threshold: Minimum similarity score for fuzzy matching (0-100)
        """
        self.core_ngos = [ngo.strip() for ngo in core_ngo_list]
        self.fuzzy_threshold = fuzzy_threshold

        # Build name variations for fast lookup
        self.ngo_variations = self._build_name_variations()

        logger.info(f"Validator initialized with {len(self.core_ngos)} core NGOs")

    def _build_name_variations(self) -> Dict[str, str]:
        """
        Create mapping of variations to canonical names.

        Examples:
            "Greenpeace" → "Greenpeace CR"
            "Hnutí DUHA" → "Hnutí DUHA"
            "DUHA" → "Hnutí DUHA"
        """
        variations = {}

        for ngo in self.core_ngos:
            ngo_lower = ngo.lower()

            # Add exact match
            variations[ngo_lower] = ngo

            # Remove common legal suffixes
            for suffix in [' z.s.', ' o.s.', ' z. s.', ' o. s.', ', z.s.', ', o.s.']:
                if ngo_lower.endswith(suffix):
                    short = ngo[:-len(suffix)].strip()
                    variations[short.lower()] = ngo
                    break

            # Add first word (if long enough to be distinctive)
            words = ngo.split()
            if len(words) > 1 and len(words[0]) > 4:
                variations[words[0].lower()] = ngo

            # Add last word (often distinctive for Czech NGOs)
            if len(words) > 1 and len(words[-1]) > 4:
                variations[words[-1].lower()] = ngo

        logger.debug(f"Built {len(variations)} name variations")
        return variations

    def validate_actor(self, actor_name: str) -> Tuple[bool, str, str]:
        """
        Validate if actor is a core NGO or should be snowballed.

        Args:
            actor_name: Actor name from extraction

        Returns:
            (is_valid, node_type, normalized_name) where:
            - is_valid: True if actor name is meaningful
            - node_type: 'core_ngo', 'snowball_org', or 'invalid'
            - normalized_name: Canonical name or cleaned name
        """
        if not actor_name:
            return (False, 'invalid', '')

        actor_clean = actor_name.strip()
        actor_lower = actor_clean.lower()

        # Check for invalid/generic names
        generic_terms = [
            'organizace', 'organization', 'ngo', 'sdružení',
            'spolek', 'občanské sdružení', 'nezisková organizace',
            'nadace', 'fond', 'unie', 'asociace'
        ]

        # Too short or generic
        if actor_lower in generic_terms or len(actor_clean) < 3:
            return (False, 'invalid', actor_clean)

        # Check exact match in variations
        if actor_lower in self.ngo_variations:
            canonical = self.ngo_variations[actor_lower]
            return (True, 'core_ngo', canonical)

        # Fuzzy match against core NGOs (if available)
        if FUZZY_AVAILABLE:
            best_match = None
            best_score = 0

            for ngo in self.core_ngos:
                score = fuzz.ratio(actor_clean.lower(), ngo.lower())
                if score > best_score:
                    best_score = score
                    best_match = ngo

            if best_score >= self.fuzzy_threshold:
                return (True, 'core_ngo', best_match)

        # Valid organization, but not in core list → snowball
        # Additional validation: must have at least one capital letter (proper name)
        if any(c.isupper() for c in actor_clean):
            return (True, 'snowball_org', actor_clean)

        return (False, 'invalid', actor_clean)

    def validate_relationship(self, relation: Dict) -> Dict:
        """
        Validate a relationship extraction.

        Args:
            relation: Relationship dict from extractor

        Returns:
            Enriched relationship dict with validation fields:
            {
                'valid': bool,
                'actor1_type': 'core_ngo' | 'snowball_org' | 'invalid',
                'actor2_type': ...,
                'actor1_normalized': str,
                'actor2_normalized': str,
                'relationship_tier': 'core' | 'extended' | 'snowball' | 'invalid'
            }
        """
        # Get actor names based on relationship type
        if 'funder' in relation:
            # Funding relationship
            actor1 = relation.get('funder', '')
            actor2 = relation.get('recipient', '')
        else:
            # Collaboration or information exchange
            actor1 = relation.get('actor1', '')
            actor2 = relation.get('actor2', '')

        # Validate both actors
        valid1, type1, norm1 = self.validate_actor(actor1)
        valid2, type2, norm2 = self.validate_actor(actor2)

        # Determine relationship tier
        if not valid1 or not valid2:
            tier = 'invalid'
        elif type1 == 'core_ngo' and type2 == 'core_ngo':
            tier = 'core'  # Both are core NGOs - COMPON compliant
        elif type1 == 'core_ngo' or type2 == 'core_ngo':
            tier = 'extended'  # At least one core NGO
        else:
            tier = 'snowball'  # Both are discovered orgs

        # Create enriched relationship
        validated = relation.copy()
        validated.update({
            'valid': valid1 and valid2,
            'actor1_type': type1,
            'actor2_type': type2,
            'actor1_normalized': norm1,
            'actor2_normalized': norm2,
            'relationship_tier': tier,
            'validation_score': min(
                self.fuzzy_threshold if type1 == 'core_ngo' else 50,
                self.fuzzy_threshold if type2 == 'core_ngo' else 50
            )
        })

        return validated

    def validate_relationships_batch(self, relationships: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
        """
        Validate a batch of relationships.

        Args:
            relationships: Dict with keys like 'collaboration', 'information_exchange', 'funding'

        Returns:
            Validated relationships dict (same structure)
        """
        validated = {}

        for rel_type, rels in relationships.items():
            validated[rel_type] = [
                self.validate_relationship(rel)
                for rel in rels
            ]

        return validated

    def get_validation_stats(self, validated_relationships: Dict[str, List[Dict]]) -> Dict:
        """
        Get statistics about validation results.

        Args:
            validated_relationships: Dict of validated relationships

        Returns:
            Statistics dict
        """
        stats = {
            'total': 0,
            'valid': 0,
            'invalid': 0,
            'by_tier': {
                'core': 0,
                'extended': 0,
                'snowball': 0,
                'invalid': 0
            },
            'by_type': {}
        }

        for rel_type, rels in validated_relationships.items():
            stats['by_type'][rel_type] = {
                'total': len(rels),
                'valid': 0,
                'invalid': 0
            }

            for rel in rels:
                stats['total'] += 1

                if rel['valid']:
                    stats['valid'] += 1
                    stats['by_type'][rel_type]['valid'] += 1
                else:
                    stats['invalid'] += 1
                    stats['by_type'][rel_type]['invalid'] += 1

                tier = rel.get('relationship_tier', 'invalid')
                stats['by_tier'][tier] += 1

        return stats
