# LLM Inter-Rater Agreement & Network Construction Report

**Final Validation Run — 4 Models + Judge LLM × 3,086 Pairs**  
*Generated: 2026-04-09*

---

## Dataset

| Item              | Value                                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------------ |
| Total pairs coded | 3,086                                                                                            |
| Source dataset    | `step6_final`                                                                                    |
| Models (round 1)  | Scout (Meta Llama 4), Mistral Small 2603, Gemma 4 31B (Google, free tier), GPT-4.1 Nano (OpenAI) |
| Judge model       | Claude Sonnet 4.6 (Anthropic), extended thinking enabled                                         |
| Categories        | `co-mention`, `collaboration`, `wrong`                                                           |

---

## Round 1: Four-Model Agreement

| Metric                  | Value                                                 |
| ----------------------- | ----------------------------------------------------- |
| **Fleiss' κ**           | **0.5905** (top of Moderate, approaching Substantial) |
| Observed agreement (P̄) | 0.7855                                                |
| Expected by chance (Pₑ) | 0.4762                                                |

| Agreement           | Count | %     |
| ------------------- | ----- | ----- |
| 4/0 (unanimous)     | 1,868 | 60.5% |
| 3/1 (majority)      | 929   | 30.1% |
| 2/2 (split → judge) | 289   | 9.4%  |

**90.6% of pairs** resolved by majority vote alone.

### Minority Voter Analysis (3/1 rows)

| Model        | Times minority | % of 929 3/1 rows |
| ------------ | -------------- | ----------------- |
| Scout        | 70             | 7.5%              |
| Mistral      | 71             | 7.6%              |
| GPT-4.1 Nano | 197            | 21.2%             |
| Gemma 4 31B  | 591            | 63.6%             |

Gemma was the systematic outlier, driven by its strong bias toward `collaboration` (1,657 assignments vs. ~1,100 for the other three models). Scout and Mistral showed the most consistent alignment.

### Split (2/2) Type Breakdown

| Split                              | Count | % of splits |
| ---------------------------------- | ----- | ----------- |
| co-mention / collaboration         | 251   | 86.9%       |
| co-mention / collaboration / wrong | 29    | 10.0%       |
| co-mention / wrong                 | 7     | 2.4%        |
| collaboration / wrong              | 2     | 0.7%        |

87% of splits were at the co-mention/collaboration boundary — the most semantically ambiguous distinction in the coding scheme.

---

## Round 2: Judge LLM (Claude Sonnet 4.6)

All 289 split cases were sent to the judge with extended thinking enabled (5,000 token thinking budget). The judge received the exact same 1,000-char proximity window excerpt that the four base models received, plus all four raters' labels and reasoning (anonymised as Rater 1–4).

| Judge outcome | Count | % of 289 |
| ------------- | ----- | -------- |
| collaboration | 148   | 51.2%    |
| co-mention    | 138   | 47.8%    |
| wrong         | 3     | 1.0%     |

### Judge contribution to collaboration edges

Of the 148 judge collaboration decisions, **only 3 represented NGO pairs that did not already appear anywhere in the majority-decided collaboration rows** — the judge mostly resolved ambiguous evidence for pairs already established by the four base models. The 289 splits therefore had negligible impact on the set of unique collaboration relationships; they primarily added nuance to edge weights.

---

## Final Label Distribution (all 3,086 rows resolved)

| Label                         | Count | %     |
| ----------------------------- | ----- | ----- |
| co-mention                    | 1,830 | 59.3% |
| collaboration                 | 1,131 | 36.7% |
| wrong (excluded from network) | 125   | 4.1%  |

**2,961 rows** (95.9%) contribute to the network as valid co-mention or collaboration evidence. 125 rows labeled `wrong` (false NGO name matches) are excluded from all edge lists.

---

## Cost Summary

| Component | Model                     | Cost (USD) |
| --------- | ------------------------- | ---------- |
| Round 1   | Scout (Meta Llama 4)      | $1.04      |
| Round 1   | Mistral Small 2603        | $0.53      |
| Round 1   | Gemma 4 31B               | $1.06      |
| Round 1   | GPT-4.1 Nano              | $1.61      |
| Round 2   | Claude Sonnet 4.6 (judge) | $3.29      |
| **Total** |                           | **$8.89**  |

Source: OpenRouter activity CSV (`openrouter-activity-spend-20260409-112936.csv`).  
Total classifications: 3,086 × 4 models + 289 judge = **12,633 LLM calls** for $8.89.

---

## Network Construction

### NGO Codes

All 19 NGOs map directly to existing COMPON 2025 codes.

| NGO                                      | Code | In dataset |
| ---------------------------------------- | ---- | ---------- |
| Aliance pro energetickou sobestacnost    | aes  | no edges   |
| Arnika                                   | arn  | yes        |
| Autoklub CR                              | aut  | yes        |
| Beleco                                   | bel  | yes        |
| Calla - Sdruzeni pro zachranu prostredi  | cal  | yes        |
| Centrum pro dopravu a energetiku         | cde  | yes        |
| CI2                                      | cit  | yes        |
| Cesky svaz ochrancu prirody              | upe  | yes        |
| Ekologicky institut Veronica             | ver  | yes        |
| Extinction Rebellion [Posledni generace] | ext  | yes        |
| Fakta o klimatu                          | fct  | yes        |
| Frank Bold                               | frb  | yes        |
| Fridays for Future                       | fff  | yes        |
| Greenpeace CR                            | grp  | yes        |
| Hnuti Duha                               | foe  | yes        |
| Klimaticka koalice                       | ccc  | yes        |
| Limity jsme my                           | lau  | yes        |
| Nesehnuti                                | nes  | yes        |
| Zeleny kruh                              | grn  | yes        |

### Edge definition

- **Directed**: source_ngo = publisher's website; target_ngo = mentioned organisation.
- **Collaboration edge exists**: ≥ 1 datapoint labeled `collaboration` for that (source, target) pair in that year.
- **Wrong** rows excluded entirely before edge construction.
- Raw evidence counts (`collab_evidence`, `comention_evidence`, `total_evidence`) retained in edge list for weighted analysis in R.

### Network summary (directed, across all years)

| Metric                                              | Value |
| --------------------------------------------------- | ----- |
| Nodes                                               | 19    |
| Unique directed collaboration edges (total)         | 94    |
| Unique directed co-mention edges (total)            | 103   |
| Pairs with both collaboration + co-mention evidence | 80    |

### NGOs with zero outgoing collaboration edges (as source)

These organisations' websites yielded no articles where they were identified as directly collaborating with another NGO in the dataset:

- Aliance pro energetickou sobestacnost *(also no incoming edges — no valid pairs at all)*
- Autoklub CR *(also no incoming edges)*
- Extinction Rebellion / Posledni generace
- Fridays for Future
- Limity jsme my

### Collaboration edges by year

| Year | Directed collaboration edges |
| ---- | ---------------------------- |
| 2016 | 7                            |
| 2017 | 19                           |
| 2018 | 19                           |
| 2019 | 23                           |
| 2020 | 38                           |
| 2021 | 41                           |
| 2022 | 39                           |
| 2023 | 37                           |
| 2024 | 46                           |
| 2025 | 59                           |

Clear upward trend from 2016 onward, with a plateau around 2021–2023 and renewed growth in 2024–2025.

---

## Output Files

| File                                                  | Description                                                    |
| ----------------------------------------------------- | -------------------------------------------------------------- |
| `data/network/ngo_codes.csv`                          | 19 NGOs with codes, COMPON IDs, dataset presence flag          |
| `data/network/edge_list_directed_by_year.csv`         | 487 rows: one per (source, target, year) with evidence counts  |
| `data/network/edge_list_directed_total.csv`           | 117 rows: one per (source, target) aggregated across all years |
| `data/network/matrices/collab_{year}_directed.csv`    | 19×19 0/1 adjacency matrix per year (10 files)                 |
| `data/network/matrices/comention_{year}_directed.csv` | 19×19 co-mention adjacency matrix per year (10 files)          |
| `data/network/matrices/collab_total_directed.csv`     | 19×19 total collaboration adjacency                            |
| `data/network/matrices/comention_total_directed.csv`  | 19×19 total co-mention adjacency                               |
