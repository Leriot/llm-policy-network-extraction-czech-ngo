"""
External Links Analyzer

Analyzes hyperlinks between NGO websites to create relationship edges.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Set
from collections import Counter, defaultdict
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ExternalLinkAnalyzer:
    """
    Analyze external links to create relationship edges.

    Strategies:
    - STRONG TIE: NGO A links to NGO B's domain (direct reference)
    - WEAK TIE: NGO A and NGO B both link to the same external resource
    """

    def __init__(self, ngo_domains: Dict[str, str]):
        """
        Initialize analyzer.

        Args:
            ngo_domains: {ngo_name: primary_domain}
                e.g., {"Greenpeace CR": "greenpeace.org"}
        """
        self.ngo_domains = ngo_domains
        self.domain_to_ngo = {v: k for k, v in ngo_domains.items()}

        logger.info(f"External links analyzer initialized with {len(ngo_domains)} NGO domains")

    @staticmethod
    def _normalize_domain(url: str) -> str:
        """
        Extract and normalize domain from URL.

        Args:
            url: Full URL

        Returns:
            Normalized domain (e.g., "greenpeace.org")
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]

            return domain
        except Exception:
            return ""

    @staticmethod
    def _normalize_resource_url(url: str) -> str:
        """
        Normalize URL for shared resource detection.

        Removes query parameters and fragments to group similar URLs.

        Args:
            url: Full URL

        Returns:
            Normalized URL
        """
        try:
            parsed = urlparse(url)
            # Keep only scheme, netloc, and path
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            return normalized.lower()
        except Exception:
            return url.lower()

    def extract_direct_references(self, external_links_dir: Path) -> List[Dict]:
        """
        Extract STRONG ties: NGO A → NGO B (direct website reference)

        Args:
            external_links_dir: Directory containing external_links.json files
                Structure: {year}/{ngo}/external_links.json

        Returns:
            List of edge dicts with:
            - source: Source NGO
            - target: Target NGO
            - edge_type: 'web_reference_direct'
            - weight: Number of links
            - compon_type: 2 (Information Exchange)
            - tie_strength: 'strong'
        """
        edges = []

        # Find all external_links.json files
        link_files = list(external_links_dir.rglob("external_links.json"))

        logger.info(f"Processing {len(link_files)} external links files")

        for link_file in link_files:
            # Extract NGO name from path
            # Path structure: {year}/{ngo}/external_links.json
            source_ngo = link_file.parent.name

            try:
                with open(link_file, 'r', encoding='utf-8') as f:
                    link_data = json.load(f)

                # Count links to each target domain
                target_counts = Counter()

                for link in link_data.get('external_links', []):
                    url = link.get('url', '')
                    domain = self._normalize_domain(url)

                    # Check if domain belongs to another NGO
                    if domain in self.domain_to_ngo:
                        target_ngo = self.domain_to_ngo[domain]

                        # No self-loops
                        if target_ngo != source_ngo:
                            target_counts[target_ngo] += 1

                # Create edges
                for target_ngo, count in target_counts.items():
                    edges.append({
                        'source': source_ngo,
                        'target': target_ngo,
                        'edge_type': 'web_reference_direct',
                        'compon_type': 2,  # Information Exchange
                        'tie_strength': 'strong',
                        'weight': count,
                        'extraction_method': 'hyperlink_direct',
                        'evidence': f'{count} hyperlinks from {source_ngo} to {target_ngo}',
                        'source_file': str(link_file)
                    })

            except Exception as e:
                logger.warning(f"Error processing {link_file}: {e}")
                continue

        logger.info(f"Extracted {len(edges)} direct reference edges")
        return edges

    def extract_shared_references(
        self,
        external_links_dir: Path,
        min_ngos: int = 2
    ) -> List[Dict]:
        """
        Extract WEAK ties: NGOs sharing references to same external resource.

        Only creates edge if ≥min_ngos NGOs link to the same resource.

        Args:
            external_links_dir: Directory containing external_links.json files
            min_ngos: Minimum number of NGOs that must share a resource

        Returns:
            List of edge dicts with:
            - source, target: NGO names
            - edge_type: 'shared_reference'
            - weight: Number of shared resources
            - compon_type: 2
            - tie_strength: 'weak'
        """
        # Build reverse index: resource → set of NGOs referencing it
        resource_to_ngos = defaultdict(set)

        # Find all external_links.json files
        link_files = list(external_links_dir.rglob("external_links.json"))

        for link_file in link_files:
            source_ngo = link_file.parent.name

            try:
                with open(link_file, 'r', encoding='utf-8') as f:
                    link_data = json.load(f)

                for link in link_data.get('external_links', []):
                    url = link.get('url', '')
                    # Normalize URL
                    normalized_url = self._normalize_resource_url(url)

                    # Exclude links to other NGO websites (those are direct refs)
                    domain = self._normalize_domain(url)
                    if domain not in self.domain_to_ngo:
                        resource_to_ngos[normalized_url].add(source_ngo)

            except Exception as e:
                logger.warning(f"Error processing {link_file}: {e}")
                continue

        # Find shared resources
        shared_resources = {
            url: ngos
            for url, ngos in resource_to_ngos.items()
            if len(ngos) >= min_ngos
        }

        logger.info(f"Found {len(shared_resources)} resources shared by ≥{min_ngos} NGOs")

        # Create edges for each pair of NGOs sharing resources
        edge_counts = defaultdict(lambda: {
            'shared_resources': [],
            'weight': 0
        })

        for url, ngos in shared_resources.items():
            ngo_list = sorted(list(ngos))

            # Create edges for all pairs
            for i in range(len(ngo_list)):
                for j in range(i + 1, len(ngo_list)):
                    pair = (ngo_list[i], ngo_list[j])
                    edge_counts[pair]['shared_resources'].append(url)
                    edge_counts[pair]['weight'] += 1

        # Convert to edges
        edges = []
        for (ngo1, ngo2), data in edge_counts.items():
            edges.append({
                'source': ngo1,
                'target': ngo2,
                'edge_type': 'shared_reference',
                'compon_type': 2,  # Information Exchange
                'tie_strength': 'weak',
                'weight': data['weight'],
                'extraction_method': 'hyperlink_shared',
                'evidence': f'{data["weight"]} shared resources',
                'shared_resources_sample': data['shared_resources'][:5]  # Keep top 5 as examples
            })

        logger.info(f"Extracted {len(edges)} shared reference edges")
        return edges

    def extract_all_links(
        self,
        external_links_dir: Path,
        min_shared_ngos: int = 2
    ) -> List[Dict]:
        """
        Extract both direct and shared reference edges.

        Args:
            external_links_dir: Directory with external_links.json files
            min_shared_ngos: Minimum NGOs for shared references

        Returns:
            Combined list of all edges
        """
        logger.info("Extracting direct references...")
        direct_edges = self.extract_direct_references(external_links_dir)

        logger.info("Extracting shared references...")
        shared_edges = self.extract_shared_references(external_links_dir, min_shared_ngos)

        logger.info(f"Total external link edges: {len(direct_edges) + len(shared_edges)}")

        return direct_edges + shared_edges
