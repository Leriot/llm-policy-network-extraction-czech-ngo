# Scripts

Numbered folders mirror the replication pipeline:

1. `01_scrape/` - collect public NGO web data.
2. `02_filter_clean/` - extract text, filter by date/keywords/NGO proximity, and clean boilerplate.
3. `03_llm_classify/` - build candidate-pair datasets and run/aggregate LLM validation.
4. `04_network_build/` - build directed edge lists/matrices and merged raw comparison matrices.
5. `05_analysis_r/` - run R network comparison, QAP/MRQAP/CUG, and ERGM analyses.
6. `06_figures_tables/` - reserved for additional figure/table export helpers.
