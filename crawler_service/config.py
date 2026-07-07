"""Environment-driven configuration for the crawler service."""

import os
from pathlib import Path


def _env(name: str, default):
    val = os.environ.get(name)
    if val is None:
        return default
    if isinstance(default, bool):
        return val.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(val)
    if isinstance(default, float):
        return float(val)
    return val


# Storage layout: DATA_DIR/raw/<org_dir>/pages/NNNNN_slug.html, DB at DATA_DIR/crawler.db
DATA_DIR = Path(_env("CRAWLER_DATA_DIR", "data"))
DB_PATH = Path(_env("CRAWLER_DB_PATH", str(DATA_DIR / "crawler.db")))

# Transparency: the crawler announces who is crawling, why, and where to read
# more / request exclusion. Sent in the User-Agent and a From: header.
CONTACT_EMAIL = _env("CRAWLER_CONTACT_EMAIL", "498079@mail.muni.cz")
INFO_URL = _env(
    "CRAWLER_INFO_URL",
    "https://github.com/Leriot/llm-policy-network-extraction-czech-ngo"
    "/blob/main/CRAWLER.md",
)
# Robots.txt can target us with: User-agent: AcademicResearch-COMPONNetworkAnalysis
USER_AGENT = _env(
    "CRAWLER_USER_AGENT",
    "AcademicResearch-COMPONNetworkAnalysis/2.0 "
    "(academic research crawl, wave 2 - expanded update of the 2025/26 wave; "
    f"+{INFO_URL}; {CONTACT_EMAIL}; opt-out via robots.txt or e-mail)",
)

# Politeness. Delay per registered domain is randomized in
# [DELAY, DELAY + DELAY_JITTER] each request — a steady metronome cadence is
# exactly what rate limiters treat as abusive; jitter is the polite pattern.
DELAY_SECONDS = _env("CRAWLER_DELAY", 2.0)
DELAY_JITTER_SECONDS = _env("CRAWLER_DELAY_JITTER", 3.0)
ERROR_DELAY_SECONDS = _env("CRAWLER_ERROR_DELAY", 10.0)
TIMEOUT_SECONDS = _env("CRAWLER_TIMEOUT", 30.0)
MAX_RETRIES = _env("CRAWLER_MAX_RETRIES", 3)
RESPECT_ROBOTS = _env("CRAWLER_RESPECT_ROBOTS", True)

# Concurrency: orgs crawled in parallel, each org serial (politeness per domain)
MAX_CONCURRENT_ORGS = _env("CRAWLER_MAX_CONCURRENT_ORGS", 6)

# Crawl behaviour
MAX_DEPTH_DEFAULT = _env("CRAWLER_MAX_DEPTH", 10)
MIN_CONTENT_LENGTH = _env("CRAWLER_MIN_CONTENT_LENGTH", 100)
FLAG_THRESHOLD_DEFAULT = _env("CRAWLER_FLAG_THRESHOLD", 50000)  # dashboard flag only, never stops

# Dev/testing only: stop an org after N page saves in one session (0 = unlimited)
DEV_MAX_PAGES = _env("CRAWLER_DEV_MAX_PAGES", 0)

# Safety valve (user decision): if the DB file exceeds this many GB, pause all
# crawling and raise an alert — a guaranteed decision point instead of a full
# disk. 0 disables.
DB_PAUSE_GB = _env("CRAWLER_DB_PAUSE_GB", 45.0)

# Connection-failure cooldown: after this many consecutive connection-level
# failures (no HTTP response — refusal, DNS blip, timeout) an org backs off and
# is auto-resumed after COOLDOWN_MINUTES. Self-healing, so a transient DNS or
# network hiccup no longer parks an org permanently.
CONN_FAIL_THRESHOLD = _env("CRAWLER_CONN_FAIL_THRESHOLD", 12)
COOLDOWN_MINUTES = _env("CRAWLER_COOLDOWN_MINUTES", 45)

# Web UI
WEB_HOST = _env("CRAWLER_WEB_HOST", "0.0.0.0")
WEB_PORT = _env("CRAWLER_WEB_PORT", 8055)

# URL patterns excluded from the frontier. Exclusions are RECORDED in the urls
# table (status=excluded, reason) so nothing is silently dropped.
URL_EXCLUSIONS = [
    "/wp-admin/", "/wp-login", "/wp-json/", "/xmlrpc.php",
    "/admin/", "/login", "/signin", "/register",
    "/cart/", "/checkout/", "/account/",
    "/feed/", "/comments/feed",
    "javascript:", "mailto:", "tel:",
    "?share=", "&share=", "?replytocom=", "&replytocom=",
    "/cdn-cgi/",
]

# Extensions recorded into the file-link registry (NOT downloaded)
FILE_EXTENSIONS = [
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".epub", ".csv",
    ".zip", ".rar", ".7z",
    ".mp3", ".mp4", ".avi", ".mov",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".bmp",
]

# Extensions we never crawl as pages but also don't register as documents
BINARY_NOISE_EXTENSIONS = [".css", ".js", ".woff", ".woff2", ".ttf", ".eot", ".map"]
