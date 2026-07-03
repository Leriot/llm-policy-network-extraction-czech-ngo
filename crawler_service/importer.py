"""Import the v1 (thesis-era) corpus into the new database.

For each org whose data/raw/<dir_name>/ exists:
  1. pages/  + url_manifest.jsonl  ->  pages rows (hash computed from the file
     on disk) + urls rows (status=pending, refetch=1) so the crawler re-fetches
     for link discovery but never re-saves unchanged content.
  2. links.json                    ->  links + file_links tables, and any
     internal target never fetched becomes a fresh frontier row — this repairs
     the resume holes the old scraper left.
  3. orgs.page_seq is set past the highest existing NNNNN_ filename so new
     snapshots never collide with old ones.

Usage:
    python -m crawler_service.importer            # all orgs with data
    python -m crawler_service.importer --org CZ051
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config, urlnorm
from .db import Database, now_iso

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _iso(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return now_iso()


def import_org(db: Database, org) -> dict:
    org_id = org["org_id"]
    raw_dir = config.DATA_DIR / "raw" / org["dir_name"]
    pages_dir = raw_dir / "pages"
    stats = {"pages": 0, "urls": 0, "links": 0, "file_links": 0,
             "frontier_recovered": 0, "missing_files": 0}
    if not raw_dir.exists():
        return stats

    # ---- 1. manifest + files -> pages + urls -------------------------------
    manifest_file = raw_dir / "url_manifest.jsonl"
    url_by_key = {}
    max_seq = 0
    if manifest_file.exists():
        with open(manifest_file, "r", encoding="utf-8") as f:
            entries = [json.loads(line) for line in f if line.strip()]
        for e in entries:
            filename = e.get("filename", "")
            url = urlnorm.normalize_url(e.get("url", ""))
            if not url or not filename:
                continue
            filepath = pages_dir / filename
            if not filepath.exists():
                stats["missing_files"] += 1
                continue
            m = re.match(r"^(\d+)_", filename)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
            content = filepath.read_bytes()
            content_hash = urlnorm.content_sha256(content)
            rel_path = filepath.relative_to(config.DATA_DIR).as_posix()
            fetched_at = _iso(e.get("saved_at", ""))
            key = urlnorm.url_key(url)
            if key in url_by_key:
                continue  # first manifest entry wins for the URL row
            url_by_key[key] = url
            db.add_page(org_id, url, rel_path, content_hash, len(content), "utf-8",
                        fetched_at=fetched_at)
            db.import_visited_url(org_id, url, key, content_hash, rel_path,
                                  len(content), fetched_at)
            stats["pages"] += 1
    db.bulk_commit()
    stats["urls"] = len(url_by_key)

    # keep sequence numbering monotonic across the era boundary
    if max_seq > int(org["page_seq"] or 0):
        db.set_org_fields(org_id, page_seq=max_seq)

    # ---- 2. links.json -> links / file_links / recovered frontier ----------
    links_file = raw_dir / "links.json"
    if links_file.exists():
        with open(links_file, "r", encoding="utf-8") as f:
            old_links = json.load(f)
        scope = json.loads(org["scope"] or "[]") or (
            urlnorm.default_scope(org["seed_url"]) if org["seed_url"] else [])
        ts = now_iso()
        link_rows, file_rows, frontier = [], [], {}
        for l in old_links:
            src = urlnorm.normalize_url(l.get("source_url", ""))
            tgt = urlnorm.normalize_url(l.get("target_url", ""))
            if not src or not tgt:
                continue
            anchor = (l.get("anchor_text") or "")[:500]
            if scope:
                ltype = "internal" if urlnorm.in_scope(tgt, scope) else "external"
            else:
                ltype = l.get("link_type", "external")
            ext = urlnorm.file_extension(tgt)
            if ext:
                file_rows.append((org_id, tgt, src, anchor, ext, ltype, ts))
            else:
                link_rows.append((org_id, src, tgt, anchor, ltype, ts, ts))
                if ltype == "internal":
                    key = urlnorm.url_key(tgt)
                    if key not in url_by_key and key not in frontier \
                            and not urlnorm.is_binary_noise(tgt):
                        frontier[key] = (tgt, src)

        db.bulk_execute(
            """INSERT INTO links (org_id, first_source_url, target_url, anchor_text,
                                  link_type, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(org_id, target_url) DO UPDATE SET
                   occurrences = occurrences + 1""",
            link_rows)
        db.bulk_execute(
            """INSERT OR IGNORE INTO file_links
               (org_id, url, source_url, anchor_text, extension, link_type, first_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            file_rows)
        for key, (tgt, src) in frontier.items():
            reason = urlnorm.exclusion_reason(tgt)
            db.add_url(org_id, tgt, key, depth=1, parent_url=src,
                       source="legacy_links",
                       status="excluded" if reason else "pending", reason=reason)
        db.bulk_commit()
        stats["links"] = len(link_rows)
        stats["file_links"] = len(file_rows)
        stats["frontier_recovered"] = sum(
            1 for k, (t, _) in frontier.items() if not urlnorm.exclusion_reason(t))

    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import v1 corpus into crawler DB")
    parser.add_argument("--org", default=None, help="import a single org id (e.g. CZ051)")
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)

    db = Database(Path(args.db) if args.db else None)
    orgs = [db.get_org(args.org)] if args.org else db.list_orgs()
    total = {"pages": 0, "links": 0, "file_links": 0, "frontier_recovered": 0}
    for org in orgs:
        if org is None:
            logger.error("org not found")
            return 1
        already = db.query_one(
            "SELECT COUNT(*) n FROM urls WHERE org_id=? AND source='import'",
            (org["org_id"],))["n"]
        if already:
            logger.info(f"{org['org_id']} {org['name']}: already imported, skipping")
            continue
        stats = import_org(db, org)
        if any(stats.values()):
            logger.info(f"{org['org_id']} {org['name']}: {stats}")
            db.add_event(org["org_id"], "info", f"legacy import: {stats}")
            for k in total:
                total[k] += stats.get(k, 0)
    logger.info(f"TOTAL: {total}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
