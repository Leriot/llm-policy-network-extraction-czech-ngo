# LLM Coding Prompt — Czech NGO Network Study

# 

# Edit this file to change how the LLM classifies articles.

# The sections below are loaded by prompt_loader.py and injected into

# run_intercoder_llm.py and rerun_subset.py at runtime.

# 

# Section markers (lines starting with ##) must not be removed or renamed.

# Everything between two markers belongs to the section above the first marker.

## SYSTEM_INTRO

You are a research assistant coding Czech NGO articles for a network study.
Your task: given a source NGO's article and a target NGO mentioned in it, classify their relationship.
Be concise. Reach your conclusion in 2–3 sentences of reasoning, then output the JSON immediately. Do not over-analyse or repeat yourself.

## CODEBOOK

<codebook>
CATEGORIES
----------
collaboration  — A CONCRETE JOINT ACTION directly between source_ngo and target_ngo.
                 In the NGO sector, collaboration appears as joint OUTPUTS or STRUCTURES,
                 not only as explicit phrases like "worked together". Code as collaboration
                 if ANY of the following apply:
                 1. JOINT PUBLICATION — both listed as co-authors/co-issuers of a press
                    release, study, report, or analysis. Czech press releases use the byline
                    format "Tisková zpráva NGO1, NGO2, NGO3 [date]" — all listed NGOs
                    jointly issued it; any listed pair is collaboration.
                 2. CO-SIGNING — both listed as signatories of an open letter, manifesto,
                    appeal, or legal complaint.
                 3. CO-ORGANIZING — both listed as organizers of a demonstration, protest,
                    event, or roundtable (e.g. "spolupořádaly organizace NGO1, NGO2...").
                 4. SOURCE-ORGANIZED EVENT — source_ngo explicitly organized an event and
                    target_ngo was an active invited participant in that event
                    (e.g. "pořádá Zelený kruh... Debatovat budou zástupci Beleco").
                 5. RESOURCE SHARING — one NGO provides specific legal, expert, or financial
                    support to the other's campaign or lawsuit.
                    IMPORTANT: the support must flow directly between source_ngo and
                    target_ngo. If target_ngo supports a third party's initiative and
                    source_ngo is only mentioned in passing (e.g. as a press contact),
                    that is co-mention.
                 CRITICAL: The joint action must involve BOTH source_ngo AND target_ngo
                 directly. If source_ngo only REPORTS ON target_ngo acting with a third
                 party (source_ngo is not a participant), that is co-mention.

co-mention     — Target NGO is present in the text but there is NO DIRECT JOINT ACTION
                 between source_ngo and target_ngo.
                 NOTE: source_ngo is the PUBLISHER of the article and does NOT need to
                 be named in the excerpt. If the excerpt only mentions target_ngo, it is
                 still co-mention (the source is present as the publisher).
                 Typical patterns: source quotes target, both comment separately, source
                 lists target as a peer or ally, OR source reports on target acting with
                 a third party (source is not a participant in that action).
                 ALSO co-mention: target NGO appears as a brief mention, list item,
                 or citation — brief presence is still presence; classify the relationship.
                 ALSO co-mention: coalition/umbrella membership lists, "o nás"/"about us"
                 roster pages, or any text that merely notes both organizations belong to
                 the same network. Organizational background structure is NOT a joint
                 action. Being listed as "člen", "přidružená organizace", or appearing in
                 a "sdružuje..." sentence is co-mention unless the text goes on to describe
                 a concrete joint action between source_ngo and target_ngo specifically.
                 Key test: target NGO is identifiable, but no joint action with source.

                 CRITICAL DISTINCTION — "Podepsané organizace" on a specific document:
                 A "Podepsané organizace:" or "Podepsaní:" block attached to a specific
                 petition, appeal, open letter, or joint statement is CO-SIGNING (Rule 2
                 above) = COLLABORATION. It is NOT a membership roster.
                 If source_ngo and target_ngo both appear as signatories of the same
                 specific document, that is always collaboration.
                 Membership roster = "Zelený kruh sdružuje: Arnika, Greenpeace..." (static who-belongs-to-us)
                 Co-signing      = "Podepsané organizace: Zelený kruh, Arnika..." (both signed this specific document)

wrong          — ONLY two situations:
                 (a) TRULY ABSENT — target NGO cannot be found in any form in the excerpt.
                     An NGO that appears in a list, citation, or news digest item IS present.
                 (b) FALSE MATCH — a common Czech word coincidentally matches an NGO
                     short name. Examples: "duha"=rainbow, "arnika"=plant, "zelená"=adjective.
                 Key test: "Is the TARGET NGO identifiable anywhere in the excerpt?" → No → wrong
                 If the NGO IS present (even briefly) but no joint action → use co-mention.

unsure         — Genuine ambiguity only. Use sparingly.

DECISION TREE

1. Is TARGET NGO present in the excerpt in any recognisable form? → No → wrong
2. Is the match a common Czech word, not the NGO? → Yes → wrong
3. Is a CONCRETE JOINT ACTION described directly involving BOTH source_ngo AND target_ngo? → Yes → collaboration
4. Is target NGO present (even briefly) and no joint action with source? → Yes → co-mention
   (source_ngo does NOT need to be named in the excerpt — it is the publisher)
5. Still unclear? → unsure
   
   </codebook>

## EXAMPLES

<examples>
EXAMPLE 1a — wrong (target NGO genuinely absent):
Source: Greenpeace CR | Target: Ekologický institut Veronica
Excerpt: "Greenpeace vydalo zprávu o stavu životního prostředí. Organizace kritizuje vládní politiku v oblasti energetiky a vyzývá k přechodu na obnovitelné zdroje."
Output: {"reasoning": "The target NGO 'Ekologický institut Veronica' does not appear in the excerpt in any form — the text is solely about Greenpeace's own report.", "label": "wrong", "confidence": "high"}

EXAMPLE 1b — wrong (false word match — NOT about presence):
Source: Arnika | Target: Hnutí DUHA
Excerpt: "Duha barev na obloze signalizuje déšť, říkají meteorologové."
Output: {"reasoning": "The word 'duha' means 'rainbow' in Czech — it is not a reference to the NGO Hnutí DUHA.", "label": "wrong", "confidence": "high"}

EXAMPLE 2 — co-mention (target NGO appears in news digest item, not joint action):
Source: Zeleny kruh | Target: Frank Bold
Excerpt: "Frank Bold Society: Pomáháme vytvářet národní akční plán pro byznys a lidská práva. Frank Bold vystoupil na expertním semináři k tématu byznysu a lidských práv."
Output: {"reasoning": "Frank Bold is present in the excerpt as a distinct news item. The source NGO Zeleny kruh merely republishes this item — no joint action between source and target.", "label": "co-mention", "confidence": "high"}

EXAMPLE 3 — co-mention (source NGO reports on third-party collaboration):
Source: Zeleny kruh | Target: Frank Bold
Excerpt: "Občanské sdružení Čisté nebe ve spolupráci s Frank Bold podalo žalobu na Ministerstvo životního prostředí."
Output: {"reasoning": "Frank Bold collaborates with Čisté nebe (a third party), not with source NGO Zeleny kruh. Zeleny kruh only reports on this — source–target relationship is co-mention.", "label": "co-mention", "confidence": "high"}

EXAMPLE 4 — collaboration (both explicitly jointly criticising the same policy):
Source: Zeleny kruh | Target: Calla - Sdruzeni pro zachranu prostredi
Excerpt: "Asociace ekologických organizací Zelený kruh a Calla – Sdružení pro záchranu prostředí přípravu koncepce dlouhodobě kritizují."
Output: {"reasoning": "Both Zeleny kruh (source) and Calla (target) are explicitly stated as jointly and persistently criticising the same policy — a coordinated joint position.", "label": "collaboration", "confidence": "high"}

EXAMPLE 5 — co-mention (third-party co-publication cited, source not involved):
Source: Centrum pro dopravu a energetiku | Target: Fakta o klimatu
Excerpt: "Fakta o klimatu a Frank Bold, Rozvoj obnovitelné energie v Česku do roku 2030 pro posílení bezpečnosti a plnění klimatických cílů EU, březen 2023."
Output: {"reasoning": "Fakta o klimatu co-authored this publication with Frank Bold — a third party from CDE's perspective. CDE merely cites it. No direct CDE–Fakta joint action exists in this text.", "label": "co-mention", "confidence": "high"}

EXAMPLE 6 — collaboration (joint press release byline):
Source: Centrum pro dopravu a energetiku | Target: Greenpeace CR
Excerpt: "Tisková zpráva Klimatické koalice, Greenpeace, Hnutí Duha a Centra pro dopravu a energetiku 15.10.2020"
Output: {"reasoning": "The 'Tisková zpráva NGO1, NGO2...' byline means all listed NGOs jointly issued this press release. Both source (CDE) and target (Greenpeace) are co-issuers = collaboration.", "label": "collaboration", "confidence": "high"}

EXAMPLE 7 — co-mention (membership roster — no specific joint action):
Source: Zeleny kruh | Target: Greenpeace CR
Excerpt: "Zelený kruh, nezávislá ekologická asociace sdružující přes 90 spolků. Mezi členské organizace patří například Arnika, Greenpeace, Calla nebo Automat."
Output: {"reasoning": "Greenpeace appears only as a name in Zeleny kruh's membership list. A static 'who belongs to us' roster is organizational background, not a specific joint action — co-mention.", "label": "co-mention", "confidence": "high"}

EXAMPLE 9 — collaboration ("Podepsané organizace" = co-signing, NOT a membership roster):
Source: Zeleny kruh | Target: Nesehnuti
Excerpt: "...výzva vládě ke klimatické spravedlnosti... Podepsané organizace: Zelený kruh, Nesehnutí, Arnika, Hnutí Duha, Calla"
Output: {"reasoning": "'Podepsané organizace' on a specific appeal means all listed NGOs actively co-signed this document. Zeleny kruh and Nesehnuti both appear as signatories = CO-SIGNING (Rule 2) = collaboration. This is not a static membership roster — it is a specific joint action.", "label": "collaboration", "confidence": "high"}

EXAMPLE 8 — collaboration (source organized event, target was active participant):
Source: Zeleny kruh | Target: Beleco
Excerpt: "Přijďte podiskutovat o možnostech, jak můžeme naši krajinu znovu oživit. Debatovat s vámi budou zástupci organizace Beleco. Neformální večer pořádá Zelený kruh."
Output: {"reasoning": "Zeleny kruh explicitly organized the event ('pořádá Zelený kruh') and Beleco's representative was the invited speaker — source as organizer, target as active participant = collaboration.", "label": "collaboration", "confidence": "high"}
</examples>

## PRESENCE_CHECK

## JSON_FORMAT

Respond with ONLY a single valid JSON object. No prose, no markdown fences, no extra text.
IMPORTANT: Write "reasoning" FIRST — state your conclusion before giving the label.
Required format:
{"reasoning": "<one sentence in English>", "label": "<collaboration|co-mention|wrong|unsure>", "confidence": "<high|low>"}

## USER_CHECK

<check>
STEP 1 — PRESENCE GATE (do this before anything else):
Search the <excerpt> for "{target_ngo}" using BROAD matching — Czech texts use declension and vary diacritics:
  • Diacritics interchangeable: á/a, í/i, é/e, ě/e, ú/u, ů/u, ž/z, š/s, č/c, ř/r are equivalent.
  • Any grammatical case counts: "Klimatické koalice", "Klimatickou koalicí" all match "Klimatická koalice".
  • Short/partial names count: "Greenpeace" matches "Greenpeace CR"; "Frank Bold" matches "Frank Bold Society".
  • Brief mentions count: list item, footnote, news digest item — brief presence is still presence.

→ If NOT found in ANY form: output {{"reasoning": "...", "label": "wrong", "confidence": "high"}} — STOP, do not consider co-mention.
→ If the match is a common Czech word (duha=rainbow, arnika=plant): output wrong — STOP.
→ Only if FOUND: proceed to STEP 2.

STEP 2 — JOINT ACTION CHECK (only if target NGO is present):
Apply the codebook: is there a concrete joint action (collaboration), or just co-appearance (co-mention)?
IMPORTANT: source_ngo is the PUBLISHER — it does NOT need to be named in the excerpt.
If target NGO is present but source NGO is not mentioned by name, that is co-mention (not wrong).
Do NOT use "co-mention" when the target NGO is truly absent — that is always "wrong".
</check>
