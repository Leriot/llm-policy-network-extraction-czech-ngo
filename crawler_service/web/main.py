"""FastAPI web dashboard: live org overview, crawl controls, URL curation,
error reporting, and audit views. LAN-only by design — no auth."""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote_plus

import csv
import io

from fastapi import FastAPI, Form, Request
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse)
from fastapi.templating import Jinja2Templates

from .. import audit as audit_mod
from .. import config, urlnorm
from ..db import Database
from ..manager import CrawlManager

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

db: Database = None
manager: CrawlManager = None


async def _nightly_backup():
    import asyncio
    while True:
        await asyncio.sleep(24 * 3600)
        try:
            target = await asyncio.to_thread(db.backup)
            db.add_event(None, "info", f"database backup written: {target.name}")
        except Exception as e:
            db.add_event(None, "error", f"database backup FAILED: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, manager
    import asyncio
    db = Database()
    manager = CrawlManager(db)
    await manager.startup()
    backup_task = asyncio.create_task(_nightly_backup())
    logger.info(f"dashboard up — data dir {config.DATA_DIR.resolve()}")
    yield
    backup_task.cancel()
    await manager.shutdown()
    db.close()


app = FastAPI(title="COMPON Crawler", lifespan=lifespan)

STATE_ORDER = {"running": 0, "queued": 1, "error": 2, "blocked": 3, "paused": 4,
               "ready": 5, "new": 6, "done": 7}


def _org_rows():
    stats = db.all_org_stats()
    rows = []
    for org in db.list_orgs():
        s = stats.get(org["org_id"], {})
        rows.append({
            "org_id": org["org_id"],
            "name": org["name"],
            "seed_url": org["seed_url"],
            "url_verified": bool(org["url_verified"]),
            "state": org["state"],
            "engine": org["engine"],
            "flagged": bool(org["flagged"]),
            "pages": s.get("pages", 0),
            "pending": s.get("pending", 0),
            "refetch_backlog": s.get("refetch_backlog", 0),
            "done": s.get("done", 0),
            "failed": s.get("failed", 0),
            "excluded": s.get("excluded", 0),
            "files": s.get("files", 0),
            "links": s.get("links", 0),
            "last_activity": s.get("last_activity"),
        })
    rows.sort(key=lambda r: (STATE_ORDER.get(r["state"], 9), r["org_id"]))
    return rows


# --------------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "rows": _org_rows(),
        "gstats": db.global_stats(),
        "running": manager.running_count(),
        "max_concurrent": config.MAX_CONCURRENT_ORGS,
    })


@app.get("/org/{org_id}", response_class=HTMLResponse)
def org_detail(request: Request, org_id: str):
    org = db.get_org(org_id)
    if org is None:
        return HTMLResponse("unknown org", status_code=404)
    report = audit_mod.audit_org(db, org_id)
    events = db.query(
        "SELECT * FROM events WHERE org_id=? ORDER BY id DESC LIMIT 50", (org_id,))
    failures = db.query(
        "SELECT url, http_status, last_error, retries FROM urls "
        "WHERE org_id=? AND status='failed' ORDER BY id DESC LIMIT 50", (org_id,))
    scope_rules = json.loads(org["scope"] or "[]")
    if not scope_rules and org["seed_url"]:
        scope_rules = urlnorm.default_scope(org["seed_url"])
    return templates.TemplateResponse(request, "org.html", {
        "org": org, "report": report, "events": events, "failures": failures,
        "scope_text": "\n".join(scope_rules),
    })


@app.get("/curation", response_class=HTMLResponse)
def curation(request: Request):
    orgs = db.list_orgs()
    todo = [o for o in orgs if not o["url_verified"]]
    done = [o for o in orgs if o["url_verified"]]
    return templates.TemplateResponse(request, "curation.html", {
        "todo": todo, "done": done, "quote_plus": quote_plus,
    })


@app.get("/events", response_class=HTMLResponse)
def events_page(request: Request):
    events = db.query(
        "SELECT * FROM events ORDER BY id DESC LIMIT 300")
    return templates.TemplateResponse(request, "events.html", {"events": events})


# --------------------------------------------------------------------- API
@app.get("/api/orgs")
def api_orgs():
    return JSONResponse({"rows": _org_rows(), "gstats": db.global_stats(),
                         "running": manager.running_count()})


@app.get("/api/audit/{org_id}")
def api_audit(org_id: str):
    return JSONResponse(audit_mod.audit_org(db, org_id))


@app.post("/api/org/{org_id}/start")
async def api_start(org_id: str):
    return JSONResponse({"result": manager.start_org(org_id)})


@app.post("/api/org/{org_id}/pause")
async def api_pause(org_id: str):
    return JSONResponse({"result": manager.pause_org(org_id)})


@app.post("/api/org/{org_id}/retry_failed")
def api_retry_failed(org_id: str):
    n = db.requeue_failed(org_id)
    db.add_event(org_id, "info", f"requeued {n} failed URLs")
    return JSONResponse({"requeued": n})


@app.post("/api/org/{org_id}/queue_refetch")
def api_queue_refetch(org_id: str, mode: str = "hubs"):
    if mode not in ("hubs", "all", "none"):
        return JSONResponse({"error": "mode must be hubs|all|none"}, status_code=400)
    result = db.queue_refetch(org_id, mode)
    db.add_event(org_id, "info",
                 f"refetch policy '{mode}': {result['queued']} queued, "
                 f"{result['demoted']} demoted to archival")
    return JSONResponse(result)


@app.post("/api/start_all")
async def api_start_all():
    return JSONResponse({"started": manager.start_all()})


@app.post("/org/{org_id}/settings")
def org_settings(org_id: str,
                       seed_url: str = Form(""),
                       url_verified: str = Form(""),
                       scope: str = Form(""),
                       engine: str = Form("http"),
                       max_depth: int = Form(config.MAX_DEPTH_DEFAULT),
                       flag_threshold: int = Form(config.FLAG_THRESHOLD_DEFAULT),
                       accept_any_status: str = Form(""),
                       notes: str = Form("")):
    org = db.get_org(org_id)
    if org is None:
        return HTMLResponse("unknown org", status_code=404)
    normalized = urlnorm.normalize_url(seed_url.strip()) if seed_url.strip() else ""
    rules = [r.strip() for r in scope.splitlines() if r.strip()]
    if normalized and not rules:
        rules = urlnorm.default_scope(normalized)
    new_engine = engine if engine in ("http", "browser") else "http"
    state = org["state"]
    if state in ("new", "error") and normalized and url_verified:
        state = "ready"
    if org["engine"] != new_engine and state == "done":
        state = "ready"  # engine change makes a 'done' org worth re-running
    db.set_org_fields(
        org_id,
        seed_url=normalized or seed_url.strip(),
        url_verified=1 if url_verified else 0,
        scope=json.dumps(rules),
        engine=new_engine,
        max_depth=max_depth,
        flag_threshold=flag_threshold,
        flagged=0,
        accept_any_status=1 if accept_any_status else 0,
        notes=notes.strip(),
        state=state,
    )
    db.add_event(org_id, "info", "settings updated")
    if org["engine"] != new_engine:
        # previously fetched pages were seen through the old engine — hub
        # pages must be re-fetched or the new engine never gets a chance
        result = db.queue_refetch(org_id, "hubs")
        db.requeue_failed(org_id)
        db.add_event(org_id, "info",
                     f"engine changed {org['engine']} -> {new_engine}: "
                     f"{result['queued']} hub pages queued for refetch, failed URLs requeued")
    return RedirectResponse(f"/org/{org_id}", status_code=303)


@app.post("/curation/{org_id}")
def curation_save(org_id: str, seed_url: str = Form(...),
                        verified: str = Form("")):
    normalized = urlnorm.normalize_url(seed_url.strip())
    if not normalized:
        return HTMLResponse("invalid URL", status_code=400)
    db.set_org_fields(
        org_id,
        seed_url=normalized,
        url_verified=1 if verified else 0,
        scope=json.dumps(urlnorm.default_scope(normalized)),
        state="ready" if verified else "new",
    )
    db.add_event(org_id, "info",
                 f"seed URL set to {normalized}" + (" (verified)" if verified else ""))
    return RedirectResponse("/curation", status_code=303)


def _csv_response(filename: str, header: list, rows) -> PlainTextResponse:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/org/{org_id}/report/failed.csv")
def report_failed(org_id: str):
    rows = db.query(
        """SELECT url, http_status, last_error, retries, discovered_at, fetched_at
           FROM urls WHERE org_id=? AND status='failed' ORDER BY http_status, url""",
        (org_id,))
    return _csv_response(f"{org_id}_failed_urls.csv",
                         ["url", "http_status", "error", "retries",
                          "discovered_at", "last_attempt"],
                         ([r["url"], r["http_status"], r["last_error"], r["retries"],
                           r["discovered_at"], r["fetched_at"]] for r in rows))


@app.get("/org/{org_id}/report/deleted.csv")
def report_deleted(org_id: str):
    """Pages we hold an archived snapshot of that now return 404/410 — i.e.
    content the organisation has since removed from its site."""
    rows = db.query(
        """SELECT u.url, u.http_status, u.fetched_at last_attempt,
                  p.file_path, p.fetched_at snapshot_taken, p.doc_id
           FROM urls u
           JOIN pages p ON p.org_id = u.org_id AND p.url = u.url
           WHERE u.org_id=? AND u.status='failed' AND u.http_status IN (404, 410)
           GROUP BY u.url HAVING p.fetched_at = MAX(p.fetched_at)
           ORDER BY u.url""",
        (org_id,))
    return _csv_response(f"{org_id}_deleted_content.csv",
                         ["url", "http_status", "last_attempt", "snapshot_doc_id",
                          "snapshot_file", "snapshot_taken"],
                         ([r["url"], r["http_status"], r["last_attempt"], r["doc_id"],
                           r["file_path"], r["snapshot_taken"]] for r in rows))


@app.post("/api/backup")
async def api_backup():
    import asyncio
    target = await asyncio.to_thread(db.backup)
    db.add_event(None, "info", f"manual database backup: {target.name}")
    return JSONResponse({"backup": target.name})


@app.get("/healthz")
def healthz():
    db.query_one("SELECT 1")
    return {"ok": True, "running_orgs": manager.running_count()}
