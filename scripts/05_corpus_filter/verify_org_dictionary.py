"""
verify_org_dictionary.py
========================
Empirically test the org dictionary against the real corpus, because guessing
which patterns are "too short" or "too broad" from the string alone is
unreliable ("arnik" looks risky but is fine; "praha" looks fine but matches
every Czech page).

Two measurements per pattern, from a random sample of real pages:

  SELF-HIT   share of the org's OWN pages where its own pattern fires.
             Near zero => the pattern is broken, or the org never names itself
             on its own site (both need a human look).

  BREADTH    share of ALL sampled pages, across every org, where it fires.
             High => the pattern is a common word / boilerplate token and will
             flood the filter with false positives.

A good identifying pattern has HIGH self-hit and LOW breadth.

Usage (on the server, where the corpus lives):
    python verify_org_dictionary.py --dict org_dictionary.yaml --db /db/crawler.db \
        --data /data --per-org 150 --out verify_report.json
"""

import argparse
import json
import random
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import yaml

TAG = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
TAGS = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def fold(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def page_text(path: Path) -> str:
    try:
        raw = path.read_bytes().decode("utf-8", errors="replace")
    except Exception:
        return ""
    raw = TAG.sub(" ", raw)
    raw = TAGS.sub(" ", raw)
    return WS.sub(" ", fold(raw))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dict", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--data", required=True, help="root that file_path is relative to")
    ap.add_argument("--per-org", type=int, default=150)
    ap.add_argument("--out", default="verify_report.json")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    random.seed(args.seed)
    doc = yaml.safe_load(Path(args.dict).read_text(encoding="utf-8"))
    data_root = Path(args.data)

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # ---- sample pages per org -------------------------------------------
    sample: list[tuple[str, str]] = []          # (owner_org, file_path)
    for org_id in doc:
        rows = conn.execute(
            "SELECT file_path FROM urls WHERE org_id=? AND status='done' "
            "AND file_path IS NOT NULL AND COALESCE(out_of_scope,0)=0 LIMIT 4000",
            (org_id,)).fetchall()
        if not rows:
            continue
        picks = random.sample(rows, min(args.per_org, len(rows)))
        sample += [(org_id, r["file_path"]) for r in picks]
    print(f"  sampled {len(sample)} pages across "
          f"{len({o for o, _ in sample})} orgs", flush=True)

    # ---- flatten patterns ------------------------------------------------
    pats = []            # (org_id, text_for_search, mode, kind)
    for org_id, v in doc.items():
        for p in v.get("patterns", []):
            t = p["text"] if p["mode"] == "cs" else p["text"].lower()
            pats.append((org_id, t, p["mode"], p["kind"], p["text"]))

    hits_self = defaultdict(int)      # (org,pat) -> pages of that org hit
    hits_any = defaultdict(int)       # (org,pat) -> pages of ANY org hit
    pages_per_org = defaultdict(int)
    orgs_hit_by = defaultdict(set)    # (org,pat) -> set of owner orgs hit

    for i, (owner, fp) in enumerate(sample, 1):
        txt = page_text(data_root / fp)
        if not txt:
            continue
        low = txt.lower()
        pages_per_org[owner] += 1
        for org_id, needle, mode, kind, orig in pats:
            hay = txt if mode == "cs" else low
            if needle in hay:
                key = (org_id, orig, mode, kind)
                hits_any[key] += 1
                orgs_hit_by[key].add(owner)
                if owner == org_id:
                    hits_self[key] += 1
        if i % 2000 == 0:
            print(f"    scanned {i}/{len(sample)}", flush=True)

    total_pages = sum(pages_per_org.values())

    # ---- report -----------------------------------------------------------
    report = []
    for org_id, v in doc.items():
        own = pages_per_org.get(org_id, 0)
        for p in v.get("patterns", []):
            key = (org_id, p["text"], p["mode"], p["kind"])
            self_rate = (hits_self[key] / own) if own else None
            breadth = hits_any[key] / total_pages if total_pages else 0
            report.append({
                "org_id": org_id, "org": v["name"], "pattern": p["text"],
                "mode": p["mode"], "kind": p["kind"],
                "own_pages_sampled": own,
                "self_hit_rate": round(self_rate, 3) if self_rate is not None else None,
                "breadth": round(breadth, 4),
                "orgs_hit": len(orgs_hit_by[key]),
            })

    Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False),
                              encoding="utf-8")

    too_broad = [r for r in report if r["breadth"] > 0.15]
    dead = [r for r in report if r["own_pages_sampled"] >= 20
            and (r["self_hit_rate"] or 0) < 0.05]
    orgs_no_signal = []
    for org_id, v in doc.items():
        rs = [r for r in report if r["org_id"] == org_id]
        if rs and rs[0]["own_pages_sampled"] >= 20 and \
           max((r["self_hit_rate"] or 0) for r in rs) < 0.05:
            orgs_no_signal.append((org_id, v["name"]))

    print(f"\n  === TOO BROAD (fires on >15% of ALL pages) — {len(too_broad)}")
    for r in sorted(too_broad, key=lambda x: -x["breadth"])[:25]:
        print(f"    {r['breadth']*100:5.1f}%  {r['org_id']} [{r['mode']}] "
              f"{r['pattern'][:38]:40} ({r['kind']})")
    print(f"\n  === DEAD PATTERNS (org's own pages, <5% self-hit) — {len(dead)}")
    for r in sorted(dead, key=lambda x: x["org_id"])[:25]:
        print(f"    self={r['self_hit_rate']:.2f}  {r['org_id']} [{r['mode']}] "
              f"{r['pattern'][:38]:40} ({r['kind']})")
    print(f"\n  === ORGS WITH NO WORKING PATTERN AT ALL — {len(orgs_no_signal)}")
    for oid, nm in orgs_no_signal:
        print(f"    {oid}  {nm[:60]}")
    print(f"\n  full report -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
