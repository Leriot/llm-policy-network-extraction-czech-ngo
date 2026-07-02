"""robots.txt handling with per-host caching, plus sitemap URL discovery."""

import logging
from typing import Dict, List, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from . import config

logger = logging.getLogger(__name__)


class RobotsCache:
    def __init__(self, user_agent: str = config.USER_AGENT):
        self.user_agent = user_agent
        self._parsers: Dict[str, Optional[RobotFileParser]] = {}
        self._sitemaps: Dict[str, List[str]] = {}

    async def _load(self, client: httpx.AsyncClient, url: str) -> str:
        parsed = urlparse(url)
        host_key = f"{parsed.scheme}://{parsed.netloc}"
        if host_key in self._parsers:
            return host_key
        robots_url = f"{host_key}/robots.txt"
        parser = RobotFileParser()
        sitemaps: List[str] = []
        try:
            resp = await client.get(robots_url, timeout=15)
            if resp.status_code == 200 and resp.text:
                lines = resp.text.splitlines()
                parser.parse(lines)
                sitemaps = [
                    line.split(":", 1)[1].strip()
                    for line in lines
                    if line.lower().startswith("sitemap:")
                ]
            else:
                parser = None  # no robots.txt -> everything allowed
        except Exception as e:
            logger.debug(f"robots.txt unavailable for {host_key}: {e}")
            parser = None
        self._parsers[host_key] = parser
        self._sitemaps[host_key] = sitemaps
        return host_key

    async def can_fetch(self, client: httpx.AsyncClient, url: str) -> bool:
        if not config.RESPECT_ROBOTS:
            return True
        host_key = await self._load(client, url)
        parser = self._parsers.get(host_key)
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True

    async def crawl_delay(self, client: httpx.AsyncClient, url: str) -> Optional[float]:
        host_key = await self._load(client, url)
        parser = self._parsers.get(host_key)
        if parser is None:
            return None
        try:
            delay = parser.crawl_delay(self.user_agent)
            return float(delay) if delay else None
        except Exception:
            return None

    async def sitemap_urls(self, client: httpx.AsyncClient, url: str) -> List[str]:
        host_key = await self._load(client, url)
        return list(self._sitemaps.get(host_key, []))
