"""
Module 2: Content Extraction & Cleaning
========================================

Transforms raw HTML data into clean text by removing website chrome
(headers, menus, footers, navigation) while preserving actual content.

Components:
-----------
- template_detector: Multi-level template detection (global + section-specific)
- extractor: Content extraction with trafilatura and BeautifulSoup fallback
- content_cleaner: Core cleaning utilities (link density, boilerplate removal)

Usage:
------
See scripts/clean_ngo_data.py for full pipeline integration.
"""

from .template_detector import TemplateDetector
from .extractor import ContentExtractor
from .content_cleaner import ContentCleaner

__all__ = ['TemplateDetector', 'ContentExtractor', 'ContentCleaner']
