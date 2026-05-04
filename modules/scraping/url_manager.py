"""
URL Manager
Handles URL queue, deduplication, and normalization
"""

import logging
from urllib.parse import urlparse, urljoin, urlunparse, parse_qs, urlencode
from typing import Set, Dict, Optional, List, Tuple
import heapq
import hashlib
import re


logger = logging.getLogger(__name__)


class URLManager:
    """
    Manages URL queue with deduplication and prioritization.
    Tracks visited URLs and handles URL normalization.
    """

    def __init__(self, base_domain: str, max_depth: int = 3, max_pages: Optional[int] = None):
        """
        Initialize URL manager.

        Args:
            base_domain: Base domain to constrain crawling to
            max_depth: Maximum crawl depth
            max_pages: Maximum pages to scrape per site (None = unlimited)
        """
        self.base_domain = self._normalize_domain(base_domain)
        self.max_depth = max_depth
        self.max_pages = max_pages

        # URL tracking
        self.visited_urls: Set[str] = set()
        self.url_hashes: Set[str] = set()  # For duplicate detection
        self.failed_urls: Dict[str, str] = {}  # URL -> error message

        # Priority queue using heapq: (priority, depth, url, parent_url)
        self.url_queue: List = []

        # Statistics
        self.stats = {
            'total_queued': 0,
            'total_visited': 0,
            'total_failed': 0,
            'total_skipped': 0,
            'duplicate_count': 0,
            'skipped_depth': 0,
            'skipped_max_pages': 0,
            'skipped_excluded': 0,
            'skipped_invalid': 0
        }

    def _normalize_domain(self, domain: str) -> str:
        """
        Normalize domain for comparison.

        Args:
            domain: Domain string

        Returns:
            Normalized domain
        """
        parsed = urlparse(domain if '://' in domain else f'http://{domain}')
        return f"{parsed.netloc}".lower()

    def normalize_url(self, url: str, parent_url: Optional[str] = None) -> Optional[str]:
        """
        Normalize URL for consistent comparison.

        - Converts to absolute URL
        - Lowercases scheme and domain
        - Removes fragments
        - Sorts query parameters
        - Removes default ports
        - Removes trailing slashes (except for root)

        Args:
            url: URL to normalize
            parent_url: Parent URL for resolving relative URLs

        Returns:
            Normalized URL or None if invalid
        """
        try:
            # Handle relative URLs
            if parent_url and not url.startswith(('http://', 'https://', '//')):
                url = urljoin(parent_url, url)

            # Parse URL
            parsed = urlparse(url)

            # Skip non-HTTP(S) URLs
            if parsed.scheme not in ('http', 'https'):
                return None

            # NORMALIZE: Always use HTTPS (treat http and https as same for deduplication)
            # Most modern sites redirect http→https anyway
            scheme = 'https'
            netloc = parsed.netloc.lower()

            # Remove default ports
            # Note: We normalized to https, so only check for :443
            if netloc.endswith(':443'):
                netloc = netloc[:-4]
            elif netloc.endswith(':80'):
                # Also remove :80 (from http URLs before normalization)
                netloc = netloc[:-3]

            # Sort query parameters
            if parsed.query:
                params = parse_qs(parsed.query, keep_blank_values=True)
                sorted_query = urlencode(sorted(params.items()), doseq=True)
            else:
                sorted_query = ''

            # Remove fragment
            fragment = ''

            # Clean path - remove trailing slash unless it's root
            path = parsed.path
            if path != '/' and path.endswith('/'):
                path = path.rstrip('/')

            # Reconstruct URL
            normalized = urlunparse((
                scheme,
                netloc,
                path,
                parsed.params,
                sorted_query,
                fragment
            ))

            return normalized

        except Exception as e:
            logger.debug(f"Error normalizing URL {url}: {e}")
            return None

    def _url_hash(self, url: str) -> str:
        """
        Create hash of URL for duplicate detection.

        Args:
            url: URL to hash

        Returns:
            Hash string
        """
        return hashlib.md5(url.encode('utf-8')).hexdigest()

    def is_internal_url(self, url: str) -> bool:
        """
        Check if URL belongs to the base domain.

        Args:
            url: URL to check

        Returns:
            True if internal, False otherwise
        """
        try:
            parsed = urlparse(url)
            url_domain = parsed.netloc.lower()
            # Check if it's the same domain or subdomain
            return url_domain == self.base_domain or url_domain.endswith(f'.{self.base_domain}')
        except Exception as e:
            logger.debug(f"Error checking if URL is internal {url}: {e}")
            return False

    def should_exclude_url(self, url: str, exclusion_patterns: List[str]) -> bool:
        """
        Check if URL matches any exclusion pattern.

        Args:
            url: URL to check
            exclusion_patterns: List of patterns to exclude

        Returns:
            True if URL should be excluded
        """
        try:
            url_lower = url.lower()
            for pattern in exclusion_patterns:
                # Skip non-string patterns silently (already validated at config load)
                if not isinstance(pattern, str):
                    continue
                if pattern.lower() in url_lower:
                    self.stats['skipped_excluded'] += 1
                    logger.debug(f"URL excluded by pattern '{pattern}': {url}")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error in should_exclude_url for {url}: {e}")
            return False  # Don't exclude on error

    def get_url_priority(self, url: str, priority_patterns: Dict[str, List[str]]) -> int:
        """
        Determine priority of URL based on patterns.
        Lower number = higher priority.

        Args:
            url: URL to check
            priority_patterns: Dict with 'high', 'medium', 'low' pattern lists

        Returns:
            Priority level (0=high, 1=medium, 2=low, 3=default)
        """
        try:
            url_lower = url.lower()

            # Check high priority
            for pattern in priority_patterns.get('high', []):
                # Skip non-string patterns silently (already validated at config load)
                if not isinstance(pattern, str):
                    continue
                if pattern.lower() in url_lower:
                    return 0

            # Check medium priority
            for pattern in priority_patterns.get('medium', []):
                if not isinstance(pattern, str):
                    continue
                if pattern.lower() in url_lower:
                    return 1

            # Check low priority
            for pattern in priority_patterns.get('low', []):
                if not isinstance(pattern, str):
                    continue
                if pattern.lower() in url_lower:
                    return 2

            # Default priority
            return 3
        except Exception as e:
            logger.error(f"Error in get_url_priority for {url}: {e}")
            return 3  # Return default priority on error

    def add_url(self, url: str, depth: int = 0, parent_url: Optional[str] = None,
                priority: Optional[int] = None) -> bool:
        """
        Add URL to queue if not already visited.

        Args:
            url: URL to add
            depth: Current depth level
            parent_url: Parent URL
            priority: Priority level (lower = higher priority)

        Returns:
            True if added, False if skipped
        """
        # Normalize URL
        normalized_url = self.normalize_url(url, parent_url)
        if not normalized_url:
            self.stats['total_skipped'] += 1
            self.stats['skipped_invalid'] += 1
            logger.debug(f"Invalid URL skipped: {url}")
            return False

        # Check if already visited or in queue
        url_hash = self._url_hash(normalized_url)
        if url_hash in self.url_hashes:
            self.stats['duplicate_count'] += 1
            logger.debug(f"Duplicate URL skipped: {normalized_url}")
            return False

        # Check depth limit
        if depth > self.max_depth:
            self.stats['total_skipped'] += 1
            self.stats['skipped_depth'] += 1
            logger.info(f"URL exceeds max depth ({depth} > {self.max_depth}): {normalized_url}")
            return False

        # Check page limit (if set)
        if self.max_pages is not None and len(self.visited_urls) >= self.max_pages:
            self.stats['total_skipped'] += 1
            self.stats['skipped_max_pages'] += 1
            logger.warning(f"Max pages limit reached ({self.max_pages}): skipping {normalized_url}")
            return False

        # Add to queue using heappush for efficient priority queueing
        priority = priority if priority is not None else 3
        heapq.heappush(self.url_queue, (priority, depth, normalized_url, parent_url))
        self.url_hashes.add(url_hash)
        self.stats['total_queued'] += 1

        logger.debug(f"Added URL to queue (priority={priority}, depth={depth}): {normalized_url}")
        return True

    def get_next_url(self) -> Optional[Tuple[int, str, Optional[str]]]:
        """
        Get next URL from queue (highest priority first).

        Returns:
            Tuple of (depth, url, parent_url) or None if queue is empty
        """
        if not self.url_queue:
            return None

        # Use heappop for O(log n) retrieval (efficient for large queues)
        priority, depth, url, parent_url = heapq.heappop(self.url_queue)
        return (depth, url, parent_url)

    def mark_visited(self, url: str):
        """
        Mark URL as visited.

        Args:
            url: URL that was visited
        """
        normalized_url = self.normalize_url(url)
        if normalized_url:
            self.visited_urls.add(normalized_url)
            self.stats['total_visited'] += 1

    def mark_failed(self, url: str, error: str):
        """
        Mark URL as failed.

        Args:
            url: URL that failed
            error: Error message
        """
        normalized_url = self.normalize_url(url)
        if normalized_url:
            self.failed_urls[normalized_url] = error
            self.stats['total_failed'] += 1

    def is_visited(self, url: str) -> bool:
        """
        Check if URL has been visited.

        Args:
            url: URL to check

        Returns:
            True if visited
        """
        normalized_url = self.normalize_url(url)
        return normalized_url in self.visited_urls if normalized_url else False

    def queue_size(self) -> int:
        """Get current queue size."""
        return len(self.url_queue)

    def get_stats(self) -> Dict:
        """Get scraping statistics."""
        return {
            **self.stats,
            'queue_size': self.queue_size(),
            'visited_count': len(self.visited_urls),
            'failed_count': len(self.failed_urls)
        }

    def save_state(self) -> Dict:
        """
        Save current state for resumption.

        Returns:
            Dict containing state information
        """
        return {
            'base_domain': self.base_domain,
            'max_depth': self.max_depth,
            'max_pages': self.max_pages,
            'visited_urls': list(self.visited_urls),
            'url_hashes': list(self.url_hashes),
            'failed_urls': self.failed_urls,
            'url_queue': list(self.url_queue),
            'stats': self.stats
        }

    def load_state(self, state: Dict):
        """
        Load state from previous session.

        Args:
            state: State dict from save_state()
        """
        self.base_domain = state.get('base_domain', self.base_domain)
        self.max_depth = state.get('max_depth', self.max_depth)
        self.max_pages = state.get('max_pages', self.max_pages)
        self.visited_urls = set(state.get('visited_urls', []))
        self.url_hashes = set(state.get('url_hashes', []))
        self.failed_urls = state.get('failed_urls', {})
        self.url_queue = state.get('url_queue', [])
        # Convert to heap if needed
        heapq.heapify(self.url_queue)
        self.stats = state.get('stats', self.stats)

        logger.info(f"Loaded state: {len(self.visited_urls)} visited, {self.queue_size()} queued")
