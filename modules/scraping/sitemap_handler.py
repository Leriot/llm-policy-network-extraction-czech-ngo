
"""
Sitemap Handler
Parses XML sitemaps to discover and filter URLs efficiently.
"""

import logging
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin
from typing import List, Dict, Optional, Set
from datetime import datetime
import gzip
import io

logger = logging.getLogger(__name__)

class SitemapHandler:
    """
    Handles fetching and parsing of XML sitemaps.
    Supports sitemap indexes and filtering by lastmod date.
    """

    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent})
        
        # XML Namespaces often found in sitemaps
        self.namespaces = {
            'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9',
            'image': 'http://www.google.com/schemas/sitemap-image/1.1',
            'news': 'http://www.google.com/schemas/sitemap-news/0.9'
        }

    def fetch_sitemap(self, url: str) -> Optional[bytes]:
        """Fetch sitemap content, handling gzip if necessary."""
        try:
            logger.info(f"Fetching sitemap: {url}")
            response = self.session.get(url, timeout=30)
            
            if response.status_code == 200:
                if url.endswith('.gz') or response.headers.get('content-type') == 'application/x-gzip':
                    return gzip.decompress(response.content)
                return response.content
            else:
                logger.warning(f"Failed to fetch sitemap {url}: HTTP {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching sitemap {url}: {e}")
            return None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse sitemap date string (W3C format)."""
        if not date_str:
            return None
        try:
            # Handle various formats: YYYY-MM-DD, YYYY-MM-DDThh:mm:ssTZD
            # Simple truncation to date part often works for filtering
            if 'T' in date_str:
                date_str = date_str.split('T')[0]
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return None

    def parse_sitemap(self, url: str, min_date: Optional[datetime] = None) -> List[Dict]:
        """
        Recursively parse sitemap (handling indexes) and return filtered URLs.
        
        Args:
            url: Sitemap URL
            min_date: Optional datetime to filter by lastmod (inclusive)
            
        Returns:
            List of dicts with 'url' and 'lastmod'
        """
        content = self.fetch_sitemap(url)
        if not content:
            return []

        urls = []
        try:
            root = ET.fromstring(content)
            
            # Check if it's a sitemap index
            # Note: ElementTree searches need namespace if present
            # We try both with and without namespace for robustness
            
            # Try to detect default namespace
            ns = {}
            if '}' in root.tag:
                ns_url = root.tag.split('}')[0].strip('{')
                ns = {'ns': ns_url}
                tag_prefix = 'ns:'
            else:
                tag_prefix = ''

            # 1. Handle Sitemap Index
            if 'sitemapindex' in root.tag:
                logger.info(f"Found sitemap index: {url}")
                sitemaps = root.findall(f'{tag_prefix}sitemap', ns)
                for sm in sitemaps:
                    loc = sm.find(f'{tag_prefix}loc', ns)
                    if loc is not None and loc.text:
                        # Check lastmod of sub-sitemap if available to skip entire chunks
                        lastmod = sm.find(f'{tag_prefix}lastmod', ns)
                        if lastmod is not None and lastmod.text and min_date:
                            sm_date = self._parse_date(lastmod.text)
                            if sm_date and sm_date < min_date:
                                logger.debug(f"Skipping old sitemap: {loc.text}")
                                continue
                        
                        # Recursively parse sub-sitemap
                        urls.extend(self.parse_sitemap(loc.text.strip(), min_date))
            
            # 2. Handle Urlset (Standard Sitemap)
            elif 'urlset' in root.tag:
                logger.info(f"Parsing urlset: {url}")
                url_elements = root.findall(f'{tag_prefix}url', ns)
                
                for url_elem in url_elements:
                    loc = url_elem.find(f'{tag_prefix}loc', ns)
                    if loc is not None and loc.text:
                        page_url = loc.text.strip()
                        lastmod = url_elem.find(f'{tag_prefix}lastmod', ns)
                        
                        page_date = None
                        if lastmod is not None and lastmod.text:
                            page_date = self._parse_date(lastmod.text)
                        
                        # Filter by date
                        if min_date and page_date:
                            if page_date < min_date:
                                continue
                        
                        urls.append({
                            'url': page_url,
                            'lastmod': page_date,
                            'priority': 0 # High priority for sitemap URLs
                        })
                        
        except ET.ParseError as e:
            logger.error(f"XML Parse Error in {url}: {e}")
        except Exception as e:
            logger.error(f"Error parsing sitemap {url}: {e}")

        return urls

    def discover_sitemaps(self, robots_txt_content: str) -> List[str]:
        """Extract sitemap URLs from robots.txt content."""
        sitemaps = []
        for line in robots_txt_content.splitlines():
            if line.strip().lower().startswith('sitemap:'):
                parts = line.split(':', 1)
                if len(parts) > 1:
                    sitemaps.append(parts[1].strip())
        return sitemaps
