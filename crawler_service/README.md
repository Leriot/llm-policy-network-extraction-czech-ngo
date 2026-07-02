# COMPON Crawler Service

Full-population web corpus collection for all ~119 COMPON organisations.
Replaces the thesis-era `scripts/01_scrape` + `modules/scraping` pipeline with a
crash-safe, auditable, dashboard-controlled crawler designed to run for weeks
in a Docker container on an Unraid server.

## Design principles (agreed 2026-07-02)

- **Scrape everything, filter later.** No page budgets, no org exclusions, no
  priority-based skipping. Every URL that *is* excluded (robots.txt, admin
  pages, depth, non-HTML) gets a database row with a reason — nothing is
  silently dropped, so the "full data" claim is defensible.
- **SQLite (WAL) is the single source of truth.** The frontier, visit ledger,
  hyperlink edges, file-link registry, and event log all live in `crawler.db`.
  A crash loses at most one in-flight page; restart resumes automatically.
- **Refetch ≠ re-save.** Previously fetched pages (including the imported
  thesis corpus) are re-fetched for *link discovery* — news indexes change —
  but a new snapshot file is only written when the content hash changed.
  Default policy is **hubs**: only listing/section/pagination pages (path
  depth ≤ 2 or pagination patterns) are re-fetched; deep article pages remain
  archival snapshots. `⟳ Refetch all` per org overrides this, and
  `python -m crawler_service.refetch --mode hubs|all|none` applies it in bulk.
- **Every snapshot is timestamped.** `pages.fetched_at` records when the
  content was actually obtained from the web (imported v1 pages keep their
  original 2025/26 scrape times from the manifests); `urls.discovered_at` /
  `fetched_at` track frontier provenance.
- **Politeness preserved:** 2s per-domain delay, robots.txt respected,
  academic User-Agent. Orgs crawl in parallel; each domain is serial.

## Layout on disk

```
/data                        <- CRAWLER_DATA_DIR (volume in Docker)
  crawler.db                 <- the database (WAL)
  raw/<OrgDirName>/pages/NNNNN_slug.html   <- same naming as the v1 corpus
```

## Local usage (Windows dev box)

```powershell
# 1. seed the org table (idempotent)
python -m crawler_service.seed --xlsx COMPON_Orgs.xlsx --ngo-config config/ngo_config.csv

# 2. one-time import of the thesis-era corpus (idempotent, skips done orgs)
python -m crawler_service.importer

# 3. run the dashboard + crawler
python -m crawler_service        # -> http://localhost:8055

# completeness audit (also visible per-org in the dashboard)
python -m crawler_service.audit --org CZ051
```

Environment overrides: `CRAWLER_DATA_DIR`, `CRAWLER_DELAY`,
`CRAWLER_MAX_CONCURRENT_ORGS`, `CRAWLER_MAX_DEPTH`, `CRAWLER_FLAG_THRESHOLD`,
`CRAWLER_DEV_MAX_PAGES` (testing only), `CRAWLER_WEB_PORT`.

## Workflow for the full run

1. **URL curation** (`/curation`): enter + manually verify the homepage of each
   of the ~100 new orgs. The 19 ENGO URLs are pre-verified from the thesis
   config. Only verified orgs can start.
2. **Start crawls** from the dashboard (`Start all ready orgs` or per-org).
   `CRAWLER_MAX_CONCURRENT_ORGS` (default 6) crawl at once; the rest queue.
3. **Watch the dashboard**: failed counts, `⚑` flags (page threshold crossed —
   flag only, never stops), redirect-out-of-scope warnings (add a scope rule on
   the org page if the domain belongs to the org), suspiciously low page counts
   (switch the org to the `browser` engine for JS-rendered sites).
4. **Audit** per org: coverage %, backlog, failures by type, exclusions by
   reason, sitemap coverage.

## Deployment on Unraid

```bash
# on the server
rsync -a <windows>/paper_conversion/data/ /mnt/user/research/compon-crawl/   # corpus + crawler.db
cd /path/to/repo/crawler_service
docker compose up -d --build
# dashboard: http://<server>:8055  (LAN only — no auth!)
```

Container auto-resumes running orgs after restart (`restart: unless-stopped` +
startup recovery), so reboots are safe.

## Database quick reference

| table        | contents |
|--------------|----------|
| `orgs`       | seed URL, verified flag, scope rules (JSON), engine, state, thresholds |
| `urls`       | every discovered URL: status (pending/in_progress/done/failed/excluded), reason, depth, parent, hash, file path, retries |
| `pages`      | immutable snapshots (a URL can have several over time) |
| `links`      | deduplicated hyperlink edges + occurrence counts (network layer) |
| `file_links` | PDFs/docs seen on pages — registered, **not** downloaded (future multiplex layer) |
| `events`     | operational log (shown in dashboard) |
| `fetch_fail` | per-attempt failure history |

Useful queries:

```sql
-- did we get everything?
SELECT org_id, COUNT(*) FROM urls WHERE status='pending' GROUP BY org_id;
-- latest snapshot per URL for corpus building
SELECT url, file_path FROM urls WHERE org_id='CZ051' AND status='done' AND file_path IS NOT NULL;
```
