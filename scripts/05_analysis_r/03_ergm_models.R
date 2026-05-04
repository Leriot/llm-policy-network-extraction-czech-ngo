# =============================================================================
# ERGM analysis: LLM-validated + Raw scraped networks vs COMPON ground truth
# Thesis analysis — Czech NGO policy networks (COMPON framework)
# v2: adds raw scraped baselines and predictive models for method validation
#
# Model numbering:
#  Baselines (1-7):  COMPON, LLM 2016-25, LLM 2024-25, LLM 2025,
#                    Raw 2016-25, Raw 2024-25, Raw 2025
#  Predictive (8-13): LLM_all→COMPON, LLM_2425→COMPON, LLM_25→COMPON,
#                     Raw_all→COMPON, Raw_2425→COMPON, Raw_25→COMPON
# =============================================================================

library(ergm)
library(sna)
library(network)
library(igraph)

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
ergm_output_dir <- file.path(project_root, "outputs", "model_results", "ergm_generated")
dir.create(ergm_output_dir, recursive = TRUE, showWarnings = FALSE)

# =============================================================================
# 1. LOAD AND PREPARE DATA
# =============================================================================

# --- LLM-validated networks --------------------------------------------------
compon_2025   <- read.csv(compon_matrix_path, header = TRUE, check.names = FALSE)
llm_all       <- read.csv(file.path(input_dir, "collab_all_LLM.csv"),           header = TRUE, check.names = FALSE)
llm_2024_2025 <- read.csv(file.path(input_dir, "collab_2024_and_2025_LLM.csv"), header = TRUE, check.names = FALSE)
llm_2025      <- read.csv(file.path(input_dir, "collab_2025_LLM.csv"),          header = TRUE, check.names = FALSE)

# --- Raw scraped networks (collab+comention=1, no LLM filter) ----------------
raw_all       <- read.csv(file.path(input_dir, "merged_2016_2025_directed.csv"),     header = TRUE, check.names = FALSE)
raw_2024_2025 <- read.csv(file.path(input_dir, "merged_2024_and_2025_directed.csv"), header = TRUE, check.names = FALSE)
raw_2025      <- read.csv(file.path(input_dir, "merged_2025_directed.csv"),          header = TRUE, check.names = FALSE)

setwd(ergm_output_dir)

# --- Set rownames from colnames ----------------------------------------------
for (df_name in c("compon_2025", "llm_all", "llm_2024_2025", "llm_2025",
                  "raw_all", "raw_2024_2025", "raw_2025")) {
  df <- get(df_name)
  rownames(df) <- colnames(df)
  assign(df_name, df)
}

# --- Canonical actor order ---------------------------------------------------
actor_order <- colnames(llm_all)

if (!all(actor_order %in% colnames(compon_2025)))   stop("Missing nodes in COMPON!")
if (!all(actor_order %in% colnames(raw_all)))       stop("Missing nodes in raw_all!")
if (!all(actor_order %in% colnames(raw_2024_2025))) stop("Missing nodes in raw_2024_2025!")
if (!all(actor_order %in% colnames(raw_2025)))      stop("Missing nodes in raw_2025!")

compon_2025   <- compon_2025[actor_order, actor_order]
llm_2024_2025 <- llm_2024_2025[actor_order, actor_order]
llm_2025      <- llm_2025[actor_order, actor_order]
raw_all       <- raw_all[actor_order, actor_order]
raw_2024_2025 <- raw_2024_2025[actor_order, actor_order]
raw_2025      <- raw_2025[actor_order, actor_order]

# --- category assignment -------------------------------------------------
categories <- list(
  umbrella   = c("ccc", "grn"),
  advocacy   = c("foe", "arn", "grp", "nes", "upe"),
  specialist = c("fct", "frb", "cde", "cit", "aes"),
  radical    = c("lau", "fff", "ext"),
  sectoral   = c("ver", "cal", "bel"),
  peripheral = c("aut")
)

cat_labels <- setNames(rep(NA, length(actor_order)), actor_order)
for (cat_name in names(categories)) {
  cat_labels[categories[[cat_name]]] <- cat_name
}

# --- Build network objects ---------------------------------------------------
make_net <- function(df, label) {
  net <- network(as.matrix(df), directed = TRUE)
  net %v% "category" <- as.character(cat_labels)
  cat(sprintf("  %-22s edges: %d\n", paste0(label, ":"), network.edgecount(net)))
  net
}

cat("Building network objects...\n")
net_compon  <- make_net(compon_2025,   "COMPON 2025")
net_llm     <- make_net(llm_all,       "LLM 2016-2025")
net_llm2425 <- make_net(llm_2024_2025, "LLM 2024-2025")
net_llm25   <- make_net(llm_2025,      "LLM 2025")
net_raw     <- make_net(raw_all,       "Raw 2016-2025")
net_raw2425 <- make_net(raw_2024_2025, "Raw 2024-2025")
net_raw25   <- make_net(raw_2025,      "Raw 2025")
cat("\n")

# Shared ERGM control settings
ergm_ctrl <- control.ergm(
  seed             = 67,
  MCMC.burnin      = 100000,
  MCMC.samplesize  = 50000,
  MCMLE.maxit      = 100
)

# =============================================================================
# 2. BASELINE ERGMs (7 networks)
# Model: edges + mutual + nodematch("category")
# =============================================================================

cat("\n==============================================================\n")
cat("2. BASELINE ERGMs\n")
cat("==============================================================\n")

# --- 2.1 COMPON 2025 ---------------------------------------------------------
cat("\n--- 2.1 Baseline: COMPON 2025 ---\n")
model_compon <- ergm(net_compon ~ edges + mutual + nodematch("category"),
                     control = ergm_ctrl)
summary(model_compon)

# --- 2.2 LLM 2016-2025 -------------------------------------------------------
cat("\n--- 2.2 Baseline: LLM 2016-2025 ---\n")
model_llm <- ergm(net_llm ~ edges + mutual + nodematch("category"),
                  control = ergm_ctrl)
summary(model_llm)

# --- 2.3 LLM 2024-2025 -------------------------------------------------------
cat("\n--- 2.3 Baseline: LLM 2024-2025 ---\n")
model_llm2425 <- ergm(net_llm2425 ~ edges + mutual + nodematch("category"),
                      control = ergm_ctrl)
summary(model_llm2425)

# --- 2.4 LLM 2025 ------------------------------------------------------------
cat("\n--- 2.4 Baseline: LLM 2025 ---\n")
model_llm25 <- ergm(net_llm25 ~ edges + mutual + nodematch("category"),
                    control = ergm_ctrl)
summary(model_llm25)

# --- 2.5 Raw 2016-2025 -------------------------------------------------------
cat("\n--- 2.5 Baseline: Raw 2016-2025 ---\n")
model_raw <- ergm(net_raw ~ edges + mutual + nodematch("category"),
                  control = ergm_ctrl)
summary(model_raw)

# --- 2.6 Raw 2024-2025 -------------------------------------------------------
cat("\n--- 2.6 Baseline: Raw 2024-2025 ---\n")
model_raw2425 <- ergm(net_raw2425 ~ edges + mutual + nodematch("category"),
                      control = ergm_ctrl)
summary(model_raw2425)

# --- 2.7 Raw 2025 ------------------------------------------------------------
cat("\n--- 2.7 Baseline: Raw 2025 ---\n")
model_raw25 <- ergm(net_raw25 ~ edges + mutual + nodematch("category"),
                    control = ergm_ctrl)
summary(model_raw25)

# =============================================================================
# 3. PREDICTIVE ERGMs (network → COMPON 2025)
# Model: COMPON ~ edges + mutual + nodematch("category") + edgecov(net_x)
# Coefficient on edgecov = how much the predictor network predicts COMPON ties
# =============================================================================

cat("\n==============================================================\n")
cat("3. PREDICTIVE ERGMs (predicting COMPON 2025)\n")
cat("==============================================================\n")

# --- 3.1 Predictive: LLM 2016-2025 → COMPON ----------------------------------
cat("\n--- 3.1 Predictive: LLM 2016-2025 → COMPON ---\n")
model_pred_llm <- ergm(net_compon ~ edges + mutual + nodematch("category") +
                         edgecov(net_llm),
                       control = ergm_ctrl)
summary(model_pred_llm)

# --- 3.2 Predictive: LLM 2024-2025 → COMPON ----------------------------------
cat("\n--- 3.2 Predictive: LLM 2024-2025 → COMPON ---\n")
model_pred_llm2425 <- ergm(net_compon ~ edges + mutual + nodematch("category") +
                              edgecov(net_llm2425),
                            control = ergm_ctrl)
summary(model_pred_llm2425)

# --- 3.3 Predictive: LLM 2025 → COMPON ---------------------------------------
cat("\n--- 3.3 Predictive: LLM 2025 → COMPON ---\n")
model_pred_llm25 <- ergm(net_compon ~ edges + mutual + nodematch("category") +
                            edgecov(net_llm25),
                          control = ergm_ctrl)
summary(model_pred_llm25)

# --- 3.4 Predictive: Raw 2016-2025 → COMPON ----------------------------------
cat("\n--- 3.4 Predictive: Raw 2016-2025 → COMPON ---\n")
model_pred_raw <- ergm(net_compon ~ edges + mutual + nodematch("category") +
                         edgecov(net_raw),
                       control = ergm_ctrl)
summary(model_pred_raw)

# --- 3.5 Predictive: Raw 2024-2025 → COMPON ----------------------------------
cat("\n--- 3.5 Predictive: Raw 2024-2025 → COMPON ---\n")
model_pred_raw2425 <- ergm(net_compon ~ edges + mutual + nodematch("category") +
                              edgecov(net_raw2425),
                            control = ergm_ctrl)
summary(model_pred_raw2425)

# --- 3.6 Predictive: Raw 2025 → COMPON ---------------------------------------
cat("\n--- 3.6 Predictive: Raw 2025 → COMPON ---\n")
model_pred_raw25 <- ergm(net_compon ~ edges + mutual + nodematch("category") +
                            edgecov(net_raw25),
                          control = ergm_ctrl)
summary(model_pred_raw25)

# =============================================================================
# 4. GOODNESS-OF-FIT
# =============================================================================

cat("\nComputing GOF for all 13 models...\n")

gof_compon      <- gof(model_compon)
gof_llm         <- gof(model_llm)
gof_llm2425     <- gof(model_llm2425)
gof_llm25       <- gof(model_llm25)
gof_raw         <- gof(model_raw)
gof_raw2425     <- gof(model_raw2425)
gof_raw25       <- gof(model_raw25)
gof_pred_llm    <- gof(model_pred_llm)
gof_pred_llm2425 <- gof(model_pred_llm2425)
gof_pred_llm25  <- gof(model_pred_llm25)
gof_pred_raw    <- gof(model_pred_raw)
gof_pred_raw2425 <- gof(model_pred_raw2425)
gof_pred_raw25  <- gof(model_pred_raw25)

cat("GOF complete.\n")

# =============================================================================
# 5. EXPORT DIAGNOSTIC PDFs — SEPARATED GOF + MCMC
# =============================================================================

# --- Helper: GOF only (in-degree, out-degree, ESP, geodesic distance) --------
save_gof_pdf <- function(gof_obj, filename, title) {
  pdf(file = filename, width = 10, height = 9)
  par(oma = c(0, 0, 3, 0))           # outer margin for the suptitle
  plot(gof_obj)
  mtext(title, outer = TRUE, cex = 1.1, font = 2, line = 1.2)
  dev.off()
  cat(sprintf("  GOF written: %s\n", filename))
}

# --- Helper: MCMC diagnostics only -------------------------------------------
save_mcmc_pdf <- function(model, filename) {
  pdf(file = filename, width = 12, height = 9)
  mcmc.diagnostics(model)
  dev.off()
  cat(sprintf("  MCMC written: %s\n", filename))
}

# --- Model registry ----------------------------------------------------------
# Each row: model object, gof object, short label
models_registry <- list(
  list(model = model_compon,      gof = gof_compon,      label = "COMPON_2025",         title = "GOF: COMPON 2025 (Baseline)"),
  list(model = model_llm,         gof = gof_llm,         label = "LLM_2016_25",         title = "GOF: LLM 2016–2025 (Baseline)"),
  list(model = model_llm2425,     gof = gof_llm2425,     label = "LLM_2024_25",         title = "GOF: LLM 2024–2025 (Baseline)"),
  list(model = model_llm25,       gof = gof_llm25,       label = "LLM_2025",            title = "GOF: LLM 2025 (Baseline)"),
  list(model = model_raw,         gof = gof_raw,         label = "Raw_2016_25",         title = "GOF: Raw 2016–2025 (Baseline)"),
  list(model = model_raw2425,     gof = gof_raw2425,     label = "Raw_2024_25",         title = "GOF: Raw 2024–2025 (Baseline)"),
  list(model = model_raw25,       gof = gof_raw25,       label = "Raw_2025",            title = "GOF: Raw 2025 (Baseline)"),
  list(model = model_pred_llm,    gof = gof_pred_llm,    label = "Pred_LLM_All",        title = "GOF: Predictive — COMPON ~ LLM 2016–2025"),
  list(model = model_pred_llm2425,gof = gof_pred_llm2425,label = "Pred_LLM_2425",      title = "GOF: Predictive — COMPON ~ LLM 2024–2025"),
  list(model = model_pred_llm25,  gof = gof_pred_llm25,  label = "Pred_LLM_2025",      title = "GOF: Predictive — COMPON ~ LLM 2025"),
  list(model = model_pred_raw,    gof = gof_pred_raw,    label = "Pred_Raw_All",        title = "GOF: Predictive — COMPON ~ Raw 2016–2025"),
  list(model = model_pred_raw2425,gof = gof_pred_raw2425,label = "Pred_Raw_2425",      title = "GOF: Predictive — COMPON ~ Raw 2024–2025"),
  list(model = model_pred_raw25,  gof = gof_pred_raw25,  label = "Pred_Raw_2025",      title = "GOF: Predictive — COMPON ~ Raw 2025"),
  list(model = model_compon_mix,  gof = gof_compon_mix,  label = "COMPON_Hypothesis",  title = "GOF: COMPON 2025 (Hypothesis Testing)"),
  list(model = model_llm_mix,     gof = gof_llm_mix,     label = "LLM_Hypothesis",     title = "GOF: LLM 2016–2025 (Hypothesis Testing)")
)

# --- Export all 15 models -----------------------------------------------------
cat("\nExporting GOF and MCMC PDFs...\n")
dir.create("GOF",  showWarnings = FALSE)
dir.create("MCMC", showWarnings = FALSE)

for (i in seq_along(models_registry)) {
  m   <- models_registry[[i]]
  idx <- sprintf("%02d", i)
  save_gof_pdf( m$gof,   file.path("GOF",  paste0("GOF_",  idx, "_", m$label, ".pdf")), m$title)
  save_mcmc_pdf(m$model, file.path("MCMC", paste0("MCMC_", idx, "_", m$label, ".pdf")))
}

cat("\nDone. 15 GOF PDFs in /GOF, 15 MCMC PDFs in /MCMC\n")

# =============================================================================
# 6. EXTRACT RESULTS & BUILD TABLES
# =============================================================================

cat("\nExtracting model results...\n")

clean_names <- c("Estimate", "Std.Error", "MCMC%", "z_value", "p_value")

extract_model <- function(model, label) {
  s  <- as.data.frame(coef(summary(model)))
  colnames(s) <- clean_names
  s$Estimate  <- round(s$Estimate,  3)
  s$Std.Error <- round(s$Std.Error, 3)
  s$z_value   <- round(s$z_value,   2)
  s$p_value   <- format.pval(s$p_value, digits = 2, eps = 0.0001, scientific = FALSE)
  data.frame(Model = label, Term = rownames(s), s, stringsAsFactors = FALSE)
}

# All 13 models
res_compon       <- extract_model(model_compon,      "01. COMPON 2025")
res_llm          <- extract_model(model_llm,         "02. LLM 2016-2025")
res_llm2425      <- extract_model(model_llm2425,     "03. LLM 2024-2025")
res_llm25        <- extract_model(model_llm25,       "04. LLM 2025")
res_raw          <- extract_model(model_raw,         "05. Raw 2016-2025")
res_raw2425      <- extract_model(model_raw2425,     "06. Raw 2024-2025")
res_raw25        <- extract_model(model_raw25,       "07. Raw 2025")
res_pred_llm     <- extract_model(model_pred_llm,    "08. Pred LLM 2016-25→COMPON")
res_pred_llm2425 <- extract_model(model_pred_llm2425,"09. Pred LLM 2024-25→COMPON")
res_pred_llm25   <- extract_model(model_pred_llm25,  "10. Pred LLM 2025→COMPON")
res_pred_raw     <- extract_model(model_pred_raw,    "11. Pred Raw 2016-25→COMPON")
res_pred_raw2425 <- extract_model(model_pred_raw2425,"12. Pred Raw 2024-25→COMPON")
res_pred_raw25   <- extract_model(model_pred_raw25,  "13. Pred Raw 2025→COMPON")

final_results_table <- rbind(
  res_compon, res_llm, res_llm2425, res_llm25,
  res_raw, res_raw2425, res_raw25,
  res_pred_llm, res_pred_llm2425, res_pred_llm25,
  res_pred_raw, res_pred_raw2425, res_pred_raw25
)

# --- Model fit metrics -------------------------------------------------------
fit_metrics <- data.frame(
  Model = c("01. COMPON 2025",
            "02. LLM 2016-2025", "03. LLM 2024-2025", "04. LLM 2025",
            "05. Raw 2016-2025", "06. Raw 2024-2025", "07. Raw 2025",
            "08. Pred LLM 2016-25→COMPON", "09. Pred LLM 2024-25→COMPON", "10. Pred LLM 2025→COMPON",
            "11. Pred Raw 2016-25→COMPON", "12. Pred Raw 2024-25→COMPON", "13. Pred Raw 2025→COMPON"),
  AIC = c(
    AIC(model_compon),
    AIC(model_llm), AIC(model_llm2425), AIC(model_llm25),
    AIC(model_raw), AIC(model_raw2425), AIC(model_raw25),
    AIC(model_pred_llm), AIC(model_pred_llm2425), AIC(model_pred_llm25),
    AIC(model_pred_raw), AIC(model_pred_raw2425), AIC(model_pred_raw25)
  ),
  BIC = c(
    BIC(model_compon),
    BIC(model_llm), BIC(model_llm2425), BIC(model_llm25),
    BIC(model_raw), BIC(model_raw2425), BIC(model_raw25),
    BIC(model_pred_llm), BIC(model_pred_llm2425), BIC(model_pred_llm25),
    BIC(model_pred_raw), BIC(model_pred_raw2425), BIC(model_pred_raw25)
  ),
  LogLik = c(
    as.numeric(logLik(model_compon)),
    as.numeric(logLik(model_llm)),     as.numeric(logLik(model_llm2425)),   as.numeric(logLik(model_llm25)),
    as.numeric(logLik(model_raw)),     as.numeric(logLik(model_raw2425)),   as.numeric(logLik(model_raw25)),
    as.numeric(logLik(model_pred_llm)), as.numeric(logLik(model_pred_llm2425)), as.numeric(logLik(model_pred_llm25)),
    as.numeric(logLik(model_pred_raw)), as.numeric(logLik(model_pred_raw2425)), as.numeric(logLik(model_pred_raw25))
  ),
  stringsAsFactors = FALSE
)

fit_metrics$AIC    <- round(fit_metrics$AIC,    2)
fit_metrics$BIC    <- round(fit_metrics$BIC,    2)
fit_metrics$LogLik <- round(fit_metrics$LogLik, 2)

#--- Predictive model comparison: LLM vs Raw (same COMPON response) ---------
  cat("\n--- Predictive model comparison: LLM vs Raw edgecov coefficients ---\n")

get_edgecov <- function(model, term_name) {
  s    <- coef(summary(model))
  row  <- s[grep("edgecov", rownames(s)), , drop = FALSE]
  list(coef = row[1, 1], pval = row[1, 4])   # col 1 = Estimate, col 4 = Pr(>|z|)
}

ec_pred_llm    <- get_edgecov(model_pred_llm)
ec_pred_llm2425 <- get_edgecov(model_pred_llm2425)
ec_pred_llm25  <- get_edgecov(model_pred_llm25)
ec_pred_raw    <- get_edgecov(model_pred_raw)
ec_pred_raw2425 <- get_edgecov(model_pred_raw2425)
ec_pred_raw25  <- get_edgecov(model_pred_raw25)

pred_compare <- data.frame(
  Window    = c("2016-2025", "2024-2025", "2025"),
  LLM_coef  = c(ec_pred_llm$coef,    ec_pred_llm2425$coef,  ec_pred_llm25$coef),
  LLM_pval  = c(ec_pred_llm$pval,    ec_pred_llm2425$pval,  ec_pred_llm25$pval),
  Raw_coef  = c(ec_pred_raw$coef,    ec_pred_raw2425$coef,  ec_pred_raw25$coef),
  Raw_pval  = c(ec_pred_raw$pval,    ec_pred_raw2425$pval,  ec_pred_raw25$pval),
  LLM_AIC   = c(AIC(model_pred_llm),    AIC(model_pred_llm2425),  AIC(model_pred_llm25)),
  Raw_AIC   = c(AIC(model_pred_raw),    AIC(model_pred_raw2425),  AIC(model_pred_raw25)),
  Delta_AIC = c(AIC(model_pred_llm)    - AIC(model_pred_raw),
                AIC(model_pred_llm2425) - AIC(model_pred_raw2425),
                AIC(model_pred_llm25)   - AIC(model_pred_raw25))
)
pred_compare[, 2:8] <- round(pred_compare[, 2:8], 4)
print(pred_compare, row.names = FALSE)
cat("\n  Note: Delta_AIC = LLM_AIC - Raw_AIC.\n")
cat("  Negative = LLM better fit; Positive = Raw better fit.\n\n")


# =============================================================================
# 6B. ADVANCED HYPOTHESIS TESTING (STABLE FALLBACK)
# Testing H4 (Umbrella Hubs) and H6 (Radical Clusters)
# =============================================================================

cat("\n==============================================================\n")
cat("6B. HYPOTHESIS TESTING (MAIN EFFECTS + DIFFERENTIAL HOMOPHILY)\n")
cat("==============================================================\n")

# Because the full mixing matrix ('nodemix') caused infinite parameters (-Inf) 
# due to zero-tie combinations, we use 'nodefactor' and 'nodematch(diff=TRUE)'.

keep_levels <- c("advocacy", "specialist", "radical", "sectoral", "umbrella")

# Reference category = advocacy (dropped from factor terms, retained in nodematch)
ref_drop <- c("specialist", "radical", "sectoral", "umbrella")

model_compon_mix <- ergm(net_compon ~ edges + mutual +
                           nodeifactor("category", levels = ref_drop) +
                           nodeofactor("category", levels = ref_drop) +
                           nodematch("category", diff = TRUE,
                                     levels = c("advocacy","specialist","radical","sectoral")),
                         control = ergm_ctrl)

# LLM: additionally drop radical from nodeofactor (zero outgoing ties → structural -Inf)
model_llm_mix <- ergm(net_llm ~ edges + mutual +
                        nodeifactor("category", levels = ref_drop) +
                        nodeofactor("category", levels = c("specialist","sectoral","umbrella")) +
                        nodematch("category", diff = TRUE,
                                  levels = c("advocacy","specialist","sectoral")),
                      control = ergm_ctrl)
#This difference is itself a reportable finding — note it in the thesis as evidence that the LLM network structurally suppresses radical actor activity.

# Extract results 
res_compon_mix <- extract_model(model_compon_mix, "14. COMPON 2025 (Hypothesis)")
res_llm_mix    <- extract_model(model_llm_mix,    "15. LLM 2016-2025 (Hypothesis)")


# Rebuild clean before appending hypothesis models
final_results_table <- rbind(
  res_compon, res_llm, res_llm2425, res_llm25,
  res_raw, res_raw2425, res_raw25,
  res_pred_llm, res_pred_llm2425, res_pred_llm25,
  res_pred_raw, res_pred_raw2425, res_pred_raw25
)

final_results_table <- rbind(final_results_table, res_compon_mix, res_llm_mix)

# Compare model fit
mix_fit_compare <- data.frame(
  Network = c("COMPON 2025", "LLM 2016-2025"),
  Match_AIC = c(AIC(model_compon), AIC(model_llm)),
  Hypo_AIC  = c(AIC(model_compon_mix), AIC(model_llm_mix)),
  Delta_AIC = c(AIC(model_compon_mix) - AIC(model_compon), 
                AIC(model_llm_mix) - AIC(model_llm))
)
mix_fit_compare[, 2:4] <- round(mix_fit_compare[, 2:4], 2)

cat("\n--- Model Fit Comparison: Uniform vs Hypothesis Model ---\n")
print(mix_fit_compare)
cat("Note: A negative Delta_AIC means the Hypothesis model is a better fit.\n\n")

cat("\nComputing GOF and exporting PDFs for Hypothesis models...\n")
gof_compon_mix <- gof(model_compon_mix)
gof_llm_mix    <- gof(model_llm_mix)

export_ergm_pdf(model_compon_mix, gof_compon_mix, "ERGM_14_COMPON_Hypothesis.pdf",
                "COMPON 2025 Hypothesis – GOF", "Hypothesis: nodefactor + nodematch(diff=TRUE)")
export_ergm_pdf(model_llm_mix, gof_llm_mix, "ERGM_15_LLM_Hypothesis.pdf",
                "LLM 2016-2025 Hypothesis – GOF", "Hypothesis: nodefactor + nodematch(diff=TRUE)")

# =============================================================================
# 7. EXPORT CSV AND TEXT REPORT
# =============================================================================

write.csv(final_results_table, "ERGM_Statistical_Results_Clean_v2.csv", row.names = FALSE)
write.csv(fit_metrics,         "ERGM_Fit_Metrics_v2.csv",               row.names = FALSE)
write.csv(pred_compare,        "ERGM_Predictive_Comparison_v2.csv",     row.names = FALSE)

sink("ERGM_Model_Summary_Report_v2.txt")
options(width = 200, scipen = 999, max.print = 100000)

cat("====================================================\n")
cat("ERGM MODEL SUMMARY REPORT v2\n")
cat(sprintf("Generated: %s\n", Sys.time()))
cat("====================================================\n\n")

cat("SECTION 1. BASELINE ERGMs — COEFFICIENTS & P-VALUES\n")
cat("====================================================\n\n")
baseline_rows <- final_results_table[
  final_results_table$Model %in% c("01. COMPON 2025",
    "02. LLM 2016-2025","03. LLM 2024-2025","04. LLM 2025",
    "05. Raw 2016-2025","06. Raw 2024-2025","07. Raw 2025"), ]
print(baseline_rows, row.names = FALSE)

cat("\n\nSECTION 2. PREDICTIVE ERGMs — COEFFICIENTS & P-VALUES\n")
cat("====================================================\n\n")
pred_rows <- final_results_table[
  final_results_table$Model %in% c(
    "08. Pred LLM 2016-25→COMPON", "09. Pred LLM 2024-25→COMPON", "10. Pred LLM 2025→COMPON",
    "11. Pred Raw 2016-25→COMPON", "12. Pred Raw 2024-25→COMPON", "13. Pred Raw 2025→COMPON"),
]
print(pred_rows, row.names = FALSE)

cat("\n\nSECTION 3. MODEL FIT METRICS (AIC / BIC / LOG-LIKELIHOOD)\n")
cat("====================================================\n\n")
print(fit_metrics, row.names = FALSE)

cat("\n\nSECTION 4. PREDICTIVE MODEL COMPARISON (LLM vs Raw → COMPON)\n")
cat("====================================================\n\n")
print(pred_compare, row.names = FALSE)
cat("\n  Note: Delta_AIC = LLM_AIC - Raw_AIC.\n")
cat("  Negative = LLM model better fit; Positive = Raw model better fit.\n")
cat("  This is the core LLM validation effect metric at the ERGM level.\n")

cat("\n\nSECTION 5. NETWORK STRUCTURE SUMMARY (isolates)\n")
cat("====================================================\n\n")
cat("COMPON 2025 Isolates:     ", summary(net_compon  ~ isolates), "\n")
cat("LLM 2016-2025 Isolates:   ", summary(net_llm     ~ isolates), "\n")
cat("LLM 2024-2025 Isolates:   ", summary(net_llm2425 ~ isolates), "\n")
cat("LLM 2025 Isolates:        ", summary(net_llm25   ~ isolates), "\n")
cat("Raw 2016-2025 Isolates:   ", summary(net_raw     ~ isolates), "\n")
cat("Raw 2024-2025 Isolates:   ", summary(net_raw2425 ~ isolates), "\n")
cat("Raw 2025 Isolates:        ", summary(net_raw25   ~ isolates), "\n")

cat("\n\nSECTION 6. HYPOTHESIS TESTING (NODEFACTOR + NODEMATCH)\n")
cat("====================================================\n\n")
cat("These coefficients test H4 (structural behaviors) via main effects and differential homophily.\n\n")

mix_rows <- final_results_table[final_results_table$Model %in% c("14. COMPON 2025 (Hypothesis)", "15. LLM 2016-2025 (Hypothesis)"), ]
print(mix_rows, row.names = FALSE)

cat("\n\nModel Fit Improvement: Unified Hypothesis vs. Baseline Uniform Homophily\n")
cat("====================================================\n")
cat("Comparing the basic homophily model against the complex H4 structural model.\n\n")
print(mix_fit_compare, row.names = FALSE)

sink()

cat("\nSuccess! Output files created:\n")
cat("  ERGM_Statistical_Results_Clean_v2.csv\n")
cat("  ERGM_Fit_Metrics_v2.csv\n")
cat("  ERGM_Predictive_Comparison_v2.csv\n")
cat("  ERGM_Model_Summary_Report_v2.txt\n")
cat("  15 diagnostic PDFs (ERGM_1 through ERGM_15)\n")
cat("\n=== ERGM script v2 complete ===\n")

