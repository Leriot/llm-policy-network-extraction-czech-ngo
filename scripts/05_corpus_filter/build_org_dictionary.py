"""
build_org_dictionary.py
=======================
Generate the organisation-name matching dictionary for the corpus filter.

Design decisions this encodes
-----------------------------
* MATCHING IS DIACRITIC-FOLDED. Czech web text is inconsistent ("Ceska" vs
  "Česká", OCR noise, missing háčky). Both the text and the patterns are folded
  to ASCII before matching. This raises recall and costs some precision, which
  is the agreed trade — the LLM ensemble is the precision stage.

* CASE MATTERS FOR ABBREVIATIONS, AND ONLY FOR THEM. Folding + lowercasing
  everything would make `ANO` (the party) identical to `ano` ("yes") and `STAN`
  identical to `stan` ("tent") — each would match millions of pages. So every
  pattern carries a mode:
      ci = case-insensitive  (full names: "hnuti duha", "arnika")
      cs = case-sensitive    (abbreviations: "ANO", "STAN", "CSOP", "CEZ")

* STEMS, NOT EXACT FORMS. Czech declines names (Arnika/Arniky/Arnikou), so
  full-name patterns are truncated to a safe stem where that is unambiguous.

* THE 19 THESIS ORGS KEEP THEIR VALIDATED PATTERNS so the re-run stays
  comparable; new orgs get generated candidates for human review.

Output: config/org_dictionary.yaml   (review + edit by hand, then verify)
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import yaml

PROJECT = Path(__file__).resolve().parent.parent.parent
OUT = PROJECT / "config" / "org_dictionary.yaml"

# Abbreviations that collide with ordinary Czech words. These MUST be matched
# case-sensitively, and even then need LLM/context disambiguation.
CZECH_WORD_COLLISIONS = {
    "ANO": "ano = 'yes'",
    "STAN": "stan = 'tent'",
    "MOST": "most = 'bridge'",
    "PRO": "pro = 'for'",
    "TOP": "top",
    "CI2": "low risk but very short",
    "EPH": "short",
    "MND": "short",
    "ODS": "short",
    "CEPS": "short",
    "SEI": "short",
    "OTE": "short",
}

# Orgs whose real-world name IS an ambiguous abbreviation. The generator cannot
# invent these safely, and omitting them loses nearly every mention. Supplied
# case-sensitively so "ANO" != "ano" ("yes") and "STAN" != "stan" ("tent").
MANUAL_ABBREV = {
    "CZ007": [("ANO", "cs"), ("hnuti ANO", "ci")],
    "CZ140": [("STAN", "cs"), ("Starostove a nezavisli", "ci")],
    "CZ090": [("ODS", "cs")],
    "CZ114": [("TOP 09", "ci")],
    "CZ075": [("KDU-CSL", "cs"), ("lidovci", "ci")],
    "CZ036": [("KSCM", "cs")],
    "CZ109": [("SOCDEM", "cs"), ("CSSD", "cs")],
    "CZ134": [("Pirati", "ci"), ("piratska strana", "ci")],
    "CZ057": [("Strana zelenych", "ci"), ("Zeleni", "cs")],
    "CZ024": [("CEZ", "cs")],
    "CZ048": [("E.ON", "ci"), ("eon energie", "ci")],   # domain token "eon" is 3 chars
    "CZ135": [("EPH", "cs"), ("Energeticky a prumyslovy holding", "ci")],
    "CZ084": [("MND", "cs")],
    "CZ204": [("CEPS", "cs")],
    "CZ091": [("OTE", "cs")],
    "CZ049": [("ERU", "cs"), ("Energeticky regulacni urad", "ci")],
    # cities/regions: bare toponyms are useless (every page says "Praha"),
    # so match the INSTITUTION, not the place
    "CZ098": [("magistrat hlavniho mesta prahy", "ci"), ("hlavni mesto praha", "ci"),
              ("hl. m. praha", "ci")],
    "CZ013": [("magistrat mesta brna", "ci"), ("statutarni mesto brno", "ci")],
    "CZ094": [("magistrat mesta ostravy", "ci"), ("statutarni mesto ostrava", "ci")],

    # Ministries: the short forms (MZP/MZe/MD/MF) are too ambiguous, but the
    # full titles are unmistakable even though they appear on many pages —
    # frequency is not ambiguity.
    "CZ080": [("ministerstvo zivotniho prostredi", "ci"), ("MZP", "cs")],
    "CZ086": [("ministerstvo zemedelstvi", "ci")],
    "CZ083": [("ministerstvo prumyslu a obchodu", "ci"), ("MPO", "cs")],
    "CZ081": [("ministerstvo dopravy", "ci")],
    "CZ082": [("ministerstvo financi", "ci")],
    "CZ079": [("ministerstvo zahranicnich veci", "ci"), ("MZV", "cs")],

    # Regions: the full "<Adjective> kraj" form is distinctive.
    "CZ059": [("kralovehradecky kraj", "ci")],
    "CZ085": [("moravskoslezsky kraj", "ci")],
    "CZ108": [("jihomoravsky kraj", "ci")],
    "CZ018": [("stredocesky kraj", "ci")],
    "CZ127": [("ustecky kraj", "ci")],
    "CZ131": [("kraj vysocina", "ci")],
    "CZ132": [("zlinsky kraj", "ci")],
    "CZ093": [("olomoucky kraj", "ci")],
    "CZ095": [("pardubicky kraj", "ci")],
    "CZ097": [("plzensky kraj", "ci")],
    "CZ104": [("jihocesky kraj", "ci")],
    "CZ076": [("karlovarsky kraj", "ci")],
    "CZ077": [("liberecky kraj", "ci")],

    # Academic units. The DB name is "Unit, Parent University", which nobody
    # writes; the unit name alone is what appears in text. These 10 orgs had
    # ZERO working patterns in the first verification pass.
    "CZ035": [("centrum pro otazky zivotniho prostredi", "ci"), ("COZP", "cs")],
    "CZ041": [("katedra environmentalnich studii", "ci")],   # "enviro" alone was 18% breadth
    "CZ072": [("ustav vodniho hospodarstvi krajiny", "ci"), ("UVHK", "cs")],
    "CZ043": [("katedra fyziky atmosfery", "ci")],
    "CZ053": [("geologicky ustav akademie ved", "ci"), ("geologicky ustav av", "ci")],
    "CZ063": [("ustav fyziky atmosfery", "ci")],
    "CZ065": [("ustav geologickych ved", "ci")],
    "CZ071": [("vyzkumny ustav vodohospodarsky", "ci"), ("VUV TGM", "ci")],
    "CZ072": [("ustav vodniho hospodarstvi krajiny", "ci")],
    "CZ123": [("fakulta zivotniho prostredi", "ci")],
    "CZ203": [("KMVES", "cs"),
              ("katedra mezinarodnich vztahu a evropskych studii", "ci")],
    # NOTE CZ050 (PrF UK) and CZ073 (PrF UJEP) are BOTH "Prirodovedecka
    # fakulta" — the bare phrase cannot separate them, so each requires its
    # university qualifier. Flagged for human review.
    "CZ050": [("prirodovedecka fakulta univerzity karlovy", "ci"),
              ("prirodovedecke fakulty uk", "ci")],
    "CZ073": [("prirodovedecka fakulta ujep", "ci"),
              ("prirodovedecke fakulty ujep", "ci")],
}

# Measured breadth from verify_org_dictionary.py (share of a 12,735-page random
# sample a pattern fires on). Used to drop LEXICALLY AMBIGUOUS patterns.
# Ambiguity != frequency: "ministerstvo zivotniho prostredi" is frequent but
# unmistakable, while "SK"/"AC"/"VE" are short tokens that fire on 80-100 orgs.
MEASURED_NOISE = {
    # pattern -> measured breadth, all short tokens hitting dozens of orgs
    "VE", "SA", "SK", "AC", "UK", "OK", "VS", "OU", "SU", "SZ", "ZK", "MZ",
    "MK", "CD", "ANO", "ERU", "CG", "SB", "ZS", "KK", "HJ", "AKC", "AES",
    "ZSC", "CBCSB", "CSZP", "KZPSC", "CVGZAV", "CHUAV", "COZPKU", "KESMU",
    "TSC", "starostove", "enviro", "STAN",
}

# Validated patterns from the thesis (scripts/02_filter_clean/04_filter_ngo_proximity.py).
# Kept verbatim in spirit so the 19-ENGO re-run remains comparable.
THESIS_PATTERNS = {
    "Aliance pro energetickou sobestacnost": [("AliES", "cs")],
    "Arnika": [("arnik", "ci")],
    "Autoklub CR": [("autoklub", "ci")],
    "Beleco": [("belec", "ci")],
    "Calla - Sdruzeni pro zachranu prostredi": [("calla", "ci"), ("cally", "ci"), ("calle", "ci")],
    "Centrum pro dopravu a energetiku": [("CDE", "cs"), ("centrum pro dopravu", "ci")],
    "Cesky svaz ochrancu prirody": [("CSOP", "cs"), ("svaz ochrancu prirod", "ci")],
    "CI2": [("CI2", "cs")],
    "Ekologicky institut Veronica": [("veronic", "ci")],
    "Extinction Rebellion [Posledni generace]": [("extinction rebellion", "ci"),
                                                  ("posledni generac", "ci")],
    "Fakta o klimatu": [("fakta o klimatu", "ci")],
    "Frank Bold": [("frank bold", "ci")],
    "Fridays for Future": [("FFF", "cs"), ("fridays for future", "ci")],
    "Greenpeace CR": [("greenpeace", "ci")],
    "Hnuti Duha": [("hnuti duha", "ci")],
    "Klimaticka koalice": [("klimaticka koalic", "ci"), ("klimaticke koalic", "ci")],
    "Limity jsme my": [("limity jsme my", "ci")],
    "Nesehnuti": [("nesehnut", "ci")],
    "Zeleny kruh": [("zeleny kruh", "ci"), ("zeleneho kruh", "ci")],
}

# Words that carry no identifying power on their own — never emit as a pattern.
STOP_TOKENS = {
    "cr", "ceske", "cesky", "ceska", "ceskych", "ceskeho", "republiky", "republika",
    "a", "pro", "na", "v", "ve", "o", "s", "se", "z", "za", "the", "of",
    "svaz", "sdruzeni", "asociace", "komora", "unie", "spolek", "institut",
    "centrum", "ustav", "fakulta", "katedra", "univerzita", "akademie", "ved",
    "ministerstvo", "kraj", "krajsky", "urad", "mesto", "obec", "group", "as",
    "sro", "ops", "zs", "spolecnost", "nadace", "fond", "agentura",
}


def fold(s: str) -> str:
    """Strip diacritics -> ASCII (Č->C, ř->r). Case is preserved."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def domain_token(seed_url: str) -> str | None:
    """Registrable name from the seed URL: arnika.org -> 'arnika'."""
    if not seed_url:
        return None
    m = re.search(r"https?://([^/]+)", seed_url)
    if not m:
        return None
    host = m.group(1).lower().removeprefix("www.")
    parts = host.split(".")
    if not parts:
        return None
    tok = parts[0]
    # for subdomained sites (enviro.fss.muni.cz) the first label is the unit
    return tok if len(tok) >= 3 else None


def acronym(name: str) -> str | None:
    """Initials of the significant words: 'Svaz prumyslu a dopravy' -> 'SPD'."""
    words = [w for w in re.split(r"[\s\-,]+", fold(name)) if w]
    sig = [w for w in words if w.lower() not in {"a", "pro", "na", "v", "ve", "o",
                                                  "s", "se", "z", "za", "the", "of"}]
    if len(sig) < 2:
        return None
    ac = "".join(w[0].upper() for w in sig if w[:1].isalpha())
    return ac if 2 <= len(ac) <= 6 else None


def name_stem(name: str) -> str | None:
    """Longest distinctive prefix of a single-word name, for declension.
    'Nesehnuti' -> 'nesehnut'. Multi-word names are handled as phrases."""
    f = fold(name).lower().strip()
    if " " in f or len(f) < 5:
        return None
    # trim 1-2 trailing vowels which are the usual declension endings
    return re.sub(r"[aeiouy]{1,2}$", "", f) or None


def build_for_org(org: dict) -> dict:
    name = org["name"]
    seed = org.get("seed_url") or ""
    pats: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(text, mode, kind):
        t = fold(text).strip()
        if not t:
            return
        key = (t.lower(), mode)
        if key in seen:
            return
        seen.add(key)
        pats.append({"text": t, "mode": mode, "kind": kind})

    # 1. validated thesis patterns take priority (match on folded name: the DB
    #    stores "Greenpeace ČR" while the thesis key is ASCII "Greenpeace CR")
    thesis_key = next((k for k in THESIS_PATTERNS
                       if fold(k).lower() == fold(name).lower()), None)
    if thesis_key:
        for t, mode in THESIS_PATTERNS[thesis_key]:
            add(t, mode, "thesis")

    # 2. the full folded name (phrase match, case-insensitive)
    folded = fold(name).lower()
    folded = re.sub(r"\s*\[.*?\]\s*", " ", folded).strip()   # drop "[Posledni generace]"
    folded = re.sub(r"\s+-\s+.*$", "", folded).strip()        # drop " - subtitle"
    if len(folded) >= 5:
        add(folded, "ci", "fullname")

    # 3. single-word name -> declension stem
    st = name_stem(folded)
    if st and st not in STOP_TOKENS:
        add(st, "ci", "stem")

    # 4. domain token (often the real short name: autosap, alies, czechglobe)
    dt = domain_token(seed)
    if dt and dt not in STOP_TOKENS and len(dt) >= 4:
        add(dt, "ci", "domain")

    # 4b. manual abbreviations for orgs known only by an ambiguous short form
    for t, mode in MANUAL_ABBREV.get(org["org_id"], []):
        add(t, mode, "manual")

    # 5. acronym (case-sensitive — this is where the dangerous ones live)
    ac = acronym(name)
    if ac:
        add(ac, "cs", "acronym")

    # Drop patterns measured as lexically ambiguous (short tokens firing across
    # dozens of unrelated orgs). Thesis patterns are exempt: they are validated
    # and changing them would break comparability with the 19-ENGO run.
    pats = [p for p in pats
            if p["kind"] == "thesis" or p["text"] not in MEASURED_NOISE]

    # Generated acronyms proved mostly dead (54 of 85 never fired on the org's
    # own pages) and the survivors were mostly noise, so drop the generator's
    # acronyms entirely and rely on MANUAL_ABBREV for real short forms.
    pats = [p for p in pats if p["kind"] != "acronym"]

    # For city/region orgs the bare toponym matches every Czech page; keep only
    # the institutional forms supplied manually.
    if org["org_id"] in {"CZ098", "CZ013", "CZ094"}:
        pats = [p for p in pats if p["kind"] == "manual"]

    # risk assessment
    risks = []
    for p in pats:
        u = p["text"].upper()
        if u in CZECH_WORD_COLLISIONS:
            risks.append(f"{p['text']}: {CZECH_WORD_COLLISIONS[u]}")
        elif p["mode"] == "ci" and len(p["text"]) <= 5 and " " not in p["text"]:
            risks.append(f"{p['text']}: very short case-insensitive pattern")
    risk = "HIGH" if risks else ("review" if not thesis_key else "validated")

    return {
        "name": name,
        "seed_url": seed,
        "verified": bool(thesis_key),
        "risk": risk,
        "risk_notes": risks,
        "patterns": pats,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--orgs-json", required=True, help="JSON dump of the orgs table")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    orgs = json.loads(Path(args.orgs_json).read_text(encoding="utf-8"))
    doc = {}
    for o in orgs:
        if not (o.get("seed_url") or "").strip() and o["org_id"] not in ("CZ121",):
            pass  # keep even URL-less orgs: they can still be MENTIONED by others
        doc[o["org_id"]] = build_for_org(o)

    Path(args.out).write_text(
        "# Organisation matching dictionary — REVIEW BEFORE USE.\n"
        "# mode: ci = case-insensitive (folded), cs = case-sensitive (abbreviations)\n"
        "# risk: HIGH = pattern collides with common Czech words; check before enabling\n"
        + yaml.safe_dump(doc, allow_unicode=True, sort_keys=True, width=100),
        encoding="utf-8")

    n_pat = sum(len(v["patterns"]) for v in doc.values())
    high = [k for k, v in doc.items() if v["risk"] == "HIGH"]
    print(f"  {len(doc)} orgs, {n_pat} patterns -> {args.out}")
    print(f"  validated (thesis): {sum(1 for v in doc.values() if v['verified'])}")
    print(f"  HIGH risk (need review): {len(high)} -> {', '.join(high)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
