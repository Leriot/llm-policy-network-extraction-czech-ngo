"""Fetch engines: plain HTTP (default) and optional Playwright browser mode,
plus the shared per-domain politeness limiter."""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import httpx

from . import config, urlnorm

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    ok: bool
    url: str                      # requested URL
    final_url: str = ""           # after redirects
    status_code: Optional[int] = None
    content: bytes = b""
    content_type: str = ""
    encoding: str = "utf-8"
    error: str = ""
    engine: str = "http"
    duration_ms: int = 0


class DomainRateLimiter:
    """Serializes requests per registered host with a minimum delay.
    Shared across all org workers so orgs on the same domain stay polite."""

    def __init__(self, delay: float = config.DELAY_SECONDS):
        self.delay = delay
        self._locks: Dict[str, asyncio.Lock] = {}
        self._last: Dict[str, float] = {}

    async def wait(self, url: str, extra_delay: Optional[float] = None):
        host = urlnorm.registered_host(url)
        lock = self._locks.setdefault(host, asyncio.Lock())
        # jittered delay: robots.txt crawl-delay is a hard floor, then a
        # random spread on top so requests don't tick like a metronome
        delay = max(self.delay, extra_delay or 0) + random.uniform(
            0, config.DELAY_JITTER_SECONDS)
        async with lock:
            elapsed = time.monotonic() - self._last.get(host, 0)
            if elapsed < delay:
                await asyncio.sleep(delay - elapsed)
            self._last[host] = time.monotonic()


class HttpFetcher:
    def __init__(self):
        common = dict(
            headers={"User-Agent": config.USER_AGENT,
                     "From": config.CONTACT_EMAIL},
            timeout=httpx.Timeout(config.TIMEOUT_SECONDS),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self.client = httpx.AsyncClient(**common)
        # Fallback for servers with broken TLS chains (missing intermediate
        # certs — common on Czech municipal/corporate sites, e.g. brno.cz).
        # Public-content research crawl: availability beats strict verification.
        self.insecure_client = httpx.AsyncClient(verify=False, **common)

    async def close(self):
        await self.client.aclose()
        await self.insecure_client.aclose()

    @staticmethod
    def _is_tls_error(error: str) -> bool:
        low = error.lower()
        return "certificate" in low or "ssl" in low or "tls" in low

    async def fetch(self, url: str, accept_any_status: bool = False) -> FetchResult:
        """accept_any_status: treat 4xx HTML responses with a body as content —
        for sites whose CMS sends 404 on every page incl. real ones
        (pakt-starostu.cz). Identical error pages collapse via content dedup."""
        start = time.monotonic()
        last_error, last_status = "", None
        client = self.client
        for attempt in range(config.MAX_RETRIES + 1):
            if attempt:
                await asyncio.sleep(min(config.ERROR_DELAY_SECONDS * attempt, 60))
            try:
                resp = await client.get(url)
                acceptable = resp.status_code == 200 or (
                    accept_any_status and 400 <= resp.status_code < 500
                    and resp.status_code != 429 and len(resp.content) > 0)
                if acceptable:
                    encoding = resp.encoding or "utf-8"
                    return FetchResult(
                        ok=True, url=url, final_url=str(resp.url),
                        status_code=resp.status_code, content=resp.content,
                        content_type=(resp.headers.get("content-type") or "").lower(),
                        encoding=encoding, engine="http",
                        duration_ms=int((time.monotonic() - start) * 1000),
                    )
                last_status = resp.status_code
                last_error = f"HTTP {resp.status_code}"
                if resp.status_code not in RETRYABLE_STATUS:
                    break
            except httpx.TimeoutException:
                last_error = "timeout"
            except httpx.HTTPError as e:
                last_error = f"{type(e).__name__}: {e}"
                # broken cert chain -> retry immediately without verification
                if client is self.client and self._is_tls_error(last_error):
                    client = self.insecure_client
                    logger.info(f"TLS fallback (unverified) for {url}: {last_error}")
                    continue
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                break
        return FetchResult(
            ok=False, url=url, final_url=url, status_code=last_status,
            error=last_error, engine="http",
            duration_ms=int((time.monotonic() - start) * 1000),
        )


class BrowserFetcher:
    """Playwright-based fetch for JS-rendered sites. Lazy: only started when an
    org has engine='browser'. Requires `pip install playwright && playwright
    install chromium` (bundled in the Docker image)."""

    def __init__(self):
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def _ensure_started(self):
        async with self._lock:
            if self._browser is not None:
                return
            from playwright.async_api import async_playwright  # lazy import
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            logger.info("Playwright chromium started")

    async def close(self):
        async with self._lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._pw:
                await self._pw.stop()
                self._pw = None

    async def fetch(self, url: str, accept_any_status: bool = False) -> FetchResult:
        start = time.monotonic()
        try:
            await self._ensure_started()
        except Exception as e:
            return FetchResult(ok=False, url=url, final_url=url, engine="browser",
                               error=f"playwright unavailable: {e}")
        context = None
        try:
            context = await self._browser.new_context(
                user_agent=config.USER_AGENT,
                extra_http_headers={"From": config.CONTACT_EMAIL})
            page = await context.new_page()
            resp = await page.goto(url, timeout=int(config.TIMEOUT_SECONDS * 1000),
                                   wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass  # networkidle is best-effort; DOM content is already there
            status = resp.status if resp else None
            acceptable = status == 200 or status is None or (
                accept_any_status and 400 <= status < 500 and status != 429)
            if not acceptable:
                return FetchResult(ok=False, url=url, final_url=page.url,
                                   status_code=status, error=f"HTTP {status}",
                                   engine="browser",
                                   duration_ms=int((time.monotonic() - start) * 1000))
            html = await page.content()
            return FetchResult(
                ok=True, url=url, final_url=page.url, status_code=status or 200,
                content=html.encode("utf-8"), content_type="text/html",
                encoding="utf-8", engine="browser",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            return FetchResult(ok=False, url=url, final_url=url, engine="browser",
                               error=f"{type(e).__name__}: {e}",
                               duration_ms=int((time.monotonic() - start) * 1000))
        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
