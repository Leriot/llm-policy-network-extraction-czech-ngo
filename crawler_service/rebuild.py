"""Offline link rebuild — re-parse saved HTML snapshots to reconstruct the
hyperlink layer, the file-link registry, and any missing frontier entries.

Why this exists: the v1 scraper only wrote links.json at finalize(), so
interrupted sessions lost their link data (Arnika: 4,554 pages but ~4.8k link
records where ~500k are expected). The pages on disk still contain everything;
this rebuilds it with zero network traffic. Also the permanent safety net: the
link tables can always be regenerated from the corpus.

Usage:
    python -m crawler_service.rebuild            # all orgs with pages
    python -m crawler_service.rebuild --org CZ009
    python -m crawler_service.rebuild --force    # redo orgs already rebuilt
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from . import config, extractor, urlnorm
from .db import Database, now_iso

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def rebuild_org(db: Database, org, force: bool = False) -> dict:
    org_id = org["org_id"]
    marker = f"rebuilt:{org_id}"
    if not force and db.query_one("SELECT value FROM kv WHERE key=?", (marker,)):
        return {}

    scope = json.loads(org["scope"] or "[]") or (
        urlnorm.default_scope(org["seed_url"]) if org["seed_url"] else [])
    if not scope:
        logger.warning(f"{org_id}: no scope (no seed URL) — skipping")
        return {}

    pages = db.query(
        "SELECT url, file_path FROM pages WHERE org_id=? ORDER BY id", (org_id,))
    if not pages:
        return {}

    # a rebuild replaces the link layer for this org (idempotent, no inflation)
    with db.lock:
        db.conn.execute("DELETE FROM links WHERE org_id=?", (org_id,))
        db.conn.execute("DELETE FROM file_links WHERE org_id=?", (org_id,))
        db.conn.commit()

    known_keys = {r["url_key"] for r in db.query(
        "SELECT url_key FROM urls WHERE org_id=?", (org_id,))}

    ts = now_iso()
    link_rows, file_rows, frontier = [], [], {}
    parsed = missing = 0
    for p in pages:
        filepath = config.DATA_DIR / p["file_path"]
        if not filepath.exists():
            missing += 1
            continue
        try:
            soup = extractor.parse_html(filepath.read_bytes(), "utf-8")
            hyperlinks, file_links = extractor.extract_links(soup, p["url"], scope)
        except Exception as e:
            logger.warning(f"{org_id}: parse failed for {p['file_path']}: {e}")
            continue
        parsed += 1
        for l in hyperlinks:
            link_rows.append((org_id, p["url"], l["url"], l["text"], l["type"], ts, ts))
            if l["type"] == "internal":
                key = urlnorm.url_key(l["url"])
                if key not in known_keys and key not in frontier:
                    frontier[key] = (l["url"], p["url"])
        for f in file_links:
            file_rows.append((org_id, f["url"], p["url"], f["text"],
                              f["extension"], f["type"], ts))
        if parsed % 2000 == 0:
            logger.info(f"{org_id}: parsed {parsed}/{len(pages)} pages…")

    db.bulk_execute(
        """INSERT INTO links (org_id, source_url, target_url, anchor_text,
                              link_type, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(org_id, source_url, target_url) DO UPDATE SET
               occurrences = occurrences + 1""",
        link_rows)
    db.bulk_execute(
        """INSERT OR IGNORE INTO file_links
           (org_id, url, source_url, anchor_text, extension, link_type, first_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        file_rows)

    frontier_rows, excluded_rows = [], []
    for key, (target, src) in frontier.items():
        reason = urlnorm.exclusion_reason(target)
        if urlnorm.is_binary_noise(target):
            continue
        if reason:
            excluded_rows.append((org_id, target, key, "excluded", reason,
                                  "rebuild", 1, src, ts))
        else:
            frontier_rows.append((org_id, target, key, "pending", None,
                                  "rebuild", 1, src, ts))
    db.bulk_execute(
        """INSERT OR IGNORE INTO urls (org_id, url, url_key, status, reason,
                                       source, depth, parent_url, discovered_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        frontier_rows + excluded_rows)
    with db.lock:
        db.conn.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (marker, ts))
        db.conn.commit()

    stats = {"pages_parsed": parsed, "missing_files": missing,
             "link_edges": len(link_rows), "file_links": len(file_rows),
             "frontier_recovered": len(frontier_rows)}
    db.add_event(org_id, "info", f"offline link rebuild: {stats}")
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rebuild link layer from saved HTML")
    parser.add_argument("--org", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)

    db = Database(Path(args.db) if args.db else None)
    orgs = [db.get_org(args.org)] if args.org else db.list_orgs()
    for org in orgs:
        if org is None:
            logger.error("org not found")
            return 1
        stats = rebuild_org(db, org, force=args.force)
        if stats:
            logger.info(f"{org['org_id']} {org['name']}: {stats}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
