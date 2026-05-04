"""
Robots.txt Handler
Manages robots.txt compliance for ethical web scraping
"""

import logging
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
from typing import Dict, Optional, Set
import time
import requests


logger = logging.getLogger(__name__)


class RobotsHandler:
    """
    Handles robots.txt parsing and compliance checking.
    Caches robots.txt files per domain to avoid repeated requests.
    """

    def __init__(self, user_agent: str):
        """
        Initialize the robots.txt handler.

        Args:
            user_agent: User agent string to check permissions for
        """
        self.user_agent = user_agent
        self.parsers: Dict[str, RobotFileParser] = {}
        self.last_fetch: Dict[str, float] = {}
        self.cache_duration = 3600  # Cache robots.txt for 1 hour
        self.logged_delays: Set[str] = set()  # Track domains we've logged delays for

    def _get_robots_url(self, url: str) -> str:
        """
        Get the robots.txt URL for a given URL.

        Args:
            url: Any URL from the domain

        Returns:
            The robots.txt URL for that domain
        """
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def _get_domain(self, url: str) -> str:
        """
        Extract domain from URL.

        Args:
            url: Full URL

        Returns:
            Domain (scheme + netloc)
        """
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _fetch_robots_txt(self, domain: str) -> Optional[RobotFileParser]:
        """
        Fetch and parse robots.txt for a domain.

        Args:
            domain: Domain to fetch robots.txt for

        Returns:
            RobotFileParser instance or None if fetch failed
        """
        robots_url = urljoin(domain, '/robots.txt')

        try:
            logger.info(f"Fetching robots.txt from {robots_url}")
            parser = RobotFileParser()
            parser.set_url(robots_url)

            # Fetch with timeout
            response = requests.get(robots_url, timeout=10)

            if response.status_code == 200:
                # Parse the content
                lines = response.text.splitlines()
                parser.parse(lines)
                logger.info(f"Successfully parsed robots.txt for {domain}")
                return parser
            elif response.status_code == 404:
                # No robots.txt means everything is allowed
                logger.info(f"No robots.txt found for {domain} (404) - assuming all allowed")
                # Create empty parser (allows everything)
                parser.parse([])
                return parser
            else:
                logger.warning(f"Unexpected status {response.status_code} for {robots_url}")
                # On error, be conservative and create empty parser
                parser.parse([])
                return parser

        except requests.RequestException as e:
            logger.error(f"Error fetching robots.txt from {robots_url}: {e}")
            # On network error, create empty parser to allow scraping
            # (being conservative would block all scraping on network errors)
            parser = RobotFileParser()
            parser.parse([])
            return parser
        except Exception as e:
            logger.error(f"Unexpected error parsing robots.txt from {robots_url}: {e}")
            parser = RobotFileParser()
            parser.parse([])
            return parser

    def can_fetch(self, url: str) -> bool:
        """
        Check if the URL can be fetched according to robots.txt.

        Args:
            url: URL to check

        Returns:
            True if fetching is allowed, False otherwise
        """
        domain = self._get_domain(url)
        current_time = time.time()

        # Check if we need to refresh the cached robots.txt
        if domain not in self.parsers or \
           (current_time - self.last_fetch.get(domain, 0)) > self.cache_duration:

            parser = self._fetch_robots_txt(domain)
            if parser:
                self.parsers[domain] = parser
                self.last_fetch[domain] = current_time
            else:
                # If we couldn't fetch, keep old parser or create permissive one
                if domain not in self.parsers:
                    parser = RobotFileParser()
                    parser.parse([])
                    self.parsers[domain] = parser

        # Check if fetch is allowed
        parser = self.parsers.get(domain)
        if parser:
            allowed = parser.can_fetch(self.user_agent, url)
            if not allowed:
                logger.warning(f"robots.txt disallows fetching: {url}")
            return allowed

        # Default to allowing if no parser (shouldn't happen)
        return True

    def get_crawl_delay(self, url: str) -> Optional[float]:
        """
        Get the crawl delay specified in robots.txt for this domain.

        Args:
            url: URL to check crawl delay for

        Returns:
            Crawl delay in seconds, or None if not specified
        """
        domain = self._get_domain(url)

        # Ensure we have the robots.txt loaded
        if domain not in self.parsers:
            self.can_fetch(url)  # This will load the robots.txt

        parser = self.parsers.get(domain)
        if parser:
            try:
                delay = parser.crawl_delay(self.user_agent)
                if delay:
                    # Only log once per domain to avoid noise
                    if domain not in self.logged_delays:
                        logger.info(f"Crawl delay for {domain}: {delay} seconds")
                        self.logged_delays.add(domain)
                    return float(delay)
            except Exception as e:
                logger.debug(f"Error getting crawl delay for {domain}: {e}")

        return None

    def get_request_rate(self, url: str) -> Optional[tuple]:
        """
        Get the request rate specified in robots.txt.

        Args:
            url: URL to check request rate for

        Returns:
            Tuple of (requests, seconds) or None if not specified
        """
        domain = self._get_domain(url)

        # Ensure we have the robots.txt loaded
        if domain not in self.parsers:
            self.can_fetch(url)

        parser = self.parsers.get(domain)
        if parser:
            try:
                rate = parser.request_rate(self.user_agent)
                if rate:
                    logger.info(f"Request rate for {domain}: {rate.requests}/{rate.seconds} seconds")
                    return (rate.requests, rate.seconds)
            except Exception as e:
                logger.debug(f"Error getting request rate for {domain}: {e}")

        return None

    def clear_cache(self):
        """Clear the robots.txt cache."""
        self.parsers.clear()
        self.last_fetch.clear()
        logger.info("Robots.txt cache cleared")
