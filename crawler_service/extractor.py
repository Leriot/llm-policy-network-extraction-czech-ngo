"""HTML link extraction: hyperlinks for the network layer, file links for the
document registry, and internal frontier candidates."""

import logging
from typing import Dict, List, Tuple

from bs4 import BeautifulSoup

from . import urlnorm

logger = logging.getLogger(__name__)


def parse_html(content: bytes, encoding: str) -> BeautifulSoup:
    try:
        html = content.decode(encoding, errors="replace")
    except (LookupError, TypeError):
        html = content.decode("utf-8", errors="replace")
    return BeautifulSoup(html, "lxml")


def extract_links(soup: BeautifulSoup, page_url: str, scope_rules: List[str]
                  ) -> Tuple[List[Dict], List[Dict]]:
    """Return (hyperlinks, file_links).

    hyperlinks: [{url, text, type internal|external}] — every <a href> resolved
    file_links: [{url, text, type, extension}] — downloadable files (registered, not fetched)
    Internal/external is decided by the org's scope rules, not by raw domain,
    so path-scoped orgs (greenpeace.org/czech) classify correctly.
    """
    hyperlinks: List[Dict] = []
    file_links: List[Dict] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        raw = a["href"]
        normalized = urlnorm.normalize_url(raw, parent_url=page_url)
        if not normalized:
            continue
        if urlnorm.is_binary_noise(normalized):
            continue
        key = urlnorm.url_key(normalized)
        if key in seen:
            # still counted as an occurrence downstream via add_links_batch dedup;
            # skipping here keeps one entry per (page, target)
            continue
        seen.add(key)

        text = a.get_text(" ", strip=True)[:500]
        link_type = "internal" if urlnorm.in_scope(normalized, scope_rules) else "external"
        ext = urlnorm.file_extension(normalized)
        if ext:
            file_links.append({"url": normalized, "text": text, "type": link_type,
                               "extension": ext})
        else:
            hyperlinks.append({"url": normalized, "text": text, "type": link_type})

    return hyperlinks, file_links


def extract_title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return soup.title.string.strip()[:300]
    return ""
