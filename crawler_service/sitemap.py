"""Sitemap discovery and recursive parsing (sitemapindex + urlset, .xml/.xml.gz)."""

import asyncio
import gzip
import logging
import random
from typing import List, Optional, Set

import httpx
from lxml import etree

logger = logging.getLogger(__name__)

MAX_SITEMAPS = 200          # safety against sitemapindex loops
MAX_URLS = 500_000


async def discover_and_parse(client: httpx.AsyncClient, base_url: str,
                             robots_sitemaps: List[str],
                             limiter=None) -> List[str]:
    """Return all page URLs found via sitemaps for a site.

    limiter: optional DomainRateLimiter — sitemap files are regular requests
    and must be paced like any other (a back-to-back sitemap burst is what
    got us rate-limited by spolchemie.cz)."""
    candidates = list(robots_sitemaps)
    root = base_url.rstrip("/")
    for common in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml"):
        candidates.append(root + common)

    urls: List[str] = []
    seen_maps: Set[str] = set()
    queue = list(dict.fromkeys(candidates))

    while queue and len(seen_maps) < MAX_SITEMAPS and len(urls) < MAX_URLS:
        sm_url = queue.pop(0)
        if sm_url in seen_maps:
            continue
        seen_maps.add(sm_url)
        try:
            if limiter is not None:
                await limiter.wait(sm_url)
            else:
                await asyncio.sleep(1 + random.uniform(0, 1))
            resp = await client.get(sm_url, timeout=30)
            if resp.status_code != 200:
                continue
            content = resp.content
            if sm_url.endswith(".gz") or content[:2] == b"\x1f\x8b":
                try:
                    content = gzip.decompress(content)
                except Exception:
                    continue
            try:
                tree = etree.fromstring(content)
            except etree.XMLSyntaxError:
                continue
            tag = etree.QName(tree.tag).localname if isinstance(tree.tag, str) else ""
            ns = {"sm": tree.nsmap.get(None) or "http://www.sitemaps.org/schemas/sitemap/0.9"}
            if tag == "sitemapindex":
                for loc in tree.findall(".//sm:sitemap/sm:loc", ns):
                    if loc.text:
                        queue.append(loc.text.strip())
            elif tag == "urlset":
                for loc in tree.findall(".//sm:url/sm:loc", ns):
                    if loc.text:
                        urls.append(loc.text.strip())
            logger.info(f"sitemap {sm_url}: cumulative {len(urls)} urls")
        except Exception as e:
            logger.debug(f"sitemap fetch failed {sm_url}: {e}")

    return urls
