"""Completeness audit — answers 'did we actually get everything?' per org.

Everything is derived from the urls table because every discovered URL has a
row there (including exclusions, with reasons). Nothing is invisible.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

from . import config
from .db import Database


def audit_org(db: Database, org_id: str) -> Dict:
    org = db.get_org(org_id)
    stats = db.org_stats(org_id)

    failed_by_error = {
        (r["cls"] or "unknown"): r["n"] for r in db.query(
            """SELECT CASE
                     WHEN last_error LIKE 'HTTP 4%' THEN substr(last_error, 1, 8)
                     WHEN last_error LIKE 'HTTP 5%' THEN substr(last_error, 1, 8)
                     WHEN last_error LIKE 'timeout%' THEN 'timeout'
                     WHEN last_error LIKE '%SSL%' OR last_error LIKE '%certificate%' THEN 'ssl'
                     WHEN last_error LIKE 'Connect%' THEN 'connection'
                     ELSE substr(COALESCE(last_error,'unknown'), 1, 30)
                   END cls, COUNT(*) n
               FROM urls WHERE org_id=? AND status='failed' GROUP BY cls ORDER BY n DESC""",
            (org_id,))
    }
    excluded_by_reason = {
        (r["cls"] or "unknown"): r["n"] for r in db.query(
            """SELECT CASE WHEN reason LIKE 'redirect_out_of_scope%' THEN 'redirect_out_of_scope'
                           ELSE COALESCE(reason,'unknown') END cls, COUNT(*) n
               FROM urls WHERE org_id=? AND status='excluded' GROUP BY cls ORDER BY n DESC""",
            (org_id,))
    }
    refetch_backlog = db.query_one(
        "SELECT COUNT(*) n FROM urls WHERE org_id=? AND status='pending' AND refetch=1",
        (org_id,))["n"]
    fresh_backlog = stats["pending"] - refetch_backlog
    sitemap_total = db.query_one(
        "SELECT COUNT(*) n FROM urls WHERE org_id=? AND source='sitemap'", (org_id,))["n"]
    sitemap_done = db.query_one(
        "SELECT COUNT(*) n FROM urls WHERE org_id=? AND source='sitemap' AND status='done'",
        (org_id,))["n"]
    dup_pages = db.query_one(
        "SELECT COUNT(*) n FROM urls WHERE org_id=? AND reason='duplicate_content'",
        (org_id,))["n"]

    discovered = sum(stats[k] for k in ("pending", "in_progress", "done", "failed", "excluded"))
    coverage = (stats["done"] / discovered * 100) if discovered else 0.0

    return {
        "org_id": org_id,
        "name": org["name"] if org else "?",
        "state": org["state"] if org else "?",
        "discovered_urls": discovered,
        "coverage_pct": round(coverage, 1),
        "fresh_backlog": fresh_backlog,
        "refetch_backlog": refetch_backlog,
        "failed": stats["failed"],
        "failed_by_error": failed_by_error,
        "excluded": stats["excluded"],
        "excluded_by_reason": excluded_by_reason,
        "duplicate_content_urls": dup_pages,
        "sitemap": {"total": sitemap_total, "fetched": sitemap_done},
        "pages_saved": stats["pages"],
        "file_links": stats["files"],
        "hyperlink_edges": stats["links"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit crawl completeness")
    parser.add_argument("--org", default=None)
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)

    db = Database(Path(args.db) if args.db else None)
    orgs = [args.org] if args.org else [o["org_id"] for o in db.list_orgs()]
    reports = []
    for org_id in orgs:
        rep = audit_org(db, org_id)
        if rep["discovered_urls"] or args.org:
            reports.append(rep)
    print(json.dumps(reports, indent=2, ensure_ascii=False))
    incomplete = [r for r in reports if r["fresh_backlog"] or r["failed"]]
    print(f"\n{len(reports)} orgs audited, {len(incomplete)} with open backlog or failures",
          file=sys.stderr)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
