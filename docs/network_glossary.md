# Glossary of Network Analysis Terms
## Social Network Analysis concepts used in the Czech NGO collaboration network study

---

## Part I — Network fundamentals

### Directed network (digraph)
A network in which ties have a direction: actor A can send a tie to actor B
without B necessarily reciprocating. In this study, a directed edge from
organisation A to organisation B represents A naming B as a collaboration
partner. The distinction matters because A→B and B→A are separate, independent
observations. An undirected network would treat any tie between A and B as
symmetric by definition.

### Adjacency matrix
The standard data format for storing a network. For N actors, an N×N matrix
where cell (i,j) = 1 if actor i has a tie to actor j, and 0 otherwise. The
diagonal (i = j, self-loops) is set to zero. All four networks in this study
are stored as 19×19 binary adjacency matrices. In a directed network the matrix
is generally asymmetric: cell (i,j) can differ from cell (j,i).

### Node (vertex, actor)
The unit of analysis in a network — here, each of the 19 Czech environmental
NGOs. Abbreviated codes (e.g. ccc, grn, foe) refer to specific organisations
as listed in the actor–code table.

### Edge (arc, tie)
A connection between two nodes. In a directed network, an edge is an ordered
pair (i→j). In this study, an edge represents a documented collaboration
relationship. The total count of edges is the network's size in terms of
connections.

### Binary network
A network where edges are coded as present (1) or absent (0), with no weight
attached. This study uses binary coding: a tie either exists or does not,
regardless of how frequently or intensely it was observed.

---

## Part II — Structural descriptives

### Density
The proportion of all possible directed ties that are actually present.
For a directed network of N nodes, the maximum possible edges is N×(N−1)
(excluding self-loops), so:

    density = observed edges / (N × (N − 1))

Density ranges from 0 (no ties) to 1 (all possible ties present). A network
with density 0.45 has 45% of all possible ties. Density is sensitive to network
size — larger networks tend to be sparser — so it should not be compared across
networks of different sizes without caution.

### Degree
The number of edges connected to a node. In a directed network, degree
splits into:

- **In-degree**: number of ties a node *receives* (how many others name this
  organisation as a partner). A proxy for popularity or perceived importance.
- **Out-degree**: number of ties a node *sends* (how many others this
  organisation names as partners). A proxy for activity or expansiveness.
- **Total degree**: in-degree + out-degree.

In a symmetric (undirected) or fully reciprocal network, in-degree equals
out-degree for every node. In this study, mean in-degree always equals mean
out-degree across the whole network (a mathematical necessity: every sent tie
is also a received tie), but individual nodes can differ substantially.

### Degree distribution
The frequency distribution of degree values across all nodes. A right-skewed
distribution (few high-degree hubs, many low-degree periphery nodes) is
characteristic of many real-world networks. Comparing degree distributions
across networks reveals whether the same actors dominate or whether
connectivity is more evenly spread.

### Reciprocity
The proportion of directed ties that are mutual — where if A→B exists, B→A
also exists. Formally, the dyadic reciprocity is:

    reciprocity = (number of mutual dyads) / (number of asymmetric + mutual dyads)

High reciprocity indicates a norm of mutual acknowledgement: organisations
that name each other tend to do so symmetrically. Values close to 1 mean
nearly all observed ties are mutual; values near 0 mean most ties are
one-directional. In this study, all LLM networks show higher reciprocity
(0.74–0.82) than COMPON 2025 (0.70), likely because the LLM preferentially
recovers well-documented, mutually acknowledged relationships while missing
weaker asymmetric ties.

### Transitivity (global clustering coefficient)
The proportion of connected triples (two edges sharing a node) that form
closed triangles (all three edges present). If A→B and B→C, transitivity
measures whether A→C also tends to exist:

    transitivity = (3 × number of triangles) / (number of connected triples)

High transitivity means "a friend of a friend tends to be a friend" — common
in organisations operating within the same coalition. Values near 1 mean
nearly all open paths are closed; values near 0 mean the network is tree-like
with few triangles. All networks in this study show high transitivity (~0.66–
0.71), significantly above the random graph baseline (CUG test p = 0).

### Local clustering coefficient
A node-level version of transitivity. For a given node, it measures the
proportion of its neighbours that are also connected to each other. A node
embedded in a tight clique has clustering near 1; a node serving as the
sole bridge between otherwise disconnected groups has clustering near 0.
Computed here using igraph's `transitivity(type = "local")`.

**Caution — sink nodes:** Nodes with only incoming edges and no outgoing edges
(out-degree = 0, as observed for the radical actors in LLM 2016–2025) receive
a clustering coefficient of 1 as a computational artefact. This is because
igraph has no outgoing neighbours to check for closure, and the formula
returns 1 by convention. These values should not be interpreted substantively.

---

## Part III — Geodesic distances and connectivity

### Geodesic distance (shortest path length)
The minimum number of edges needed to travel from node i to node j following
directed edges. If no directed path exists, the geodesic distance is infinite
(the pair is unreachable). In this study, geodesic distances are computed using
the `geodist()` function from the sna package.

### Mean geodesic distance (average path length)
The average shortest path length computed only over reachable pairs (finite
geodesic distances). This measures how quickly information or influence can
spread across the connected parts of the network. A low value means most
reachable actors are only a few steps apart ("small world" effect).

**Important caveat:** Mean geodesic distance is computed only over reachable
pairs. If a network is highly fragmented (many unreachable pairs), a low mean
distance does not imply global efficiency — it simply means that within the
islands that are connected, distances are short. Always interpret alongside
reachable pair share.

### Diameter
The maximum geodesic distance observed between any two reachable nodes.
The longest shortest path in the network. A diameter of 3 means any two
reachable actors can reach each other in at most 3 steps; a diameter of 4
means at least one pair requires 4 steps.

### Reachable pair share
The proportion of all ordered node pairs (i,j) for which a directed path
from i to j exists (finite geodesic distance). Ranges from 0 (completely
disconnected) to 1 (every node can reach every other node via directed paths).
This is the most important connectivity indicator in this study: COMPON 2025
has reachable pair share 0.95 (near-fully connected), while LLM 2016–2025
reaches only 0.66, confirming that the LLM network is structurally fragmented
into semi-isolated islands despite preserving local clustering.

### Geodesic distance distribution
The full histogram of pairwise geodesic distances (including the mass at
infinity for unreachable pairs). This is the standard goodness-of-fit (GoF)
statistic for ERGM evaluation. Comparing the distribution across networks
reveals whether they have the same global connectivity profile, not just the
same mean.

---

## Part IV — Triad census

### Dyad
A pair of nodes. In a directed network, a dyad can be in one of three states:
- **Null (00)**: no edge in either direction
- **Asymmetric (10)**: one directed edge
- **Mutual (11)**: edges in both directions

### Triad
A set of three nodes. In a directed network, there are 16 possible
configurations of edges among three nodes, labelled by the MAN notation
(M = mutual dyads, A = asymmetric dyads, N = null dyads within the triple,
with additional suffixes for directionality).

### Triad census
A count of how many triads of each of the 16 types appear in the network.
The full census provides a structural fingerprint — two networks with similar
density can have very different triad compositions, reflecting different
organising logics (hierarchies vs. cliques vs. chains). The key types in
this study:

| Code | Description | Interpretation |
|---|---|---|
| 003 | No edges (empty) | Unconnected triple — more common in sparse networks |
| 102 | One mutual dyad, no third ties | Isolated mutual pair |
| 300 | All three mutual dyads (full clique) | Dense, tightly integrated triple |
| 210 | Two mutual + one asymmetric | Near-clique with one weak link |
| 021D | One node receives from two others | Local hierarchy / star |
| 030T | Transitive triple A→B→C, A→C | Hierarchical chain with closure |

The LLM networks have far more 003 (empty) triads and far fewer 300
(full clique) triads than COMPON, consistent with their lower density and
fragmentation.

---

## Part V — Centrality measures

### Degree centrality
The simplest centrality measure: a node's degree (total, in, or out) as a
proportion of the maximum possible degree (N−1). A node with degree centrality
1.0 is connected to every other node. Used here to operationalise the ACF
hypothesis that umbrella actors are the most central.

### Betweenness centrality
The proportion of shortest paths between all pairs of nodes that pass through
a given node. A node with high betweenness sits on many shortest paths and
acts as a broker or gatekeeper — information or influence flowing across the
network must pass through it. Formally:

    betweenness(v) = Σ_{s≠v≠t} [σ(s,t|v) / σ(s,t)]

where σ(s,t) is the number of shortest paths from s to t, and σ(s,t|v) is
the number of those paths that pass through v. Normalised betweenness divides
by the maximum possible value (N−1)(N−2) for directed networks.

In this study, betweenness is used to test H3 (specialist organisations as
knowledge brokers). The unexpected finding is that Ekologický institut Veronica
(ver) has the highest normalised betweenness in COMPON 2025 (0.170), far
exceeding all specialist organisations.

### Broker index
A composite measure constructed for this study as:

    broker index = betweenness / (degree / max_degree)

This captures betweenness *relative to* degree: a high broker index means a
node has disproportionately high betweenness given how many connections it has.
Pure hubs (high degree, high betweenness) score similarly to smaller nodes;
true brokers (moderate degree, very high betweenness) score highest. Used to
operationalise the ACF prediction that specialists function as knowledge brokers
independently of their raw connection count.

---

## Part VI — CUG tests

### Conditional Uniform Graph (CUG) test
A hypothesis test that asks: is the observed value of a network statistic
(e.g. transitivity, reciprocity) significantly different from what we would
expect in a random network of the same type?

A large sample of random graphs is generated under a null model, the statistic
is computed for each, and the observed statistic is compared to this null
distribution. The p-value is the proportion of random graphs with a statistic
greater than or equal to the observed value.

**Conditioning matters.** The null model can be conditioned on different
properties of the observed network:

- **Conditioned on edges**: random graphs have the same number of edges as
  observed, distributed uniformly at random. Tests whether clustering/reciprocity
  is higher than density alone would predict.
- **Conditioned on dyad census**: random graphs preserve the observed counts of
  null, asymmetric, and mutual dyads. This controls for the observed level of
  reciprocity when testing transitivity — a more conservative test.

In this study, both conditioning approaches are used for transitivity, and
edge-conditioning for reciprocity. All networks return p = 0 (the observed
statistic exceeds all 2000 simulated graphs), confirming that both clustering
and mutuality are genuine structural properties, not density artefacts.

---

## Part VII — Edge reconstruction quality metrics

These metrics evaluate how accurately the LLM-reconstructed networks reproduce
the COMPON 2025 ground truth at the level of individual edges.

### True positive (TP)
An edge present in both the LLM network and COMPON 2025. A correctly
identified collaboration tie.

### False positive (FP)
An edge present in the LLM network but absent in COMPON 2025. A tie the
LLM predicts but that does not appear in the ground truth — a hallucinated
or incorrectly inferred collaboration.

### False negative (FN)
An edge present in COMPON 2025 but absent in the LLM network. A real
collaboration tie the LLM failed to recover — a missed relationship.

### True negative (TN)
A cell that is 0 in both matrices. A correctly identified absence of a tie.

### Precision
The proportion of predicted ties that are correct:

    precision = TP / (TP + FP)

High precision means the LLM rarely invents ties that do not exist. In this
study, precision is stable at ~0.73 across all time windows, meaning roughly
three in four LLM-predicted ties are genuinely present in COMPON.

### Recall (sensitivity)
The proportion of real ties that are successfully recovered:

    recall = TP / (TP + FN)

Low recall means many real ties are missed. In this study, recall improves
from 0.28 (LLM 2025) to 0.45 (LLM 2016–2025) as the evidence window widens,
but remains well below 1.0. The LLM misses more ties than it finds.

### F1 score
The harmonic mean of precision and recall:

    F1 = 2 × (precision × recall) / (precision + recall)

Balances the trade-off between precision and recall in a single number.
Ranges from 0 to 1; higher is better. Used here as the primary summary
measure of reconstruction quality (0.40 → 0.46 → 0.55 across the three
LLM windows).

### Jaccard similarity
The proportion of ties present in either network that are present in both:

    Jaccard = TP / (TP + FP + FN)

Equivalent to the intersection over union of the two edge sets. Less
sensitive to the TN count than overall accuracy. Ranges from 0 to 1; values
in this study range from 0.25 (LLM 2025) to 0.38 (LLM 2016–2025).

### Hamming distance
The total number of cells where the two matrices disagree (FP + FN). A raw
count of edge-level disagreements regardless of direction. Lower is better.
Decreases from 128 (LLM 2025) to 111 (LLM 2016–2025) as reconstruction
quality improves.

---

## Part VIII — Statistical tests used

### Kruskal-Wallis test
A non-parametric one-way analysis of variance that tests whether the
distribution of a continuous variable differs across more than two groups.
Used here to test whether total degree differs significantly across the six
ACF actor categories. The null hypothesis is that all groups are drawn from
the same distribution. Does not assume normality. With n = 19 nodes across
6 categories (some with only 1–2 members), statistical power is very low
and results should be treated as exploratory.

### Wilcoxon rank-sum test (Mann-Whitney U test)
A non-parametric test comparing two independent groups. Tests whether one
group tends to have higher values than another. Used here for directional
(one-sided) hypothesis tests (e.g. "do umbrella actors have higher degree
than all others?"). The exact p-value cannot be computed when ties are present
in the data; the normal approximation (`exact = FALSE`) is used throughout,
which is standard practice with integer-valued network metrics.

### Pairwise Wilcoxon test with BH correction
All possible pairwise comparisons between the six ACF categories, with
Benjamini-Hochberg (BH) false discovery rate correction applied to control
for multiple comparisons. BH correction is less conservative than Bonferroni
and more appropriate when testing many related hypotheses simultaneously.

### Spearman rank correlation
A non-parametric correlation coefficient that measures the agreement between
two sets of rankings. Used here to measure: (1) how well the LLM preserves
the degree rank ordering of individual actors relative to COMPON; and (2) how
well the LLM preserves the degree rank ordering of ACF categories relative to
COMPON. Ranges from −1 (perfect reversal) to +1 (perfect agreement). Values
around 0.5–0.6 for individual actors and 0.71 for categories are interpreted
as moderate rank preservation.

---

## Part IX — ACF framework concepts referenced in hypotheses

### Advocacy Coalition Framework (ACF)
A theory of the policy process developed by Sabatier and Weible (2007).
Policy change occurs through competition between coalitions of actors who
share core policy beliefs and coordinate their strategies. Key concepts:

- **Policy core beliefs**: normative and empirical positions on fundamental
  policy issues (e.g. whether climate change requires systemic economic
  transformation). These are relatively stable and define coalition boundaries.
- **Secondary beliefs**: positions on specific policy instruments, more
  negotiable and subject to learning.
- **Policy-oriented learning**: the mechanism through which coalitions update
  beliefs in response to evidence, often mediated by technical brokers.

### Umbrella platform
In the Czech environmental context: organisations such as Klimatická koalice
(ccc) and Zelený kruh (grn) that aggregate member organisations around shared
belief systems and serve as the primary interface between the coalition and
state actors. Expected to have highest degree centrality because member
organisations routinely reference and co-produce outputs with the umbrella body.

### Knowledge broker
An actor who supplies technical and legal arguments that legitimate a
coalition's policy core beliefs (Sabatier & Weible, 2007). Expected to have
high betweenness centrality relative to degree — cited across otherwise
disconnected parts of the network. Operationalised here as the broker index.
In this study, Fakta o klimatu (fct), Frank Bold (frb), and CDE (cde) were
hypothesised to fulfil this role; the empirical finding is that Veronica (ver)
and Calla (cal) appear to be the actual structural brokers in COMPON 2025.

### Radical flank effect
The dynamic described by Haines (1984) whereby confrontational actors
(Limity jsme my, Fridays for Future, Extinction Rebellion) derive strategic
value from proximity to moderate coalition members while remaining structurally
isolated from the institutionalised periphery. Expected to produce a densely
connected sub-cluster with selective bridging ties to mainstream advocacy actors.

### Resource dependence theory
Pfeffer and Salancik (1978): organisations with regionally or thematically
bounded resource pools (sectoral specialists: Veronica, Calla, Beleco) will
maintain targeted ties to actors commanding broader coalition resources, without
becoming generalist connectors. Used to predict the semi-peripheral position
of sectoral specialists. Partially contradicted by COMPON 2025 data, where
Veronica and Calla are among the most central actors in the network.
