"""
Network Builder

Combines text-based and link-based relationships into network structures.
"""

import json
import logging
import pandas as pd
from pathlib import Path
from typing import Dict, List
from collections import defaultdict

logger = logging.getLogger(__name__)


class NetworkBuilder:
    """Build network structures from extracted relationships"""

    def __init__(self, confidence_threshold: float = 0.6):
        """
        Initialize network builder.

        Args:
            confidence_threshold: Minimum confidence for including edges
        """
        self.confidence_threshold = confidence_threshold

    def merge_edges(
        self,
        text_edges: List[Dict],
        link_edges: List[Dict]
    ) -> pd.DataFrame:
        """
        Merge and deduplicate edges from text extraction and links.

        Args:
            text_edges: Edges from relationship extraction
            link_edges: Edges from external links analysis

        Returns:
            DataFrame with merged edges
        """
        all_edges = text_edges + link_edges

        logger.info(f"Merging {len(text_edges)} text edges + {len(link_edges)} link edges")

        # Group by (source, target, edge_type)
        edge_groups = defaultdict(lambda: {
            'weight': 0,
            'contexts': [],
            'methods': set(),
            'compon_types': set(),
            'tie_strengths': set(),
            'source_files': set()
        })

        for edge in all_edges:
            # Determine actors
            if edge.get('edge_type') == 'funding_ties':
                source = edge.get('funder') or edge.get('actor1_normalized', '')
                target = edge.get('recipient') or edge.get('actor2_normalized', '')
            else:
                source = edge.get('source') or edge.get('actor1_normalized', '')
                target = edge.get('target') or edge.get('actor2_normalized', '')

            # Skip if invalid
            if not source or not target:
                continue

            # For undirected edges (non-funding), sort to avoid duplicates
            if edge.get('edge_type') != 'funding_ties':
                source, target = sorted([source, target])

            edge_type = edge.get('edge_type', 'unknown')
            key = (source, target, edge_type)

            # Aggregate data
            data = edge_groups[key]
            data['weight'] += edge.get('weight', 1)

            if 'context' in edge:
                data['contexts'].append(edge['context'])

            if 'extraction_method' in edge:
                data['methods'].add(edge['extraction_method'])

            if 'compon_type' in edge:
                data['compon_types'].add(edge['compon_type'])

            if 'tie_strength' in edge:
                data['tie_strengths'].add(edge['tie_strength'])

            if 'source_file' in edge:
                data['source_files'].add(edge['source_file'])

        # Convert to DataFrame
        edges_data = []
        for (source, target, edge_type), data in edge_groups.items():
            edges_data.append({
                'source': source,
                'target': target,
                'edge_type': edge_type,
                'weight': data['weight'],
                'num_mentions': len(data['contexts']),
                'extraction_methods': '|'.join(sorted(data['methods'])),
                'contexts_sample': data['contexts'][:3],  # Keep up to 3 context examples
                'compon_type': max(data['compon_types']) if data['compon_types'] else None,
                'tie_strength': list(data['tie_strengths'])[0] if len(data['tie_strengths']) == 1 else 'mixed',
                'num_sources': len(data['source_files'])
            })

        edges_df = pd.DataFrame(edges_data)

        logger.info(f"Merged into {len(edges_df)} unique edges")

        return edges_df

    def build_nodes_from_edges(self, edges_df: pd.DataFrame, core_ngos: List[str]) -> pd.DataFrame:
        """
        Extract nodes from edges and classify them.

        Args:
            edges_df: DataFrame of edges
            core_ngos: List of core NGO names

        Returns:
            DataFrame of nodes with metadata
        """
        # Get all unique actors
        all_actors = set(edges_df['source'].unique()) | set(edges_df['target'].unique())

        nodes_data = []
        for actor in all_actors:
            # Determine if core or snowball
            is_core = actor in core_ngos

            # Count edges
            actor_edges = edges_df[
                (edges_df['source'] == actor) | (edges_df['target'] == actor)
            ]

            nodes_data.append({
                'node_id': actor,
                'node_type': 'core_ngo' if is_core else 'snowball_org',
                'tier': 1 if is_core else 2,
                'degree': len(actor_edges),
                'num_collaboration': len(actor_edges[actor_edges['edge_type'].str.contains('collaboration', na=False)]),
                'num_information': len(actor_edges[actor_edges['edge_type'].str.contains('information', na=False)]),
                'num_funding': len(actor_edges[actor_edges['edge_type'].str.contains('funding', na=False)]),
                'num_web_ref': len(actor_edges[actor_edges['edge_type'].str.contains('web_reference', na=False)])
            })

        nodes_df = pd.DataFrame(nodes_data)
        logger.info(f"Built {len(nodes_df)} nodes ({len(nodes_df[nodes_df['tier']==1])} core + {len(nodes_df[nodes_df['tier']==2])} snowball)")

        return nodes_df

    def export_networks(
        self,
        edges_df: pd.DataFrame,
        nodes_df: pd.DataFrame,
        output_dir: Path,
        year: str
    ):
        """
        Export two-tier networks (core and extended).

        Args:
            edges_df: All edges
            nodes_df: All nodes
            output_dir: Base output directory
            year: Year label
        """
        output_dir = Path(output_dir)

        # === CORE NETWORK ===
        core_nodes = nodes_df[nodes_df['tier'] == 1].copy()
        core_node_ids = set(core_nodes['node_id'])

        # Core edges: both source and target are core NGOs
        core_edges = edges_df[
            edges_df['source'].isin(core_node_ids) &
            edges_df['target'].isin(core_node_ids)
        ].copy()

        # Export core network
        core_dir = output_dir / year / "core_network"
        core_dir.mkdir(parents=True, exist_ok=True)

        core_nodes.to_csv(core_dir / "nodes.csv", index=False)
        core_edges.to_csv(core_dir / "edges.csv", index=False)

        # Core network stats
        core_stats = {
            'num_nodes': len(core_nodes),
            'num_edges': len(core_edges),
            'edge_types': core_edges['edge_type'].value_counts().to_dict(),
            'compon_distribution': core_edges['compon_type'].value_counts().to_dict(),
            'avg_degree': core_nodes['degree'].mean() if len(core_nodes) > 0 else 0,
            'density': len(core_edges) / (len(core_nodes) * (len(core_nodes) - 1) / 2) if len(core_nodes) > 1 else 0
        }

        with open(core_dir / "network_stats.json", 'w', encoding='utf-8') as f:
            json.dump(core_stats, f, indent=2)

        logger.info(f"  ✓ Core network: {len(core_nodes)} nodes, {len(core_edges)} edges")
        logger.info(f"    Density: {core_stats['density']:.4f}")

        # === EXTENDED NETWORK ===
        # Extended edges: at least one core NGO involved
        extended_edges = edges_df[
            edges_df['source'].isin(core_node_ids) |
            edges_df['target'].isin(core_node_ids)
        ].copy()

        # Extended nodes: all nodes involved in extended edges
        extended_node_ids = set(extended_edges['source']) | set(extended_edges['target'])
        extended_nodes = nodes_df[nodes_df['node_id'].isin(extended_node_ids)].copy()

        # Export extended network
        extended_dir = output_dir / year / "extended_network"
        extended_dir.mkdir(parents=True, exist_ok=True)

        extended_nodes.to_csv(extended_dir / "nodes.csv", index=False)
        extended_edges.to_csv(extended_dir / "edges.csv", index=False)

        # Extended network stats
        extended_stats = {
            'num_nodes': len(extended_nodes),
            'num_core_ngos': len(extended_nodes[extended_nodes['tier'] == 1]),
            'num_snowball_orgs': len(extended_nodes[extended_nodes['tier'] == 2]),
            'num_edges': len(extended_edges),
            'edge_types': extended_edges['edge_type'].value_counts().to_dict(),
            'avg_degree': extended_nodes['degree'].mean() if len(extended_nodes) > 0 else 0
        }

        with open(extended_dir / "network_stats.json", 'w', encoding='utf-8') as f:
            json.dump(extended_stats, f, indent=2)

        logger.info(f"  ✓ Extended network: {len(extended_nodes)} nodes " +
                   f"({extended_stats['num_core_ngos']} core + {extended_stats['num_snowball_orgs']} snowball), " +
                   f"{len(extended_edges)} edges")

    def export_raw_relationships(
        self,
        validated_relationships: Dict[str, List[Dict]],
        output_dir: Path,
        ngo_name: str,
        year: str
    ):
        """
        Export raw extracted relationships for inspection.

        Args:
            validated_relationships: Dict of validated relationships
            output_dir: Base output directory
            ngo_name: NGO name
            year: Year
        """
        raw_dir = output_dir / year / "raw_extractions" / ngo_name
        raw_dir.mkdir(parents=True, exist_ok=True)

        # Export each relationship type
        for rel_type, rels in validated_relationships.items():
            if rels:
                output_file = raw_dir / f"{rel_type}.jsonl"
                with open(output_file, 'w', encoding='utf-8') as f:
                    for rel in rels:
                        f.write(json.dumps(rel, ensure_ascii=False) + '\n')

        logger.debug(f"Exported raw extractions for {ngo_name}/{year}")
