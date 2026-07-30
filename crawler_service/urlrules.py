"""URL scope & canonicalization rules — crawler-trap control.

WHY THIS EXISTS
---------------
Several sites in the population expose an effectively infinite URL space by
encoding *presentation state* (sort order, filters, portlet/viewer state,
pagination) in query parameters. The crawler was enumerating those states
rather than discovering content: 96.4% of the remaining frontier (3.26M of
3.38M URLs) was query-string permutations of a small number of real pages —
e.g. 30,000 sampled CZ039 URLs collapsed to just 2 distinct content addresses.

Three tiers of rules, each independently documentable in the methods section:

  1. CONTENT-SCOPE exclusions (per-org path patterns)
     Sections that are outside the domain of policy communication, e.g. the
     České dráhy `/fanshop/` merchandise catalogue. This is a substantive
     scope judgment, not a technical one.

  2. STATE-PARAMETER canonicalization
     Query parameters that control presentation rather than identity are
     stripped before the URL enters the frontier, so all states of a resource
     collapse to one content address. This is CONTENT-PRESERVING: unlike a
     page budget it keeps every distinct content address and removes only
     redundant permutations (a budget truncates arbitrarily and biases which
     content is retained).

  3. PAGINATION DEPTH CAP
     Paginated listings are followed to a bounded depth. Default 100.
     CZ073 uses 30: pagination there was empirically shown to return
     *identical extracted text* beyond the real range (base vs ?strana=200 vs
     ?strana=99999 — the latter two textually identical, similarity 1.000),
     because `?strana=` paginates an exhausted sidebar on a single article.

Byte-level content hashing does NOT catch these (measured 0-42% duplicate
rate) because pages differ by a token or an echoed page number while the
extracted text is unchanged — which is exactly why URL-level rules are needed.
"""

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# ── tier 2: parameters that encode presentation state, not content identity ──
GLOBAL_DROP_PARAMS = {
    # sorting / display
    "order", "sort", "dir", "printable", "force_format", "notify",
    # MediaWiki navigation & history actions
    "returnto", "returntoquery", "mobileaction", "oldid", "diff", "veaction",
    "curid", "action", "printable",
    # generic session/back-link noise
    "back", "_sourcePage",
}

GLOBAL_DROP_PREFIXES = ("p_p_", "p_r_p_", "f[", "_com_liferay")   # portlet state, facet filters
GLOBAL_DROP_SUBSTR = ("ordercolumn", "ordertype")        # Nette datagrid sort state

# Liferay instance-scoped params look like
#   _com_liferay_asset_publisher_..._INSTANCE_<id>_{cur,delta,redirect,resetCur}
# `_cur` is the pagination cursor (content-bearing: it reveals older items and
# must be kept); the rest is render state. `_redirect` is the worst offender —
# it embeds a URL-encoded copy of another paginated URL, which is why one
# listing path exploded into 21,406 frontier entries for ~219 real pages.
KEEP_SUFFIXES = ("_cur",)
GLOBAL_DROP_SUFFIXES = ("_delta", "_redirect", "_resetcur")

# ── tier 3: pagination ──
# Deliberately narrow: `start`/`offset` are excluded because sites use them for
# timestamps (CZ035 had start=20170902103457, which a loose regex misreads as
# page 20 trillion).
PAGINATION_PARAMS = re.compile(r"^(?:strana|page|paged)$|_cur$|-page$", re.I)
DEFAULT_PAGINATION_CAP = 100

# ── per-org rules ──
ORG_RULES: dict[str, dict] = {
    "CZ039": {  # České dráhy — merchandise e-shop, 2.1M filter permutations
        "exclude_paths": ["/fanshop/"],
        "exclude_reason": "content_scope:merchandise_shop",
        "drop_params": {"q"},
    },
    "CZ050": {  # PřF UK — faceted publication search (?f[author]=&s=&o=)
        "drop_params": {"s", "o"},
    },
    "CZ059": {  # Královéhradecký kraj — Nette datagrid + signal params
        "drop_params": {"do", "type"},
    },
    "CZ079": {  # MZV — per-embassy event calendars (infinite month/year/day)
        "drop_params": {"month", "year", "day"},
    },
    "CZ094": {  # Ostrava — /vademecum/ digitised-book viewer state
        "drop_params": {"zanchor", "row", "rowTxt", "activ"},
    },
    "CZ073": {  # PřF UJEP — ?strana= on article pages returns identical text
        "pagination_cap": 30,
    },
    "CZ018": {  # Středočeský kraj — Liferay. Canonicalization alone removes
                # 88.6% with NO content loss, so the cap must NOT bite here:
                # listings run to _cur=219 at _delta=5 items/page (~1,100 real
                # articles). A cap of 100 would silently drop the older half.
        "pagination_cap": 400,
    },
}


def _drop_params_for(org_id: str) -> set:
    return GLOBAL_DROP_PARAMS | set(ORG_RULES.get(org_id, {}).get("drop_params", ()))


def pagination_cap(org_id: str) -> int:
    return ORG_RULES.get(org_id, {}).get("pagination_cap", DEFAULT_PAGINATION_CAP)


def _is_state_param(key: str, drop: set) -> bool:
    k = key.lower()
    # pagination cursors are content-bearing — never strip them
    if any(k.endswith(s) for s in KEEP_SUFFIXES):
        return False
    if key in drop or k in {d.lower() for d in drop}:
        return True
    if any(k.endswith(s) for s in GLOBAL_DROP_SUFFIXES):
        return True
    if any(k.startswith(p.lower()) for p in GLOBAL_DROP_PREFIXES):
        return True
    if any(s in k for s in GLOBAL_DROP_SUBSTR):
        return True
    return False


def canonicalize(url: str, org_id: str) -> str:
    """Strip presentation-state parameters so all states of a resource collapse
    to a single content address. Content-bearing params (ids, titles, slugs,
    pagination) are preserved."""
    try:
        p = urlparse(url)
        if not p.query:
            return url
        drop = _drop_params_for(org_id)
        kept = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                if not _is_state_param(k, drop)]
        return urlunparse((p.scheme, p.netloc, p.path, p.params,
                           urlencode(kept, doseq=True), ""))
    except Exception:
        return url


def pagination_depth(url: str) -> int:
    """Highest pagination index appearing in the URL (0 if unpaginated)."""
    try:
        best = 0
        for k, v in parse_qsl(urlparse(url).query, keep_blank_values=True):
            if PAGINATION_PARAMS.search(k) and v.isdigit():
                # guard against timestamp-like values masquerading as pages
                n = int(v)
                if n < 1_000_000:
                    best = max(best, n)
        return best
    except Exception:
        return 0


def trap_reason(url: str, org_id: str) -> str | None:
    """Return an exclusion reason if this URL is out of scope or a trap.
    None means the URL is crawlable. Excluded URLs are still RECORDED in the
    urls table with this reason — nothing is silently dropped."""
    rules = ORG_RULES.get(org_id, {})
    low = url.lower()
    for pat in rules.get("exclude_paths", ()):
        if pat.lower() in low:
            return rules.get("exclude_reason", f"content_scope:{pat}")
    cap = pagination_cap(org_id)
    d = pagination_depth(url)
    if d > cap:
        return f"pagination_depth>{cap}"
    return None
