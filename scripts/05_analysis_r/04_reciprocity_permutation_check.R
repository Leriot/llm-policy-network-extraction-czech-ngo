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
output_dir <- file.path(project_root, "outputs", "tables")
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

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

library(sna)

# --- helper: CSV to adjacency matrix -----------------------------------------
csv_to_mat <- function(df) {
  m <- as.matrix(df)
  mode(m) <- "numeric"
  m[is.na(m)] <- 0
  m
}

# --- load matrices ------------------------------------------------------------
mat_compon       <- csv_to_mat(compon_2025)
mat_llm_2025     <- csv_to_mat(llm_2025)
mat_llm_2024_25  <- csv_to_mat(llm_2024_2025)
mat_llm_all      <- csv_to_mat(llm_all)
mat_raw_2025     <- csv_to_mat(raw_2025)
mat_raw_2024_25  <- csv_to_mat(raw_2024_2025)
mat_raw_all      <- csv_to_mat(raw_all)

networks <- list(
  llm_2025     = mat_llm_2025,
  llm_2024_25  = mat_llm_2024_25,
  llm_all      = mat_llm_all,
  raw_2025     = mat_raw_2025,
  raw_2024_25  = mat_raw_2024_25,
  raw_all      = mat_raw_all
)

# --- permutation test function ------------------------------------------------
perm_reciprocity_test <- function(mat_a, mat_b, n_perm = 5000, label_a = "COMPON", label_b = "network") {
  r_a   <- grecip(mat_a, measure = "dyadic.nonnull")
  r_b   <- grecip(mat_b, measure = "dyadic.nonnull")
  obs   <- r_b - r_a
  
  perm_diffs <- replicate(n_perm, {
    grecip(rmperm(mat_b), measure = "dyadic.nonnull") -
      grecip(rmperm(mat_a), measure = "dyadic.nonnull")
  })
  
  p_two  <- mean(abs(perm_diffs) >= abs(obs))
  p_pos  <- mean(perm_diffs >= obs)   # one-tailed: b > a
  p_neg  <- mean(perm_diffs <= obs)   # one-tailed: b < a
  
  list(
    label_a    = label_a,
    label_b    = label_b,
    recip_a    = round(r_a, 4),
    recip_b    = round(r_b, 4),
    obs_diff   = round(obs, 4),
    p_twotail  = round(p_two, 4),
    p_onetail  = round(min(p_pos, p_neg), 4),
    n_perm     = n_perm
  )
}

# --- run all comparisons against COMPON --------------------------------------
set.seed(42)
results <- lapply(names(networks), function(nm) {
  perm_reciprocity_test(mat_compon, networks[[nm]],
                        label_a = "COMPON_2025", label_b = nm)
})

# --- tidy results table -------------------------------------------------------
results_df <- do.call(rbind, lapply(results, as.data.frame))
print(results_df)

# optional: write to CSV
write.csv(results_df, file.path(output_dir, "reciprocity_permtest_results.csv"), row.names = FALSE)

library(sna)

cug_recip <- function(mat, n_perm = 5000) {
  obs <- grecip(mat, measure = "dyadic.nonnull")
  den <- gden(mat)
  null <- replicate(n_perm, 
                    grecip(rgraph(nrow(mat), tprob = den), measure = "dyadic.nonnull"))
  p <- mean(null >= obs)
  list(observed = round(obs, 4), density = round(den, 4), p_vs_random = round(p, 4))
}

set.seed(42)
all_nets <- c(list(COMPON_2025 = mat_compon), networks)
recip_results <- lapply(all_nets, cug_recip)
recip_df <- do.call(rbind, lapply(recip_results, as.data.frame))
print(recip_df)
