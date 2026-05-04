"""
Module 3: Keyword Filter

Filters pages by collaboration-relevant keywords and NGO mentions.
This is a fast, cheap filter that runs BEFORE date filtering to reduce
the dataset before expensive operations.

Input:
    - data/cleaned/{ngo}/text/*.txt
    - config/content_filter_keywords.yaml
    - config/ngo_config.csv

Output:
    - data/keyword_filtered/{ngo}/text/*.txt
    - data/keyword_filtered/{ngo}/filter_stats.json
    - data/keyword_filtered/{ngo}/excluded.jsonl

Pipeline Position:
    Module 1: Scraper
    Module 2: Content Cleaning
    → Module 3: Keyword Filter (HERE - reduces dataset by 60-70%)
    Module 4: Date Filter
    Module 5: Actor Extraction (GLiNER)
"""

from .keyword_filter import KeywordFilter

__all__ = ['KeywordFilter']
