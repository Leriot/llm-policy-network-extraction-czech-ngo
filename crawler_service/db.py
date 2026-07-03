"""SQLite persistence layer — the single source of truth.

Tables:
  orgs        one row per COMPON organisation (seed URL, scope, state, engine)
  urls        persistent frontier + visit ledger; every discovered URL has a row
  pages       immutable saved snapshots (a URL may have several over time)
  links       deduplicated hyperlink edges (source page -> target) for network analysis
  file_links  registry of downloadable files (PDF etc.) seen on pages — not downloaded
  events      operational log surfaced in the dashboard
  fetch_fail  per-attempt failure log (successes live on the urls row)

All writes go through this module and are serialized with a lock; WAL mode
keeps dashboard reads cheap while a crawl is running.
"""

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (
    org_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dir_name TEXT NOT NULL,
    aliases TEXT DEFAULT '',
    seed_url TEXT DEFAULT '',
    url_verified INTEGER DEFAULT 0,
    scope TEXT DEFAULT '[]',
    engine TEXT DEFAULT 'http',
    state TEXT DEFAULT 'new',
    max_depth INTEGER DEFAULT {max_depth},
    flag_threshold INTEGER DEFAULT {flag_threshold},
    flagged INTEGER DEFAULT 0,
    accept_any_status INTEGER DEFAULT 0,
    page_seq INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS urls (
    id INTEGER PRIMARY KEY,
    org_id TEXT NOT NULL,
    url TEXT NOT NULL,
    url_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reason TEXT,
    source TEXT DEFAULT 'link',
    depth INTEGER DEFAULT 0,
    parent_url TEXT,
    discovered_at TEXT,
    fetched_at TEXT,
    http_status INTEGER,
    content_type TEXT,
    content_hash TEXT,
    file_path TEXT,
    size_bytes INTEGER,
    retries INTEGER DEFAULT 0,
    last_error TEXT,
    refetch INTEGER DEFAULT 0,
    UNIQUE(org_id, url_key)
);
CREATE INDEX IF NOT EXISTS idx_urls_org_status ON urls(org_id, status);
CREATE INDEX IF NOT EXISTS idx_urls_org_refetch ON urls(org_id, status, refetch, depth);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    doc_id TEXT,
    org_id TEXT NOT NULL,
    url TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    size_bytes INTEGER,
    encoding TEXT,
    fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_pages_org_url ON pages(org_id, url);
CREATE INDEX IF NOT EXISTS idx_pages_org_hash ON pages(org_id, content_hash);

CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY,
    org_id TEXT NOT NULL,
    target_url TEXT NOT NULL,
    anchor_text TEXT DEFAULT '',
    link_type TEXT DEFAULT 'internal',
    first_source_url TEXT DEFAULT '',
    occurrences INTEGER DEFAULT 1,
    first_seen TEXT,
    last_seen TEXT,
    UNIQUE(org_id, target_url)
);
CREATE INDEX IF NOT EXISTS idx_links_org ON links(org_id);

CREATE TABLE IF NOT EXISTS file_links (
    id INTEGER PRIMARY KEY,
    org_id TEXT NOT NULL,
    url TEXT NOT NULL,
    source_url TEXT NOT NULL,
    anchor_text TEXT DEFAULT '',
    extension TEXT DEFAULT '',
    link_type TEXT DEFAULT 'internal',
    first_seen TEXT,
    UNIQUE(org_id, url, source_url)
);
CREATE INDEX IF NOT EXISTS idx_file_links_org ON file_links(org_id);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts TEXT,
    org_id TEXT,
    level TEXT,
    message TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_org ON events(org_id, id);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS fetch_fail (
    id INTEGER PRIMARY KEY,
    ts TEXT,
    org_id TEXT,
    url TEXT,
    http_status INTEGER,
    error TEXT,
    engine TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or config.DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=60)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        # Separate read-only connection for dashboard/audit analytics: in WAL
        # mode readers never block the writer, so a minutes-long GROUP BY over
        # the links table can no longer freeze the crawl (or healthz).
        self._read_conn = None
        self._read_lock = threading.Lock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(
                SCHEMA.format(
                    max_depth=config.MAX_DEPTH_DEFAULT,
                    flag_threshold=config.FLAG_THRESHOLD_DEFAULT,
                )
            )
            self.conn.commit()
        self._migrate()

    def _migrate(self):
        """In-place schema upgrades for databases created by earlier versions."""
        self._migrate_links_dedup()
        with self.lock:
            org_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(orgs)")}
            if "accept_any_status" not in org_cols:
                self.conn.execute(
                    "ALTER TABLE orgs ADD COLUMN accept_any_status INTEGER DEFAULT 0")
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(pages)")}
            if "doc_id" not in cols:
                self.conn.execute("ALTER TABLE pages ADD COLUMN doc_id TEXT")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pages_doc_id ON pages(doc_id)")
            # content-addressed datapoint id: stable across DB rebuilds and
            # machines, reproducible from the file itself
            self.conn.execute(
                "UPDATE pages SET doc_id = org_id || '-' || substr(content_hash, 1, 12) "
                "WHERE doc_id IS NULL")
            self.conn.commit()

    def _migrate_links_dedup(self):
        """One-time collapse of the per-page-pair edge list to unique
        (org, target) links. Per-page fidelity stays recoverable from the
        archived HTML (rebuild.py); the DB only needs unique links — the
        26M-row/14GB edge list was 95% nav-menu repetition. Runs at startup
        on a stopped world; takes minutes on the old data."""
        with self.lock:
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(links)")}
            if "first_source_url" in cols or "source_url" not in cols:
                return  # already migrated (or fresh install)
            import logging
            log = logging.getLogger(__name__)
            n = self.conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
            log.warning(f"links dedup migration starting: {n} rows -> unique (org, target)…")
            self.conn.executescript("""
                CREATE TABLE links_new (
                    id INTEGER PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    target_url TEXT NOT NULL,
                    anchor_text TEXT DEFAULT '',
                    link_type TEXT DEFAULT 'internal',
                    first_source_url TEXT DEFAULT '',
                    occurrences INTEGER DEFAULT 1,
                    first_seen TEXT,
                    last_seen TEXT,
                    UNIQUE(org_id, target_url)
                );
                INSERT INTO links_new (org_id, target_url, anchor_text, link_type,
                                       first_source_url, occurrences, first_seen, last_seen)
                    SELECT org_id, target_url, MIN(anchor_text), MAX(link_type),
                           MIN(source_url), SUM(occurrences), MIN(first_seen), MAX(last_seen)
                    FROM links GROUP BY org_id, target_url;
                DROP TABLE links;
                ALTER TABLE links_new RENAME TO links;
                CREATE INDEX IF NOT EXISTS idx_links_org ON links(org_id);
            """)
            self.conn.commit()
            kept = self.conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
            log.warning(f"links dedup: {n} -> {kept} rows; reclaiming space (VACUUM)…")
            self.conn.execute("VACUUM")
            log.warning("links dedup migration finished")

    def close(self):
        with self.lock:
            self.conn.close()
        with self._read_lock:
            if self._read_conn is not None:
                self._read_conn.close()

    def backup(self, keep: int = 5) -> Path:
        """Consistent online snapshot via VACUUM INTO (safe during writes,
        unlike copying the file). Keeps the newest `keep` snapshots.
        Backups always target the array data share, even when the live DB
        sits on the SSD cache."""
        backup_dir = config.DATA_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"crawler-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.db"
        with self.lock:
            self.conn.execute("VACUUM INTO ?", (str(target),))
        snapshots = sorted(backup_dir.glob("crawler-*.db"))
        for old in snapshots[:-keep]:
            old.unlink()
        return target

    # ------------------------------------------------------------------ util
    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def _reader(self) -> sqlite3.Connection:
        if self._read_conn is None:
            self._read_conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro", uri=True,
                check_same_thread=False, timeout=60)
            self._read_conn.row_factory = sqlite3.Row
        return self._read_conn

    def read_query(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        """Analytics reads on the dedicated read-only connection — never
        contends with the crawl's writer lock."""
        with self._read_lock:
            return self._reader().execute(sql, params).fetchall()

    def read_query_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        with self._read_lock:
            return self._reader().execute(sql, params).fetchone()

    # ------------------------------------------------------------------ orgs
    def upsert_org(self, org_id: str, name: str, dir_name: str, aliases: str = ""):
        self._exec(
            """INSERT INTO orgs (org_id, name, dir_name, aliases, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(org_id) DO UPDATE SET name=excluded.name, aliases=excluded.aliases,
                   updated_at=excluded.updated_at""",
            (org_id, name, dir_name, aliases, now_iso(), now_iso()),
        )

    def set_org_fields(self, org_id: str, **fields):
        allowed = {
            "seed_url", "url_verified", "scope", "engine", "state", "max_depth",
            "flag_threshold", "flagged", "notes", "page_seq", "dir_name", "aliases",
            "accept_any_status",
        }
        cols, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                raise ValueError(f"unknown org field {k}")
            cols.append(f"{k}=?")
            vals.append(v)
        cols.append("updated_at=?")
        vals.append(now_iso())
        vals.append(org_id)
        self._exec(f"UPDATE orgs SET {', '.join(cols)} WHERE org_id=?", tuple(vals))

    def get_org(self, org_id: str) -> Optional[sqlite3.Row]:
        return self.query_one("SELECT * FROM orgs WHERE org_id=?", (org_id,))

    def list_orgs(self) -> List[sqlite3.Row]:
        return self.query("SELECT * FROM orgs ORDER BY org_id")

    def next_page_seq(self, org_id: str) -> int:
        """Atomically increment and return the per-org page sequence number."""
        with self.lock:
            self.conn.execute(
                "UPDATE orgs SET page_seq = page_seq + 1 WHERE org_id=?", (org_id,)
            )
            row = self.conn.execute(
                "SELECT page_seq FROM orgs WHERE org_id=?", (org_id,)
            ).fetchone()
            self.conn.commit()
            return int(row["page_seq"])

    # ------------------------------------------------------------------ urls
    def add_url(self, org_id: str, url: str, url_key: str, depth: int,
                parent_url: Optional[str], source: str = "link",
                status: str = "pending", reason: Optional[str] = None) -> bool:
        """Insert a URL if its key is new for this org. Returns True if inserted."""
        with self.lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO urls
                   (org_id, url, url_key, status, reason, source, depth, parent_url, discovered_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (org_id, url, url_key, status, reason, source, depth, parent_url, now_iso()),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def add_urls_batch(self, rows: List[tuple]):
        """One transaction for a page's whole frontier contribution.
        rows: (org_id, url, url_key, status, reason, source, depth, parent_url).
        Critical on slow storage: per-link commits starved the event loop."""
        ts = now_iso()
        with self.lock:
            self.conn.executemany(
                """INSERT OR IGNORE INTO urls (org_id, url, url_key, status, reason,
                       source, depth, parent_url, discovered_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [r + (ts,) for r in rows])
            self.conn.commit()

    def claim_next_url(self, org_id: str) -> Optional[sqlite3.Row]:
        """Claim the next pending URL (fresh URLs before refetches, shallow first)."""
        with self.lock:
            row = self.conn.execute(
                """SELECT * FROM urls WHERE org_id=? AND status='pending'
                   ORDER BY refetch ASC, depth ASC, id ASC LIMIT 1""",
                (org_id,),
            ).fetchone()
            if row is None:
                return None
            self.conn.execute(
                "UPDATE urls SET status='in_progress' WHERE id=?", (row["id"],)
            )
            self.conn.commit()
            return row

    def finish_url(self, url_id: int, status: str, *, http_status: Optional[int] = None,
                   content_type: Optional[str] = None, content_hash: Optional[str] = None,
                   file_path: Optional[str] = None, size_bytes: Optional[int] = None,
                   last_error: Optional[str] = None, reason: Optional[str] = None,
                   retries: Optional[int] = None):
        sets = ["status=?", "fetched_at=?"]
        vals: List[Any] = [status, now_iso()]
        for col, v in [
            ("http_status", http_status), ("content_type", content_type),
            ("content_hash", content_hash), ("file_path", file_path),
            ("size_bytes", size_bytes), ("last_error", last_error),
            ("reason", reason), ("retries", retries),
        ]:
            if v is not None:
                sets.append(f"{col}=?")
                vals.append(v)
        if status == "done":
            sets.append("refetch=0")
        vals.append(url_id)
        self._exec(f"UPDATE urls SET {', '.join(sets)} WHERE id=?", tuple(vals))

    def release_stale_claims(self, org_id: Optional[str] = None):
        """Return crashed in_progress URLs to the frontier (called on startup)."""
        if org_id:
            self._exec(
                "UPDATE urls SET status='pending' WHERE status='in_progress' AND org_id=?",
                (org_id,),
            )
        else:
            self._exec("UPDATE urls SET status='pending' WHERE status='in_progress'")

    def requeue_failed(self, org_id: str) -> int:
        cur = self._exec(
            "UPDATE urls SET status='pending', last_error=NULL WHERE org_id=? AND status='failed'",
            (org_id,),
        )
        return cur.rowcount

    def queue_refetch(self, org_id: str, mode: str = "hubs") -> Dict[str, int]:
        """Set the link-discovery refetch queue for an org.

        mode='all'  — every previously fetched HTML page
        mode='hubs' — only listing/section/pagination pages (see
                      urlnorm.is_hub_url); deep article pages stay archival
        mode='none' — clear the refetch queue

        Only touches rows that are already-fetched pages (done, or currently
        queued for refetch); fresh never-fetched URLs are never affected.
        Returns {'queued': n, 'demoted': n}.
        """
        from . import urlnorm  # local import to avoid cycle

        rows = self.query(
            """SELECT id, url, status FROM urls WHERE org_id=? AND content_type LIKE 'text/html%'
               AND (status='done' OR (status='pending' AND refetch=1))""",
            (org_id,),
        )
        if mode == "all":
            selected = {r["id"] for r in rows}
        elif mode == "hubs":
            selected = {r["id"] for r in rows if urlnorm.is_hub_url(r["url"])}
        else:
            selected = set()
        queue = [(r["id"],) for r in rows if r["id"] in selected]
        demote = [(r["id"],) for r in rows
                  if r["id"] not in selected and r["status"] == "pending"]
        with self.lock:
            self.conn.executemany(
                "UPDATE urls SET status='pending', refetch=1 WHERE id=?", queue)
            self.conn.executemany(
                "UPDATE urls SET status='done', refetch=0 WHERE id=?", demote)
            self.conn.commit()
        return {"queued": len(queue), "demoted": len(demote)}

    def import_visited_url(self, org_id: str, url: str, url_key: str,
                           content_hash: str, file_path: str, size_bytes: int,
                           fetched_at: str, refetch: bool = True):
        """Bulk-import helper for the legacy corpus: URL already fetched once;
        queued as pending+refetch so link discovery re-runs, but the stored
        hash prevents re-saving unchanged content."""
        with self.lock:
            self.conn.execute(
                """INSERT INTO urls (org_id, url, url_key, status, source, depth,
                                     discovered_at, fetched_at, http_status, content_type,
                                     content_hash, file_path, size_bytes, refetch)
                   VALUES (?, ?, ?, 'pending', 'import', 1, ?, ?, 200, 'text/html',
                           ?, ?, ?, ?)
                   ON CONFLICT(org_id, url_key) DO NOTHING""",
                (org_id, url, url_key, fetched_at, fetched_at,
                 content_hash, file_path, size_bytes, 1 if refetch else 0),
            )

    def bulk_commit(self):
        with self.lock:
            self.conn.commit()

    def bulk_execute(self, sql: str, rows: List[tuple]):
        """executemany without per-call commit — caller uses bulk_commit()."""
        with self.lock:
            self.conn.executemany(sql, rows)

    # ------------------------------------------------------------------ pages
    def add_page(self, org_id: str, url: str, file_path: str, content_hash: str,
                 size_bytes: int, encoding: str, fetched_at: Optional[str] = None):
        """fetched_at = when the content was actually obtained from the web;
        the importer passes the original v1 scrape time from the manifest.
        doc_id is the stable content-addressed datapoint identifier."""
        doc_id = f"{org_id}-{content_hash[:12]}"
        self._exec(
            """INSERT INTO pages (doc_id, org_id, url, file_path, content_hash, size_bytes, encoding, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, org_id, url, file_path, content_hash, size_bytes, encoding,
             fetched_at or now_iso()),
        )

    def find_page_by_hash(self, org_id: str, content_hash: str) -> Optional[sqlite3.Row]:
        return self.query_one(
            "SELECT * FROM pages WHERE org_id=? AND content_hash=? LIMIT 1",
            (org_id, content_hash),
        )

    # ------------------------------------------------------------------ links
    def add_links_batch(self, org_id: str, source_url: str, links: List[Dict]):
        """links: [{url, text, type}] — unique (org, target) rows; repeats
        bump the counter in place instead of adding rows (nav menus would
        otherwise multiply every target by the page count)."""
        ts = now_iso()
        with self.lock:
            self.conn.executemany(
                """INSERT INTO links (org_id, target_url, anchor_text, link_type,
                                      first_source_url, occurrences, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(org_id, target_url) DO UPDATE SET
                       occurrences = occurrences + 1, last_seen = excluded.last_seen""",
                [(org_id, link["url"], (link.get("text") or "")[:500],
                  link.get("type", "internal"), source_url, ts, ts)
                 for link in links],
            )
            self.conn.commit()

    def add_file_links_batch(self, org_id: str, source_url: str, files: List[Dict]):
        ts = now_iso()
        with self.lock:
            for f in files:
                self.conn.execute(
                    """INSERT OR IGNORE INTO file_links
                       (org_id, url, source_url, anchor_text, extension, link_type, first_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (org_id, f["url"], source_url, (f.get("text") or "")[:500],
                     f.get("extension", ""), f.get("type", "internal"), ts),
                )
            self.conn.commit()

    # ------------------------------------------------------------------ events
    def add_event(self, org_id: Optional[str], level: str, message: str):
        self._exec(
            "INSERT INTO events (ts, org_id, level, message) VALUES (?, ?, ?, ?)",
            (now_iso(), org_id, level, message[:2000]),
        )

    def add_fetch_fail(self, org_id: str, url: str, http_status: Optional[int],
                       error: str, engine: str):
        self._exec(
            "INSERT INTO fetch_fail (ts, org_id, url, http_status, error, engine) VALUES (?, ?, ?, ?, ?, ?)",
            (now_iso(), org_id, url, http_status, error[:1000], engine),
        )

    # ------------------------------------------------------------------ stats
    def _ttl_cached(self, key: str, ttl: float, fn):
        """Serve dashboard aggregates from a short-lived cache — full-table
        scans over millions of rows must not run on every 10s UI poll.
        Singleflight: while one thread recomputes, everyone else gets the
        stale value instead of stampeding the same heavy query."""
        cache = getattr(self, "_ttl_cache", None)
        if cache is None:
            cache = self._ttl_cache = {}
            self._ttl_flight = threading.Lock()
        hit = cache.get(key)
        now = time.monotonic()
        if hit and now - hit[0] < ttl:
            return hit[1]
        if hit and not self._ttl_flight.acquire(blocking=False):
            return hit[1]  # someone is already refreshing — serve stale
        elif not hit:
            self._ttl_flight.acquire()  # cold start: everyone must wait once
        try:
            hit = cache.get(key)
            if hit and time.monotonic() - hit[0] < ttl:
                return hit[1]
            value = fn()
            cache[key] = (time.monotonic(), value)
            return value
        finally:
            self._ttl_flight.release()

    def org_stats(self, org_id: str) -> Dict[str, Any]:
        counts = {r["status"]: r["n"] for r in self.read_query(
            "SELECT status, COUNT(*) n FROM urls WHERE org_id=? GROUP BY status", (org_id,)
        )}
        pages = self.read_query_one("SELECT COUNT(*) n FROM pages WHERE org_id=?", (org_id,))["n"]
        files = self.read_query_one("SELECT COUNT(*) n FROM file_links WHERE org_id=?", (org_id,))["n"]
        links = self.read_query_one("SELECT COUNT(*) n FROM links WHERE org_id=?", (org_id,))["n"]
        last = self.read_query_one(
            "SELECT MAX(fetched_at) t FROM urls WHERE org_id=?", (org_id,)
        )["t"]
        return {
            "pending": counts.get("pending", 0),
            "in_progress": counts.get("in_progress", 0),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
            "excluded": counts.get("excluded", 0),
            "pages": pages, "files": files, "links": links,
            "last_activity": last,
        }

    def all_org_stats(self) -> Dict[str, Dict[str, Any]]:
        return self._ttl_cached("all_org_stats", 30, self._all_org_stats)

    def _all_org_stats(self) -> Dict[str, Dict[str, Any]]:
        """Stats for every org in four GROUP BY queries (dashboard polling)."""
        stats: Dict[str, Dict[str, Any]] = {}

        def bucket(org_id):
            return stats.setdefault(org_id, {
                "pending": 0, "in_progress": 0, "done": 0, "failed": 0,
                "excluded": 0, "refetch_backlog": 0, "pages": 0, "files": 0,
                "links": 0, "last_activity": None,
            })

        for r in self.read_query(
                "SELECT org_id, status, COUNT(*) n, MAX(fetched_at) t "
                "FROM urls GROUP BY org_id, status"):
            b = bucket(r["org_id"])
            b[r["status"]] = r["n"]
            if r["t"] and (b["last_activity"] is None or r["t"] > b["last_activity"]):
                b["last_activity"] = r["t"]
        for r in self.read_query(
                "SELECT org_id, COUNT(*) n FROM urls "
                "WHERE status='pending' AND refetch=1 GROUP BY org_id"):
            bucket(r["org_id"])["refetch_backlog"] = r["n"]
        for r in self.read_query("SELECT org_id, COUNT(*) n FROM pages GROUP BY org_id"):
            bucket(r["org_id"])["pages"] = r["n"]
        for r in self.read_query("SELECT org_id, COUNT(*) n FROM file_links GROUP BY org_id"):
            bucket(r["org_id"])["files"] = r["n"]
        # links can reach tens of millions of rows — count via a cached value
        # refreshed at most once a minute instead of on every dashboard poll
        now = time.monotonic()
        cached = getattr(self, "_links_cache", None)
        if cached is None or now - cached[0] > 300:
            counts = {r["org_id"]: r["n"] for r in self.read_query(
                "SELECT org_id, COUNT(*) n FROM links GROUP BY org_id")}
            self._links_cache = (now, counts)
        for org_id, n in self._links_cache[1].items():
            bucket(org_id)["links"] = n
        return stats

    def global_stats(self) -> Dict[str, Any]:
        return self._ttl_cached("global_stats", 30, self._global_stats)

    def _global_stats(self) -> Dict[str, Any]:
        by_status = {r["status"]: r["n"] for r in self.read_query(
            "SELECT status, COUNT(*) n FROM urls GROUP BY status"
        )}
        pages = self.read_query_one("SELECT COUNT(*) n FROM pages")["n"]
        files = self.read_query_one("SELECT COUNT(*) n FROM file_links")["n"]
        cached = getattr(self, "_links_cache", None)
        links = sum(cached[1].values()) if cached else \
            self.read_query_one("SELECT COUNT(*) n FROM links")["n"]
        recent = self.read_query_one(
            "SELECT COUNT(*) n FROM urls WHERE fetched_at > ?",
            (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:") + "00:00Z",),
        )["n"]
        return {"urls_by_status": by_status, "pages": pages, "files": files,
                "links": links, "fetched_this_hour": recent}
