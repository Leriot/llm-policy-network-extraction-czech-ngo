"""
Module 1: Scraping

Collects raw web content from NGO websites.

Input:
    - config/ngo_config.csv (NGO URLs)
    - config/scraping_rules.yaml (scraping parameters)

Output:
    - data/raw/{ngo}/{session}/pages/*.html
    - data/raw/{ngo}/{session}/documents/*.pdf
    - data/raw/{ngo}/{session}/links.json
    - data/raw/{ngo}/{session}/metadata.json
    - data/raw/{ngo}/{session}/page_metadata.jsonl

See modules/scraping/README.md for detailed documentation.
"""

from .scraper import NGOScraper
from .session_manager import SessionManager
from .content_extractor import ContentExtractor
from .url_manager import URLManager
from .robots_handler import RobotsHandler
from .sitemap_handler import SitemapHandler
from .storage import StorageManager

__all__ = [
    'NGOScraper',
    'SessionManager',
    'ContentExtractor',
    'URLManager',
    'RobotsHandler',
    'SitemapHandler',
    'StorageManager',
]
