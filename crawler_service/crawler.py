"""Per-org crawl loop with a fully persistent, transactional frontier.

Every discovered URL becomes a row in `urls` immediately (including excluded
ones, with a reason — nothing is silently dropped). A crash at any point loses
at most the single in-flight page; `release_stale_claims()` returns it to the
frontier on restart.

Refetch semantics (the "news page 1 changed" case): URLs imported from the v1
corpus or re-queued for refresh carry refetch=1. They are fetched again for
LINK DISCOVERY, but a new snapshot file is only written when the content hash
actually changed — unchanged pages cost one request, zero storage.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from . import config, extractor, sitemap, urlnorm
from .db import Database
from .fetcher import BrowserFetcher, DomainRateLimiter, FetchResult, HttpFetcher
from .robots import RobotsCache

logger = logging.getLogger(__name__)


class OrgCrawler:
    def __init__(self, db: Database, org_id: str, limiter: DomainRateLimiter,
                 http_fetcher: HttpFetcher, browser_fetcher: BrowserFetcher,
                 robots: RobotsCache):
        self.db = db
        self.org_id = org_id
        self.limiter = limiter
        self.http_fetcher = http_fetcher
        self.browser_fetcher = browser_fetcher
        self.robots = robots
        self.session_saved = 0
        self.session_processed = 0
        self.consecutive_conn_failures = 0

    # ------------------------------------------------------------------ setup
    def _org(self):
        return self.db.get_org(self.org_id)

    def _scope(self, org) -> List[str]:
        try:
            rules = json.loads(org["scope"] or "[]")
        except json.JSONDecodeError:
            rules = []
        if not rules and org["seed_url"]:
            rules = urlnorm.default_scope(org["seed_url"])
        return rules

    def _pages_dir(self, org) -> Path:
        d = config.DATA_DIR / "raw" / org["dir_name"] / "pages"
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def _seed_frontier(self, org):
        """Ensure the seed URL is queued; run sitemap discovery when stale.
        Sitemaps also run for imported orgs — they are the cheapest way to
        find articles published since the last crawl."""
        seed = urlnorm.normalize_url(org["seed_url"])
        if not seed:
            raise ValueError(f"invalid seed URL: {org['seed_url']!r}")
        self.db.add_url(self.org_id, seed, urlnorm.url_key(seed), depth=0,
                        parent_url=None, source="seed")

        marker = f"sitemap:{self.org_id}"
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
        last = self.db.query_one("SELECT value FROM kv WHERE key=?", (marker,))
        if last and last["value"] > week_ago:
            return

        scope = self._scope(org)
        try:
            robots_maps = await self.robots.sitemap_urls(self.http_fetcher.client, seed)
            urls = await sitemap.discover_and_parse(
                self.http_fetcher.client, seed, robots_maps, limiter=self.limiter)
            rows, seen = [], set()
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for u in urls:
                normalized = urlnorm.normalize_url(u)
                if not normalized or not urlnorm.in_scope(normalized, scope):
                    continue
                if urlnorm.file_extension(normalized) or urlnorm.is_binary_noise(normalized):
                    continue
                key = urlnorm.url_key(normalized)
                if key in seen:
                    continue
                seen.add(key)
                rows.append((self.org_id, normalized, key, "pending", None,
                             "sitemap", 0, None, ts))
            if rows:
                # bulk insert — big-city sitemaps can list 100k+ URLs
                self.db.bulk_execute(
                    """INSERT OR IGNORE INTO urls (org_id, url, url_key, status,
                           reason, source, depth, parent_url, discovered_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows)
                self.db.bulk_commit()
                self.db.add_event(self.org_id, "info",
                                  f"sitemap: {len(rows)} URLs queued")
            with self.db.lock:
                self.db.conn.execute(
                    "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
                    (marker, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
                self.db.conn.commit()
        except Exception as e:
            self.db.add_event(self.org_id, "warning", f"sitemap discovery failed: {e}")

    # ------------------------------------------------------------------ loop
    async def run(self):
        org = self._org()
        if not org or not org["seed_url"]:
            self.db.add_event(self.org_id, "error", "cannot start: no seed URL")
            self.db.set_org_fields(self.org_id, state="error")
            return
        try:
            await self._seed_frontier(org)
        except Exception as e:
            self.db.add_event(self.org_id, "error", f"seeding failed: {e}")
            self.db.set_org_fields(self.org_id, state="error")
            return

        self.db.add_event(self.org_id, "info", "crawl started")
        check_counter = 0
        while True:
            # honor pause/stop requested via the dashboard
            check_counter += 1
            if check_counter % 5 == 1:
                state = (await asyncio.to_thread(self._org))["state"]
                if state != "running":
                    self.db.add_event(self.org_id, "info", f"stopping (state={state})")
                    return

            row = await asyncio.to_thread(self.db.claim_next_url, self.org_id)
            if row is None:
                self.db.set_org_fields(self.org_id, state="done")
                self.db.add_event(self.org_id, "info", "frontier exhausted — org done")
                return

            try:
                await self._process(row)
            except Exception as e:
                logger.exception(f"[{self.org_id}] error processing {row['url']}")
                self.db.finish_url(row["id"], "failed",
                                   last_error=f"internal: {type(e).__name__}: {e}")
                self.db.add_event(self.org_id, "error",
                                  f"internal error on {row['url']}: {e}")

            self.session_processed += 1
            if config.DEV_MAX_PAGES and self.session_processed >= config.DEV_MAX_PAGES:
                self.db.set_org_fields(self.org_id, state="paused")
                self.db.add_event(self.org_id, "warning",
                                  f"dev page limit {config.DEV_MAX_PAGES} reached — paused")
                return

    # ------------------------------------------------------------------ page
    async def _process(self, row):
        org = await asyncio.to_thread(self._org)
        scope = self._scope(org)
        url = row["url"]

        # robots.txt (recorded, not silent)
        if not await self.robots.can_fetch(self.http_fetcher.client, url):
            await asyncio.to_thread(self.db.finish_url, row["id"], "excluded", reason="robots_txt")
            return

        crawl_delay = await self.robots.crawl_delay(self.http_fetcher.client, url)
        await self.limiter.wait(url, extra_delay=crawl_delay)

        fetcher = self.browser_fetcher if org["engine"] == "browser" else self.http_fetcher
        result: FetchResult = await fetcher.fetch(
            url, accept_any_status=bool(org["accept_any_status"]))

        if not result.ok:
            self.db.add_fetch_fail(self.org_id, url, result.status_code,
                                   result.error, result.engine)
            self.db.finish_url(row["id"], "failed", http_status=result.status_code,
                               last_error=result.error,
                               retries=(row["retries"] or 0) + 1)
            if row["source"] == "seed" and row["depth"] == 0:
                self.db.add_event(self.org_id, "error",
                                  f"SEED fetch failed ({result.error}) — check URL/scope/engine")
            # Connection-level failures (refused/timeout, no HTTP response) on a
            # host that worked before usually mean WE are being rate-limited.
            # Politeness: back off increasingly, and stop knocking entirely
            # after a streak — the URLs stay pending for a later resume.
            if result.status_code is None:
                self.consecutive_conn_failures += 1
                if self.consecutive_conn_failures >= 10:
                    self.db.set_org_fields(self.org_id, state="paused")
                    self.db.add_event(
                        self.org_id, "warning",
                        f"{self.consecutive_conn_failures} consecutive connection "
                        f"failures — server refusing us; paused for politeness. "
                        f"Resume in a few hours (frontier is preserved).")
                    return
                await asyncio.sleep(min(30 * self.consecutive_conn_failures, 180))
            else:
                # an HTTP error still proves the server is talking to us
                self.consecutive_conn_failures = 0
            return

        self.consecutive_conn_failures = 0

        # Redirect landed out of scope: flag for review instead of silently dropping
        final = urlnorm.normalize_url(result.final_url) or result.final_url
        if not urlnorm.in_scope(final, scope):
            self.db.finish_url(row["id"], "excluded",
                               http_status=result.status_code,
                               reason=f"redirect_out_of_scope:{final[:300]}")
            self.db.add_event(self.org_id, "warning",
                              f"redirect out of scope: {url} -> {final} "
                              f"(add a scope rule if this domain belongs to the org)")
            return

        if "text/html" not in result.content_type and result.engine == "http":
            ext = urlnorm.file_extension(url) or ""
            self.db.add_file_links_batch(self.org_id, row["parent_url"] or "", [
                {"url": url, "text": "", "type": "internal", "extension": ext}])
            self.db.finish_url(row["id"], "done", http_status=result.status_code,
                               content_type=result.content_type, reason="non_html")
            return

        if len(result.content) < config.MIN_CONTENT_LENGTH:
            self.db.finish_url(row["id"], "excluded",
                               http_status=result.status_code,
                               content_type=result.content_type, reason="too_short")
            return

        # HTML parsing + all storage writes are synchronous and, on slow
        # storage (Unraid fuse array), long enough to starve the event loop —
        # run the whole step in a worker thread so fetching and the web UI
        # keep breathing.
        await asyncio.to_thread(self._store_page, org, row, scope, url, final, result)

    def _store_page(self, org, row, scope, url: str, final: str, result: FetchResult):
        # ---- link extraction (always, also on refetch — that's the point) ----
        soup = extractor.parse_html(result.content, result.encoding)
        hyperlinks, file_links = extractor.extract_links(soup, final, scope)
        if hyperlinks:
            self.db.add_links_batch(self.org_id, url, hyperlinks)
        if file_links:
            self.db.add_file_links_batch(self.org_id, url, file_links)

        new_depth = (row["depth"] or 0) + 1
        max_depth = org["max_depth"] or config.MAX_DEPTH_DEFAULT
        frontier_rows = []
        for link in hyperlinks:
            if link["type"] != "internal":
                continue
            target = link["url"]
            key = urlnorm.url_key(target)
            reason = urlnorm.exclusion_reason(target)
            if reason:
                frontier_rows.append((self.org_id, target, key, "excluded",
                                      reason, "link", new_depth, url))
            elif new_depth > max_depth:
                frontier_rows.append((self.org_id, target, key, "excluded",
                                      "max_depth", "link", new_depth, url))
            else:
                frontier_rows.append((self.org_id, target, key, "pending",
                                      None, "link", new_depth, url))
        if frontier_rows:
            self.db.add_urls_batch(frontier_rows)

        # ---- snapshot save (only when content actually changed) ----
        content_hash = urlnorm.content_sha256(result.content)
        if row["content_hash"] == content_hash and row["file_path"]:
            self.db.finish_url(row["id"], "done", http_status=result.status_code,
                               content_type=result.content_type or "text/html",
                               content_hash=content_hash, reason="unchanged")
            return

        duplicate = self.db.find_page_by_hash(self.org_id, content_hash)
        if duplicate:
            self.db.finish_url(row["id"], "done", http_status=result.status_code,
                               content_type=result.content_type or "text/html",
                               content_hash=content_hash,
                               file_path=duplicate["file_path"],
                               reason="duplicate_content")
            return

        seq = self.db.next_page_seq(self.org_id)
        filename = urlnorm.url_to_filename(url, seq)
        filepath = self._pages_dir(org) / filename
        filepath.write_bytes(result.content)
        # POSIX-style relative path so the DB is portable Windows <-> Linux
        rel_path = filepath.relative_to(config.DATA_DIR).as_posix()

        self.db.add_page(self.org_id, url, rel_path, content_hash,
                         len(result.content), result.encoding)
        self.db.finish_url(row["id"], "done", http_status=result.status_code,
                           content_type=result.content_type or "text/html",
                           content_hash=content_hash, file_path=rel_path,
                           size_bytes=len(result.content),
                           reason="changed" if row["refetch"] else None)
        self.session_saved += 1

        # flag-only threshold (never pauses — per project decision)
        if not org["flagged"] and org["flag_threshold"]:
            n_pages = self.db.query_one(
                "SELECT COUNT(*) n FROM pages WHERE org_id=?", (self.org_id,))["n"]
            if n_pages >= org["flag_threshold"]:
                self.db.set_org_fields(self.org_id, flagged=1)
                self.db.add_event(self.org_id, "warning",
                                  f"page count crossed {org['flag_threshold']} — "
                                  f"review crawl scope (crawl continues)")
