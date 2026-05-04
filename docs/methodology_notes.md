# Methodology Notes

This repository keeps the final replication path and archives earlier exploratory attempts.

The final public-data pipeline is:

1. scrape public NGO websites,
2. extract readable text,
3. reduce by keywords and dates,
4. filter by NGO/proximity evidence,
5. clean boilerplate iteratively,
6. build yearly source-target candidate pairs,
7. classify candidate pairs with multiple LLM raters,
8. adjudicate split decisions,
9. build directed network matrices, and
10. compare the reconstructed networks against COMPON with R network models.

Real COMPON data is not distributed. R scripts use a synthetic COMPON-format matrix unless `COMPON_MATRIX_PATH` points to a local restricted matrix.
