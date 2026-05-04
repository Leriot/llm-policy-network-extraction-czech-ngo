# ============================================================================
# SCRIPT: Extract Specific NGO Collaboration Sub-Matrix (CLEAN LOAD VERSION)
# ============================================================================

library(readxl)
library(tidyverse)

# ------------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------

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

input_file <- Sys.getenv(
  "COMPON_COLLABORATION_XLSX",
  file.path(project_root, "data", "external", "COMPON_RESTRICTED", "CZ2025_COLLABORATION_NET.xlsx")
)

target_ngos <- c("aes", "arn", "aut", "bel", "cal", "cde", "cit", "upe", "ver", 
                 "ext", "fct", "frb", "fff", "grp", "foe", "ccc", "lau", "nes", "grn")

output_file <- Sys.getenv(
  "COMPON_SUBSET_OUTPUT",
  file.path(project_root, "data", "external", "compon_local", "collab_2025_compon.csv")
)
dir.create(dirname(output_file), recursive = TRUE, showWarnings = FALSE)

# ------------------------------------------------------------------------------
# STEP 1: LOAD AND FIX STRUCTURE
# -----------------------------------------------------------------------------

cat("Reading the Excel file...\n")

# 1. Load the file without assuming any headers
# This avoids the '...1' confusion during the initial read
df <- read_excel(input_file, col_names = FALSE)

# 2. Promote the first row to be the Column Names
# We take the first row and use it as the names for the whole dataframe
colnames(df) <- as.character(df[1, ])

# 3. Promote the first column to be the Row Names
# We take the first column and use it as the row names
# We remove the first row from this selection so we don't include the header name itself
#row_names_vector <- as.character(df[[1]][-1])

# 4. Create the clean data matrix
# We remove the first row (the headers) and the first column (the row names)
# This should result in your 103x103 matrix
clean_df <- df %>%
  slice(-1) %>%      # Remove only the first row
  as.data.frame()

# 6. Final Cleaning: Ensure all values are numeric and names are standardized
clean_df <- as.data.frame(lapply(clean_df, function(x) as.numeric(as.character(x))))


cat(paste0("Matrix successfully reconstructed: ", nrow(clean_df), " rows x ", ncol(clean_df), " columns\n"))

# ----------------------------------------------------------------------------------
# STEP 2: SUBSETTING
# ------------------------------------------------------------------------------

cat("Subsetting for the 19 specific NGOs...\n")

target_ngos_clean <- str_trim(str_to_lower(target_ngos))

# Check which requested NGOs exist in the COLUMN names
# Force both sides to be trimmed, lowercase, and character type before comparing
existing_ngos <- intersect(str_trim(str_to_lower(target_ngos_clean)), 
                           str_trim(str_to_lower(colnames(clean_df))))

missing_ngos <- setdiff(str_trim(str_to_lower(target_ngos_clean)), 
                        str_trim(str_to_lower(colnames(clean_df))))
#if missing_ngos is empty, all that we are looking for are in the dataset, we can proceed

# 1. Find the numeric positions of the existing NGOs in the columns
target_indices <- which(colnames(clean_df) %in% existing_ngos)

# 2. Extract the sub-matrix using those numeric positions for BOTH rows and columns
# This forces it to be a 19x19 square
subset_matrix <- clean_df[target_indices, target_indices, drop = FALSE]

# 3. (Optional) If you want the row names to be the NGO names instead of numbers:
rownames(subset_matrix) <- colnames(subset_matrix)

subset_matrix_no_diagonal <- subset_matrix; diag(subset_matrix_no_diagonal) <- 0
# ----------------------------------------------------------------------------------
# STEP 3: SAVE OUTPUT
# --------------------------------------------------------------------------------a

final_output <- subset_matrix_no_diagonal

write.csv(final_output, output_file, row.names = FALSE)

cat("\n================================================\n")
cat("SUCCESS!\n")
cat("NGOs found: ", length(existing_ngos), "\n")
cat("Output saved to: ", output_file, "\n")
cat("================================================\n")


