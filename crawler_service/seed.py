"""Seed the orgs table from COMPON_Orgs.xlsx, merging verified seed URLs for
the 19 ENGOs from the thesis-era config/ngo_config.csv.

Usage:
    python -m crawler_service.seed --xlsx COMPON_Orgs.xlsx --ngo-config config/ngo_config.csv
"""

import argparse
import json
import logging
import sys
import unicodedata
from pathlib import Path

import pandas as pd

from . import urlnorm
from .db import Database

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def ascii_fold(text: str) -> str:
    """Strip diacritics: 'Česká pirátská strana' -> 'Ceska piratska strana'."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def match_key(name: str) -> str:
    return " ".join(ascii_fold(name).lower().split())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Seed COMPON orgs into the crawler DB")
    parser.add_argument("--xlsx", default="COMPON_Orgs.xlsx")
    parser.add_argument("--ngo-config", default="config/ngo_config.csv",
                        help="v1 config with verified URLs for the 19 ENGOs")
    parser.add_argument("--db", default=None, help="override DB path")
    args = parser.parse_args(argv)

    db = Database(Path(args.db) if args.db else None)

    df = pd.read_excel(args.xlsx)
    df = df.rename(columns={c: c.strip() for c in df.columns})
    df = df[df["e"].astype(str).str.match(r"CZ\d+")]
    df = df[df["CZ_NAME"].notna()]

    # Known-good URLs from the thesis run (dir names there are the ground truth
    # for the legacy corpus layout, so reuse the csv ngo_name as dir_name).
    known = {}
    ngo_cfg = Path(args.ngo_config)
    if ngo_cfg.exists():
        cfg = pd.read_csv(ngo_cfg)
        for _, r in cfg.iterrows():
            known[match_key(r["ngo_name"])] = {
                "url": r["url"],
                "dir_name": urlnorm.sanitize_dirname(ascii_fold(str(r["ngo_name"])).strip()),
                "aliases": r.get("aliases") if isinstance(r.get("aliases"), str) else "",
            }

    created = matched = 0
    for _, row in df.iterrows():
        org_id = str(row["e"]).strip()
        name = str(row["CZ_NAME"]).strip()
        k = match_key(name)
        info = known.get(k)
        dir_name = info["dir_name"] if info else urlnorm.sanitize_dirname(
            ascii_fold(name))
        aliases = info["aliases"] if info else ""

        db.upsert_org(org_id, name, dir_name, aliases)
        if info:
            seed = urlnorm.normalize_url(info["url"])
            db.set_org_fields(
                org_id,
                seed_url=seed or info["url"],
                url_verified=1,
                scope=json.dumps(urlnorm.default_scope(seed or info["url"])),
                state="ready",
            )
            matched += 1
        created += 1

    logger.info(f"Seeded {created} orgs ({matched} with verified URLs from {args.ngo_config})")
    unmatched = [o["name"] for o in db.list_orgs() if not o["seed_url"]]
    logger.info(f"{len(unmatched)} orgs still need URL curation (use the web UI)")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
