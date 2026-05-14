
# Network comparison: LLM-validated + RAW scraped vs COMPON ground truth

# --- SET SEED ----
set.seed(67) #also updated iteratons to 15k for more accurate p values
# 0. LOAD DATA

#I do run a bunch of QAP and MRQAP tests, on 15k iterations it takes like 20 min, could upgrade to library(future) and multi-core them to 6 cores
#since it seems to only use one thread and according to the internet this is the fix, but i think its fine its still plenty fast, not gonna rerun
library(sna)
library(network)
library(igraph)
library(purrr)
library(scales)
library(graphlayouts)

find_project_root <- function() {
  candidates <- unique(normalizePath(c(
    getwd(),
    file.path(getwd(), ".."),
    file.path(getwd(), "..", "..")
  ), winslash = "/", mustWork = FALSE))
  for (p in candidates) {
    if (dir.exists(file.path(p, "data")) && dir.exists(file.path(p, "scripts"))) {
      return(p)
    }
  }
  stop("Could not find project root. Run from the repository root or scripts/05_analysis_r.")
}

project_root <- find_project_root()
input_dir <- file.path(project_root, "data", "processed", "network", "r_inputs")
default_compon <- file.path(project_root, "data", "external", "compon_synthetic", "collab_2025_compon_synthetic.csv")
compon_matrix_path <- Sys.getenv("COMPON_MATRIX_PATH", default_compon)
analysis_output_dir <- file.path(project_root, "outputs", "analysis_r")
dir.create(analysis_output_dir, recursive = TRUE, showWarnings = FALSE)

# --- COMPON network ----
compon_2025   <- read.csv(compon_matrix_path, header = TRUE, check.names = FALSE)

# --- LLM-validated networks --------------------------------------------------
llm_2025      <- read.csv(file.path(input_dir, "collab_2025_LLM.csv"),          header = TRUE, check.names = FALSE)
llm_2024_2025 <- read.csv(file.path(input_dir, "collab_2024_and_2025_LLM.csv"), header = TRUE, check.names = FALSE)
llm_all       <- read.csv(file.path(input_dir, "collab_all_LLM.csv"),           header = TRUE, check.names = FALSE)

# --- Raw scraped networks (collab + comention = 1, directed, no LLM filter) --
raw_2025      <- read.csv(file.path(input_dir, "merged_2025_directed.csv"),          header = TRUE, check.names = FALSE)
raw_2024_2025 <- read.csv(file.path(input_dir, "merged_2024_and_2025_directed.csv"), header = TRUE, check.names = FALSE)
raw_all       <- read.csv(file.path(input_dir, "merged_2016_2025_directed.csv"),     header = TRUE, check.names = FALSE)

setwd(analysis_output_dir)

# --- Set rownames from colnames ----------------------------------------------
for (df_name in c("llm_2025", "compon_2025", "llm_2024_2025", "llm_all",
                  "raw_2025", "raw_2024_2025", "raw_all")) {
  df <- get(df_name)
  rownames(df) <- colnames(df)
  assign(df_name, df)
}

# --- Canonical actor order (LLM all as reference) ----------------------------
actor_order <- colnames(llm_all)

# Sanity checks
if (!all(actor_order %in% colnames(compon_2025)))   stop("Missing nodes in COMPON data!")
if (!all(actor_order %in% colnames(raw_2025)))      stop("Missing nodes in raw_2025!")
if (!all(actor_order %in% colnames(raw_2024_2025))) stop("Missing nodes in raw_2024_2025!")
if (!all(actor_order %in% colnames(raw_all)))       stop("Missing nodes in raw_all!")

# Reindex all networks to canonical order
# [FIX v3] llm_all was previously missing from this block
llm_2025      <- llm_2025[actor_order, actor_order]
compon_2025   <- compon_2025[actor_order, actor_order]
llm_2024_2025 <- llm_2024_2025[actor_order, actor_order]
llm_all       <- llm_all[actor_order, actor_order]   
raw_2025      <- raw_2025[actor_order, actor_order]
raw_2024_2025 <- raw_2024_2025[actor_order, actor_order]
raw_all       <- raw_all[actor_order, actor_order]

# --- Build binary matrices ---------------------------------------------------

to_mat <- function(df) {
  m <- matrix(as.integer(as.matrix(df) > 0), nrow = length(actor_order),
              dimnames = list(rownames(df), colnames(df)))
  diag(m) <- 0
  m
}

m_llm25    <- to_mat(llm_2025)
m_comp25   <- to_mat(compon_2025)
m_llm2425  <- to_mat(llm_2024_2025)
m_llm_all  <- to_mat(llm_all)
m_raw25    <- to_mat(raw_2025)
m_raw2425  <- to_mat(raw_2024_2025)
m_raw_all  <- to_mat(raw_all)

# --- Structural control matrices for MRQAP (derived from COMPON response) ----
# Transitive closure: (i,j) = 1 if any 2-path i→k→j exists in COMPON
trans_comp25        <- ((m_comp25 %*% m_comp25) > 0) * 1L
diag(trans_comp25)  <- 0
# Reciprocity: (i,j) = 1 if reverse tie j→i exists in COMPON
recip_comp25        <- t(m_comp25)

storage.mode(trans_comp25) <- "double"
storage.mode(recip_comp25) <- "double"

# --- Build sna network objects -----------------------------------------------
net_llm25    <- as.network(m_llm25,   directed = TRUE)
net_comp25   <- as.network(m_comp25,  directed = TRUE)
net_llm2425  <- as.network(m_llm2425, directed = TRUE)
net_llm_all  <- as.network(m_llm_all, directed = TRUE)
net_raw25    <- as.network(m_raw25,   directed = TRUE)
net_raw2425  <- as.network(m_raw2425, directed = TRUE)
net_raw_all  <- as.network(m_raw_all, directed = TRUE)

# --- Build igraph objects ----------------------------------------------------
ig_llm25    <- graph_from_adjacency_matrix(m_llm25,   mode = "directed")
ig_comp25   <- graph_from_adjacency_matrix(m_comp25,  mode = "directed")
ig_llm2425  <- graph_from_adjacency_matrix(m_llm2425, mode = "directed")
ig_llm_all  <- graph_from_adjacency_matrix(m_llm_all, mode = "directed")
ig_raw25    <- graph_from_adjacency_matrix(m_raw25,   mode = "directed")
ig_raw2425  <- graph_from_adjacency_matrix(m_raw2425, mode = "directed")
ig_raw_all  <- graph_from_adjacency_matrix(m_raw_all, mode = "directed")

V(ig_llm25)$name    <- actor_order
V(ig_comp25)$name   <- actor_order
V(ig_llm2425)$name  <- actor_order
V(ig_llm_all)$name  <- actor_order
V(ig_raw25)$name    <- actor_order
V(ig_raw2425)$name  <- actor_order
V(ig_raw_all)$name  <- actor_order

cat("=== Networks loaded. Nodes:", network.size(net_comp25), "===\n")
cat("Actor order:", paste(actor_order, collapse = ", "), "\n\n")
cat(sprintf("Edges — LLM 2025: %d | LLM 2024+25: %d | LLM 2016-25: %d\n",
            network.edgecount(net_llm25), network.edgecount(net_llm2425),
            network.edgecount(net_llm_all)))
cat(sprintf("       Raw 2025: %d | Raw 2024+25: %d | Raw 2016-25: %d\n",
            network.edgecount(net_raw25), network.edgecount(net_raw2425),
            network.edgecount(net_raw_all)))
cat(sprintf("       COMPON 2025: %d\n\n", network.edgecount(net_comp25)))


# - --1. HELPER FUNCTIONS ----


# --- 1a. Basic descriptives --------------------------------------------------
basic_stats <- function(net, mat, label) {
  n      <- network.size(net)
  edges  <- network.edgecount(net)
  dens   <- gden(net, diag = FALSE)
  recip  <- grecip(net, measure = "dyadic")
  trans  <- gtrans(net)
  indeg  <- sna::degree(net, cmode = "indegree")
  outdeg <- sna::degree(net, cmode = "outdegree")

  cat("----------------------------------------------------------------------\n")
  cat("NETWORK:", label, "\n")
  cat("  Nodes:            ", n, "\n")
  cat("  Edges:            ", edges, "\n")
  cat("  Density:          ", round(dens,  4), "\n")
  cat("  Reciprocity:      ", round(recip, 4), "\n")
  cat("  Transitivity:     ", round(trans, 4), "\n")
  cat("  In-degree  mean:  ", round(mean(indeg),  3), "  sd:", round(sd(indeg),  3), "\n")
  cat("  Out-degree mean:  ", round(mean(outdeg), 3), "  sd:", round(sd(outdeg), 3), "\n\n")

  invisible(list(n=n, edges=edges, density=dens, reciprocity=recip,
                 transitivity=trans, indeg=indeg, outdeg=outdeg))
}

# --- 1b. Geodesic distance stats ---------------------------------------------
geo_stats <- function(net, label) {
  gd     <- geodist(net)$gdist
  finite <- gd[gd < Inf & gd > 0]
  n2     <- nrow(gd)^2 - nrow(gd)

  cat("  Geodesic distances [", label, "]:\n")
  cat("    Mean (reachable):      ", round(mean(finite), 3), "\n")
  cat("    Diameter:              ", max(finite), "\n")
  cat("    Reachable pair share:  ", round(length(finite) / n2, 3), "\n\n")

  invisible(finite)
}

# --- 1c. Triad census --------------------------------------------------------
triad_stats <- function(net, label) {
  tc <- sna::triad.census(net)
  cat("  Triad census [", label, "]:\n")
  print(tc)
  cat("\n")
  invisible(tc)
}

# --- 1d. CUG tests (conditioned on edges AND dyad census) --------------------
run_cug_strict <- function(net, label, reps = 15000) {
  indeg_var    <- function(x) { var(sna::degree(x, cmode = "indegree")) }
  outdeg_var   <- function(x) { var(sna::degree(x, cmode = "outdegree")) }
  mutual_dyads <- function(x) { sna::dyad.census(x)[1] }

  stat_funs <- list(
    reciprocity  = function(x) grecip(x, measure = "dyadic"),
    transitivity = gtrans,
    indeg_var    = indeg_var,
    outdeg_var   = outdeg_var,
    mutual_dyads = mutual_dyads
  )

  run_one <- function(cmode) {
    results <- lapply(names(stat_funs), function(stat_name) {
      cug  <- cug.test(net, FUN = stat_funs[[stat_name]], cmode = cmode, reps = reps)
      obs  <- cug$obs.stat
      nmn  <- mean(cug$rep.stat)
      nsd  <- sd(cug$rep.stat)

      if (nsd == 0 || is.na(nsd)) {
        z <- 0; pval <- 1
      } else {
        z    <- (obs - nmn) / nsd
        pval <- min(2 * min(cug$pgteobs, cug$plteobs), 1)
      }

      stars    <- ifelse(pval < 0.001, "***",
                         ifelse(pval < 0.01, "**",
                                ifelse(pval < 0.05, "*",
                                       ifelse(pval < 0.1, ".", ""))))
      pval_fmt <- ifelse(pval < 0.0001, "< 0.0001", sprintf("%.4f", pval))

      data.frame(
        Statistic = stat_name,
        Observed  = round(obs, 4),
        Null_mean = round(nmn, 4),
        Null_SD   = round(nsd, 4),
        p_value   = pval_fmt,
        z         = sprintf("%+.2f%s", z, stars),
        stringsAsFactors = FALSE
      )
    })
    do.call(rbind, results)
  }

  tbl_edges <- run_one("edges")
  tbl_dyad  <- run_one("dyad.census")

  cat("\nCUG test results —", label, "(reps =", reps, ")\n")
  cat(rep("=", 72), "\n", sep = "")
  cat("  Conditioned on: EDGES\n")
  cat(rep("-", 72), "\n", sep = "")
  print(tbl_edges, row.names = FALSE)
  cat(rep("-", 72), "\n", sep = "")
  cat("\n  Conditioned on: DYAD CENSUS\n")
  cat(rep("-", 72), "\n", sep = "")
  print(tbl_dyad, row.names = FALSE)
  cat(rep("-", 72), "\n", sep = "")
  cat("Signif. codes: *** p<0.001  ** p<0.01  * p<0.05  . p<0.1\n\n")

  invisible(list(edges = tbl_edges, dyad_census = tbl_dyad))
}

# --- 1e. Edge-level overlap --------------------------------------------------
edge_overlap <- function(mat_a, mat_b, label_a, label_b) {
  n_nodes    <- nrow(mat_a)
  n_dyads    <- n_nodes * (n_nodes - 1)
  tp         <- sum(mat_a == 1 & mat_b == 1)
  fp         <- sum(mat_a == 1 & mat_b == 0)
  fn         <- sum(mat_a == 0 & mat_b == 1)
  tn         <- n_dyads - tp - fp - fn
  agree      <- (tp + tn) / n_dyads
  precision  <- tp / (tp + fp)
  recall     <- tp / (tp + fn)
  f1         <- 2 * precision * recall / (precision + recall)
  jaccard    <- tp / (tp + fp + fn)
  hamming    <- fp + fn

  cat("  Edge overlap:", label_a, "vs", label_b, "\n")
  cat("    TP:", tp, "  FP:", fp, "  FN:", fn, "  TN:", tn, "\n")
  cat("    Precision: ", round(precision, 3), "\n")
  cat("    Recall:    ", round(recall,    3), "\n")
  cat("    F1 score:  ", round(f1,        3), "\n")
  cat("    Jaccard:   ", round(jaccard,   3), "\n")
  cat("    Hamming:   ", hamming, "edge disagreements\n")
  cat("    Cell agree:", round(agree * 100, 1), "%\n\n")

  invisible(list(tp=tp, fp=fp, fn=fn, tn=tn,
                 precision=precision, recall=recall, f1=f1,
                 jaccard=jaccard, hamming=hamming))
}

# --- 1f. Degree correlation between networks ---------------------------------
deg_correlation <- function(net_a, net_b, label_a, label_b) {
  in_a  <- sna::degree(net_a, cmode = "indegree")
  in_b  <- sna::degree(net_b, cmode = "indegree")
  out_a <- sna::degree(net_a, cmode = "outdegree")
  out_b <- sna::degree(net_b, cmode = "outdegree")
  r_in  <- cor(in_a, in_b,  method = "spearman")
  r_out <- cor(out_a, out_b, method = "spearman")

  cat("  Degree rank correlation:", label_a, "vs", label_b, "\n")
  cat("    In-degree  Spearman r:", round(r_in,  3), "\n")
  cat("    Out-degree Spearman r:", round(r_out, 3), "\n\n")

  invisible(list(r_in=r_in, r_out=r_out))
}

# --- 1g. QAP Matrix Correlation ----------------------------------------------
qap_correlation <- function(mat_llm, mat_comp, label_llm, label_comp, reps = 15000) {
  qap_res <- sna::qaptest(list(mat_llm, mat_comp), gcor, g1 = 1, g2 = 2, reps = reps)
  pval    <- qap_res$pgreq

  cat("  QAP Matrix Correlation:", label_llm, "vs", label_comp, "\n")
  cat("    Observed correlation (gcor):", round(qap_res$testval, 4), "\n")
  cat("    p-value (reps=", reps, "):     ", pval, "\n\n", sep = "")

  invisible(qap_res)
}

# --- 1h. QAP Logistic Regression ---------------------------------------------
run_qap_logit <- function(mat_pred, mat_resp, label_pred, label_resp, reps = 15000) {
  cat("  QAP Logistic Regression:\n")
  cat("    Predictor:", label_pred, "--> Response:", label_resp, "\n")
  nl_model <- sna::netlogit(mat_resp, list(mat_pred), reps = reps)
  coef_obs <- nl_model$coefficients[2]
  pval     <- nl_model$pgteobs[2]

  cat("    Predictor Coefficient: ", round(coef_obs, 4), "\n")
  cat("    p-value (reps=", reps, "):     ", pval, "\n\n", sep = "")

  invisible(nl_model)
}

# --- 1i. ESP — Edgewise Shared Partners (OTP) [NEW] -------------------------
# For each directed edge i→j, counts nodes h where both i→h and j→h
# (outgoing two-path shared partners). Matrix formula: sp_mat = M %*% t(M).
# No external package required.

esp_stats <- function(mat, label) {
  sp_mat       <- mat %*% t(mat)
  diag(sp_mat) <- 0
  edge_sp      <- sp_mat[mat == 1]

  if (length(edge_sp) == 0) {
    cat("  ESP [", label, "]: no edges\n\n")
    return(invisible(integer(0)))
  }

  max_k  <- min(max(edge_sp), 8)
  counts <- tabulate(edge_sp + 1, nbins = max_k + 1)
  names(counts) <- as.character(0:max_k)

  cat("  ESP (OTP shared partners) [", label, "]:\n")
  cat("    Distribution:", paste(names(counts), "=", counts, collapse = "  "), "\n")
  cat("    Mean ESP:    ", round(mean(edge_sp), 3), "\n")
  cat("    Max ESP:     ", max(edge_sp), "\n\n")

  invisible(counts)
}

# --- 1j. MRQAP — Step 1: base (unadjusted), Step 2: controlled ---------------

# Step 1 — raw predictive power, no structural controls
run_mrqap_base <- function(mat_pred, mat_resp, label_pred, reps = 15000) {
  cat("  MRQAP Step 1 — Base (unadjusted):", label_pred, "\n")
  nl <- sna::netlogit(mat_resp, list(mat_pred), reps = reps)
  stars <- ifelse(nl$pgreq[2] < 0.001, "***",
                  ifelse(nl$pgreq[2] < 0.01,  "**",
                         ifelse(nl$pgreq[2] < 0.05, "*",
                                ifelse(nl$pgreq[2] < 0.1, ".", ""))))
  cat(sprintf("    %-26s Coef: %+8.4f  OR: %7.4f  p: %.4f %s\n",
              label_pred, nl$coefficients[2],
              exp(nl$coefficients[2]), nl$pgreq[2], stars))
  cat(sprintf("    Pseudo-R2 (McFadden): %.4f\n\n",
              1 - nl$deviance / nl$null.deviance))
  invisible(nl)
}

# Step 2 — controlled for COMPON's own transitivity and reciprocity
run_mrqap_controlled <- function(mat_pred, mat_resp, mat_trans, mat_recip,
                                 label_pred, reps = 15000) {
  cat("  MRQAP Step 2 — Controlled (transitivity + reciprocity):", label_pred, "\n")
  nl <- sna::netlogit(mat_resp, list(mat_pred, mat_trans, mat_recip), reps = reps)
  pred_names <- c(label_pred, "Transitivity (2-path)", "Reciprocity")
  for (i in 2:4) {
    stars <- ifelse(nl$pgreq[i] < 0.001, "***",
                    ifelse(nl$pgreq[i] < 0.01,  "**",
                           ifelse(nl$pgreq[i] < 0.05, "*",
                                  ifelse(nl$pgreq[i] < 0.1, ".", ""))))
    cat(sprintf("    %-26s Coef: %+8.4f  OR: %7.4f  p: %.4f %s\n",
                pred_names[i - 1], nl$coefficients[i],
                exp(nl$coefficients[i]), nl$pgreq[i], stars))
  }
  cat(sprintf("    Pseudo-R2 (McFadden): %.4f\n\n",
              1 - nl$deviance / nl$null.deviance))
  invisible(nl)
}


# --- 2.  COMPARISON A — llm_2025 vs compon_2025 ----


cat("\n##############################################################\n")
cat("# COMPARISON A: LLM 2025  vs  COMPON 2025                   #\n")
cat("##############################################################\n\n")

stats_llm25  <- basic_stats(net_llm25,  m_llm25,  "LLM 2025")
stats_comp25 <- basic_stats(net_comp25, m_comp25, "COMPON 2025")

geo_llm25  <- geo_stats(net_llm25,  "LLM 2025")
geo_comp25 <- geo_stats(net_comp25, "COMPON 2025")

triad_stats(net_llm25,  "LLM 2025")
triad_stats(net_comp25, "COMPON 2025")

esp_llm25  <- esp_stats(m_llm25,  "LLM 2025")
esp_comp25 <- esp_stats(m_comp25, "COMPON 2025")

cug_strict_llm25  <- run_cug_strict(net_llm25,  "LLM 2025")
cug_strict_comp25 <- run_cug_strict(net_comp25, "COMPON 2025")

overlap_A  <- edge_overlap(m_llm25, m_comp25, "LLM 2025", "COMPON 2025")
degcor_A   <- deg_correlation(net_llm25, net_comp25, "LLM 2025", "COMPON 2025")
qap_cor_A  <- qap_correlation(m_llm25, m_comp25, "LLM 2025", "COMPON 2025")
qap_log_A  <- run_qap_logit(m_llm25, m_comp25, "LLM 2025", "COMPON 2025")


# --- 3.  COMPARISON B — llm_2024_2025 vs compon_2025 ----


cat("\n##############################################################\n")
cat("# COMPARISON B: LLM 2024+2025  vs  COMPON 2025              #\n")
cat("##############################################################\n\n")

stats_llm2425 <- basic_stats(net_llm2425, m_llm2425, "LLM 2024+2025")

geo_llm2425   <- geo_stats(net_llm2425, "LLM 2024+2025")
triad_stats(net_llm2425, "LLM 2024+2025")

esp_llm2425 <- esp_stats(m_llm2425, "LLM 2024+2025")

cug_strict_llm2425 <- run_cug_strict(net_llm2425, "LLM 2024+2025")

overlap_B  <- edge_overlap(m_llm2425, m_comp25, "LLM 2024+2025", "COMPON 2025")
degcor_B   <- deg_correlation(net_llm2425, net_comp25, "LLM 2024+2025", "COMPON 2025")
qap_cor_B  <- qap_correlation(m_llm2425, m_comp25, "LLM 2024+2025", "COMPON 2025")
qap_log_B  <- run_qap_logit(m_llm2425, m_comp25, "LLM 2024+2025", "COMPON 2025")


# --- 4.  COMPARISON C — llm_all vs compon_2025 ----


cat("\n##############################################################\n")
cat("# COMPARISON C: LLM 2016-2025  vs  COMPON 2025              #\n")
cat("##############################################################\n\n")

stats_llm_all <- basic_stats(net_llm_all, m_llm_all, "LLM 2016-2025")
geo_llm_all   <- geo_stats(net_llm_all, "LLM 2016-2025")
triad_stats(net_llm_all, "LLM 2016-2025")

esp_llm_all <- esp_stats(m_llm_all, "LLM 2016-2025")

cug_strict_llm_all <- run_cug_strict(net_llm_all, "LLM 2016-2025")

overlap_C  <- edge_overlap(m_llm_all, m_comp25, "LLM 2016-2025", "COMPON 2025")
degcor_C   <- deg_correlation(net_llm_all, net_comp25, "LLM 2016-2025", "COMPON 2025")
qap_cor_C  <- qap_correlation(m_llm_all, m_comp25, "LLM 2016-2025", "COMPON 2025")
qap_log_C  <- run_qap_logit(m_llm_all, m_comp25, "LLM 2016-2025", "COMPON 2025")


# --- 5.  COMPARISON D — raw_2025 vs compon_2025 ----


cat("\n##############################################################\n")
cat("# COMPARISON D: RAW 2025  vs  COMPON 2025                   #\n")
cat("##############################################################\n\n")

stats_raw25 <- basic_stats(net_raw25, m_raw25, "Raw 2025")
geo_raw25   <- geo_stats(net_raw25, "Raw 2025")
triad_stats(net_raw25, "Raw 2025")

esp_raw25 <- esp_stats(m_raw25, "Raw 2025")

cug_strict_raw25 <- run_cug_strict(net_raw25, "Raw 2025")

overlap_D  <- edge_overlap(m_raw25, m_comp25, "Raw 2025", "COMPON 2025")
degcor_D   <- deg_correlation(net_raw25, net_comp25, "Raw 2025", "COMPON 2025")
qap_cor_D  <- qap_correlation(m_raw25, m_comp25, "Raw 2025", "COMPON 2025")
qap_log_D  <- run_qap_logit(m_raw25, m_comp25, "Raw 2025", "COMPON 2025")


# --- 6.  COMPARISON E — raw_2024_2025 vs compon_2025 ----


cat("\n##############################################################\n")
cat("# COMPARISON E: RAW 2024+2025  vs  COMPON 2025              #\n")
cat("##############################################################\n\n")

stats_raw2425 <- basic_stats(net_raw2425, m_raw2425, "Raw 2024+2025")
geo_raw2425   <- geo_stats(net_raw2425, "Raw 2024+2025")
triad_stats(net_raw2425, "Raw 2024+2025")

esp_raw2425 <- esp_stats(m_raw2425, "Raw 2024+2025")

cug_strict_raw2425 <- run_cug_strict(net_raw2425, "Raw 2024+2025")

overlap_E  <- edge_overlap(m_raw2425, m_comp25, "Raw 2024+2025", "COMPON 2025")
degcor_E   <- deg_correlation(net_raw2425, net_comp25, "Raw 2024+2025", "COMPON 2025")
qap_cor_E  <- qap_correlation(m_raw2425, m_comp25, "Raw 2024+2025", "COMPON 2025")
qap_log_E  <- run_qap_logit(m_raw2425, m_comp25, "Raw 2024+2025", "COMPON 2025")


# --- 7.  COMPARISON F — raw_all vs compon_2025 ----


cat("\n##############################################################\n")
cat("# COMPARISON F: RAW 2016-2025  vs  COMPON 2025              #\n")
cat("##############################################################\n\n")

stats_raw_all <- basic_stats(net_raw_all, m_raw_all, "Raw 2016-2025")
geo_raw_all   <- geo_stats(net_raw_all, "Raw 2016-2025")
triad_stats(net_raw_all, "Raw 2016-2025")

esp_raw_all <- esp_stats(m_raw_all, "Raw 2016-2025")

cug_strict_raw_all <- run_cug_strict(net_raw_all, "Raw 2016-2025")

overlap_F  <- edge_overlap(m_raw_all, m_comp25, "Raw 2016-2025", "COMPON 2025")
degcor_F   <- deg_correlation(net_raw_all, net_comp25, "Raw 2016-2025", "COMPON 2025")
qap_cor_F  <- qap_correlation(m_raw_all, m_comp25, "Raw 2016-2025", "COMPON 2025")
qap_log_F  <- run_qap_logit(m_raw_all, m_comp25, "Raw 2016-2025", "COMPON 2025")


# --- 8.  SUMMARY TABLES (side-by-side, all 7 networks) ----


cat("\n##############################################################\n")
cat("# SUMMARY — all networks side by side                       #\n")
cat("##############################################################\n\n")

n_nodes <- stats_llm25$n
n_dyads <- n_nodes * (n_nodes - 1)

summary_df <- data.frame(
  Metric        = c("Nodes", "Edges", "Density", "Reciprocity", "Transitivity",
                    "Mean in-degree", "Mean out-degree",
                    "Mean geodesic dist.", "Diameter", "Reachable pair share"),
  COMPON_2025   = c(stats_comp25$n,   stats_comp25$edges,
                    round(stats_comp25$density, 4),   round(stats_comp25$reciprocity, 4),
                    round(stats_comp25$transitivity, 4), round(mean(stats_comp25$indeg), 3),
                    round(mean(stats_comp25$outdeg), 3), round(mean(geo_comp25), 3),
                    max(geo_comp25),   round(length(geo_comp25)  / n_dyads, 3)),
  LLM_2025      = c(stats_llm25$n,    stats_llm25$edges,
                    round(stats_llm25$density, 4),    round(stats_llm25$reciprocity, 4),
                    round(stats_llm25$transitivity, 4), round(mean(stats_llm25$indeg), 3),
                    round(mean(stats_llm25$outdeg), 3), round(mean(geo_llm25), 3),
                    max(geo_llm25),    round(length(geo_llm25)   / n_dyads, 3)),
  LLM_2024_2025 = c(stats_llm2425$n,  stats_llm2425$edges,
                    round(stats_llm2425$density, 4),  round(stats_llm2425$reciprocity, 4),
                    round(stats_llm2425$transitivity, 4), round(mean(stats_llm2425$indeg), 3),
                    round(mean(stats_llm2425$outdeg), 3), round(mean(geo_llm2425), 3),
                    max(geo_llm2425),  round(length(geo_llm2425) / n_dyads, 3)),
  LLM_2016_2025 = c(stats_llm_all$n,  stats_llm_all$edges,
                    round(stats_llm_all$density, 4),  round(stats_llm_all$reciprocity, 4),
                    round(stats_llm_all$transitivity, 4), round(mean(stats_llm_all$indeg), 3),
                    round(mean(stats_llm_all$outdeg), 3), round(mean(geo_llm_all), 3),
                    max(geo_llm_all),  round(length(geo_llm_all) / n_dyads, 3)),
  Raw_2025      = c(stats_raw25$n,    stats_raw25$edges,
                    round(stats_raw25$density, 4),    round(stats_raw25$reciprocity, 4),
                    round(stats_raw25$transitivity, 4), round(mean(stats_raw25$indeg), 3),
                    round(mean(stats_raw25$outdeg), 3), round(mean(geo_raw25), 3),
                    max(geo_raw25),    round(length(geo_raw25)   / n_dyads, 3)),
  Raw_2024_2025 = c(stats_raw2425$n,  stats_raw2425$edges,
                    round(stats_raw2425$density, 4),  round(stats_raw2425$reciprocity, 4),
                    round(stats_raw2425$transitivity, 4), round(mean(stats_raw2425$indeg), 3),
                    round(mean(stats_raw2425$outdeg), 3), round(mean(geo_raw2425), 3),
                    max(geo_raw2425),  round(length(geo_raw2425) / n_dyads, 3)),
  Raw_2016_2025 = c(stats_raw_all$n,  stats_raw_all$edges,
                    round(stats_raw_all$density, 4),  round(stats_raw_all$reciprocity, 4),
                    round(stats_raw_all$transitivity, 4), round(mean(stats_raw_all$indeg), 3),
                    round(mean(stats_raw_all$outdeg), 3), round(mean(geo_raw_all), 3),
                    max(geo_raw_all),  round(length(geo_raw_all) / n_dyads, 3))
)

print(summary_df, row.names = FALSE)

cat("\n--- Edge overlap vs COMPON 2025 (LLM-validated) ---\n")
cat(sprintf("  LLM 2025      — Precision: %.3f  Recall: %.3f  F1: %.3f  Jaccard: %.3f\n",
            overlap_A$precision, overlap_A$recall, overlap_A$f1, overlap_A$jaccard))
cat(sprintf("  LLM 2024+25   — Precision: %.3f  Recall: %.3f  F1: %.3f  Jaccard: %.3f\n",
            overlap_B$precision, overlap_B$recall, overlap_B$f1, overlap_B$jaccard))
cat(sprintf("  LLM 2016-2025 — Precision: %.3f  Recall: %.3f  F1: %.3f  Jaccard: %.3f\n",
            overlap_C$precision, overlap_C$recall, overlap_C$f1, overlap_C$jaccard))

cat("\n--- Edge overlap vs COMPON 2025 (Raw scraped) ---\n")
cat(sprintf("  Raw 2025      — Precision: %.3f  Recall: %.3f  F1: %.3f  Jaccard: %.3f\n",
            overlap_D$precision, overlap_D$recall, overlap_D$f1, overlap_D$jaccard))
cat(sprintf("  Raw 2024+25   — Precision: %.3f  Recall: %.3f  F1: %.3f  Jaccard: %.3f\n",
            overlap_E$precision, overlap_E$recall, overlap_E$f1, overlap_E$jaccard))
cat(sprintf("  Raw 2016-2025 — Precision: %.3f  Recall: %.3f  F1: %.3f  Jaccard: %.3f\n",
            overlap_F$precision, overlap_F$recall, overlap_F$f1, overlap_F$jaccard))

cat("\n--- Degree rank correlation (Spearman) vs COMPON 2025 ---\n")
cat(sprintf("  LLM 2025      — In-deg r: %.3f  Out-deg r: %.3f\n", degcor_A$r_in, degcor_A$r_out))
cat(sprintf("  LLM 2024+25   — In-deg r: %.3f  Out-deg r: %.3f\n", degcor_B$r_in, degcor_B$r_out))
cat(sprintf("  LLM 2016-2025 — In-deg r: %.3f  Out-deg r: %.3f\n", degcor_C$r_in, degcor_C$r_out))
cat(sprintf("  Raw 2025      — In-deg r: %.3f  Out-deg r: %.3f\n", degcor_D$r_in, degcor_D$r_out))
cat(sprintf("  Raw 2024+25   — In-deg r: %.3f  Out-deg r: %.3f\n", degcor_E$r_in, degcor_E$r_out))
cat(sprintf("  Raw 2016-2025 — In-deg r: %.3f  Out-deg r: %.3f\n", degcor_F$r_in, degcor_F$r_out))


# --- 9.  PLOTS ----


# Shared base layout (FR, for COMPON-coloured network in section 10)
base_layout <- layout_with_fr(ig_comp25)

# Helper: push overlapping nodes apart
repulse <- function(lo, min_dist = 0.25, iters = 1000) {
  n <- nrow(lo)
  for (i in seq_len(iters)) {
    moved <- FALSE
    for (a in 1:(n - 1)) {
      for (b in (a + 1):n) {
        dx <- lo[b, 1] - lo[a, 1]
        dy <- lo[b, 2] - lo[a, 2]
        d  <- sqrt(dx^2 + dy^2)
        if (d < min_dist && d > 1e-9) {
          push      <- (min_dist - d) / 2
          lo[a, 1]  <- lo[a, 1] - push * dx / d
          lo[a, 2]  <- lo[a, 2] - push * dy / d
          lo[b, 1]  <- lo[b, 1] + push * dx / d
          lo[b, 2]  <- lo[b, 2] + push * dy / d
          moved     <- TRUE
        }
      }
    }
    if (!moved) break
  }
  lo
}

plot_net <- function(mat, title) {
  g <- graph_from_adjacency_matrix(mat, mode = "directed")

  iso_idx <- which(igraph::degree(g, mode = "all") == 0)
  con_idx <- which(igraph::degree(g, mode = "all") > 0)

  set.seed(42)
  lo <- graphlayouts::layout_with_stress(g)

  if (length(con_idx) > 0) {
    cx <- lo[con_idx, 1] - mean(lo[con_idx, 1])
    cy <- lo[con_idx, 2] - mean(lo[con_idx, 2])
    s  <- max(max(abs(cx)), max(abs(cy))) + 1e-9
    lo[con_idx, 1] <- cx / s * 1.8
    lo[con_idx, 2] <- cy / s * 1.8
  }

  n_iso <- length(iso_idx)
  if (n_iso > 0) {
    angles <- seq(0, 2 * pi, length.out = n_iso + 1)[-(n_iso + 1)]
    lo[iso_idx, 1] <- cos(angles) * 2.8
    lo[iso_idx, 2] <- sin(angles) * 2.8
  }

  if (length(con_idx) > 1)
    lo[con_idx, ] <- repulse(lo[con_idx, ], min_dist = 0.30, iters = 1000)

  deg   <- igraph::degree(g, mode = "all")
  vsize <- scales::rescale(deg, to = c(8, 20))
  vsize[deg == 0] <- 7

  plot(g,
       layout              = lo,
       rescale             = TRUE,
       vertex.size         = vsize,
       vertex.color        = "#C6DDF5",
       vertex.frame.color  = "#1A5FA8",
       vertex.frame.width  = 1.4,
       vertex.label        = V(g)$name,
       vertex.label.cex    = 0.52,
       vertex.label.color  = "#031E3A",
       vertex.label.font   = 2,
       vertex.label.dist   = 0,
       edge.arrow.size     = 0.35,
       edge.arrow.width    = 1.0,
       edge.color          = adjustcolor("#555550", alpha.f = 0.55),
       edge.width          = 0.9,
       edge.curved         = 0.18,
       main                = title,
       cex.main            = 1.05,
       font.main           = 2,
       margin              = c(0.12, 0.08, 0.05, 0.08))
}

plot_deg <- function(net, label, cmode) {
  d <- sna::degree(net, cmode = cmode)
  barplot(table(d), main = paste(label, "\n", cmode),
          xlab = "Degree", ylab = "Count",
          col = "#B5D4F4", border = "#185FA5")
}

plot_geo <- function(net, label) {
  gd      <- geodist(net)$gdist
  gd_vals <- gd[gd < Inf & gd > 0]
  max_d   <- max(gd_vals)
  hist(gd_vals, breaks = seq(0.5, max_d + 0.5, 1),
       main = paste("Geodesic dist.\n", label),
       xlab = "Distance", ylab = "Frequency",
       col = "#9FE1CB", border = "#0F6E56",
       right = FALSE, xaxt = "n")
  axis(1, at = 1:max_d)
}

plot_esp <- function(mat, label) {
  sp_mat       <- mat %*% t(mat)
  diag(sp_mat) <- 0
  edge_sp      <- sp_mat[mat == 1]

  if (length(edge_sp) == 0) {
    plot.new(); title(paste("ESP (OTP)\n", label, "\n[no edges]")); return(invisible(NULL))
  }

  max_k  <- min(max(edge_sp), 8)
  counts <- tabulate(edge_sp + 1, nbins = max_k + 1)
  names(counts) <- as.character(0:max_k)

  barplot(counts,
          names.arg = names(counts),
          main  = paste("ESP (OTP)\n", label),
          xlab  = "Shared partners (k)",
          ylab  = "# edges with k shared partners",
          col   = "#C6A5E8",
          border = "#6A3DAA")
}

make_diff_mat <- function(mat_llm, mat_comp) {
  result <- matrix(0, nrow = nrow(mat_llm), ncol = ncol(mat_llm))
  result[mat_llm == 1 & mat_comp == 1] <- 1
  result[mat_llm == 1 & mat_comp == 0] <- 2
  result[mat_llm == 0 & mat_comp == 1] <- 3
  result
}

plot_diff <- function(dmat, label) {
  cols <- c("white", "#1D9E75", "#D85A30", "#378ADD")
  image(t(dmat[nrow(dmat):1, ]), col = cols, axes = FALSE,
        main = paste("Edge agreement:\n", label, "vs COMPON 2025"))
  legend("topright", legend = c("Both 0", "TP (both 1)", "FP (LLM only)", "FN (COMPON only)"),
         fill = cols, cex = 0.75, bty = "n")
}

plot_degcor <- function(net_llm, net_ref, cmode, label) {
  d_llm <- sna::degree(net_llm, cmode = cmode)
  d_ref <- sna::degree(net_ref, cmode = cmode)
  r     <- round(cor(d_llm, d_ref, method = "spearman"), 3)
  plot(d_ref, d_llm,
       xlab = paste("COMPON 2025", cmode),
       ylab = paste(label, cmode),
       main = paste(label, "\nr =", r),
       pch = 19, col = "#378ADD", cex = 1.2)
  abline(lm(d_llm ~ d_ref), col = "#D85A30", lwd = 1.5)
}

# Convenience: safe filename fragment from a label string
safe_name <- function(label) gsub("[^A-Za-z0-9]", "_", label)

# --- 9a. Network plots — individual PNGs + portrait panel -------------------

net_plot_list <- list(
  "LLM 2025"      = m_llm25,
  "LLM 2024+2025" = m_llm2425,
  "LLM 2016-2025" = m_llm_all,
  "Raw 2025"      = m_raw25,
  "Raw 2024+2025" = m_raw2425,
  "Raw 2016-2025" = m_raw_all
)

for (nm in names(net_plot_list)) {
  fname <- paste0("net_", safe_name(nm), ".png")
  png(fname, width = 2000, height = 1800, res = 220)
  par(mar = c(2, 1, 3, 1))
  plot_net(net_plot_list[[nm]], nm)
  dev.off()
  cat("Saved:", fname, "\n")
}

png("network_comparison_portrait.png", width = 2480, height = 3508, res = 220)
layout(matrix(c(1, 2, 3, 4, 5, 6), nrow = 3, byrow = TRUE))
par(mar = c(2.5, 1, 3.5, 1), oma = c(0, 0, 3, 0))
plot_net(m_llm25,   "LLM 2025")
plot_net(m_raw25,   "Raw 2025")
plot_net(m_llm2425, "LLM 2024+2025")
plot_net(m_raw2425, "Raw 2024+2025")
plot_net(m_llm_all, "LLM 2016-2025")
plot_net(m_raw_all, "Raw 2016-2025")
mtext("Policy Network Reconstruction — LLM-validated vs Raw scraped",
      outer = TRUE, cex = 1.15, font = 2, col = "#031E3A")
dev.off()
cat("Saved: network_comparison_portrait.png\n")

# --- 9b. Degree distributions — panels (in-degree and out-degree) -----------

png("dist_degree_indegree_panel.png", width = 3200, height = 1600, res = 220)
par(mfrow = c(2, 4), mar = c(4, 4, 3, 1))
plot_deg(net_comp25,  "COMPON 2025",    "indegree")
plot_deg(net_llm25,   "LLM 2025",       "indegree")
plot_deg(net_llm2425, "LLM 2024+25",    "indegree")
plot_deg(net_llm_all, "LLM 2016-25",    "indegree")
plot_deg(net_raw25,   "Raw 2025",       "indegree")
plot_deg(net_raw2425, "Raw 2024+25",    "indegree")
plot_deg(net_raw_all, "Raw 2016-25",    "indegree")
dev.off()
cat("Saved: dist_degree_indegree_panel.png\n")

png("dist_degree_outdegree_panel.png", width = 3200, height = 1600, res = 220)
par(mfrow = c(2, 4), mar = c(4, 4, 3, 1))
plot_deg(net_comp25,  "COMPON 2025",    "outdegree")
plot_deg(net_llm25,   "LLM 2025",       "outdegree")
plot_deg(net_llm2425, "LLM 2024+25",    "outdegree")
plot_deg(net_llm_all, "LLM 2016-25",    "outdegree")
plot_deg(net_raw25,   "Raw 2025",       "outdegree")
plot_deg(net_raw2425, "Raw 2024+25",    "outdegree")
plot_deg(net_raw_all, "Raw 2016-25",    "outdegree")
dev.off()
cat("Saved: dist_degree_outdegree_panel.png\n")

# Individual degree distribution PNGs (in-degree and out-degree)
deg_net_list <- list(
  "COMPON 2025"   = net_comp25,
  "LLM 2025"      = net_llm25,
  "LLM 2024+2025" = net_llm2425,
  "LLM 2016-2025" = net_llm_all,
  "Raw 2025"      = net_raw25,
  "Raw 2024+2025" = net_raw2425,
  "Raw 2016-2025" = net_raw_all
)

for (nm in names(deg_net_list)) {
  for (cmode in c("indegree", "outdegree")) {
    fname <- paste0("dist_degree_", cmode, "_", safe_name(nm), ".png")
    png(fname, width = 1400, height = 1200, res = 220)
    par(mar = c(5, 4, 4, 2))
    plot_deg(deg_net_list[[nm]], nm, cmode)
    dev.off()
    cat("Saved:", fname, "\n")
  }
}

# --- 9c. Geodesic distributions — panel + 7 individual PNGs -----------------

# All-networks panel
png("dist_geo_panel.png", width = 3200, height = 1600, res = 220)
par(mfrow = c(2, 4), mar = c(4, 4, 3, 1))
plot_geo(net_comp25,  "COMPON 2025")
plot_geo(net_llm25,   "LLM 2025")
plot_geo(net_llm2425, "LLM 2024+2025")
plot_geo(net_llm_all, "LLM 2016-2025")
plot_geo(net_raw25,   "Raw 2025")
plot_geo(net_raw2425, "Raw 2024+2025")
plot_geo(net_raw_all, "Raw 2016-2025")
dev.off()
cat("Saved: dist_geo_panel.png\n")

# Individual geodesic PNGs
geo_net_list <- list(
  "COMPON 2025"   = net_comp25,
  "LLM 2025"      = net_llm25,
  "LLM 2024+2025" = net_llm2425,
  "LLM 2016-2025" = net_llm_all,
  "Raw 2025"      = net_raw25,
  "Raw 2024+2025" = net_raw2425,
  "Raw 2016-2025" = net_raw_all
)
for (nm in names(geo_net_list)) {
  fname <- paste0("dist_geo_", safe_name(nm), ".png")
  png(fname, width = 1400, height = 1200, res = 220)
  par(mar = c(5, 4, 4, 2))
  plot_geo(geo_net_list[[nm]], nm)
  dev.off()
  cat("Saved:", fname, "\n")
}

# --- 9d. ESP distributions — panel + 7 individual PNGs [NEW] ----------------

esp_mat_list <- list(
  "COMPON 2025"   = m_comp25,
  "LLM 2025"      = m_llm25,
  "LLM 2024+2025" = m_llm2425,
  "LLM 2016-2025" = m_llm_all,
  "Raw 2025"      = m_raw25,
  "Raw 2024+2025" = m_raw2425,
  "Raw 2016-2025" = m_raw_all
)

# All-networks panel
png("dist_esp_panel.png", width = 3200, height = 1600, res = 220)
par(mfrow = c(2, 4), mar = c(4, 4, 3, 1))
for (nm in names(esp_mat_list)) plot_esp(esp_mat_list[[nm]], nm)
dev.off()
cat("Saved: dist_esp_panel.png\n")

# Individual ESP PNGs
for (nm in names(esp_mat_list)) {
  fname <- paste0("dist_esp_", safe_name(nm), ".png")
  png(fname, width = 1400, height = 1200, res = 220)
  par(mar = c(5, 4, 4, 2))
  plot_esp(esp_mat_list[[nm]], nm)
  dev.off()
  cat("Saved:", fname, "\n")
}

# --- 9e. Edge agreement heatmaps 2x3 (LLM row, Raw row) --------------------

diff_A <- make_diff_mat(m_llm25,   m_comp25)
diff_B <- make_diff_mat(m_llm2425, m_comp25)
diff_C <- make_diff_mat(m_llm_all, m_comp25)
diff_D <- make_diff_mat(m_raw25,   m_comp25)
diff_E <- make_diff_mat(m_raw2425, m_comp25)
diff_F <- make_diff_mat(m_raw_all, m_comp25)

png("edge_agreement_panel.png", width = 2800, height = 2000, res = 220)
par(mfrow = c(2, 3), mar = c(2, 2, 4, 1))
plot_diff(diff_A, "LLM 2025")
plot_diff(diff_B, "LLM 2024+2025")
plot_diff(diff_C, "LLM 2016-2025")
plot_diff(diff_D, "Raw 2025")
plot_diff(diff_E, "Raw 2024+2025")
plot_diff(diff_F, "Raw 2016-2025")
dev.off()
cat("Saved: edge_agreement_panel.png\n")

# --- 9f. Precision/Recall/F1/Jaccard grouped barplot -----------------------

perf_df <- data.frame(
  Network   = c("LLM 2025", "LLM 2024+25", "LLM 2016-25",
                "Raw 2025", "Raw 2024+25", "Raw 2016-25"),
  Precision = c(overlap_A$precision, overlap_B$precision, overlap_C$precision,
                overlap_D$precision, overlap_E$precision, overlap_F$precision),
  Recall    = c(overlap_A$recall,    overlap_B$recall,    overlap_C$recall,
                overlap_D$recall,    overlap_E$recall,    overlap_F$recall),
  F1        = c(overlap_A$f1,        overlap_B$f1,        overlap_C$f1,
                overlap_D$f1,        overlap_E$f1,        overlap_F$f1),
  Jaccard   = c(overlap_A$jaccard,   overlap_B$jaccard,   overlap_C$jaccard,
                overlap_D$jaccard,   overlap_E$jaccard,   overlap_F$jaccard)
)

png("perf_metrics_panel.png", width = 2400, height = 1600, res = 220)
par(mfrow = c(1, 1), mar = c(7, 4, 4, 2))
bp <- t(as.matrix(perf_df[, c("Precision", "Recall", "F1", "Jaccard")]))
colnames(bp) <- perf_df$Network
barplot(bp, beside = TRUE, ylim = c(0, 1),
        col    = c("#378ADD", "#1D9E75", "#D85A30", "#BA7517"),
        border = NA,
        legend.text = rownames(bp),
        args.legend = list(x = "topright", bty = "n", cex = 0.85),
        ylab  = "Score",
        main  = "Edge reconstruction quality vs COMPON 2025\n(LLM-validated vs Raw scraped)",
        las   = 2, cex.names = 0.8)
abline(h = seq(0.2, 1, 0.2), col = "#D3D1C7", lty = 2, lwd = 0.8)
abline(v = 13.5, col = "#888780", lty = 3, lwd = 1.5)
text(7,  0.05, "LLM-validated", cex = 0.85, col = "gray40")
text(19, 0.05, "Raw scraped",   cex = 0.85, col = "gray40")
dev.off()
cat("Saved: perf_metrics_panel.png\n")

# --- 9g. Degree correlation scatter plots 2x3 panels (in- and out-degree) ---

png("degree_scatter_indegree_panel.png", width = 2800, height = 2000, res = 220)
par(mfrow = c(2, 3), mar = c(4, 4, 3, 1))
plot_degcor(net_llm25,   net_comp25, "indegree", "LLM 2025")
plot_degcor(net_llm2425, net_comp25, "indegree", "LLM 2024+25")
plot_degcor(net_llm_all, net_comp25, "indegree", "LLM 2016-25")
plot_degcor(net_raw25,   net_comp25, "indegree", "Raw 2025")
plot_degcor(net_raw2425, net_comp25, "indegree", "Raw 2024+25")
plot_degcor(net_raw_all, net_comp25, "indegree", "Raw 2016-25")
dev.off()
cat("Saved: degree_scatter_indegree_panel.png\n")

png("degree_scatter_outdegree_panel.png", width = 2800, height = 2000, res = 220)
par(mfrow = c(2, 3), mar = c(4, 4, 3, 1))
plot_degcor(net_llm25,   net_comp25, "outdegree", "LLM 2025")
plot_degcor(net_llm2425, net_comp25, "outdegree", "LLM 2024+25")
plot_degcor(net_llm_all, net_comp25, "outdegree", "LLM 2016-25")
plot_degcor(net_raw25,   net_comp25, "outdegree", "Raw 2025")
plot_degcor(net_raw2425, net_comp25, "outdegree", "Raw 2024+25")
plot_degcor(net_raw_all, net_comp25, "outdegree", "Raw 2016-25")
dev.off()
cat("Saved: degree_scatter_outdegree_panel.png\n")

# --- 9h. Density & reachability trajectory (all 7 networks) -----------------

png("density_reachability_panel.png", width = 2400, height = 1400, res = 220)
par(mfrow = c(1, 2), mar = c(8, 4, 3, 1))
bar_cols   <- c("#1D9E75", "#B5D4F4", "#85B7EB", "#378ADD",
                "#F4C4A4", "#E8924A", "#D85A30")
net_labels <- c("COMPON 2025", "LLM 2025", "LLM 2024+25", "LLM 2016-25",
                "Raw 2025",    "Raw 2024+25", "Raw 2016-25")

barplot(c(stats_comp25$density,  stats_llm25$density,  stats_llm2425$density,
          stats_llm_all$density, stats_raw25$density,  stats_raw2425$density,
          stats_raw_all$density),
        names.arg = net_labels, col = bar_cols, border = NA,
        ylim = c(0, 0.7), ylab = "Density",
        main = "Network density", las = 2, cex.names = 0.75)
abline(h = seq(0.1, 0.6, 0.1), col = "#D3D1C7", lty = 2, lwd = 0.8)

barplot(c(length(geo_comp25) / n_dyads, length(geo_llm25)   / n_dyads,
          length(geo_llm2425)/ n_dyads, length(geo_llm_all) / n_dyads,
          length(geo_raw25)  / n_dyads, length(geo_raw2425) / n_dyads,
          length(geo_raw_all)/ n_dyads),
        names.arg = net_labels, col = bar_cols, border = NA,
        ylim = c(0, 1), ylab = "Reachable pair share",
        main = "Global connectivity", las = 2, cex.names = 0.75)
abline(h = seq(0.2, 1, 0.2), col = "#D3D1C7", lty = 2, lwd = 0.8)
dev.off()
cat("Saved: density_reachability_panel.png\n")


#--- 10.  ACF CATEGORY ANALYSIS, HYPOTHESIS TESTS & NODE CENTRALITY----


categories <- list(
  umbrella   = c("ccc", "grn"),
  advocacy   = c("foe", "arn", "grp", "nes", "upe"),
  specialist = c("fct", "frb", "cde", "cit", "aes"),
  radical    = c("lau", "fff", "ext"),
  sectoral   = c("ver", "cal", "bel"),
  peripheral = c("aut")
)

node_names <- colnames(m_comp25)
cat_labels  <- setNames(rep(NA, length(node_names)), node_names)
for (cat in names(categories)) {
  cat_labels[categories[[cat]]] <- cat
}
cat_labels <- factor(cat_labels,
                     levels = c("umbrella","advocacy","specialist",
                                "radical","sectoral","peripheral"))

cat_cols <- c(umbrella   = "#1D9E75",
              advocacy   = "#378ADD",
              specialist = "#BA7517",
              radical    = "#D85A30",
              sectoral   = "#7F77DD",
              peripheral = "#888780")

# --- 10a. Node-level metrics (COMPON 2025) -----------------------------------
indeg_c  <- sna::degree(net_comp25, cmode = "indegree")
outdeg_c <- sna::degree(net_comp25, cmode = "outdegree")
totdeg_c <- indeg_c + outdeg_c
btwn_c   <- igraph::betweenness(ig_comp25, directed = TRUE, normalized = TRUE)
clust_c  <- igraph::transitivity(ig_comp25, type = "local", isolates = "zero")
broker_c <- ifelse(totdeg_c > 0, btwn_c / (totdeg_c / max(totdeg_c)), NA)

node_df <- data.frame(
  node = node_names, category = cat_labels,
  indegree = indeg_c, outdegree = outdeg_c, totdegree = totdeg_c,
  betweenness = round(btwn_c, 4), clustering = round(clust_c, 4),
  broker_idx  = round(broker_c, 4)
)

cat("\n--- Node metrics by category (COMPON 2025) ---\n")
print(node_df[order(node_df$category), ], row.names = FALSE)

cat_summary <- aggregate(
  cbind(totdegree, betweenness, clustering, broker_idx) ~ category,
  data = node_df, FUN = mean, na.rm = TRUE
)
cat_summary[, -1] <- round(cat_summary[, -1], 3)
cat("\n--- Category means (COMPON 2025) ---\n")
print(cat_summary, row.names = FALSE)

# --- 10b. Hypothesis tests ---------------------------------------------------
cat("\n##############################################################\n")
cat("# HYPOTHESIS TESTS (COMPON 2025)                            #\n")
cat("##############################################################\n\n")

run_hypothesis_tests <- function(node_df_input, mat_input, label) {
  cat(sprintf("--- Hypothesis tests: %s ---\n\n", label))

  kw_deg <- kruskal.test(totdegree ~ category, data = node_df_input)
  cat("H1/H2/H5/H6 — Kruskal-Wallis on total degree:\n")
  cat("  chi-squared =", round(kw_deg$statistic, 3),
      "  df =", kw_deg$parameter, "  p =", round(kw_deg$p.value, 4), "\n\n")

  pw_deg <- pairwise.wilcox.test(node_df_input$totdegree, node_df_input$category,
                                 p.adjust.method = "BH", exact = FALSE)
  cat("  Pairwise Wilcoxon (BH correction):\n"); print(pw_deg$p.value); cat("\n")

  umbrella_deg <- node_df_input$totdegree[node_df_input$category == "umbrella"]
  others_deg   <- node_df_input$totdegree[node_df_input$category != "umbrella"]
  wt_h1 <- wilcox.test(umbrella_deg, others_deg, alternative = "greater", exact = FALSE)
  cat("H1 — Umbrella > all others: W =", wt_h1$statistic, "  p =", round(wt_h1$p.value, 4), "\n")
  cat("  Umbrella mean:", round(mean(umbrella_deg), 2), "| Others mean:", round(mean(others_deg), 2), "\n\n")

  advocacy_deg <- node_df_input$totdegree[node_df_input$category == "advocacy"]
  lower_deg    <- node_df_input$totdegree[node_df_input$category %in%
                    c("specialist","sectoral","peripheral")]
  wt_h2 <- wilcox.test(advocacy_deg, lower_deg, alternative = "greater", exact = FALSE)
  cat("H2 — Advocacy > specialist/sectoral/peripheral: W =", wt_h2$statistic,
      "  p =", round(wt_h2$p.value, 4), "\n")
  cat("  Advocacy mean:", round(mean(advocacy_deg), 2),
      "| Lower groups mean:", round(mean(lower_deg), 2), "\n\n")

  specialist_broker <- node_df_input$broker_idx[node_df_input$category == "specialist"]
  others_broker     <- node_df_input$broker_idx[node_df_input$category != "specialist"]
  wt_h3 <- wilcox.test(specialist_broker, others_broker, alternative = "greater", exact = FALSE)
  cat("H3 — Specialist broker index > others: W =", wt_h3$statistic,
      "  p =", round(wt_h3$p.value, 4), "\n\n")

  radical_nodes    <- categories$radical
  nonradical_nodes <- node_names[!node_names %in% radical_nodes]
  rad_sub   <- mat_input[radical_nodes, radical_nodes]
  rad_dens  <- sum(rad_sub) / (length(radical_nodes) * (length(radical_nodes) - 1))
  radical_clust    <- node_df_input$clustering[node_df_input$category == "radical"]
  nonradical_clust <- node_df_input$clustering[node_df_input$category != "radical"]
  wt_h4 <- wilcox.test(radical_clust, nonradical_clust, alternative = "greater", exact = FALSE)
  cat("H4 — Radical flank: internal density =", round(rad_dens, 3),
      "| Wilcoxon W =", wt_h4$statistic, "p =", round(wt_h4$p.value, 4), "\n\n")

  sectoral_nodes   <- categories$sectoral
  sectoral_ties_up <- apply(mat_input[sectoral_nodes,
                                      c(categories$umbrella, categories$advocacy)], 1, sum)
  cat("H5 — Sectoral ties to umbrella/advocacy:\n")
  print(data.frame(node = sectoral_nodes, ties_to_core = sectoral_ties_up)); cat("\n")

  periph_deg <- node_df_input$totdegree[node_df_input$category == "peripheral"]
  cat("H6 — Peripheral actor (aut) degree:", periph_deg, "  Rank:",
      rank(node_df_input$totdegree)[node_df_input$category == "peripheral"],
      "out of", nrow(node_df_input), "\n\n")
}

run_hypothesis_tests(node_df, m_comp25, "COMPON 2025")

# --- 10c. ACF plots — COMPON 2025 (saved to PNG) ----------------------------

png("acf_compon_panel.png", width = 3000, height = 2200, res = 220)
par(mfrow = c(2, 3), mar = c(6, 4, 3, 1))

boxplot(totdegree ~ category, data = node_df, col = cat_cols[levels(node_df$category)],
        border = "gray30", las = 2, ylab = "Total degree",
        main = "H1/H2 — Degree by category (COMPON)")
stripchart(totdegree ~ category, data = node_df, method = "jitter",
           pch = 19, cex = 0.9, col = "gray20", vertical = TRUE, add = TRUE)

boxplot(betweenness ~ category, data = node_df, col = cat_cols[levels(node_df$category)],
        border = "gray30", las = 2, ylab = "Betweenness (norm.)",
        main = "H3 — Betweenness (COMPON)")
stripchart(betweenness ~ category, data = node_df, method = "jitter",
           pch = 19, cex = 0.9, col = "gray20", vertical = TRUE, add = TRUE)

boxplot(broker_idx ~ category, data = node_df, col = cat_cols[levels(node_df$category)],
        border = "gray30", las = 2, ylab = "Broker index",
        main = "H3 — Broker index (COMPON)")
stripchart(broker_idx ~ category, data = node_df, method = "jitter",
           pch = 19, cex = 0.9, col = "gray20", vertical = TRUE, add = TRUE)

boxplot(clustering ~ category, data = node_df, col = cat_cols[levels(node_df$category)],
        border = "gray30", las = 2, ylab = "Local clustering",
        main = "H4 — Clustering (COMPON)")
stripchart(clustering ~ category, data = node_df, method = "jitter",
           pch = 19, cex = 0.9, col = "gray20", vertical = TRUE, add = TRUE)

plot(node_df$totdegree, node_df$betweenness,
     col = cat_cols[as.character(node_df$category)], pch = 19, cex = 1.5,
     xlab = "Total degree", ylab = "Betweenness",
     main = "Degree vs Betweenness (COMPON)")
text(node_df$totdegree, node_df$betweenness, labels = node_df$node, cex = 0.65, pos = 3)
legend("topright", legend = names(cat_cols), fill = cat_cols, bty = "n", cex = 0.75)

par(mar = c(1, 1, 3, 1))
g_col <- cat_cols[as.character(cat_labels[V(ig_comp25)$name])]
plot(ig_comp25, layout = base_layout,
     vertex.size = 8 + igraph::degree(ig_comp25) * 0.8,
     vertex.color = g_col, vertex.frame.color = "gray30",
     vertex.label = V(ig_comp25)$name, vertex.label.cex = 0.65,
     vertex.label.color = "black", edge.arrow.size = 0.25,
     edge.color = "#D3D1C7", main = "COMPON 2025 — ACF categories")
legend("bottomleft", legend = names(cat_cols), fill = cat_cols, bty = "n", cex = 0.7)

dev.off()
cat("Saved: acf_compon_panel.png\n")

# --- 10d. ACF Analysis — LLM 2016-2025 --------------------------------------

cat("\n##############################################################\n")
cat("# SECTION 10d: ACF ANALYSIS ON LLM 2016-2025               #\n")
cat("##############################################################\n\n")

make_node_df <- function(net, ig, mat, label) {
  indeg  <- sna::degree(net, cmode = "indegree")
  outdeg <- sna::degree(net, cmode = "outdegree")
  totdeg <- indeg + outdeg
  btwn   <- igraph::betweenness(ig, directed = TRUE, normalized = TRUE)
  clust  <- igraph::transitivity(ig, type = "local", isolates = "zero")
  broker <- ifelse(totdeg > 0, btwn / (totdeg / max(totdeg)), NA)
  data.frame(
    node = node_names, category = cat_labels,
    indegree = indeg, outdegree = outdeg, totdegree = totdeg,
    betweenness = round(btwn, 4), clustering = round(clust, 4),
    broker_idx  = round(broker, 4)
  )
}

node_df_llm <- make_node_df(net_llm_all, ig_llm_all, m_llm_all, "LLM 2016-2025")

cat("--- Node metrics by category (LLM 2016-2025) ---\n")
print(node_df_llm[order(node_df_llm$category), ], row.names = FALSE)

cat_summary_llm <- aggregate(
  cbind(totdegree, betweenness, clustering, broker_idx) ~ category,
  data = node_df_llm, FUN = mean, na.rm = TRUE
)
cat_summary_llm[, -1] <- round(cat_summary_llm[, -1], 3)
cat("\n--- Category means (LLM 2016-2025) ---\n")
print(cat_summary_llm, row.names = FALSE)

run_hypothesis_tests(node_df_llm, m_llm_all, "LLM 2016-2025")

# --- 10e. ACF Analysis — Raw 2016-2025 --------------------------------------

cat("\n##############################################################\n")
cat("# SECTION 10e: ACF ANALYSIS ON RAW 2016-2025               #\n")
cat("##############################################################\n\n")

node_df_raw <- make_node_df(net_raw_all, ig_raw_all, m_raw_all, "Raw 2016-2025")

cat("--- Node metrics by category (Raw 2016-2025) ---\n")
print(node_df_raw[order(node_df_raw$category), ], row.names = FALSE)

cat_summary_raw <- aggregate(
  cbind(totdegree, betweenness, clustering, broker_idx) ~ category,
  data = node_df_raw, FUN = mean, na.rm = TRUE
)
cat_summary_raw[, -1] <- round(cat_summary_raw[, -1], 3)
cat("\n--- Category means (Raw 2016-2025) ---\n")
print(cat_summary_raw, row.names = FALSE)

run_hypothesis_tests(node_df_raw, m_raw_all, "Raw 2016-2025")

# 3-way category degree rank comparison (COMPON / LLM / Raw)
all_cats <- c("umbrella", "advocacy", "specialist", "radical", "sectoral", "peripheral")

make_cat_summary <- function(df_nodes) {
  data.frame(
    category  = all_cats,
    totdegree = sapply(all_cats, function(cat) {
      vals <- df_nodes$totdegree[as.character(df_nodes$category) == cat]
      if (length(vals) == 0) 0 else mean(vals, na.rm = TRUE)
    })
  )
}

cat_sum_c <- make_cat_summary(node_df)
cat_sum_l <- make_cat_summary(node_df_llm)
cat_sum_r <- make_cat_summary(node_df_raw)

rank_comp <- rank(-cat_sum_c$totdegree)
rank_llm  <- rank(-cat_sum_l$totdegree)
rank_raw  <- rank(-cat_sum_r$totdegree)

rank_cor_cl <- cor(rank_comp, rank_llm, method = "spearman")
rank_cor_cr <- cor(rank_comp, rank_raw, method = "spearman")
rank_cor_lr <- cor(rank_llm,  rank_raw, method = "spearman")

rank_df <- data.frame(
  category     = all_cats,
  rank_COMPON  = as.integer(rank_comp),
  rank_LLM_all = as.integer(rank_llm),
  rank_Raw_all = as.integer(rank_raw)
)

cat("\n--- Category degree rank preservation ---\n")
cat("  COMPON vs LLM 2016-25 Spearman r:", round(rank_cor_cl, 3), "\n")
cat("  COMPON vs Raw 2016-25 Spearman r:", round(rank_cor_cr, 3), "\n")
cat("  LLM    vs Raw 2016-25 Spearman r:", round(rank_cor_lr, 3), "\n\n")
print(rank_df, row.names = FALSE)

png("acf_3way_comparison.png", width = 2400, height = 1400, res = 220)
par(mfrow = c(1, 2), mar = c(6, 4, 3, 1))

bp_means <- rbind(cat_sum_l$totdegree, cat_sum_r$totdegree, cat_sum_c$totdegree)
rownames(bp_means) <- c("LLM 2016-2025", "Raw 2016-2025", "COMPON 2025")
barplot(bp_means, beside = TRUE, names.arg = all_cats,
        col = c("#378ADD", "#D85A30", "#1D9E75"), border = NA,
        legend.text = rownames(bp_means),
        args.legend = list(x = "topright", bty = "n", cex = 0.85),
        las = 2, cex.names = 0.85, ylab = "Mean total degree",
        main = "Category degree: LLM vs Raw vs COMPON")

plot(rank_df$rank_COMPON, rank_df$rank_LLM_all,
     pch = 19, cex = 1.5, col = cat_cols[rank_df$category],
     xlim = c(0.5, 6.5), ylim = c(0.5, 6.5),
     xlab = "COMPON 2025 rank", ylab = "Rank (network)",
     main = sprintf("Category degree rank\nLLM r=%.2f  Raw r=%.2f", rank_cor_cl, rank_cor_cr))
points(rank_df$rank_COMPON, rank_df$rank_Raw_all,
       pch = 17, cex = 1.5, col = cat_cols[rank_df$category])
abline(0, 1, lty = 2, col = "gray60")
text(rank_df$rank_COMPON, rank_df$rank_LLM_all,
     labels = rank_df$category, cex = 0.65, pos = 3)
legend("bottomright", legend = c("LLM 2016-25 (circle)", "Raw 2016-25 (triangle)"),
       pch = c(19, 17), col = "gray40", bty = "n", cex = 0.8)

dev.off()
cat("Saved: acf_3way_comparison.png\n")

cat("\n=== Section 10e complete ===\n")

# --- 10f. Node centrality — all 7 networks [integrated from v2 Frankenstein] -

cat("\n##############################################################\n")
cat("# SECTION 10f: NODE CENTRALITY — ALL NETWORKS               #\n")
cat("##############################################################\n\n")

node_stats <- function(mat, net_name) {
  g <- graph_from_adjacency_matrix(mat, mode = "directed")

  in_deg    <- igraph::degree(g,       mode = "in")
  out_deg   <- igraph::degree(g,       mode = "out")
  between   <- igraph::betweenness(g,  directed = TRUE, normalized = TRUE)
  close_in  <- igraph::closeness(g,    mode = "in",  normalized = TRUE)
  close_out <- igraph::closeness(g,    mode = "out", normalized = TRUE)
  eigen_c   <- igraph::eigen_centrality(g, directed = TRUE)$vector
  authority <- igraph::authority_score(g)$vector
  hub_sc    <- igraph::hub_score(g)$vector

  df <- data.frame(
    network       = net_name,
    actor         = names(in_deg),
    in_degree     = in_deg,
    out_degree    = out_deg,
    betweenness   = round(between,   4),
    closeness_in  = round(close_in,  4),
    closeness_out = round(close_out, 4),
    eigenvector   = round(eigen_c,   4),
    authority     = round(authority, 4),
    hub           = round(hub_sc,    4),
    row.names     = NULL
  )
  df[order(-df$betweenness), ]
}

# Use networks_all to avoid collision with the net_plot_list variable
networks_all <- list(
  "COMPON 2025"   = m_comp25,
  "LLM 2025"      = m_llm25,
  "LLM 2024+2025" = m_llm2425,
  "LLM 2016-2025" = m_llm_all,
  "Raw 2025"      = m_raw25,
  "Raw 2024+2025" = m_raw2425,
  "Raw 2016-2025" = m_raw_all
)

all_stats <- do.call(rbind, mapply(node_stats, networks_all, names(networks_all),
                                   SIMPLIFY = FALSE))

# Top-4 actors per measure per network
get_top_4 <- function(d, measure_col) {
  sorted_actors <- d$actor[order(d[[measure_col]], decreasing = TRUE)]
  paste(head(sorted_actors, 4), collapse = ", ")
}

top_actors <- do.call(rbind, lapply(names(networks_all), function(nm) {
  d <- all_stats[all_stats$network == nm, ]
  data.frame(
    network         = nm,
    top_indegree    = get_top_4(d, "in_degree"),
    top_outdegree   = get_top_4(d, "out_degree"),
    top_betweenness = get_top_4(d, "betweenness"),
    top_authority   = get_top_4(d, "authority"),
    top_hub         = get_top_4(d, "hub"),
    n_isolates      = sum(d$in_degree + d$out_degree == 0)
  )
}))

print(top_actors)
write.csv(all_stats,  "node_centrality_all.csv",  row.names = FALSE)
write.csv(top_actors, "top_actors_summary.csv",   row.names = FALSE)
cat("Saved: node_centrality_all.csv, top_actors_summary.csv\n")

cat("\n=== Section 10f complete ===\n")


# ---11.  LLM VALIDATION EFFECT ANALYSIS----
#      Compares Raw vs LLM within each time window to assess what the
#      LLM validation step actually adds or removes relative to COMPON.


cat("\n##############################################################\n")
cat("# SECTION 11: LLM VALIDATION EFFECT                        #\n")
cat("# Raw scraped  vs  LLM-validated  (within time window)     #\n")
cat("##############################################################\n\n")

# --- 11a. Direct raw vs LLM edge overlap (not vs COMPON) --------------------
cat("--- 11a. Raw vs LLM edge overlap (within window) ---\n\n")
overlap_raw_llm_2025  <- edge_overlap(m_raw25,   m_llm25,   "Raw 2025",      "LLM 2025")
overlap_raw_llm_2425  <- edge_overlap(m_raw2425, m_llm2425, "Raw 2024+2025", "LLM 2024+2025")
overlap_raw_llm_all   <- edge_overlap(m_raw_all, m_llm_all, "Raw 2016-2025", "LLM 2016-2025")

# --- 11b. F1 delta table (LLM improvement over Raw vs COMPON) ---------------
cat("--- 11b. LLM validation effect: delta F1 vs COMPON 2025 ---\n\n")

delta_df <- data.frame(
  Window       = c("2025", "2024+2025", "2016-2025"),
  Raw_F1       = round(c(overlap_D$f1,   overlap_E$f1,   overlap_F$f1),   3),
  LLM_F1       = round(c(overlap_A$f1,   overlap_B$f1,   overlap_C$f1),   3),
  Delta_F1     = round(c(overlap_A$f1   - overlap_D$f1,
                         overlap_B$f1   - overlap_E$f1,
                         overlap_C$f1   - overlap_F$f1), 3),
  Raw_Prec     = round(c(overlap_D$precision, overlap_E$precision, overlap_F$precision), 3),
  LLM_Prec     = round(c(overlap_A$precision, overlap_B$precision, overlap_C$precision), 3),
  Delta_Prec   = round(c(overlap_A$precision - overlap_D$precision,
                         overlap_B$precision - overlap_E$precision,
                         overlap_C$precision - overlap_F$precision), 3),
  Raw_Recall   = round(c(overlap_D$recall, overlap_E$recall, overlap_F$recall), 3),
  LLM_Recall   = round(c(overlap_A$recall, overlap_B$recall, overlap_C$recall), 3),
  Delta_Recall = round(c(overlap_A$recall - overlap_D$recall,
                         overlap_B$recall - overlap_E$recall,
                         overlap_C$recall - overlap_F$recall), 3)
)

cat("LLM validation effect: positive delta = LLM improves over raw\n")
print(delta_df, row.names = FALSE)

cat("\n--- Interpretation ---\n")
for (i in seq_len(nrow(delta_df))) {
  w   <- delta_df$Window[i]
  df1 <- delta_df$Delta_F1[i]
  dp  <- delta_df$Delta_Prec[i]
  dr  <- delta_df$Delta_Recall[i]
  if (df1 > 0) {
    cat(sprintf("  %s: LLM IMPROVES on raw (ΔF1=+%.3f, ΔPrec=%+.3f, ΔRec=%+.3f)\n", w, df1, dp, dr))
  } else if (df1 < 0) {
    cat(sprintf("  %s: Raw OUTPERFORMS LLM (ΔF1=%.3f, ΔPrec=%+.3f, ΔRec=%+.3f)\n", w, df1, dp, dr))
  } else {
    cat(sprintf("  %s: No difference in F1 (ΔPrec=%+.3f, ΔRec=%+.3f)\n", w, dp, dr))
  }
}

# --- 11c. QAP: raw vs LLM (within window) -----------------------------------
cat("\n--- 11c. QAP matrix correlation: Raw vs LLM (within window) ---\n\n")
qap_raw_llm_2025 <- qap_correlation(m_raw25,   m_llm25,   "Raw 2025",      "LLM 2025")
qap_raw_llm_2425 <- qap_correlation(m_raw2425, m_llm2425, "Raw 2024+2025", "LLM 2024+2025")
qap_raw_llm_all  <- qap_correlation(m_raw_all, m_llm_all, "Raw 2016-2025", "LLM 2016-2025")

# --- 11d. Degree correlation table (raw vs LLM vs COMPON) ------------------
cat("\n--- 11d. Degree rank correlation: Raw vs LLM (vs COMPON reference) ---\n\n")
cat(sprintf("  %-20s | %-14s | %-14s\n", "Network", "In-Deg (r)", "Out-Deg (r)"))
cat("  ---------------------|----------------|----------------\n")
for (nm in c("Raw 2025", "LLM 2025", "Raw 2024+25", "LLM 2024+25", "Raw 2016-25", "LLM 2016-25")) {
  dc <- switch(nm,
    "Raw 2025"    = degcor_D, "LLM 2025"    = degcor_A,
    "Raw 2024+25" = degcor_E, "LLM 2024+25" = degcor_B,
    "Raw 2016-25" = degcor_F, "LLM 2016-25" = degcor_C)
  cat(sprintf("  %-20s | %-14.3f | %-14.3f\n", nm, dc$r_in, dc$r_out))
}

# --- 11e. Delta F1 visualisation (saved to PNG) -----------------------------
png("llm_validation_effect.png", width = 2400, height = 1400, res = 220)
par(mfrow = c(1, 2), mar = c(5, 4, 4, 2))

f1_mat <- rbind(
  c(overlap_D$f1, overlap_E$f1, overlap_F$f1),
  c(overlap_A$f1, overlap_B$f1, overlap_C$f1)
)
rownames(f1_mat) <- c("Raw scraped", "LLM validated")
colnames(f1_mat) <- c("2025", "2024+25", "2016-25")

barplot(f1_mat, beside = TRUE, ylim = c(0, 1),
        col    = c("#D85A30", "#378ADD"), border = NA,
        legend.text = rownames(f1_mat),
        args.legend = list(x = "topright", bty = "n", cex = 0.9),
        ylab = "F1 Score vs COMPON 2025",
        main = "LLM validation effect on F1")
abline(h = seq(0.2, 1, 0.2), col = "#D3D1C7", lty = 2, lwd = 0.8)

barplot(delta_df$Delta_F1,
        names.arg = delta_df$Window,
        col    = ifelse(delta_df$Delta_F1 >= 0, "#378ADD", "#D85A30"),
        border = NA,
        ylab   = "\u0394F1 (LLM \u2212 Raw)",
        main   = "LLM validation effect: \u0394F1 vs COMPON\n(+ve = LLM improves on raw)",
        ylim   = c(min(delta_df$Delta_F1) - 0.05, max(delta_df$Delta_F1) + 0.05))
abline(h = 0, col = "gray40", lwd = 1)

dev.off()
cat("Saved: llm_validation_effect.png\n")

cat("\n=== Section 11a complete ===\n\n")


# 11b. MRQAP — HIERARCHICAL (Step 1: base, Step 2: controlled)
#
#  Step 1: Y ~ X            — raw accuracy, unadulterated R2
#  Step 2: Y ~ X + Trans + Recip — robustness check: does X predict ties
#          that can't already be explained by COMPON's own structure?
#  Both use COMPON 2025 as Y. Controls are derived from COMPON (not predictor).


cat("\n##############################################################\n")
cat("# SECTION 11b: MRQAP HIERARCHICAL                          #\n")
cat("##############################################################\n\n")

cat("--- Step 1: Base models (unadjusted) ---\n\n")
mrqap_base_llm25   <- run_mrqap_base(m_llm25,   m_comp25, "LLM 2025")
mrqap_base_llm2425 <- run_mrqap_base(m_llm2425, m_comp25, "LLM 2024+2025")
mrqap_base_llm_all <- run_mrqap_base(m_llm_all, m_comp25, "LLM 2016-2025")
mrqap_base_raw25   <- run_mrqap_base(m_raw25,   m_comp25, "Raw 2025")
mrqap_base_raw2425 <- run_mrqap_base(m_raw2425, m_comp25, "Raw 2024+2025")
mrqap_base_raw_all <- run_mrqap_base(m_raw_all, m_comp25, "Raw 2016-2025")

cat("--- Step 2: Controlled models ---\n\n")
mrqap_llm25   <- run_mrqap_controlled(m_llm25,   m_comp25, trans_comp25, recip_comp25, "LLM 2025")
mrqap_llm2425 <- run_mrqap_controlled(m_llm2425, m_comp25, trans_comp25, recip_comp25, "LLM 2024+2025")
mrqap_llm_all <- run_mrqap_controlled(m_llm_all, m_comp25, trans_comp25, recip_comp25, "LLM 2016-2025")
mrqap_raw25   <- run_mrqap_controlled(m_raw25,   m_comp25, trans_comp25, recip_comp25, "Raw 2025")
mrqap_raw2425 <- run_mrqap_controlled(m_raw2425, m_comp25, trans_comp25, recip_comp25, "Raw 2024+2025")
mrqap_raw_all <- run_mrqap_controlled(m_raw_all, m_comp25, trans_comp25, recip_comp25, "Raw 2016-2025")

cat("=== Section 11b complete ===\n\n")

# 12.  EXPORT MASTER REPORT


export_master_report <- function(filepath) {

  cat("MASTER NETWORK COMPARISON REPORT\n", file = filepath)
  cat("==================================================================================\n",
      file = filepath, append = TRUE)
  cat(sprintf("Generated on: %s\n", Sys.time()), file = filepath, append = TRUE)
  cat("Ground Truth Reference Network: COMPON 2025\n", file = filepath, append = TRUE)
  cat("Network types: LLM-validated (A/B/C) and Raw scraped (D/E/F)\n",
      file = filepath, append = TRUE)
  cat("==================================================================================\n\n",
      file = filepath, append = TRUE)

  
  # PART 1: OVERALL CROSS-COMPARISON SUMMARIES
  
  cat("PART 1: OVERALL EXECUTIVE SUMMARIES\n", file = filepath, append = TRUE)
  cat("==================================================================================\n\n",
      file = filepath, append = TRUE)

  cat("1. OVERALL NETWORK DESCRIPTIVES\n", file = filepath, append = TRUE)
  cat("----------------------------------------------------------------------------------\n",
      file = filepath, append = TRUE)
  cat(sprintf("%-20s | %-6s | %-6s | %-8s | %-11s | %-12s\n",
              "Network", "Nodes", "Edges", "Density", "Reciprocity", "Transitivity"),
      file = filepath, append = TRUE)
  cat("---------------------|--------|--------|----------|-------------|-------------\n",
      file = filepath, append = TRUE)

  write_desc_row <- function(name, stats) {
    cat(sprintf("%-20s | %-6d | %-6d | %-8.4f | %-11.4f | %-12.4f\n",
                name, stats$n, stats$edges, stats$density,
                stats$reciprocity, stats$transitivity),
        file = filepath, append = TRUE)
  }
  write_desc_row("COMPON 2025 (Ref)",  stats_comp25)
  write_desc_row("LLM 2025",           stats_llm25)
  write_desc_row("LLM 2024+2025",      stats_llm2425)
  write_desc_row("LLM 2016-2025",      stats_llm_all)
  write_desc_row("Raw 2025",           stats_raw25)
  write_desc_row("Raw 2024+2025",      stats_raw2425)
  write_desc_row("Raw 2016-2025",      stats_raw_all)
  cat("\n", file = filepath, append = TRUE)

  cat("2. OVERALL EDGE OVERLAP & ACCURACY (vs COMPON 2025)\n", file = filepath, append = TRUE)
  cat("----------------------------------------------------------------------------------\n",
      file = filepath, append = TRUE)
  cat(sprintf("%-20s | %-8s | %-11s | %-9s | %-8s | %-8s\n",
              "Network", "F1 Score", "Jaccard Sim", "Precision", "Recall", "Hamming"),
      file = filepath, append = TRUE)
  cat("---------------------|----------|-------------|-----------|----------|----------\n",
      file = filepath, append = TRUE)

  write_acc_row <- function(name, overlap) {
    cat(sprintf("%-20s | %-8.3f | %-11.3f | %-9.3f | %-8.3f | %-8d\n",
                name, overlap$f1, overlap$jaccard,
                overlap$precision, overlap$recall, overlap$hamming),
        file = filepath, append = TRUE)
  }
  write_acc_row("LLM 2025",      overlap_A)
  write_acc_row("LLM 2024+2025", overlap_B)
  write_acc_row("LLM 2016-2025", overlap_C)
  write_acc_row("Raw 2025",      overlap_D)
  write_acc_row("Raw 2024+2025", overlap_E)
  write_acc_row("Raw 2016-2025", overlap_F)
  cat("\n", file = filepath, append = TRUE)

  cat("3. OVERALL NODE-LEVEL CORRELATIONS (Spearman r)\n", file = filepath, append = TRUE)
  cat("----------------------------------------------------------------------------------\n",
      file = filepath, append = TRUE)
  cat(sprintf("%-20s | %-14s | %-14s\n", "Network", "In-Degree (r)", "Out-Degree (r)"),
      file = filepath, append = TRUE)
  cat("---------------------|----------------|----------------\n", file = filepath, append = TRUE)

  write_cor_row <- function(name, degcor) {
    cat(sprintf("%-20s | %-14.3f | %-14.3f\n", name, degcor$r_in, degcor$r_out),
        file = filepath, append = TRUE)
  }
  write_cor_row("LLM 2025",      degcor_A)
  write_cor_row("LLM 2024+2025", degcor_B)
  write_cor_row("LLM 2016-2025", degcor_C)
  write_cor_row("Raw 2025",      degcor_D)
  write_cor_row("Raw 2024+2025", degcor_E)
  write_cor_row("Raw 2016-2025", degcor_F)
  cat("\n", file = filepath, append = TRUE)

  cat("4. OVERALL QAP STATISTICS\n", file = filepath, append = TRUE)
  cat("----------------------------------------------------------------------------------\n",
      file = filepath, append = TRUE)
  cat(sprintf("%-20s | %-14s | %-9s | %-12s | %-10s\n",
              "Network", "QAP Cor (gcor)", "p-value", "Log Reg Coef", "Odds Ratio"),
      file = filepath, append = TRUE)
  cat("---------------------|----------------|-----------|--------------|-------------\n",
      file = filepath, append = TRUE)

  write_qap_row <- function(name, qap_cor, qap_log) {
    cat(sprintf("%-20s | %-14.4f | %-9.4f | %-12.4f | %-10.4f\n",
                name, qap_cor$testval, qap_log$pgreq[2],
                qap_log$coefficients[2], exp(qap_log$coefficients[2])),
        file = filepath, append = TRUE)
  }
  write_qap_row("LLM 2025",      qap_cor_A, qap_log_A)
  write_qap_row("LLM 2024+2025", qap_cor_B, qap_log_B)
  write_qap_row("LLM 2016-2025", qap_cor_C, qap_log_C)
  write_qap_row("Raw 2025",      qap_cor_D, qap_log_D)
  write_qap_row("Raw 2024+2025", qap_cor_E, qap_log_E)
  write_qap_row("Raw 2016-2025", qap_cor_F, qap_log_F)
  cat("\n==================================================================================\n\n",
      file = filepath, append = TRUE)

  cat("4b. MRQAP HIERARCHICAL SUMMARY\n", file = filepath, append = TRUE)
  cat("----------------------------------------------------------------------------------\n",
      file = filepath, append = TRUE)
  cat("  Step 1: Base — Y ~ Predictor only (raw accuracy)\n", file = filepath, append = TRUE)
  cat(sprintf("  %-20s | %-10s | %-8s | %-14s\n",
              "Network", "Coef", "p", "Pseudo-R2"),
      file = filepath, append = TRUE)
  cat("  ---------------------|-----------|---------|---------------\n",
      file = filepath, append = TRUE)
  
  write_mrqap_base_row <- function(name, nl) {
    cat(sprintf("  %-20s | %+10.4f | %-8.4f | %-14.4f\n",
                name, nl$coefficients[2], nl$pgreq[2],
                1 - nl$deviance / nl$null.deviance),
        file = filepath, append = TRUE)
  }
  write_mrqap_base_row("LLM 2025",      mrqap_base_llm25)
  write_mrqap_base_row("LLM 2024+2025", mrqap_base_llm2425)
  write_mrqap_base_row("LLM 2016-2025", mrqap_base_llm_all)
  write_mrqap_base_row("Raw 2025",      mrqap_base_raw25)
  write_mrqap_base_row("Raw 2024+2025", mrqap_base_raw2425)
  write_mrqap_base_row("Raw 2016-2025", mrqap_base_raw_all)
  
  cat("\n  Step 2: Controlled — Y ~ Predictor + Transitivity + Reciprocity\n",
      file = filepath, append = TRUE)
  cat(sprintf("  %-20s | %-10s | %-8s | %-22s | %-8s | %-22s | %-8s | %-14s\n",
              "Network", "Main Coef", "Main p",
              "Trans Coef", "Trans p", "Recip Coef", "Recip p", "Pseudo-R2"),
      file = filepath, append = TRUE)
  cat("  ---------------------|-----------|---------|------------------------|---------|------------------------|---------|---------------\n",
      file = filepath, append = TRUE)
  
  write_mrqap_ctrl_row <- function(name, nl) {
    cat(sprintf("  %-20s | %+10.4f | %-8.4f | %+22.4f | %-8.4f | %+22.4f | %-8.4f | %-14.4f\n",
                name,
                nl$coefficients[2], nl$pgreq[2],
                nl$coefficients[3], nl$pgreq[3],
                nl$coefficients[4], nl$pgreq[4],
                1 - nl$deviance / nl$null.deviance),
        file = filepath, append = TRUE)
  }
  write_mrqap_ctrl_row("LLM 2025",      mrqap_llm25)
  write_mrqap_ctrl_row("LLM 2024+2025", mrqap_llm2425)
  write_mrqap_ctrl_row("LLM 2016-2025", mrqap_llm_all)
  write_mrqap_ctrl_row("Raw 2025",      mrqap_raw25)
  write_mrqap_ctrl_row("Raw 2024+2025", mrqap_raw2425)
  write_mrqap_ctrl_row("Raw 2016-2025", mrqap_raw_all)
  cat("\n  Controls derived from COMPON 2025 (DV). If Main Coef stays significant\n",
      file = filepath, append = TRUE)
  cat("  in Step 2, the predictor captures unique ties beyond structural tendencies.\n\n",
      file = filepath, append = TRUE)
  
  cat("5. LLM VALIDATION EFFECT (Raw -> LLM delta vs COMPON 2025)\n",
      file = filepath, append = TRUE)
  cat("----------------------------------------------------------------------------------\n",
      file = filepath, append = TRUE)
  cat(sprintf("  %-12s | %-8s | %-8s | %-8s | %-8s | %-8s | %-8s | %-9s | %-9s | %-10s\n",
              "Window", "Raw F1", "LLM F1", "D F1", "Raw Prec", "LLM Prec", "D Prec",
              "Raw Rec", "LLM Rec", "D Recall"),
      file = filepath, append = TRUE)
  cat("  -------------|---------|---------|---------|---------|---------|--------|",
      "----------|----------|----------\n", file = filepath, append = TRUE)
  for (i in seq_len(nrow(delta_df))) {
    cat(sprintf("  %-12s | %-8.3f | %-8.3f | %-8.3f | %-8.3f | %-8.3f | %-8.3f | %-9.3f | %-9.3f | %-10.3f\n",
                delta_df$Window[i],
                delta_df$Raw_F1[i],    delta_df$LLM_F1[i],    delta_df$Delta_F1[i],
                delta_df$Raw_Prec[i],  delta_df$LLM_Prec[i],  delta_df$Delta_Prec[i],
                delta_df$Raw_Recall[i],delta_df$LLM_Recall[i],delta_df$Delta_Recall[i]),
        file = filepath, append = TRUE)
  }
  cat("\n  Note: Positive delta = LLM-validated improves over raw scraped vs COMPON.\n",
      file = filepath, append = TRUE)
  cat("  Negative delta = raw scraped is closer to COMPON than LLM output.\n\n",
      file = filepath, append = TRUE)

  cat("6. RAW vs LLM EDGE OVERLAP (within time window — structural similarity)\n",
      file = filepath, append = TRUE)
  cat("----------------------------------------------------------------------------------\n",
      file = filepath, append = TRUE)
  cat(sprintf("  %-14s | %-9s | %-8s | %-8s | %-8s | %-8s\n",
              "Window", "Precision", "Recall", "F1", "Jaccard", "Hamming"),
      file = filepath, append = TRUE)
  cat("  --------------|-----------|---------|---------|---------|----------\n",
      file = filepath, append = TRUE)
  for (pair in list(
    list("2025",      overlap_raw_llm_2025),
    list("2024+2025", overlap_raw_llm_2425),
    list("2016-2025", overlap_raw_llm_all)
  )) {
    cat(sprintf("  %-14s | %-9.3f | %-8.3f | %-8.3f | %-8.3f | %-8d\n",
                pair[[1]], pair[[2]]$precision, pair[[2]]$recall,
                pair[[2]]$f1, pair[[2]]$jaccard, pair[[2]]$hamming),
        file = filepath, append = TRUE)
  }
  cat("\n  Note: Precision = (Raw & LLM) / Raw. Recall = (Raw & LLM) / LLM.\n",
      file = filepath, append = TRUE)
  cat("  High F1 = raw and LLM largely agree; low F1 = LLM removed many raw edges.\n\n",
      file = filepath, append = TRUE)
  cat("==================================================================================\n\n\n",
      file = filepath, append = TRUE)
  

  
  # PART 2: DETAILED PER-CASE BREAKDOWNS
  
  cat("PART 2: DETAILED PER-CASE BREAKDOWNS\n", file = filepath, append = TRUE)
  cat("==================================================================================\n\n",
      file = filepath, append = TRUE)

  write_cug_block <- function(label, cug_res, filepath) {
    for (cmode_name in c("edges", "dyad_census")) {
      cug_tbl   <- cug_res[[cmode_name]]
      cmode_lbl <- ifelse(cmode_name == "edges", "Edges", "Dyad Census")
      cat(sprintf("  [%s | conditioned on: %s]\n", label, cmode_lbl),
          file = filepath, append = TRUE)
      cat(sprintf("  %-14s | %-8s | %-9s | %-8s | %-8s\n",
                  "Statistic", "Observed", "Null Mean", "Null SD", "z (sig)"),
          file = filepath, append = TRUE)
      cat("  ---------------|----------|-----------|----------|----------\n",
          file = filepath, append = TRUE)
      for (i in seq_len(nrow(cug_tbl))) {
        cat(sprintf("  %-14s | %-8.4f | %-9.4f | %-8.4f | %-8s  p=%s\n",
                    cug_tbl$Statistic[i], as.numeric(cug_tbl$Observed[i]),
                    as.numeric(cug_tbl$Null_mean[i]), as.numeric(cug_tbl$Null_SD[i]),
                    cug_tbl$z[i], cug_tbl$p_value[i]),
            file = filepath, append = TRUE)
      }
      cat("\n", file = filepath, append = TRUE)
    }
  }

  # write_section now includes geo and ESP per-case summaries [updated v3]
  write_section <- function(section_title, name_a, stats_a, geo_a, esp_a,
                             overlap, degcor, qap_cor, qap_log, mrqap_base, mrqap_ctrl, cug_tbl_arg,
                             filepath) {
    cat(sprintf("%s\n", toupper(section_title)), file = filepath, append = TRUE)
    cat("--------------------------------------------------\n\n", file = filepath, append = TRUE)

    # Basic descriptives
    cat("1. Basic Descriptives\n", file = filepath, append = TRUE)
    cat(sprintf("%-15s | %-15s | %-15s\n", "Metric", name_a, "COMPON 2025"),
        file = filepath, append = TRUE)
    cat("----------------|-----------------|----------------\n", file = filepath, append = TRUE)
    cat(sprintf("%-15s | %-15d | %-15d\n", "Nodes",
                stats_a$n,           stats_comp25$n),           file = filepath, append = TRUE)
    cat(sprintf("%-15s | %-15d | %-15d\n", "Edges",
                stats_a$edges,       stats_comp25$edges),        file = filepath, append = TRUE)
    cat(sprintf("%-15s | %-15.4f | %-15.4f\n", "Density",
                stats_a$density,     stats_comp25$density),      file = filepath, append = TRUE)
    cat(sprintf("%-15s | %-15.4f | %-15.4f\n", "Reciprocity",
                stats_a$reciprocity, stats_comp25$reciprocity),  file = filepath, append = TRUE)
    cat(sprintf("%-15s | %-15.4f | %-15.4f\n\n", "Transitivity",
                stats_a$transitivity,stats_comp25$transitivity), file = filepath, append = TRUE)

    # Geodesic stats [NEW in v3]
    cat("2. Geodesic Distance Statistics\n", file = filepath, append = TRUE)
    n2 <- stats_a$n * (stats_a$n - 1)
    cat(sprintf("  %-28s | %-12s | %-12s\n", "Metric", name_a, "COMPON 2025"),
        file = filepath, append = TRUE)
    cat(sprintf("  %-28s | %-12.3f | %-12.3f\n", "Mean geodesic dist (reachable)",
                mean(geo_a), mean(geo_comp25)),
        file = filepath, append = TRUE)
    cat(sprintf("  %-28s | %-12d | %-12d\n", "Diameter",
                max(geo_a), max(geo_comp25)),
        file = filepath, append = TRUE)
    cat(sprintf("  %-28s | %-12.3f | %-12.3f\n\n", "Reachable pair share",
                length(geo_a) / n2, length(geo_comp25) / n2),
        file = filepath, append = TRUE)

    # ESP stats [NEW in v3]
    cat("3. ESP Distribution (OTP shared partners)\n", file = filepath, append = TRUE)
    cat(sprintf("  %s: %s\n", name_a,
                paste(names(esp_a), "=", esp_a, collapse = "  ")),
        file = filepath, append = TRUE)
    cat(sprintf("  COMPON: %s\n\n",
                paste(names(esp_comp25), "=", esp_comp25, collapse = "  ")),
        file = filepath, append = TRUE)

    # Edge overlap
    cat("4. Edge Overlap & Accuracy\n", file = filepath, append = TRUE)
    cat(sprintf("  TP / FP / FN / TN: %d / %d / %d / %d\n",
                overlap$tp, overlap$fp, overlap$fn, overlap$tn),
        file = filepath, append = TRUE)
    cat(sprintf("  Precision:         %.3f\n", overlap$precision), file = filepath, append = TRUE)
    cat(sprintf("  Recall:            %.3f\n", overlap$recall),    file = filepath, append = TRUE)
    cat(sprintf("  F1 Score:          %.3f\n", overlap$f1),        file = filepath, append = TRUE)
    cat(sprintf("  Jaccard Sim:       %.3f\n", overlap$jaccard),   file = filepath, append = TRUE)
    cat(sprintf("  Hamming Dist:      %d\n\n", overlap$hamming),   file = filepath, append = TRUE)

    # Degree correlations
    cat("5. Node-Level Correlations\n", file = filepath, append = TRUE)
    cat(sprintf("  In-Degree Spearman r:  %.3f\n",  degcor$r_in),  file = filepath, append = TRUE)
    cat(sprintf("  Out-Degree Spearman r: %.3f\n\n", degcor$r_out), file = filepath, append = TRUE)

    # QAP
    cat("6. QAP Matrix Significance\n", file = filepath, append = TRUE)
    cat(sprintf("  QAP Matrix Cor (gcor):      %.4f (p-value = %.4f)\n",
                qap_cor$testval, qap_cor$pgreq),
        file = filepath, append = TRUE)
    cat(sprintf("  QAP Log Reg Coef:           %.4f (p-value = %.4f)\n",
                qap_log$coefficients[2], qap_log$pgreq[2]),
        file = filepath, append = TRUE)
    cat(sprintf("  Odds Ratio (e^coef):        %.4f\n\n",
                exp(qap_log$coefficients[2])),
        file = filepath, append = TRUE)

    # MRQAP
    cat("6b. MRQAP Step 1 — Base (unadjusted)\n", file = filepath, append = TRUE)
    cat(sprintf("  %-26s Coef: %+8.4f  OR: %7.4f  p: %.4f  Pseudo-R2: %.4f\n\n",
                name_a,
                mrqap_base$coefficients[2], exp(mrqap_base$coefficients[2]),
                mrqap_base$pgreq[2],
                1 - mrqap_base$deviance / mrqap_base$null.deviance),
        file = filepath, append = TRUE)
    
    cat("6c. MRQAP Step 2 — Controlled (Transitivity + Reciprocity)\n",
        file = filepath, append = TRUE)
    for (idx in 2:4) {
      lbl <- c(name_a, "Transitivity (2-path)", "Reciprocity")[idx - 1]
      cat(sprintf("  %-26s Coef: %+8.4f  OR: %7.4f  p: %.4f\n",
                  lbl, mrqap_ctrl$coefficients[idx],
                  exp(mrqap_ctrl$coefficients[idx]), mrqap_ctrl$pgreq[idx]),
          file = filepath, append = TRUE)
    }
    cat(sprintf("  Pseudo-R2 (McFadden): %.4f\n\n",
                1 - mrqap_ctrl$deviance / mrqap_ctrl$null.deviance),
        file = filepath, append = TRUE)
    
    # CUG
    cat("7. CUG Test Results\n", file = filepath, append = TRUE)
    write_cug_block(name_a, cug_tbl_arg, filepath)

    cat("==================================================================================\n\n",
        file = filepath, append = TRUE)
  }

  # LLM comparisons
  write_section("Comparison A: LLM 2025",      "LLM 2025",
                stats_llm25,  geo_llm25,  esp_llm25,
                overlap_A, degcor_A, qap_cor_A, qap_log_A, mrqap_base_llm25, mrqap_llm25, cug_strict_llm25, filepath)
  write_section("Comparison B: LLM 2024+2025", "LLM 2024+25",
                stats_llm2425, geo_llm2425, esp_llm2425,
                overlap_B, degcor_B, qap_cor_B, qap_log_B, mrqap_base_llm2425, mrqap_llm2425, cug_strict_llm2425, filepath)
  write_section("Comparison C: LLM 2016-2025", "LLM 2016-25",
                stats_llm_all, geo_llm_all, esp_llm_all,
                overlap_C, degcor_C, qap_cor_C, qap_log_C, mrqap_base_llm_all, mrqap_llm_all, cug_strict_llm_all, filepath)

  # Raw comparisons
  write_section("Comparison D: Raw 2025",       "Raw 2025",
                stats_raw25,   geo_raw25,   esp_raw25,
                overlap_D, degcor_D, qap_cor_D, qap_log_D, mrqap_base_raw25, mrqap_raw25, cug_strict_raw25, filepath)
  write_section("Comparison E: Raw 2024+2025",  "Raw 2024+25",
                stats_raw2425, geo_raw2425, esp_raw2425,
                overlap_E, degcor_E, qap_cor_E, qap_log_E, mrqap_base_raw2425, mrqap_raw2425, cug_strict_raw2425, filepath)
  write_section("Comparison F: Raw 2016-2025",  "Raw 2016-25",
                stats_raw_all, geo_raw_all, esp_raw_all,
                overlap_F, degcor_F, qap_cor_F, qap_log_F, mrqap_base_raw_all, mrqap_raw_all, cug_strict_raw_all, filepath)

  # Consolidated CUG block for all networks
  cat("PART 3: CUG TESTS — ALL NETWORKS (Strict, reps=2000)\n",
      file = filepath, append = TRUE)
  cat("----------------------------------------------------------------------------------\n",
      file = filepath, append = TRUE)
  write_cug_block("COMPON 2025",    cug_strict_comp25,  filepath)
  write_cug_block("LLM 2025",       cug_strict_llm25,   filepath)
  write_cug_block("LLM 2024+2025",  cug_strict_llm2425, filepath)
  write_cug_block("LLM 2016-2025",  cug_strict_llm_all, filepath)
  write_cug_block("Raw 2025",       cug_strict_raw25,   filepath)
  write_cug_block("Raw 2024+2025",  cug_strict_raw2425, filepath)
  write_cug_block("Raw 2016-2025",  cug_strict_raw_all, filepath)
  cat("==================================================================================\n\n",
      file = filepath, append = TRUE)

  cat(sprintf("\n=== Successfully exported master report to: %s ===\n", filepath))
}

export_master_report("Master_Network_Comparisons_v3.txt")

cat("\n##############################################################\n")
cat("# EXTRA: SPECIALIST BRIDGING TESTS                                 #\n")
cat("##############################################################\n\n")

make_bridging_df <- function(mat, label) {
  g <- igraph::graph_from_adjacency_matrix(mat, mode = "directed", diag = FALSE)
  igraph::V(g)$name <- colnames(mat)

  node <- colnames(mat)
  category <- cat_labels[node]

  indegree  <- colSums(mat)
  outdegree <- rowSums(mat)
  total_degree <- indegree + outdegree

  betweenness <- igraph::betweenness(g, directed = TRUE, normalized = TRUE)

  max_degree <- max(total_degree, na.rm = TRUE)
  broker_idx <- ifelse(total_degree > 0 & max_degree > 0,
                       betweenness / (total_degree / max_degree),
                       NA)

  cross_ties <- sapply(seq_along(node), function(i) {
    other_cat <- category != category[i]
    out_cross <- sum(mat[i, other_cat], na.rm = TRUE)
    in_cross  <- sum(mat[other_cat, i], na.rm = TRUE)
    out_cross + in_cross
  })

  cross_share <- ifelse(total_degree > 0, cross_ties / total_degree, NA)

  data.frame(
    network = label,
    node = node,
    category = category,
    specialist = category == "specialist",
    indegree = indegree,
    outdegree = outdegree,
    total_degree = total_degree,
    betweenness = betweenness,
    broker_idx = broker_idx,
    cross_ties = cross_ties,
    cross_share = cross_share,
    stringsAsFactors = FALSE
  )
}

safe_wilcox_specialist_greater <- function(df, metric) {
  x <- df[df$specialist, metric]
  y <- df[!df$specialist, metric]

  x <- x[!is.na(x)]
  y <- y[!is.na(y)]

  if (length(x) < 2 || length(y) < 2 || length(unique(c(x, y))) < 2) {
    return(data.frame(
      metric = metric,
      specialist_mean = mean(x, na.rm = TRUE),
      other_mean = mean(y, na.rm = TRUE),
      specialist_median = median(x, na.rm = TRUE),
      other_median = median(y, na.rm = TRUE),
      W = NA,
      p_value = NA
    ))
  }

  wt <- wilcox.test(x, y, alternative = "greater", exact = FALSE)

  data.frame(
    metric = metric,
    specialist_mean = mean(x, na.rm = TRUE),
    other_mean = mean(y, na.rm = TRUE),
    specialist_median = median(x, na.rm = TRUE),
    other_median = median(y, na.rm = TRUE),
    W = as.numeric(wt$statistic),
    p_value = wt$p.value
  )
}

run_specialist_bridging_tests <- function(mat, label) {
  df <- make_bridging_df(mat, label)

  cat("\n==============================================================\n")
  cat("SPECIALIST BRIDGING TEST:", label, "\n")
  cat("==============================================================\n\n")

  cat("Specialist nodes:\n")
  spec_tbl <- df[df$specialist, c(
    "node", "category", "indegree", "outdegree", "total_degree",
    "betweenness", "broker_idx", "cross_ties", "cross_share"
  )]
  spec_tbl$betweenness_rank <- rank(-df$betweenness, ties.method = "min")[df$specialist]
  spec_tbl$broker_rank <- rank(-df$broker_idx, ties.method = "min", na.last = "keep")[df$specialist]
  spec_tbl$cross_ties_rank <- rank(-df$cross_ties, ties.method = "min")[df$specialist]
  print(spec_tbl, row.names = FALSE)

  cat("\nTop 10 nodes by betweenness:\n")
  top_b <- df[order(-df$betweenness), c(
    "node", "category", "betweenness", "broker_idx", "cross_ties", "cross_share", "total_degree"
  )]
  print(head(top_b, 10), row.names = FALSE)

  cat("\nGroup means: specialists vs non-specialists\n")
  group_summary <- aggregate(
    cbind(betweenness, broker_idx, cross_ties, cross_share, total_degree, indegree, outdegree) ~ specialist,
    data = df,
    FUN = mean,
    na.rm = TRUE
  )
  print(group_summary, row.names = FALSE)

  cat("\nOne-sided Wilcoxon tests, specialist > non-specialist:\n")
  tests <- do.call(rbind, lapply(
    c("betweenness", "broker_idx", "cross_ties", "cross_share", "total_degree", "indegree", "outdegree"),
    function(metric) safe_wilcox_specialist_greater(df, metric)
  ))
  tests[, c("specialist_mean", "other_mean", "specialist_median", "other_median", "p_value")] <-
    round(tests[, c("specialist_mean", "other_mean", "specialist_median", "other_median", "p_value")], 4)
  print(tests, row.names = FALSE)

  cat("\nInterpretation rule:\n")
  cat("  Direct support for specialist bridging requires specialists to be higher on betweenness,\n")
  cat("  broker_idx, or cross-category bridging measures, not merely on in-degree or out-degree.\n")
  cat("  If only degree differs, this is not evidence of a bridging profile.\n\n")

  invisible(list(df = df, tests = tests))
}

bridge_comp25  <- run_specialist_bridging_tests(m_comp25,  "COMPON 2025")
bridge_llm_all <- run_specialist_bridging_tests(m_llm_all, "LLM 2016-2025")
bridge_raw_all <- run_specialist_bridging_tests(m_raw_all, "Raw 2016-2025")

cat("\n=== Script complete ===\n")
