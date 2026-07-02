"""CrawlManager — owns the asyncio worker tasks, shared fetchers, and the
concurrency cap. One worker task per running org; orgs beyond the cap wait in
state 'queued'. Orgs left in state 'running' by a crash/restart are resumed
automatically at startup (a month-long server run should survive reboots)."""

import asyncio
import logging
from typing import Dict, Optional

from . import config
from .crawler import OrgCrawler
from .db import Database
from .fetcher import BrowserFetcher, DomainRateLimiter, HttpFetcher
from .robots import RobotsCache

logger = logging.getLogger(__name__)


class CrawlManager:
    def __init__(self, db: Database):
        self.db = db
        self.limiter = DomainRateLimiter()
        self.http_fetcher = HttpFetcher()
        self.browser_fetcher = BrowserFetcher()
        self.robots = RobotsCache()
        self.semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_ORGS)
        self.tasks: Dict[str, asyncio.Task] = {}

    async def startup(self):
        """Recover from an unclean shutdown, then resume orgs that were running."""
        self.db.release_stale_claims()
        for org in self.db.list_orgs():
            if org["state"] in ("running", "queued"):
                self.start_org(org["org_id"], auto=True)

    async def shutdown(self):
        for org_id, task in list(self.tasks.items()):
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()
        await self.http_fetcher.close()
        await self.browser_fetcher.close()

    # ------------------------------------------------------------------ ops
    def start_org(self, org_id: str, auto: bool = False) -> str:
        org = self.db.get_org(org_id)
        if org is None:
            return "unknown org"
        if not org["seed_url"]:
            return "no seed URL set"
        if not org["url_verified"]:
            return "seed URL not verified yet"
        existing = self.tasks.get(org_id)
        if existing and not existing.done():
            return "already running"
        self.db.set_org_fields(org_id, state="queued")
        if not auto:
            self.db.add_event(org_id, "info", "start requested")
        self.tasks[org_id] = asyncio.create_task(self._worker(org_id))
        return "ok"

    def pause_org(self, org_id: str) -> str:
        org = self.db.get_org(org_id)
        if org is None:
            return "unknown org"
        self.db.set_org_fields(org_id, state="paused")
        self.db.add_event(org_id, "info", "pause requested")
        return "ok"

    def start_all(self) -> int:
        started = 0
        for org in self.db.list_orgs():
            if (org["url_verified"] and org["seed_url"]
                    and org["state"] in ("new", "ready", "paused", "error")):
                if self.start_org(org["org_id"]) == "ok":
                    started += 1
        return started

    def running_count(self) -> int:
        return sum(1 for t in self.tasks.values() if not t.done())

    # ------------------------------------------------------------------ worker
    async def _worker(self, org_id: str):
        try:
            # wait for a slot, but abandon the wait if the org gets paused
            while True:
                try:
                    await asyncio.wait_for(self.semaphore.acquire(), timeout=10)
                    break
                except asyncio.TimeoutError:
                    if self.db.get_org(org_id)["state"] != "queued":
                        return
            try:
                self.db.set_org_fields(org_id, state="running")
                self.db.release_stale_claims(org_id)
                crawler = OrgCrawler(self.db, org_id, self.limiter,
                                     self.http_fetcher, self.browser_fetcher,
                                     self.robots)
                await crawler.run()
            finally:
                self.semaphore.release()
        except asyncio.CancelledError:
            # service shutdown: leave state as 'running' so startup() resumes it
            raise
        except Exception as e:
            logger.exception(f"worker crashed for {org_id}")
            self.db.set_org_fields(org_id, state="error")
            self.db.add_event(org_id, "error", f"worker crashed: {e}")
        finally:
            self.tasks.pop(org_id, None)
