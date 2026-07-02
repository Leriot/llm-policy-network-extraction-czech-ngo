# About this crawler / O tomto crawleru

**User-Agent:** `AcademicResearch-COMPONNetworkAnalysis/2.0`
**Contact / Kontakt:** 498079@mail.muni.cz

*(Česká verze níže.)*

## What is this?

You are (probably) reading this because you saw our crawler in your web server
logs. This is a **non-commercial academic research crawler** operated by a
researcher affiliated with Masaryk University, Brno. It collects **publicly
available web pages** of organisations active in Czech climate and energy
policy, for social-network research on inter-organisational collaboration.

- **Wave 1** (Nov 2025 – Jan 2026): 19 environmental non-governmental
  organisations, used in a master's thesis validating LLM-based extraction of
  collaboration networks against the COMPON survey.
- **Wave 2** (2026, current): an **expanded and updated** crawl covering the
  full population of ~119 organisations in the Czech climate-policy network
  (public institutions, companies, unions, academia, municipalities, NGOs),
  as the thesis is developed into a peer-reviewed paper. If you saw us in
  wave 1: same project, same operator, larger scope.

## What we collect and how

- Public HTML pages only, reached by following links from your homepage and
  your sitemap. We store page snapshots for text analysis and the link
  structure for network analysis.
- Links to PDFs and other documents are **recorded but the files are not
  downloaded**.
- We **respect robots.txt** (including `Crawl-delay`), identify ourselves in
  every request (this User-Agent and a `From:` e-mail header), and space
  requests to any one site several seconds apart. The crawl is slow by design.
- We do not log in anywhere, do not submit forms, and do not collect anything
  behind authentication. No personal data is targeted; content is analysed at
  the level of organisations.

## How to opt out

- Add this to your robots.txt (honoured automatically):

  ```
  User-agent: AcademicResearch-COMPONNetworkAnalysis
  Disallow: /
  ```

- Or e-mail **498079@mail.muni.cz** and we will exclude your domain and
  delete collected snapshots of your site on request.

## Data use

Collected data are used for academic research only (network measurement
methodology; see this repository for the wave-1 replication materials).
Published outputs contain aggregated network analyses, not full-text
republication of your content.

---

## Česky

Tento crawler je **nekomerční akademický výzkumný nástroj** provozovaný
výzkumníkem spojeným s Masarykovou univerzitou v Brně. Sbírá **veřejně
dostupné webové stránky** organizací působících v české klimatické a
energetické politice pro síťovou analýzu mezi-organizační spolupráce
(vlna 1: 2025/26, 19 ekologických NNO; vlna 2: 2026, celá populace ~119
organizací — rozšíření diplomové práce na odborný článek).

Respektujeme robots.txt včetně `Crawl-delay`, požadavky rozkládáme v čase
(několik sekund mezi požadavky na tentýž web), nestahujeme dokumenty (PDF
pouze evidujeme) a nesbíráme nic za přihlášením.

**Nechcete být v datech?** Přidejte do robots.txt blok pro
`User-agent: AcademicResearch-COMPONNetworkAnalysis` (respektujeme
automaticky), nebo napište na **498079@mail.muni.cz** — vaši doménu vyřadíme
a stažené snímky na požádání smažeme.
