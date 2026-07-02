"""Candidate homepage URLs for the wave-2 orgs — proposals for human
verification in the /curation UI, not ground truth. Load with:

    python -m crawler_service.url_candidates          # fills empty seed_urls
    python -m crawler_service.url_candidates --probe  # + live-check every URL

Notes:
- CZ022 and CZ099 are both organisationally vlada.cz — decide during curation
  whether to crawl the site under one org (recommended) or both.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from . import urlnorm
from .db import Database

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CANDIDATES = {
    "CZ001": "https://autosap.cz/",                      # Sdruzeni automobiloveho prumyslu
    "CZ002": "https://www.akcr.cz/",                     # Agrarni komora CR
    "CZ005": "https://www.zscr.cz/",                     # Zemedelsky svaz CR
    "CZ007": "https://www.anobudelip.cz/",               # ANO 2011
    "CZ012": "https://biom.cz/",                         # CZ Biom
    "CZ013": "https://www.brno.cz/",                     # Brno
    "CZ014": "https://www.antarcticfoundation.cz/",      # Cesky antarkticky nadacni fond (user-corrected)
    "CZ018": "https://www.stredoceskykraj.cz/",          # Stredocesky kraj
    "CZ021": "https://www.kzps.cz/",                     # KZPS
    "CZ022": "https://vlada.gov.cz/",                    # Vlada - evropske zalezitosti (shared with CZ099)
    "CZ024": "https://www.cez.cz/",                      # CEZ Group
    "CZ025": "https://sanceprobudovy.cz/",               # Sance pro budovy
    "CZ026": "https://www.czechglobe.cz/",               # CzechGlobe AV CR
    "CZ027": "https://cgs.gov.cz/",                     # Ceska geologicka sluzba (moved to gov.cz)
    "CZ028": "https://www.tscr.cz/",                     # Teplarenske sdruzeni
    "CZ029": "https://www.chmi.cz/",                     # CHMU
    "CZ032": "https://www.cmkos.cz/",                    # CMKOS
    "CZ033": "https://www.cgoa.cz/",                     # Cesky plynarensky svaz
    "CZ034": "https://www.komora.cz/",                   # Hospodarska komora
    "CZ035": "https://www.czp.cuni.cz/",                 # Centrum pro otazky ZP UK
    "CZ036": "https://www.kscm.cz/",                     # KSCM
    "CZ037": "https://www.pakt-starostu.cz/",   # Pakt starostu (verify!)
    "CZ038": "https://cefas.cz/",                        # Ceska fotovoltaicka asociace (user-corrected)
    "CZ039": "https://www.cd.cz/",                       # Ceske drahy
    "CZ041": "https://enviro.fss.muni.cz/",              # Katedra environmentalnich studii MU
    "CZ042": "https://fvt.unob.cz/fakulta/struktura/katedra-vojenske-geografie-a-meteorologie-k-210/",  # dept page, path-scoped (user)
    "CZ043": "https://kfa.mff.cuni.cz/",                 # Katedra fyziky atmosfery UK
    "CZ045": "https://www.eazk.cz/",                     # Energeticka agentura ZK
    "CZ046": "https://os-echo.cz/",                   # OS ECHO
    "CZ047": "https://www.ieep.cz/",                     # IEEP (verify!)
    "CZ048": "https://www.eon.cz/",                      # E.ON
    "CZ049": "https://eru.gov.cz/",                      # ERU
    "CZ050": "https://www.natur.cuni.cz/",               # PrF UK
    "CZ053": "https://www.gli.cas.cz/",                  # Geologicky ustav AV
    "CZ054": "https://glopolis.org/",                    # Glopolis
    "CZ057": "https://www.zeleni.cz/",                   # Strana Zelenych
    "CZ058": "https://www.hornijiretin.cz/",             # Horni Jiretin
    "CZ059": "https://www.khk.cz/",                      # Kralovehradecky kraj (verify!)
    "CZ061": "https://hyundai-motor.cz/",                # HMMC (verify!)
    "CZ063": "https://www.ufa.cas.cz/",                  # Ustav fyziky atmosfery AV
    "CZ065": "https://ugv.sci.muni.cz/",             # Ustav geologickych ved MU (verify!)
    "CZ066": "https://geogr.sci.muni.cz/",                   # Geograficky ustav MU
    "CZ068": "https://www.politikaspolecnost.cz/",       # Institut pro politiku a spolecnost
    "CZ071": "https://www.vuv.cz/",                      # VUV TGM
    "CZ072": "https://www.fce.vutbr.cz/",                # UVHK VUT (faculty site) (verify!)
    "CZ073": "https://prf.ujep.cz/",                     # PrF UJEP
    "CZ075": "https://www.kdu.cz/",                      # KDU-CSL
    "CZ076": "https://www.kr-karlovarsky.cz/",           # Karlovarsky kraj
    "CZ077": "https://www.kraj-lbc.cz/",                 # Liberecky kraj
    "CZ078": "https://www.mulitvinov.cz/",               # Litvinov
    "CZ079": "https://mzv.gov.cz/",                      # MZV
    "CZ080": "https://mzp.gov.cz/",                      # MZP
    "CZ081": "https://md.gov.cz/",                       # Ministerstvo dopravy
    "CZ082": "https://mf.gov.cz/",                     # Ministerstvo financi (verify: mfcr.cz)
    "CZ083": "https://mpo.gov.cz/",                      # MPO
    "CZ084": "https://www.mnd.eu/",                      # MND
    "CZ085": "https://www.msk.cz/",                      # Moravskoslezsky kraj
    "CZ086": "https://mze.gov.cz/",                      # Ministerstvo zemedelstvi
    "CZ090": "https://www.ods.cz/",                      # ODS
    "CZ091": "https://www.ote-cr.cz/",                   # OTE
    "CZ093": "https://www.olkraj.cz/",                   # Olomoucky kraj
    "CZ094": "https://www.ostrava.cz/",                  # Ostrava
    "CZ095": "https://www.pardubickykraj.cz/",           # Pardubicky kraj
    "CZ096": "https://www.solarniasociace.cz/",          # Solarni asociace (same as CZ038? verify!)
    "CZ097": "https://www.plzensky-kraj.cz/",            # Plzensky kraj
    "CZ098": "https://www.praha.eu/",                    # Praha
    "CZ099": "https://vlada.gov.cz/",                    # Vlada (premier) (shared with CZ022)
    "CZ100": "https://www.ceproas.cz/",                  # CEPRO
    "CZ103": "https://www.innogy.cz/",                   # Innogy
    "CZ104": "https://www.kraj-jihocesky.cz/",           # Jihocesky kraj
    "CZ105": "https://sei.gov.cz/",                   # SEI (verify!)
    "CZ106": "https://www.7.cz/",                        # Sev.en Ceska energie (JS app, browser engine)
    "CZ107": "https://www.skoda-auto.cz/",               # Skoda Auto
    "CZ108": "https://www.jmk.cz/",                      # Jihomoravsky kraj (verify: kr-jihomoravsky)
    "CZ109": "https://www.socdem.cz/",                   # SOCDEM
    "CZ110": "https://www.suas.cz/",                     # Sokolovska uhelna
    "CZ111": "https://www.spolchemie.cz/",               # Spolchemie
    "CZ113": "https://www.trz.cz/",                      # Trinecke zelezarny
    "CZ114": "https://www.top09.cz/",                    # TOP 09
    "CZ115": "https://www.toyotacz.com/",                # TMMCZ (verify!)
    "CZ118": "https://www.schp.cz/",                     # Svaz chemickeho prumyslu
    "CZ119": "https://www.smocr.cz/",                    # Svaz mest a obci
    "CZ121": "",                  # OS pracovniku kultury a ochrany prirody (verify!)
    "CZ122": "https://www.spcr.cz/",                     # Svaz prumyslu a dopravy
    "CZ123": "https://www.fzp.czu.cz/",                  # FZP CZU
    "CZ124": "https://www.osphgn.cz/",                   # OS PHGN (verify!)
    "CZ125": "https://www.orlenunipetrol.cz/",           # Orlen Unipetrol
    "CZ127": "https://www.kr-ustecky.cz/",               # Ustecky kraj
    "CZ128": "https://www.vecr.cz/",            # Veolia Energie CR (verify!)
    "CZ130": "https://www.vitkovicesteel.com/",          # Vitkovice Steel
    "CZ131": "https://www.kr-vysocina.cz/",              # Kraj Vysocina
    "CZ132": "https://zlinskykraj.cz/",                  # Zlinsky kraj
    "CZ133": "https://www.agrofert.cz/",                 # Agrofert
    "CZ134": "https://www.pirati.cz/",                   # Ceska piratska strana
    "CZ135": "https://www.epholding.cz/",                # EPH
    "CZ140": "https://www.starostove.cz/",     # STAN
    "CZ200": "https://www.hlinsko.cz/",                  # Hlinsko
    "CZ201": "https://www.chrudim.eu/",                  # Chrudim
    "CZ203": "https://mve.fss.muni.cz/",               # KMVES FSS MUNI (verify!)
    "CZ204": "https://www.ceps.cz/",                     # CEPS
}


def fill(db: Database) -> int:
    n = 0
    for org_id, url in CANDIDATES.items():
        if not url:
            continue  # no known website (e.g. CZ121)
        org = db.get_org(org_id)
        if org is None:
            logger.warning(f"{org_id} not in DB")
            continue
        if org["seed_url"]:
            continue  # never overwrite an existing (possibly verified) URL
        normalized = urlnorm.normalize_url(url) or url
        db.set_org_fields(
            org_id,
            seed_url=normalized,
            url_verified=0,
            scope=json.dumps(urlnorm.default_scope(normalized)),
        )
        n += 1
    return n


def probe(db: Database):
    """Live-check every unverified candidate: does it resolve, where does it land."""
    import httpx

    from . import config

    results = []
    with httpx.Client(headers={"User-Agent": config.USER_AGENT},
                      follow_redirects=True, timeout=15, verify=True) as client:
        for org in db.list_orgs():
            if not org["seed_url"] or org["url_verified"]:
                continue
            url = org["seed_url"]
            try:
                r = client.get(url)
                final = str(r.url)
                same_host = urlnorm.host_of(url) == urlnorm.host_of(final)
                verdict = "OK" if (r.status_code == 200 and same_host) else (
                    "REDIRECTED" if r.status_code == 200 else f"HTTP {r.status_code}")
                results.append((org["org_id"], org["name"], verdict, url, final))
            except Exception as e:
                results.append((org["org_id"], org["name"],
                                f"FAIL {type(e).__name__}", url, ""))
    for org_id, name, verdict, url, final in results:
        extra = f" -> {final}" if final and verdict != "OK" else ""
        logger.info(f"{verdict:22} {org_id} {name[:45]:47} {url}{extra}")
    bad = [r for r in results if not r[2].startswith("OK")]
    logger.info(f"{len(results)} probed, {len(bad)} need attention")
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fill candidate seed URLs")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)

    db = Database(Path(args.db) if args.db else None)
    n = fill(db)
    logger.info(f"filled {n} candidate URLs (unverified)")
    if args.probe:
        probe(db)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
