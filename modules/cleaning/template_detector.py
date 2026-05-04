"""
Template Detector - Multi-Level Boilerplate Detection
======================================================

Detects repeated HTML elements (templates/boilerplate) at two levels:
1. Global: Elements appearing on most pages across the entire site
2. Section-specific: Elements appearing on most pages within a URL path group

This enables removal of both site-wide chrome (header, footer) and
section-specific boilerplate (e.g., sidebar in /aktuality/ section).
"""

import json
import logging
import random
from pathlib import Path
from collections import Counter, defaultdict
from typing import Dict, List, Set, Tuple, Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class TemplateDetector:
    """
    Detects template elements at global and section-specific levels.
    """

    def __init__(self, ngo_name: str, config: Dict):
        """
        Initialize template detector.

        Args:
            ngo_name: Name of the NGO
            config: Configuration dict from cleaning_config.yaml
        """
        self.ngo_name = ngo_name
        self.config = config

        # Paths
        self.raw_dir = Path("data/raw") / ngo_name
        self.pages_dir = self.raw_dir / "pages"  # HTML files are in pages/ subfolder
        self.cleaned_dir = Path("data/interim/step1_content_extraction") / ngo_name
        self.cleaned_dir.mkdir(parents=True, exist_ok=True)

        # Template signature file
        self.template_file = self.cleaned_dir / "templates.json"

        # URL manifest for file→URL mapping
        self.manifest_file = self.raw_dir / "url_manifest.jsonl"

        # Statistics
        self.stats = {
            'total_files': 0,
            'sampled_files': 0,
            'global_elements_found': 0,
            'section_groups': 0,
            'section_elements_found': 0
        }

    def load_url_manifest(self) -> Dict[str, str]:
        """
        Load URL manifest to map filenames to URLs.

        Returns:
            Dict mapping filename to URL
        """
        manifest = {}

        if not self.manifest_file.exists():
            logger.warning(f"URL manifest not found: {self.manifest_file}")
            return manifest

        try:
            with open(self.manifest_file, 'r', encoding='utf-8') as f:
                for line in f:
                    entry = json.loads(line.strip())
                    filename = entry.get('filename')  # Correct field name
                    url = entry.get('url')
                    if filename and url:
                        manifest[filename] = url

            logger.info(f"Loaded {len(manifest)} URL mappings from manifest")

        except Exception as e:
            logger.error(f"Error loading URL manifest: {e}")

        return manifest

    def extract_url_path_pattern(self, url: str, depth: int = 1) -> str:
        """
        Extract URL path pattern for grouping.

        Args:
            url: Full URL
            depth: Number of path segments to include (1 = /aktuality/, 2 = /aktuality/clanky/)

        Returns:
            Path pattern (e.g., '/aktuality/')
        """
        try:
            parsed = urlparse(url)
            path = parsed.path.strip('/')

            if not path:
                return '/'

            segments = path.split('/')[:depth]
            pattern = '/' + '/'.join(segments) + '/'

            return pattern

        except Exception as e:
            logger.debug(f"Error extracting path pattern from {url}: {e}")
            return '/'

    def group_pages_by_url_path(self, manifest: Dict[str, str]) -> Dict[str, List[str]]:
        """
        Group page files by URL path pattern.

        Args:
            manifest: Dict mapping filename to URL

        Returns:
            Dict mapping path pattern to list of filenames
        """
        groups = defaultdict(list)
        path_depth = self.config['template_detection'].get('path_depth', 1)

        for filename, url in manifest.items():
            pattern = self.extract_url_path_pattern(url, depth=path_depth)
            groups[pattern].append(filename)

        logger.info(f"Grouped {len(manifest)} pages into {len(groups)} URL path patterns")

        return dict(groups)

    def extract_element_signatures(self, html_content: str) -> Set[str]:
        """
        Extract element signatures from HTML (class, id, tag+class combinations).

        Args:
            html_content: Raw HTML content

        Returns:
            Set of element signatures
        """
        signatures = set()

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            for elem in soup.find_all(True):  # All elements
                # Class-based signatures
                if elem.get('class'):
                    for cls in elem['class']:
                        signatures.add(f"class:{cls}")
                        signatures.add(f"{elem.name}.{cls}")  # tag.class combo

                # ID-based signatures
                if elem.get('id'):
                    signatures.add(f"id:{elem['id']}")

                # Role-based signatures (for ARIA)
                if elem.get('role'):
                    signatures.add(f"role:{elem['role']}")

        except Exception as e:
            logger.debug(f"Error extracting signatures: {e}")

        return signatures

    def detect_global_template(self, manifest: Dict[str, str]) -> Dict[str, any]:
        """
        Detect global template elements appearing on most pages.

        Args:
            manifest: Dict mapping filename to URL

        Returns:
            Dict with global template signature
        """
        sample_size = self.config['template_detection'].get('sample_size', 200)
        threshold = self.config['template_detection'].get('global_threshold', 0.80)

        # Get all HTML files from pages/ subfolder
        html_files = list(self.pages_dir.glob('*.html'))
        self.stats['total_files'] = len(html_files)

        if not html_files:
            logger.warning(f"No HTML files found in {self.pages_dir}")
            return {'elements': [], 'threshold': threshold, 'sampled': 0}

        # Sample random pages
        sample_size = min(sample_size, len(html_files))
        sampled_files = random.sample(html_files, sample_size)
        self.stats['sampled_files'] = sample_size

        logger.info(f"Sampling {sample_size} pages for global template detection")

        # Count element frequency across sampled pages
        element_counter = Counter()

        for html_file in sampled_files:
            try:
                html_content = html_file.read_text(encoding='utf-8', errors='ignore')
                signatures = self.extract_element_signatures(html_content)
                element_counter.update(signatures)

            except Exception as e:
                logger.debug(f"Error processing {html_file.name}: {e}")

        # Find elements above threshold
        min_count = int(sample_size * threshold)
        global_elements = [
            elem for elem, count in element_counter.items()
            if count >= min_count
        ]

        self.stats['global_elements_found'] = len(global_elements)

        logger.info(f"Found {len(global_elements)} global template elements (threshold: {threshold:.0%})")

        return {
            'elements': global_elements,
            'threshold': threshold,
            'sampled': sample_size,
            'total_elements_analyzed': len(element_counter)
        }

    def detect_section_templates(self, manifest: Dict[str, str],
                                  path_groups: Dict[str, List[str]]) -> Dict[str, Dict]:
        """
        Detect section-specific template elements.

        Args:
            manifest: Dict mapping filename to URL
            path_groups: Dict mapping path pattern to list of filenames

        Returns:
            Dict mapping path pattern to section template signature
        """
        threshold = self.config['template_detection'].get('section_threshold', 0.80)
        min_section_size = self.config['template_detection'].get('min_section_size', 10)

        section_templates = {}

        for pattern, filenames in path_groups.items():
            # Skip small sections
            if len(filenames) < min_section_size:
                logger.debug(f"Skipping section {pattern} (only {len(filenames)} pages, need ≥{min_section_size})")
                continue

            logger.info(f"Analyzing section: {pattern} ({len(filenames)} pages)")

            # Count element frequency within this section
            element_counter = Counter()

            for filename in filenames:
                html_file = self.pages_dir / filename
                if not html_file.exists():
                    continue

                try:
                    html_content = html_file.read_text(encoding='utf-8', errors='ignore')
                    signatures = self.extract_element_signatures(html_content)
                    element_counter.update(signatures)

                except Exception as e:
                    logger.debug(f"Error processing {filename}: {e}")

            # Find elements above threshold
            min_count = int(len(filenames) * threshold)
            section_elements = [
                elem for elem, count in element_counter.items()
                if count >= min_count
            ]

            section_templates[pattern] = {
                'elements': section_elements,
                'threshold': threshold,
                'page_count': len(filenames),
                'total_elements_analyzed': len(element_counter)
            }

            self.stats['section_elements_found'] += len(section_elements)

            logger.info(f"  Found {len(section_elements)} section-specific elements in {pattern}")

        self.stats['section_groups'] = len(section_templates)

        return section_templates

    def analyze_templates(self) -> Dict[str, any]:
        """
        Run full template analysis (global + section-specific).

        Returns:
            Dict with complete template signature
        """
        logger.info(f"Starting template analysis for {self.ngo_name}")

        # Load URL manifest
        manifest = self.load_url_manifest()

        if not manifest:
            logger.warning("No URL manifest found, skipping template detection")
            return {'global': {}, 'sections': {}, 'stats': self.stats}

        # Group pages by URL path
        path_groups = self.group_pages_by_url_path(manifest)

        # Detect global template
        global_template = self.detect_global_template(manifest)

        # Detect section-specific templates
        section_templates = self.detect_section_templates(manifest, path_groups)

        # Combine results
        template_signature = {
            'ngo_name': self.ngo_name,
            'global': global_template,
            'sections': section_templates,
            'stats': self.stats
        }

        return template_signature

    def save_templates(self, templates: Dict[str, any]):
        """
        Save template signatures to JSON file.

        Args:
            templates: Template signature dict
        """
        try:
            with open(self.template_file, 'w', encoding='utf-8') as f:
                json.dump(templates, f, indent=2, ensure_ascii=False)

            logger.info(f"Template signatures saved to {self.template_file}")

        except Exception as e:
            logger.error(f"Error saving templates: {e}")

    def load_templates(self) -> Optional[Dict[str, any]]:
        """
        Load template signatures from JSON file.

        Returns:
            Template signature dict or None if not found
        """
        if not self.template_file.exists():
            return None

        try:
            with open(self.template_file, 'r', encoding='utf-8') as f:
                templates = json.load(f)

            logger.info(f"Loaded template signatures from {self.template_file}")
            return templates

        except Exception as e:
            logger.error(f"Error loading templates: {e}")
            return None

    def run(self, force_reanalyze: bool = False) -> Dict[str, any]:
        """
        Run template detection (load existing or analyze new).

        Args:
            force_reanalyze: If True, re-analyze even if templates exist

        Returns:
            Template signature dict
        """
        # Check if templates already exist
        if not force_reanalyze and self.template_file.exists():
            logger.info(f"Loading existing templates for {self.ngo_name}")
            templates = self.load_templates()
            if templates:
                return templates

        # Analyze templates
        templates = self.analyze_templates()

        # Save results
        self.save_templates(templates)

        return templates
