"""URL normalization, identity keys, and crawl-scope rules.

Design notes (fixes for known v1 scraper bugs):
- We do NOT force https:// on fetch URLs (http-only sites broke before). Instead
  the dedup identity (`url_key`) is scheme-less and www-less, so http/https and
  www/non-www variants of the same page collapse to one frontier entry while the
  fetch still uses the URL as discovered.
- Scope is a list of explicit rules instead of a raw string-prefix on the seed
  (which silently dropped Extinction Rebellion / Fridays for Future):
    "domain:example.cz"                  host == example.cz or *.example.cz
    "prefix:greenpeace.org/czech"        scheme/www-insensitive path prefix
  The default scope is derived from the seed URL: its exact host (www stripped),
  plus a prefix rule when the seed itself points below the root.
"""

import hashlib
import re
from typing import Dict, List, Optional
from urllib.parse import (parse_qs, unquote, urlencode, urljoin, urlparse,
                          urlunparse)

from . import config


def normalize_url(url: str, parent_url: Optional[str] = None) -> Optional[str]:
    """Normalize for fetching: absolute, lowercase host, no fragment, sorted
    query, no default port, no trailing slash (except root). Scheme preserved."""
    try:
        url = url.strip()
        if not url:
            return None
        if parent_url and not url.startswith(("http://", "https://", "//")):
            url = urljoin(parent_url, url)
        if url.startswith("//"):
            parent_scheme = urlparse(parent_url).scheme if parent_url else "https"
            url = f"{parent_scheme or 'https'}:{url}"

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        netloc = parsed.netloc.lower()
        if netloc.endswith(":443") and parsed.scheme == "https":
            netloc = netloc[:-4]
        elif netloc.endswith(":80") and parsed.scheme == "http":
            netloc = netloc[:-3]
        if not netloc or "." not in netloc.split(":")[0]:
            return None

        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            query = urlencode(sorted(params.items()), doseq=True)
        else:
            query = ""

        path = parsed.path or "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        return urlunparse((parsed.scheme, netloc, path, parsed.params, query, ""))
    except Exception:
        return None


def url_key(normalized_url: str) -> str:
    """Scheme-less, www-less, percent-decoding identity for deduplication
    ('/domů' and '/dom%C5%AF' are the same page)."""
    parsed = urlparse(normalized_url)
    host = parsed.netloc
    if host.startswith("www."):
        host = host[4:]
    path = unquote(parsed.path)
    query = unquote(parsed.query)
    return urlunparse(("", host, path, parsed.params, query, "")).lstrip("/")


def host_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def registered_host(url: str) -> str:
    """Exact host of the URL with www stripped — used as the default scope unit
    and as the politeness (rate-limit) key. Deliberately NOT collapsed to an
    eTLD+1 guess: ci2.co.cz must not become co.cz."""
    return host_of(url)


def default_scope(seed_url: str) -> List[str]:
    parsed = urlparse(seed_url)
    host = host_of(seed_url)
    path = parsed.path.rstrip("/")
    rules = []
    if path and path not in ("", "/"):
        # Seed below root (e.g. greenpeace.org/czech): path-scoped by default
        rules.append(f"prefix:{host}{path}")
    else:
        rules.append(f"domain:{host}")
    return rules


def in_scope(url: str, scope_rules: List[str]) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    bare_host = host[4:] if host.startswith("www.") else host
    key = url_key(url)
    for rule in scope_rules:
        rule = rule.strip()
        if not rule:
            continue
        if rule.startswith("domain:"):
            dom = rule[7:].strip().lower()
            if dom.startswith("www."):
                dom = dom[4:]
            if bare_host == dom or bare_host.endswith("." + dom):
                return True
        elif rule.startswith("prefix:"):
            prefix = rule[7:].strip().lower()
            prefix = re.sub(r"^https?://", "", prefix)
            if prefix.startswith("www."):
                prefix = prefix[4:]
            if key.lower().startswith(prefix.rstrip("/")):
                return True
    return False


def exclusion_reason(url: str) -> Optional[str]:
    low = url.lower()
    for pattern in config.URL_EXCLUSIONS:
        if pattern in low:
            return f"pattern:{pattern}"
    return None


def file_extension(url: str) -> Optional[str]:
    """Extension if the URL points at a registrable file (PDF etc.), else None."""
    path = urlparse(url).path.lower()
    for ext in config.FILE_EXTENSIONS:
        if path.endswith(ext):
            return ext
    return None


def is_binary_noise(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in config.BINARY_NOISE_EXTENSIONS)


# Pagination/archive URLs are hubs regardless of path depth — new content
# surfaces there first
_PAGINATION_RE = re.compile(
    r"(/page/|[?&]page=|[?&]paged=|[?&]start=|[?&]offset=|/strana|[?&]stranka=|/archiv)",
    re.IGNORECASE,
)


def is_hub_url(url: str, max_path_depth: int = 2) -> bool:
    """Heuristic for listing/section pages worth re-fetching for link
    discovery: shallow paths (/, /aktuality, /aktuality/2024) and any
    pagination/archive URL. Deep article pages are archival snapshots."""
    parsed = urlparse(url)
    if _PAGINATION_RE.search(url):
        return True
    segments = [s for s in parsed.path.split("/") if s]
    return len(segments) <= max_path_depth


def sanitize_dirname(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = name.strip(". ")
    return name[:200] or "unnamed"


def url_to_filename(url: str, sequence: int, extension: str = ".html") -> str:
    """NNNNN_descriptive-slug.html — same convention as the v1 corpus."""
    parsed = urlparse(url)
    path = (parsed.path or "index").strip("/")
    if "/" in path:
        path = path.split("/")[-1]
    if "." in path:
        path = path.rsplit(".", 1)[0]
    path = re.sub(r"[^a-zA-Z0-9-]", "-", path)
    path = re.sub(r"-+", "-", path).strip("-")
    if len(path) > 50:
        path = path[:50].rstrip("-")
    if not path:
        path = "page"
    return f"{sequence:05d}_{path}{extension}"


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
