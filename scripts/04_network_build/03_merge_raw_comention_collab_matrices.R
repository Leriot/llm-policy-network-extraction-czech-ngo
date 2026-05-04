# --- Load and Merge Collaboration + Co-mention Networks ----------------------
# Combines collaboration and co-mention adjacency matrices using logical OR
# Logic: if (collab==1 OR comention==1) then 1, else 0
# Output: 3 merged networks at different time scales

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
  stop("Could not find project root. Run from the repository root or scripts/04_network_build.")
}

project_root <- find_project_root()
input_dir <- file.path(project_root, "data", "processed", "network", "matrices")
output_dir <- file.path(project_root, "data", "processed", "network", "r_inputs")
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

read_network_matrix <- function(filename) {
  path <- file.path(input_dir, filename)
  df <- read.csv(path, header = TRUE, check.names = FALSE, row.names = 1)
  as.data.frame(lapply(df, as.integer), check.names = FALSE)
}

write_network_matrix <- function(df, filename) {
  write.csv(df, file.path(output_dir, filename), row.names = FALSE)
}

# --- Load raw CSVs -----------------------------------------------------------
# Collaboration networks
collab_2024      <- read_network_matrix("collab_2024_directed.csv")
collab_2025      <- read_network_matrix("collab_2025_directed.csv")
collab_total     <- read_network_matrix("collab_total_directed.csv")

# Co-mention networks
comention_2024      <- read_network_matrix("comention_2024_directed.csv")
comention_2025      <- read_network_matrix("comention_2025_directed.csv")
comention_total     <- read_network_matrix("comention_total_directed.csv")

# Create 2024-2025 combined matrices (if not already created)
comention_2024_2025 <- pmax(as.matrix(comention_2024), as.matrix(comention_2025))
comention_2024_2025 <- as.data.frame(comention_2024_2025)
collab_2024_2025    <- pmax(as.matrix(collab_2024), as.matrix(collab_2025))
collab_2024_2025    <- as.data.frame(collab_2024_2025)

# --- Merge 2025: Collaboration OR Co-mention --------------------------------
merged_2025 <- pmax(as.matrix(collab_2025), as.matrix(comention_2025))
rownames(merged_2025) <- rownames(collab_2025)
colnames(merged_2025) <- colnames(collab_2025)
merged_2025 <- as.data.frame(merged_2025)

write_network_matrix(merged_2025, "merged_2025_directed.csv")

# --- Merge 2024-2025: Collaboration OR Co-mention ---------------------------
merged_2024_2025 <- pmax(as.matrix(collab_2024_2025), as.matrix(comention_2024_2025))
rownames(merged_2024_2025) <- rownames(collab_2024_2025)
colnames(merged_2024_2025) <- colnames(collab_2024_2025)
merged_2024_2025 <- as.data.frame(merged_2024_2025)

write_network_matrix(merged_2024_2025, "merged_2024_and_2025_directed.csv")

# --- Merge Total (2016-2025): Collaboration OR Co-mention -------------------
merged_total <- pmax(as.matrix(collab_total), as.matrix(comention_total))
rownames(merged_total) <- rownames(collab_total)
colnames(merged_total) <- colnames(collab_total)
merged_total <- as.data.frame(merged_total)

write_network_matrix(merged_total, "merged_2016_2025_directed.csv")

# --- Summary -----------------------------------------------------------------
cat(paste0("=", strrep("=", 58), "=\n"))
cat("COLLABORATION + CO-MENTION MERGED NETWORKS\n")
cat(paste0("=", strrep("=", 58), "=\n\n"))

cat("2025 (Collaboration OR Co-mention):\n")
cat("  Collaboration connections:", sum(collab_2025, na.rm = TRUE), "\n")
cat("  Co-mention connections:   ", sum(comention_2025, na.rm = TRUE), "\n")
cat("  Merged connections:       ", sum(merged_2025, na.rm = TRUE), "\n\n")

cat("2024-2025 (Collaboration OR Co-mention):\n")
cat("  Collaboration connections:", sum(collab_2024_2025, na.rm = TRUE), "\n")
cat("  Co-mention connections:   ", sum(comention_2024_2025, na.rm = TRUE), "\n")
cat("  Merged connections:       ", sum(merged_2024_2025, na.rm = TRUE), "\n\n")

cat("2016-2025 (Collaboration OR Co-mention):\n")
cat("  Collaboration connections:", sum(collab_total, na.rm = TRUE), "\n")
cat("  Co-mention connections:   ", sum(comention_total, na.rm = TRUE), "\n")
cat("  Merged connections:       ", sum(merged_total, na.rm = TRUE), "\n\n")

cat(paste0("=", strrep("=", 58), "=\n"))
cat("✓ All three merged networks saved:\n")
cat("  - merged_2025_directed.csv\n")
cat("  - merged_2024_and_2025_directed.csv\n")
cat("  - merged_2016_2025_directed.csv\n")
cat(paste0("=", strrep("=", 58), "=\n"))

# --- Load for downstream use (format as in your pipeline) -------------------
# Uncomment and use these when loading all matrices:
#
# llm_2025            <- read.csv("collab_2025_LLM.csv",              header = TRUE, check.names = FALSE)
# compon_2025         <- read.csv("collab_2025_compon.csv",           header = TRUE, check.names = FALSE)
# llm_2024_2025       <- read.csv("merged_2024_and_2025_directed.csv", header = TRUE, check.names = FALSE)
# llm_all             <- read.csv("merged_2016_2025_directed.csv",     header = TRUE, check.names = FALSE)
