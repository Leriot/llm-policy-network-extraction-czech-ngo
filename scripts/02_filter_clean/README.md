# 02 Filter And Clean

Transforms `data/raw/` into retained interim steps under `data/interim/`.

The expected order is:

1. `01_extract_content.py`
2. `02_filter_by_date.py`
3. `03_split_by_year.py`
4. `date_fixups/reprocess_*.py` — per-NGO date re-parsing for the four
   NGOs whose dates the generic filter misses (CI2, Frank Bold,
   Klimatická koalice, Ekologický institut Veronica). See
   `date_fixups/README.md`.
5. `04_filter_ngo_proximity.py`
6. `05_iterative_boilerplate_cleaning.py`
