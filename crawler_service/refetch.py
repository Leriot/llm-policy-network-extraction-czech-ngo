"""Apply a link-discovery refetch policy across orgs.

    python -m crawler_service.refetch --mode hubs          # all orgs
    python -m crawler_service.refetch --mode all --org CZ009

hubs = listing/section/pagination pages only (path depth <= 2 or pagination
patterns) — where new links appear; deep article pages stay archival snapshots.
"""

import argparse
import logging
import sys
from pathlib import Path

from .db import Database

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Set refetch policy")
    parser.add_argument("--mode", choices=["hubs", "all", "none"], required=True)
    parser.add_argument("--org", default=None)
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)

    db = Database(Path(args.db) if args.db else None)
    orgs = [db.get_org(args.org)] if args.org else db.list_orgs()
    total_q = total_d = 0
    for org in orgs:
        if org is None:
            logger.error("org not found")
            return 1
        result = db.queue_refetch(org["org_id"], args.mode)
        if result["queued"] or result["demoted"]:
            logger.info(f"{org['org_id']} {org['name']}: {result}")
            db.add_event(org["org_id"], "info",
                         f"refetch policy '{args.mode}': {result['queued']} queued, "
                         f"{result['demoted']} demoted to archival")
            total_q += result["queued"]
            total_d += result["demoted"]
    logger.info(f"TOTAL: queued={total_q} demoted={total_d}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
