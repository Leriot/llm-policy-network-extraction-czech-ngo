"""
filter_pass.py — single-pass corpus filter
==========================================
One pass over the crawled HTML producing a queryable index instead of copied
step-directories:

    HTML -> text (saved once) -> date -> org-name hits -> keyword hits -> DB rows

Design
------
* SEPARATE DATABASE (filter.db). The crawler DB stays untouched and uncontended
  — the crawl may still be running — and the whole thing moves to another
  machine by copying two paths.

* TEXT IS SAVED ONCE (text/<org>/<doc_id>.txt). Everything downstream
  (boilerplate v2, typology features, LLM prompts) re-reads that instead of
  re-parsing HTML, which is the expensive part.

* DELIBERATELY OVER-INCLUSIVE. Only <script>/<style>/<noscript> are dropped;
  navigation and footers are kept because boilerplate is detected statistically
  in a second pass (blocks recurring across an org's pages) and applied as a
  FLAG on the hit rows. Stripping it here would be guesswork and irreversible.

* MATCHING IS DIACRITIC-FOLDED, with per-pattern case mode (see
  config/org_dictionary.yaml): `ci` for names, `cs` for abbreviations, because
  folding+lowercasing would make ANO='yes' and STAN='tent'.

* GATE STAYS FROZEN. The co-occurrence gate uses the validated `relations`
  keywords only. Funding-programme terms (OPZP, SFZP, LIFE...) are recorded in
  their own category as evidence/features but do NOT enter the gate, so the
  19-ENGO re-run stays comparable.

Crash safety / resume
---------------------
* A doc is "done" only once its `docs` row is committed; the row is written
  AFTER its text file, so a crash leaves at most an orphan .txt (harmless,
  rewritten on retry) and never a row pointing at a missing file.
* Work is committed in batches; a power cut loses at most one batch, which is
  simply redone. SQLite runs in WAL mode with a busy timeout.
* SIGINT/SIGTERM are caught: the current batch is committed and the process
  exits cleanly rather than leaving a half-written transaction.
* Re-running is always safe: already-indexed doc_ids are skipped.

Politeness to the machine
-------------------------
* --workers controls parallelism (default 2: the corpus lives on spinning
  array disks where extra readers mostly cause seeking, not throughput).
* The process niced itself and pauses when system load exceeds --max-load, so
  it never monopolises a box that is also running other services.

Usage
-----
    python filter_pass.py --crawler-db /db/crawler.db --data /data \
        --out /data/filter --dict config/org_dictionary.yaml \
        --keywords config/content_filter_keywords.yaml --workers 2
    python filter_pass.py ... --status        # progress only
"""

import argparse
import json
import os
import re
import signal
import sqlite3
import sys
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import yaml

# ── text extraction ────────────────────────────────────────────────────────────
COMMENT = re.compile(r"(?s)<!--.*?-->")
DROP = re.compile(r"(?is)<(script|style|noscript)\b[^>]*>.*?</\1\s*>")
BR = re.compile(r"(?i)<(br|/p|/div|/li|/h[1-6]|/tr)\s*/?>")
TAGS = re.compile(r"<[^>]+>")
SPACES = re.compile(r"[ \t\x0b\f\r]+")
NLS = re.compile(r"\n{3,}")

META_DATE = re.compile(
    r"(?is)<meta[^>]+(?:property|name)=[\"'](?:article:published_time|datePublished"
    r"|og:published_time|pubdate|date)[\"'][^>]*content=[\"']([^\"']+)")
TIME_TAG = re.compile(r"(?is)<time[^>]+datetime=[\"']([^\"']+)")
ISO = re.compile(r"(20[0-2]\d)-(\d{2})-(\d{2})")
CZ_DATE = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(20[0-2]\d)\b")
CZ_MONTHS = ("ledna|unora|brezna|dubna|kvetna|cervna|cervence|srpna|zari|rijna"
             "|listopadu|prosince")
CZ_TEXT_DATE = re.compile(rf"\b(\d{{1,2}})\.\s?({CZ_MONTHS})\s+(20[0-2]\d)\b")
MONTH_IDX = {m: i + 1 for i, m in enumerate(CZ_MONTHS.split("|"))}


def fold(s: str) -> str:
    """Strip diacritics; preserve case (case carries meaning for abbreviations)."""
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(c))


def html_to_text(raw: str) -> str:
    t = COMMENT.sub(" ", raw)
    t = DROP.sub(" ", t)
    t = BR.sub("\n", t)
    t = TAGS.sub(" ", t)
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    t = SPACES.sub(" ", t)
    t = "\n".join(ln.strip() for ln in t.split("\n"))
    return NLS.sub("\n\n", t).strip()


def extract_date(raw_html: str, text: str):
    """(iso_date, source) — meta tags are trusted over body text."""
    for rx, src in ((META_DATE, "meta"), (TIME_TAG, "time")):
        m = rx.search(raw_html)
        if m:
            d = ISO.search(m.group(1))
            if d:
                return f"{d.group(1)}-{d.group(2)}-{d.group(3)}", src
    m = CZ_TEXT_DATE.search(fold(text).lower())
    if m:
        return f"{m.group(3)}-{MONTH_IDX[m.group(2)]:02d}-{int(m.group(1)):02d}", "text_cz"
    m = CZ_DATE.search(text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}", "text_num"
    m = ISO.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "text_iso"
    return None, None


# ── matcher ────────────────────────────────────────────────────────────────────
class Matcher:
    """One regex alternation per case-mode; alternatives sorted longest-first so
    the most specific surface form wins."""

    def __init__(self, org_dict: dict, keywords: dict):
        self.org_ci, self.org_cs = {}, {}
        for org_id, v in org_dict.items():
            for p in v.get("patterns", []):
                tgt = self.org_ci if p["mode"] == "ci" else self.org_cs
                key = p["text"].lower() if p["mode"] == "ci" else p["text"]
                tgt.setdefault(key, set()).add(org_id)
        self.kw = {}          # folded lowercase term -> (category, root)
        for cat in ("relations", "funding", "funding_programmes"):
            for entry in keywords.get(cat, []) or []:
                root = entry["root"]
                for term in [root] + list(entry.get("variations", []) or []):
                    t = fold(term).lower().strip()
                    if t:
                        self.kw.setdefault(t, (cat, root))
        self.rx_org_ci = self._compile(self.org_ci)
        self.rx_org_cs = self._compile(self.org_cs)
        self.rx_kw = self._compile(self.kw)

    SHORT = 5   # folded terms below this length must match as whole words

    @classmethod
    def _compile(cls, d):
        if not d:
            return None
        alts = sorted(d, key=len, reverse=True)
        parts = []
        for a in alts:
            esc = re.escape(a)
            # left boundary always; right boundary only for short terms, so
            # "spoluprac" still catches "spolupracovat" but "sit" cannot match
            # inside "position".
            # A left word-boundary ALWAYS: without it "sit" (the folded form
            # of "sit"/"site") matched inside "po-sit-ion". A right boundary
            # only for SHORT terms, so Czech inflection still works
            # ("spoluprac" -> "spolupracovat") while 3-4 letter folded stems
            # cannot bleed into unrelated words ("sit" vs "situace").
            wb = "\\b"
            parts.append(wb + esc + (wb if len(a) < cls.SHORT else ""))
        return re.compile("|".join(parts))

    def scan(self, text: str):
        folded = fold(text)
        low = folded.lower()
        orgs, kws = {}, {}
        if self.rx_org_ci:
            for m in self.rx_org_ci.finditer(low):
                for o in self.org_ci.get(m.group(0), ()):
                    orgs[o] = orgs.get(o, 0) + 1
        if self.rx_org_cs:
            for m in self.rx_org_cs.finditer(folded):
                for o in self.org_cs.get(m.group(0), ()):
                    orgs[o] = orgs.get(o, 0) + 1
        if self.rx_kw:
            for m in self.rx_kw.finditer(low):
                hit = self.kw.get(m.group(0))
                if not hit:
                    continue
                cat, root = hit
                k = (cat, root)
                kws[k] = kws.get(k, 0) + 1
        return orgs, kws


# ── schema ─────────────────────────────────────────────────────────────────────
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS docs (
    doc_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,          -- publisher (whose site it came from)
    url TEXT,
    html_path TEXT,
    text_path TEXT,
    text_chars INTEGER,
    n_lines INTEGER,
    pub_date TEXT,
    date_source TEXT,
    n_other_orgs INTEGER DEFAULT 0,   -- orgs mentioned excluding the publisher
    n_relation_kw INTEGER DEFAULT 0,
    passes_gate INTEGER DEFAULT 0,    -- other org + relation keyword (frozen rule)
    scan_version INTEGER DEFAULT 1,
    indexed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_docs_org ON docs(org_id);
CREATE INDEX IF NOT EXISTS idx_docs_gate ON docs(passes_gate);
CREATE INDEX IF NOT EXISTS idx_docs_date ON docs(pub_date);

CREATE TABLE IF NOT EXISTS doc_orgs (
    doc_id TEXT NOT NULL,
    org_id TEXT NOT NULL,          -- mentioned org
    n_hits INTEGER,
    is_self INTEGER DEFAULT 0,
    in_boilerplate INTEGER DEFAULT 0,
    PRIMARY KEY (doc_id, org_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_doc_orgs_org ON doc_orgs(org_id);

CREATE TABLE IF NOT EXISTS doc_kw (
    doc_id TEXT NOT NULL,
    category TEXT NOT NULL,
    root TEXT NOT NULL,
    n_hits INTEGER,
    in_boilerplate INTEGER DEFAULT 0,
    PRIMARY KEY (doc_id, category, root)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_doc_kw_root ON doc_kw(root);

CREATE TABLE IF NOT EXISTS doc_errors (
    doc_id TEXT PRIMARY KEY,
    org_id TEXT,
    html_path TEXT,
    error TEXT,
    attempts INTEGER DEFAULT 1,
    last_try TEXT
);

CREATE TABLE IF NOT EXISTS runlog (
    ts TEXT, event TEXT, detail TEXT
);
"""

_STOP = {"flag": False}


def _sig(signum, frame):
    _STOP["flag"] = True
    print("\n  signal received — finishing current batch, then exiting cleanly…",
          flush=True)


# ── worker ─────────────────────────────────────────────────────────────────────
_M = None
_CFG = None


def _init(dict_path, kw_path):
    global _M, _CFG
    od = yaml.safe_load(Path(dict_path).read_text(encoding="utf-8"))
    kw = yaml.safe_load(Path(kw_path).read_text(encoding="utf-8"))["keywords"]
    _M = Matcher(od, kw)
    _CFG = True


def _process(job):
    doc_id, org_id, url, html_path, data_root, text_root = job
    try:
        raw = (Path(data_root) / html_path).read_bytes().decode("utf-8", "replace")
    except Exception as e:
        return {"doc_id": doc_id, "org_id": org_id, "html_path": html_path,
                "error": str(e)[:200]}
    text = html_to_text(raw)
    pub_date, date_src = extract_date(raw, text)
    orgs, kws = _M.scan(text)

    tp = Path(text_root) / org_id / f"{doc_id}.txt"
    try:
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text(text, encoding="utf-8")          # file BEFORE db row
    except Exception as e:
        return {"doc_id": doc_id, "org_id": org_id, "html_path": html_path,
                "error": f"write: {e}"[:200]}

    others = {o: n for o, n in orgs.items() if o != org_id}
    n_rel = sum(n for (cat, _), n in kws.items() if cat == "relations")
    return {
        "doc_id": doc_id, "org_id": org_id, "url": url, "html_path": html_path,
        "text_path": str(tp), "text_chars": len(text),
        "n_lines": text.count("\n") + 1,
        "pub_date": pub_date, "date_source": date_src,
        "orgs": orgs, "kws": {f"{c}|{r}": n for (c, r), n in kws.items()},
        "n_other_orgs": len(others), "n_relation_kw": n_rel,
        "passes_gate": int(bool(others) and n_rel > 0),
    }


# ── driver ─────────────────────────────────────────────────────────────────────
def load_todo(crawler_db, out_path, limit=None, exclude_orgs=()):
    """Anti-join in SQL rather than a Python set: on resume this avoids pulling
    4.15M ids into memory just to discard most of them."""
    src = sqlite3.connect(f"file:{crawler_db}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    src.execute("ATTACH DATABASE ? AS f", (str(out_path),))
    total = src.execute(
        "SELECT COUNT(*) FROM pages WHERE doc_id IS NOT NULL "
        "AND file_path IS NOT NULL").fetchone()[0]
    already = src.execute("SELECT COUNT(*) FROM f.docs").fetchone()[0]
    q = ("SELECT p.doc_id, p.org_id, p.url, p.file_path FROM pages p "
         "WHERE p.doc_id IS NOT NULL AND p.file_path IS NOT NULL "
         "AND NOT EXISTS (SELECT 1 FROM f.docs d WHERE d.doc_id = p.doc_id) ")
    params = []
    if exclude_orgs:
        q += "AND p.org_id NOT IN (%s) " % ",".join("?" * len(exclude_orgs))
        params = list(exclude_orgs)
    q += "ORDER BY p.org_id, p.id"
    if limit:
        q += f" LIMIT {int(limit)}"
    todo = [(r["doc_id"], r["org_id"], r["url"], r["file_path"])
            for r in src.execute(q, params)]
    src.close()
    return todo, already, total


def wait_for_load(max_load: float):
    """Pause while the machine is busy so other services keep their share."""
    if not max_load:
        return
    while True:
        try:
            load1 = os.getloadavg()[0]
        except (OSError, AttributeError):
            return
        if load1 <= max_load or _STOP["flag"]:
            return
        time.sleep(15)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crawler-db", required=True)
    ap.add_argument("--data", required=True, help="root that html paths are relative to")
    ap.add_argument("--out", required=True, help="output dir (filter.db + text/)")
    ap.add_argument("--dict", required=True)
    ap.add_argument("--keywords", required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-load", type=float, default=0.0,
                    help="pause while 1-min load average exceeds this (0=off)")
    ap.add_argument("--nice", type=int, default=10)
    ap.add_argument("--exclude-orgs", default="",
                    help="comma-separated org_ids to skip (e.g. orgs still "
                         "being crawled); re-run later to pick them up")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args(argv)

    out_root = Path(args.out)
    text_root = out_root / "text"
    out_root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(out_root / "filter.db", timeout=120)
    db.executescript(SCHEMA)
    db.commit()

    if args.status:
        n = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        g = db.execute("SELECT COUNT(*) FROM docs WHERE passes_gate=1").fetchone()[0]
        d = db.execute("SELECT COUNT(*) FROM docs WHERE pub_date IS NOT NULL").fetchone()[0]
        e = db.execute("SELECT COUNT(*) FROM doc_errors").fetchone()[0]
        print(f"  indexed {n:,} docs | passes gate {g:,} | with date {d:,} "
              f"| failed {e:,}")
        for r in db.execute("SELECT error, COUNT(*) c FROM doc_errors "
                            "GROUP BY substr(error,1,40) ORDER BY c DESC LIMIT 5"):
            print(f"      {r[1]:5}  {r[0][:80]}")
        return 0

    try:
        os.nice(args.nice)
    except Exception:
        pass
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    excl = tuple(x.strip() for x in args.exclude_orgs.split(",") if x.strip())
    todo, already, total = load_todo(args.crawler_db, out_root / 'filter.db',
                                     args.limit, excl)
    if excl:
        print(f"  excluding orgs (still crawling): {', '.join(excl)}")
    print(f"  corpus {total:,} docs | already indexed {already:,} | to do {len(todo):,}")
    print(f"  workers={args.workers} batch={args.batch} nice={args.nice} "
          f"max_load={args.max_load or 'off'}", flush=True)
    if not todo:
        return 0
    db.execute("INSERT INTO runlog VALUES (datetime('now'),'start',?)",
               (json.dumps({"todo": len(todo), "workers": args.workers}),))
    db.commit()

    jobs = [(d, o, u, h, args.data, str(text_root)) for d, o, u, h in todo]
    t0 = time.time()
    done = errors = gated = 0
    pending = []
    err_pending = []

    def flush():
        nonlocal pending, err_pending
        if err_pending:
            db.executemany(
                "INSERT INTO doc_errors (doc_id,org_id,html_path,error,attempts,"
                "last_try) VALUES (?,?,?,?,1,datetime('now')) "
                "ON CONFLICT(doc_id) DO UPDATE SET attempts=attempts+1, "
                "error=excluded.error, last_try=excluded.last_try",
                [(e["doc_id"], e.get("org_id"), e.get("html_path"), e["error"])
                 for e in err_pending])
            err_pending = []
        if not pending:
            db.commit()
            return
        db.executemany(
            "INSERT OR REPLACE INTO docs (doc_id,org_id,url,html_path,text_path,"
            "text_chars,n_lines,pub_date,date_source,n_other_orgs,n_relation_kw,"
            "passes_gate,scan_version,indexed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,"
            "datetime('now'))",
            [(r["doc_id"], r["org_id"], r["url"], r["html_path"], r["text_path"],
              r["text_chars"], r["n_lines"], r["pub_date"], r["date_source"],
              r["n_other_orgs"], r["n_relation_kw"], r["passes_gate"])
             for r in pending])
        db.executemany(
            "INSERT OR REPLACE INTO doc_orgs (doc_id,org_id,n_hits,is_self) "
            "VALUES (?,?,?,?)",
            [(r["doc_id"], o, n, int(o == r["org_id"]))
             for r in pending for o, n in r["orgs"].items()])
        db.executemany(
            "INSERT OR REPLACE INTO doc_kw (doc_id,category,root,n_hits) VALUES (?,?,?,?)",
            [(r["doc_id"], k.split("|", 1)[0], k.split("|", 1)[1], n)
             for r in pending for k, n in r["kws"].items()])
        db.commit()
        pending = []

    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init,
                             initargs=(args.dict, args.keywords)) as ex:
        for res in ex.map(_process, jobs, chunksize=16):
            if res.get("error"):
                errors += 1
                err_pending.append(res)
            else:
                pending.append(res)
                gated += res["passes_gate"]
            done += 1
            if len(pending) + len(err_pending) >= args.batch:
                flush()
                wait_for_load(args.max_load)
            if done % 5000 == 0:
                rate = done / max(time.time() - t0, 1e-9)
                eta = (len(jobs) - done) / rate / 3600 if rate else 0
                print(f"    {done:,}/{len(jobs):,}  {rate:.0f} docs/s  "
                      f"gate={gated:,}  err={errors}  eta {eta:.1f}h", flush=True)
            if _STOP["flag"]:
                break
    flush()
    db.execute("INSERT INTO runlog VALUES (datetime('now'),'stop',?)",
               (json.dumps({"done": done, "errors": errors, "gated": gated}),))
    db.commit()
    el = time.time() - t0
    print(f"\n  indexed {done:,} docs in {el/3600:.2f}h "
          f"({done/max(el,1e-9):.0f}/s) | gate passed {gated:,} | errors {errors}")
    print(f"  -> {out_root/'filter.db'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
