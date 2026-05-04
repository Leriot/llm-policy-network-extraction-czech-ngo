# Network Reconstruction Analysis: Results and Interpretation
## LLM-reconstructed vs. COMPON 2025 ground truth
### Czech environmental NGO collaboration network (COMPON framework)

---

## 1. Network-level descriptives

| Metric | LLM 2025 | LLM 2024+25 | LLM 2016–25 | COMPON 2025 |
|---|---|---|---|---|
| Nodes | 19 | 19 | 19 | 19 |
| Edges | 59 | 69 | 94 | 155 |
| Density | 0.173 | 0.202 | 0.275 | 0.453 |
| Reciprocity | 0.819 | 0.807 | 0.743 | 0.702 |
| Transitivity | 0.714 | 0.636 | 0.660 | 0.689 |
| Mean degree | 3.11 | 3.63 | 4.95 | 8.16 |
| Mean geodesic distance | 1.61 | 1.76 | 1.77 | 1.57 |
| Diameter | 4 | 4 | 4 | 3 |
| Reachable pair share | 0.342 | 0.491 | 0.655 | 0.947 |

### Edge reconstruction quality vs. COMPON 2025

| Network | Precision | Recall | F1 | Jaccard |
|---|---|---|---|---|
| LLM 2025 | 0.729 | 0.277 | 0.402 | 0.251 |
| LLM 2024+25 | 0.754 | 0.335 | 0.464 | 0.302 |
| LLM 2016–25 | 0.734 | 0.445 | 0.554 | 0.383 |

### Degree rank correlation (Spearman) vs. COMPON 2025

| Network | In-degree r | Out-degree r |
|---|---|---|
| LLM 2025 | 0.446 | 0.417 |
| LLM 2024+25 | 0.494 | 0.467 |
| LLM 2016–25 | 0.559 | 0.477 |

### CUG tests (all networks, reps = 2000)

All three LLM networks and COMPON 2025 show transitivity and reciprocity
significantly above chance under both edge-conditioned and dyad-census-conditioned
null distributions (p = 0 in all cases), confirming that clustering and mutuality
are genuine structural properties rather than density artefacts.

---

## 2. Interpretation: network-level comparison

**The LLM consistently underestimates connectivity.** Even the broadest window
(2016–2025) recovers only 94 of 155 COMPON edges (density 0.275 vs. 0.453).
Widening the temporal window improves recall monotonically (0.28 → 0.34 → 0.45)
while precision remains stable around 0.73, suggesting the model is not
introducing random noise with more data — it is selectively retrieving a
higher-confidence subset of real ties.

**The LLM errs toward omission, not hallucination.** With precision ~0.73,
roughly three in four ties the LLM predicts are genuinely present in COMPON.
The problem is the 86 false negatives in LLM 2016–2025 — ties the LLM never
surfaces. This pattern is consistent with a recall-limited extraction pipeline
that captures salient, frequently co-documented relationships but misses
peripheral or episodic ones.

**Reciprocity is paradoxically higher in the LLM networks** (0.74–0.82) than
in COMPON (0.70). This is not a substantive finding but a structural artefact:
because the LLM only recovers the densest, most mutually documented ties, the
surviving edges are disproportionately mutual. Weak, asymmetric ties are the
first to be missed.

**Local clustering is well-preserved.** Transitivity is nearly identical across
all four networks (~0.66–0.71). This indicates that where the LLM does detect
ties, it reconstructs triadic closure correctly — the local neighbourhood
structure of the network is captured even when the global scaffold is incomplete.

**Global integration is severely underestimated.** Reachable pair share rises
from 0.34 (LLM 2025) to 0.66 (LLM 2016–2025) but remains far below COMPON's
0.95. The LLM network is fragmented into islands; COMPON is near-fully
connected. Mean geodesic distance looks similar across all networks (1.57–1.77)
but this is misleading — it is computed only over reachable pairs, masking the
fact that most pairs are unreachable in the LLM networks. This is the single
largest structural divergence between the two sources.

**Degree rank correlation improves with temporal scope** (r = 0.45 to 0.56 for
in-degree), confirming that a wider evidence base helps the model identify which
actors are relatively more central. However, even r = 0.56 means the LLM has
only moderate agreement with COMPON on who the central players are.

---

## 3. CUG test results

| Test | LLM 2025 | LLM 2024+25 | LLM 2016–25 | COMPON 2025 |
|---|---|---|---|---|
| Transitivity \| edges (obs) | 0.714 | 0.636 | 0.660 | 0.689 |
| Transitivity \| edges (p) | 0.000 | 0.000 | 0.000 | 0.000 |
| Transitivity \| dyad census (p) | 0.000 | 0.000 | 0.000 | 0.000 |
| Reciprocity \| edges (obs) | 0.819 | 0.807 | 0.743 | 0.702 |
| Reciprocity \| edges (p) | 0.000 | 0.000 | 0.000 | 0.000 |

All p-values are the proportion of simulated networks with a statistic
greater than or equal to the observed value (p-lower = p(sim ≥ obs)).
Values of 0 indicate the observed statistic exceeds all 2000 random
graphs drawn under the null. The CUG results are consistent across all
networks: both transitivity and reciprocity are genuine non-random
structural properties, not artefacts of edge density.

---

## 4. Triad census

| Type | LLM 2025 | LLM 2024+25 | LLM 2016–25 | COMPON 2025 |
|---|---|---|---|---|
| 003 (empty) | 452 | 397 | 277 | 108 |
| 012 | 244 | 248 | 239 | 149 |
| 102 (mutual dyad) | 96 | 113 | 105 | 128 |
| 300 (full triangle) | 8 | 10 | 22 | 61 |
| 210 | 16 | 28 | 39 | 112 |

The LLM networks have far more empty triads (003) than COMPON and far fewer
closed triangles (300: 8–22 vs. 61). As the time window widens, the count of
300 triads increases (8 → 10 → 22), approaching but not reaching COMPON levels.
This mirrors the reachability finding: the LLM captures local clustering but
produces a globally sparser graph with fewer multi-path connections between
actors.

---

## 5. ACF category analysis — COMPON 2025 (ground truth)

### Node-level metrics

| Node | Category | Total degree | Betweenness | Clustering | Broker index |
|---|---|---|---|---|---|
| ccc | umbrella | 26 | 0.092 | 0.733 | 0.092 |
| grn | umbrella | 23 | 0.040 | 0.758 | 0.045 |
| foe | advocacy | 26 | 0.080 | 0.714 | 0.080 |
| grp | advocacy | 21 | 0.037 | 0.695 | 0.046 |
| arn | advocacy | 18 | 0.005 | 0.859 | 0.007 |
| nes | advocacy | 15 | 0.005 | 0.873 | 0.009 |
| upe | advocacy | 6 | 0.000 | 1.000 | 0.000 |
| ver | sectoral | 26 | 0.170 | 0.559 | 0.170 |
| cal | sectoral | 25 | 0.097 | 0.714 | 0.101 |
| bel | sectoral | 12 | 0.000 | 0.889 | 0.001 |
| fff | radical | 20 | 0.029 | 0.894 | 0.038 |
| lau | radical | 16 | 0.003 | 0.873 | 0.005 |
| ext | radical | 12 | 0.001 | 0.889 | 0.002 |
| fct | specialist | 19 | 0.015 | 0.758 | 0.020 |
| frb | specialist | 18 | 0.012 | 0.891 | 0.017 |
| cde | specialist | 16 | 0.012 | 0.844 | 0.019 |
| cit | specialist | 5 | 0.000 | 1.000 | 0.001 |
| aes | specialist | 5 | 0.000 | 1.000 | 0.000 |
| aut | peripheral | 1 | 0.000 | 0.000 | 0.000 |

### Category means — COMPON 2025

| Category | Mean total degree | Mean betweenness | Mean clustering | Mean broker index |
|---|---|---|---|---|
| umbrella | 24.5 | 0.066 | 0.746 | 0.069 |
| sectoral | 21.0 | 0.089 | 0.721 | 0.090 |
| advocacy | 17.2 | 0.025 | 0.828 | 0.028 |
| radical | 16.0 | 0.011 | 0.885 | 0.015 |
| specialist | 12.6 | 0.008 | 0.899 | 0.012 |
| peripheral | 1.0 | 0.000 | 0.000 | 0.000 |

---

## 6. ACF category analysis — LLM 2016–2025

### Node-level metrics

| Node | Category | Total degree | Betweenness | Clustering | Broker index |
|---|---|---|---|---|---|
| ccc | umbrella | 21 | 0.060 | 0.486 | 0.060 |
| grn | umbrella | 21 | 0.115 | 0.590 | 0.115 |
| arn | advocacy | 17 | 0.069 | 0.621 | 0.086 |
| grp | advocacy | 21 | 0.084 | 0.577 | 0.084 |
| foe | advocacy | 14 | 0.036 | 0.833 | 0.054 |
| nes | advocacy | 15 | 0.011 | 0.673 | 0.015 |
| upe | advocacy | 7 | 0.049 | 0.667 | 0.147 |
| cde | specialist | 18 | 0.047 | 0.652 | 0.055 |
| frb | specialist | 9 | 0.050 | 0.857 | 0.116 |
| cit | specialist | 5 | 0.004 | 0.500 | 0.018 |
| fct | specialist | 4 | 0.000 | 1.000 | 0.000 |
| aes | specialist | 0 | 0.000 | 0.000 | — |
| ext | radical | 3 | 0.000 | 1.000 | 0.000 |
| fff | radical | 6 | 0.000 | 1.000 | 0.000 |
| lau | radical | 6 | 0.000 | 1.000 | 0.000 |
| cal | sectoral | 12 | 0.035 | 0.722 | 0.061 |
| bel | sectoral | 6 | 0.000 | 1.000 | 0.000 |
| ver | sectoral | 3 | 0.003 | 0.000 | 0.019 |
| aut | peripheral | 0 | 0.000 | 0.000 | — |

### Category means — LLM 2016–2025

| Category | Mean total degree | Mean betweenness | Mean clustering | Mean broker index |
|---|---|---|---|---|
| umbrella | 21.0 | 0.087 | 0.538 | 0.087 |
| advocacy | 14.8 | 0.050 | 0.674 | 0.077 |
| specialist | 7.2 | 0.020 | 0.602 | 0.047 |
| sectoral | 7.0 | 0.013 | 0.574 | 0.027 |
| radical | 5.0 | 0.000 | 1.000 | 0.000 |
| peripheral | 0.0 | 0.000 | 0.000 | — |

### Category degree rank comparison

| Category | COMPON 2025 rank | LLM 2016–25 rank |
|---|---|---|
| umbrella | 1 | 1 |
| sectoral | 2 | 4 |
| advocacy | 3 | 2 |
| radical | 4 | 5 |
| specialist | 5 | 3 |
| peripheral | 6 | 6 |

**Spearman r = 0.714** — moderate rank preservation. Umbrella (rank 1) and
peripheral (rank 6) are correctly placed. The main discrepancies are sectoral
(rank 2 in COMPON, rank 4 in LLM) and radical (rank 4 in COMPON, rank 5 in LLM).

---

## 7. Hypothesis tests

### Tested on COMPON 2025

| Hypothesis | Test | Result | p-value | Verdict |
|---|---|---|---|---|
| H1: Umbrella highest degree | One-sided Wilcoxon vs. all others | W = 30 | 0.048 | **Supported** |
| H2: Advocacy intermediate degree | One-sided Wilcoxon vs. lower groups | W = 28 | 0.252 | Not supported |
| H3: Specialists high broker index | One-sided Wilcoxon vs. others | W = 25 | 0.835 | Not supported |
| H4: Radical high clustering | One-sided Wilcoxon vs. others | W = 35 | 0.119 | Not supported |
| H5: Sectoral tied to core | Descriptive — ties to umbrella/advocacy | — | — | Partially supported |
| H6: Peripheral lowest degree | Rank check | Rank 1/19 | — | **Supported** |

Kruskal-Wallis across all categories: χ²(5) = 7.64, p = 0.177

### Tested on LLM 2016–2025

| Hypothesis | Test | Result | p-value | Verdict |
|---|---|---|---|---|
| H1: Umbrella highest degree | One-sided Wilcoxon vs. all others | W = 33 | 0.019 | **Supported** |
| H2: Advocacy intermediate degree | One-sided Wilcoxon vs. lower groups | W = 39 | 0.016 | **Supported** |
| H3: Specialists high broker index | One-sided Wilcoxon vs. others | W = 26 | 0.523 | Not supported |
| H4: Radical high clustering | One-sided Wilcoxon vs. others | W = 45 | 0.010 | Supported* |
| H5: Sectoral tied to core | Ties to umbrella/advocacy: 1–3 per actor | — | — | Weakly supported |
| H6: Peripheral lowest degree | Rank 1.5/19 (tied with aes) | — | — | **Supported** |

Kruskal-Wallis across all categories: χ²(5) = 11.25, p = 0.047

*H4 is flagged — see interpretation below.

---

## 8. Interpretation: ACF hypotheses

### H1 — Umbrella actors have highest degree centrality
**Supported in both networks.** Klimatická koalice (ccc, degree 26) and Zelený
kruh (grn, degree 23) are among the most connected nodes in COMPON 2025.
The LLM correctly recovers their dominant position (both have degree 21 in
LLM 2016–2025). The hypothesis is more strongly supported in the LLM network
(p = 0.019) than COMPON (p = 0.048), likely because the LLM disproportionately
captures the most salient, coalition-level ties that umbrella bodies are party to.

### H2 — Advocacy actors occupy intermediate positions
**Not supported in COMPON; supported in LLM.** In COMPON 2025, sectoral actors
(ver: 26, cal: 25) outrank advocacy actors in mean degree (21.0 vs. 17.2),
violating the predicted ordering. In the LLM network, advocacy correctly sits
above specialist and sectoral groups (14.8 vs. 7.2 and 7.0, p = 0.016).
This divergence is substantively interesting: COMPON reveals that Ekologický
institut Veronica and Calla are more central than the ACF framework predicts
for sectoral specialists, possibly because these organisations have evolved
beyond a purely regional/thematic scope. The LLM misses this, defaulting to
the theoretically expected hierarchy.

### H3 — Specialist organisations have disproportionately high betweenness
**Not supported in either network.** The broker index (betweenness normalised
by degree) for specialists is 0.012 in COMPON and 0.047 in LLM — neither
significantly above other categories. The actual knowledge brokers in COMPON
2025 are sectoral actors: ver has betweenness 0.170 (by far the highest in the
network), and cal has 0.097. This suggests that in the Czech environmental
coalition as observed in 2025, the brokerage function is performed by
regionally-embedded organisations with broad cross-coalition ties (ver, cal)
rather than technical/legal specialists (fct, frb, cde). The LLM does not
capture this pattern at all — ver has betweenness near zero in LLM 2016–2025.

### H4 — Radical flank forms dense internal cluster
**Results are contradictory and must be interpreted with caution.**
In COMPON 2025, the radical sub-cluster (ext, fff, lau) has internal density
0.833 — highly cohesive — with 6 edges to advocacy actors and only 2 to
sectoral/peripheral, partially consistent with the Haines (1984) bridging
prediction. However, the clustering test is not significant (p = 0.119).

In the LLM 2016–2025 network, the radical actors (ext, fff, lau) have
**zero outgoing edges**. They appear exclusively as targets of ties from other
actors (primarily grp, ccc, nes, arn). This means the LLM detects these
organisations as being mentioned in the context of others' collaboration
outputs, but does not extract any collaborative initiative originating from
them. The internal density is 0, betweenness is 0 for all three, and their
clustering coefficient of 1.0 is a computational artefact of sink-node
geometry rather than a substantive finding. The significant Wilcoxon result
(p = 0.010) is therefore an artefact and should not be interpreted as
supporting the hypothesis.

### H5 — Sectoral specialists maintain targeted ties to core
**Partially supported in COMPON; weakly supported in LLM.**
In COMPON 2025, all three sectoral actors maintain 5–7 ties to umbrella and
advocacy nodes — consistent with the Resource Dependence prediction of targeted
upward linkages. However, ver (degree 26) and cal (degree 25) are far from
semi-peripheral, ranking alongside the most central actors in the network.
The hypothesis holds for bel (degree 12) but fails for the other two.

In the LLM, sectoral actors are much more peripheral (degrees 3–12, ties to
core reduced to 1–3), which better fits the semi-peripheral prediction but
likely reflects the LLM's general tendency to underestimate connectivity
rather than a genuine structural difference.

### H6 — Autoklub ČR has lowest degree centrality
**Supported in both networks.** Autoklub (aut) has degree 1 in COMPON 2025
(rank 1/19) and degree 0 in LLM 2016–2025 (rank 1.5/19, tied with aes which
is also isolated in the LLM). The single COMPON tie involving aut is an
incoming edge from ver, which is consistent with a contrast-framing co-mention
rather than a coalition collaboration.

---

## 9. Key structural divergences: LLM vs. COMPON

**Sectoral actors are the main misclassification.** Ver and cal are among the
most central and highest-betweenness nodes in COMPON but near-peripheral in
the LLM. This is the largest individual-level error in the reconstruction and
accounts for much of the Spearman rank discrepancy (sectoral drops from rank 2
to rank 4). These organisations may be more visible in the COMPON interview
data than in publicly available documentary sources, which the LLM relies on.

**Radical actors are asymmetrically reconstructed.** The LLM captures radical
organisations as recipients of coalition attention (incoming ties from grp, ccc,
nes) but not as collaborative initiators. This directional bias may reflect that
Limity jsme my, Fridays for Future, and Extinction Rebellion appear most
prominently in documents authored by mainstream coalition members referencing
them, rather than in joint outputs where both parties are named as equal partners.

**aes (Aliance pro energetickou soběstačnost) is completely invisible to the
LLM.** In COMPON it has degree 5 with ties to cal, ccc, fct, frb, and cde.
This actor receives no edges and sends none in LLM 2016–2025, suggesting it
is not sufficiently represented in the public documentary record that the LLM
was trained on.

**Precision is remarkably stable across time windows (~0.73).** This is a
methodologically reassuring finding: extending the evidence window does not
introduce new false positives at a higher rate. The LLM maintains consistent
specificity while improving coverage. For a methodology chapter, this supports
using the widest available window as the primary network for any downstream
analysis.
