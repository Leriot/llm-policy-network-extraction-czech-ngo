"""Apply urlrules.py to the EXISTING frontier and corpus.

Nothing is ever deleted. Pending URLs that the rules reject are marked
status='excluded' with a machine-readable reason, so every decision stays
auditable and reversible (set them back to 'pending' to undo).

Already-FETCHED pages that the rules would now reject are flagged in a
separate column `out_of_scope` rather than touched — the HTML stays on disk
(consistent with the project's "collect broadly, filter at analysis time"
design) but downstream text passes can skip them cheaply.

Usage
-----
    python -m crawler_service.apply_urlrules --dry-run      # report only
    python -m crawler_service.apply_urlrules                # apply
    python -m crawler_service.apply_urlrules --org CZ039
"""

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from . import config, urlrules

BATCH = 20000


def connect(db_path):
    conn = sqlite3.connect(str(db_path), timeout=120)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(urls)")}
    if "out_of_scope" not in cols:
        conn.execute("ALTER TABLE urls ADD COLUMN out_of_scope INTEGER DEFAULT 0")
        conn.commit()
        print("  added urls.out_of_scope column")


def process(conn, org_id, dry_run):
    """Returns (n_excluded, n_flagged_fetched, reasons Counter)."""
    reasons = Counter()
    excluded = flagged = 0

    def scan(status):
        """Stream rows in id-ranges so a 2M-row org never lands in memory."""
        last = 0
        while True:
            chunk = conn.execute(
                "SELECT id, url FROM urls WHERE org_id=? AND status=? AND id>? "
                "ORDER BY id LIMIT ?", (org_id, status, last, BATCH)).fetchall()
            if not chunk:
                return
            last = chunk[-1]["id"]
            yield chunk

    # ---- pending: reject traps, canonicalize survivors -------------------
    for chunk in scan("pending"):
        to_exclude, to_canon = [], []
        for r in chunk:
            reason = urlrules.trap_reason(r["url"], org_id)
            if reason:
                reasons[reason] += 1
                to_exclude.append((reason, r["id"]))
            else:
                canon = urlrules.canonicalize(r["url"], org_id)
                if canon != r["url"]:
                    to_canon.append((canon, r["id"]))
        excluded += len(to_exclude)
        if dry_run:
            continue
        conn.executemany(
            "UPDATE urls SET status='excluded', reason=? WHERE id=?", to_exclude)
        # a canonicalised URL may collide with an existing row: record it as a
        # duplicate rather than losing the row to an IntegrityError
        for canon, rid in to_canon:
            try:
                conn.execute("UPDATE urls SET url=? WHERE id=?", (canon, rid))
            except sqlite3.IntegrityError:
                conn.execute("UPDATE urls SET status='excluded', "
                             "reason='canonical_duplicate' WHERE id=?", (rid,))
        conn.commit()

    # ---- already fetched: flag only (never delete, never re-status) ------
    for chunk in scan("done"):
        to_flag = [(r["id"],) for r in chunk
                   if urlrules.trap_reason(r["url"], org_id)]
        flagged += len(to_flag)
        if dry_run or not to_flag:
            continue
        conn.executemany("UPDATE urls SET out_of_scope=1 WHERE id=?", to_flag)
        conn.commit()

    return excluded, flagged, reasons


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--org", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=None)
    args = ap.parse_args(argv)

    db_path = Path(args.db) if args.db else config.DB_PATH
    conn = connect(db_path)
    if not args.dry_run:
        ensure_column(conn)

    orgs = ([args.org] if args.org else
            [r[0] for r in conn.execute(
                "SELECT DISTINCT org_id FROM urls WHERE status='pending'")])

    tot_ex = tot_fl = 0
    print(f"{'org':8} {'excluded':>10} {'flagged_done':>13}  reasons")
    for org in sorted(orgs):
        ex, fl, reasons = process(conn, org, args.dry_run)
        tot_ex += ex
        tot_fl += fl
        if ex or fl:
            top = ", ".join(f"{k}={v}" for k, v in reasons.most_common(3))
            print(f"{org:8} {ex:10,} {fl:13,}  {top}")
    mode = "WOULD EXCLUDE" if args.dry_run else "EXCLUDED"
    print(f"\n  {mode}: {tot_ex:,} pending URLs;  flagged out-of-scope "
          f"(kept on disk): {tot_fl:,} fetched pages")
    remaining = conn.execute(
        "SELECT COUNT(*) FROM urls WHERE status='pending'").fetchone()[0]
    print(f"  pending frontier now: {remaining:,}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
