"""
Date Filter
Extracts publication dates from HTML and filters content by date range
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from bs4 import BeautifulSoup
import json

logger = logging.getLogger(__name__)


class DateFilter:
    """
    Filters scraped HTML pages by publication date.
    Uses 4-layer fallback for date extraction.
    """

    def __init__(self, start_date: str = "2025-01-01", end_date: str = "2025-12-31",
                 use_gliner: bool = False):
        """
        Initialize date filter.

        Args:
            start_date: Start of date range (ISO format YYYY-MM-DD)
            end_date: End of date range (ISO format YYYY-MM-DD)
            use_gliner: Whether to use GLiNER for date extraction (Layer 4)
        """
        self.start_date = start_date
        self.end_date = end_date
        self.use_gliner = use_gliner
        self._gliner_model = None

        logger.info(f"Date filter initialized: {start_date} to {end_date}")

    def filter_scraped_data(self, scrape_dir: Path, output_dir: Path) -> Dict:
        """
        Filter scraped HTML files by date range.

        Args:
            scrape_dir: Directory containing scraped data (pages/, links.json, etc.)
            output_dir: Directory to save filtered results

        Returns:
            Dictionary with filtering statistics
        """
        scrape_dir = Path(scrape_dir)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        pages_dir = scrape_dir / "pages"
        if not pages_dir.exists():
            raise ValueError(f"Pages directory not found: {pages_dir}")

        # Statistics
        stats = {
            'total_pages': 0,
            'pages_with_dates': 0,
            'pages_in_range': 0,
            'pages_out_of_range': 0,
            'pages_no_date': 0,
            'pages_with_2025_text': 0,
            'date_sources': {}
        }

        # Process all HTML files
        html_files = list(pages_dir.glob("*.html"))
        stats['total_pages'] = len(html_files)

        logger.info(f"Processing {len(html_files)} HTML files from {scrape_dir}")

        filtered_pages = []
        filtered_links = []

        for html_file in html_files:
            # Read HTML
            with open(html_file, 'r', encoding='utf-8', errors='replace') as f:
                html = f.read()

            # Extract date
            result = self.extract_date(html, str(html_file))
            pub_date = result['date']
            source = result['source']

            # Check if in range
            in_range = False
            if pub_date:
                stats['pages_with_dates'] += 1
                stats['date_sources'][source] = stats['date_sources'].get(source, 0) + 1

                # Check date range
                if self._is_in_date_range(pub_date):
                    stats['pages_in_range'] += 1
                    in_range = True
                else:
                    stats['pages_out_of_range'] += 1
            else:
                stats['pages_no_date'] += 1
                # Check if contains target year in text
                if '2025' in html:
                    stats['pages_with_2025_text'] += 1
                    in_range = True  # Keep pages mentioning 2025

            # Save if in range
            if in_range:
                filtered_pages.append({
                    'file': html_file.name,
                    'date': pub_date,
                    'source': source
                })

                # Copy HTML file
                output_pages_dir = output_dir / "pages"
                output_pages_dir.mkdir(exist_ok=True)

                import shutil
                shutil.copy(html_file, output_pages_dir / html_file.name)

        # Save metadata
        metadata = {
            'filter_date_range': {
                'start': self.start_date,
                'end': self.end_date
            },
            'statistics': stats,
            'filtered_pages': filtered_pages
        }

        metadata_file = output_dir / "filter_metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        logger.info(f"Filtering complete: {stats['pages_in_range']}/{stats['total_pages']} pages in range")

        return stats

    def extract_date(self, html: str, url: str) -> Dict:
        """
        Extract publication date using 4-layer fallback.

        Args:
            html: HTML content
            url: Page URL or identifier

        Returns:
            Dict with 'date', 'source', and 'raw_value'
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Layer 1: Schema.org JSON-LD
        date, raw = self._extract_schema_org_date(soup)
        if date:
            return {'date': date, 'source': 'Schema.org JSON-LD', 'raw_value': raw}

        # Layer 2: OpenGraph / Twitter Cards
        date, raw = self._extract_opengraph_date(soup)
        if date:
            return {'date': date, 'source': 'OpenGraph metadata', 'raw_value': raw}

        # Layer 3: Meta tags
        date, raw = self._extract_meta_date(soup)
        if date:
            return {'date': date, 'source': 'Meta tags', 'raw_value': raw}

        # Layer 4: Content heuristics + visible text
        date, raw = self._extract_date_from_content(soup)
        if date:
            return {'date': date, 'source': 'Content/visible text', 'raw_value': raw}

        # Layer 5: GLiNER (ML model - optional, heavy)
        if self.use_gliner:
            text = soup.get_text(separator=' ', strip=True)
            date = self._extract_date_from_gliner(text)
            if date:
                return {'date': date, 'source': 'GLiNER ML model', 'raw_value': date}

        return {'date': None, 'source': 'Not found', 'raw_value': None}

    def _is_in_date_range(self, date_str: str) -> bool:
        """Check if date is within configured range."""
        try:
            date = datetime.fromisoformat(date_str[:10])  # Take YYYY-MM-DD part
            start = datetime.fromisoformat(self.start_date)
            end = datetime.fromisoformat(self.end_date)
            return start <= date <= end
        except (ValueError, TypeError):
            return False

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse various date formats to ISO format (YYYY-MM-DD)."""
        if not date_str:
            return None

        date_str = str(date_str).strip()

        # Try ISO format first
        iso_pattern = r'(\d{4})-(\d{1,2})-(\d{1,2})'
        match = re.search(iso_pattern, date_str)
        if match:
            year, month, day = match.groups()
            try:
                date = datetime(int(year), int(month), int(day))
                return date.strftime('%Y-%m-%d')
            except ValueError:
                pass

        # Try Czech format: d.m.YYYY or d. m. YYYY
        czech_pattern = r'(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})'
        match = re.search(czech_pattern, date_str)
        if match:
            day, month, year = match.groups()
            try:
                date = datetime(int(year), int(month), int(day))
                return date.strftime('%Y-%m-%d')
            except ValueError:
                pass

        # Try Czech month names: "28 srpna, 2019" or "11 července, 2025"
        czech_months = {
            'ledna': 1, 'února': 2, 'března': 3, 'dubna': 4,
            'května': 5, 'června': 6, 'července': 7, 'srpna': 8,
            'září': 9, 'října': 10, 'listopadu': 11, 'prosince': 12
        }
        # Pattern: day month_name, year
        czech_name_pattern = r'(\d{1,2})\s+(' + '|'.join(czech_months.keys()) + r'),?\s+(\d{4})'
        match = re.search(czech_name_pattern, date_str, re.IGNORECASE)
        if match:
            day, month_name, year = match.groups()
            month = czech_months[month_name.lower()]
            try:
                date = datetime(int(year), month, int(day))
                return date.strftime('%Y-%m-%d')
            except ValueError:
                pass

        # Try slash format: DD/MM/YYYY
        slash_pattern = r'(\d{1,2})/(\d{1,2})/(\d{4})'
        match = re.search(slash_pattern, date_str)
        if match:
            day, month, year = match.groups()
            try:
                date = datetime(int(year), int(month), int(day))
                return date.strftime('%Y-%m-%d')
            except ValueError:
                pass

        return None

    def _extract_schema_org_date(self, soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
        """Layer 1: Extract date from Schema.org JSON-LD."""
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)

                # Handle single object or array
                if isinstance(data, list):
                    items = data
                else:
                    items = [data]

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    # Check various Schema.org date properties
                    for key in ['datePublished', 'dateCreated', 'dateModified', 'publishDate']:
                        if key in item:
                            raw_value = item[key]
                            date = self._parse_date(raw_value)
                            if date:
                                return date, raw_value
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue

        return None, None

    def _extract_opengraph_date(self, soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
        """Layer 2: Extract date from OpenGraph or Twitter Card meta tags.

        FIX: Prefer PUBLISHED time over MODIFIED/UPDATED time.
        Using modified_time as the publication date causes false positives when
        sites refresh old articles (e.g. a 2019 article updated in 2025 appears as 2025).
        Only fall back to modified_time if no published_time is found.
        """
        # Priority 1: Published date properties (most reliable)
        published_props = [
            'article:published_time',
            'og:published_time',
            'og:article:published_time',
            'twitter:published_time',
        ]
        for prop in published_props:
            tag = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
            if tag and tag.get('content'):
                raw_value = tag['content']
                date = self._parse_date(raw_value)
                if date:
                    return date, raw_value

        # Priority 2: Modified/updated date (fallback only — may not equal publication date)
        modified_props = [
            'article:modified_time',
            'og:updated_time',
        ]
        for prop in modified_props:
            tag = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
            if tag and tag.get('content'):
                raw_value = tag['content']
                date = self._parse_date(raw_value)
                if date:
                    return date, raw_value

        return None, None

    def _extract_meta_date(self, soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
        """Layer 3: Extract date from various meta tags."""
        meta_names = [
            'DC.date',
            'dcterms.created',
            'dcterms.modified',
            'date',
            'pubdate',
            'publishdate',
            'publication_date',
            'article.published',
            'article:published_time'
        ]

        for name in meta_names:
            tag = soup.find('meta', attrs={'name': name}) or soup.find('meta', attrs={'property': name})
            if tag and tag.get('content'):
                raw_value = tag['content']
                date = self._parse_date(raw_value)
                if date:
                    return date, raw_value

        return None, None

    def _get_single_article_soup(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """
        If the page has exactly one <article> element, return it.
        If zero or multiple <article> elements, return None.

        This distinguishes single-article pages (have a publication date) from
        listing pages (multiple articles with different dates, or no article tag).
        """
        articles = soup.find_all('article')
        if len(articles) == 1:
            return articles[0]
        return None

    def _extract_date_from_content(self, soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
        """Layer 4: Extract date from visible content with context.

        FIX (false-positive reduction):
        - For pages with exactly one <article> element (single-post pages), search
          only within that article. This avoids picking up dates from sidebar news
          listings on non-article pages (e.g. Frank Bold homepage listing items
          as 2025-12-17 for every page).
        - For pages with no <article> or multiple <article> elements, fall back to
          full-page search but apply priority classes first.
        """
        context_markers = [
            r'vydáno', r'publikováno', r'aktualizováno', r'zveřejněno', r'datum',
            r'published', r'posted', r'updated', r'date'
        ]

        date_patterns = [
            r'(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})',  # Czech: 20.11.2017
            r'(\d{4})-(\d{1,2})-(\d{1,2})',           # ISO:   2017-11-20
            r'(\d{1,2})/(\d{1,2})/(\d{4})'            # Slash: 20/11/2017
        ]

        # Tier 1: WordPress/standard date classes — reliable regardless of article structure
        priority_classes = [
            'single-post-time', 'entry-date', 'published', 'post-date', 'article-date',
            'post-timestamp', 'article-timestamp', 'published-date', 'date-published',
            # Drupal CMS date classes
            'date-display-single', 'date-display-start', 'field-name-field-datum',
            'field-type-datetime',
        ]

        # --- Determine search scope ---
        # If exactly one <article> element exists, the page is a single-post page.
        # Search for dates INSIDE that article only.
        # If zero or multiple <article> elements, the page is a listing or template —
        # use full-page priority-class search but avoid generic <time> fallback.
        single_article = self._get_single_article_soup(soup)
        search_scope = single_article if single_article is not None else soup
        is_single_article_page = single_article is not None

        # PRIORITY 1: <time> with article-specific priority classes in scope
        for cls in priority_classes:
            for elem in search_scope.find_all('time'):
                elem_classes = elem.get('class', [])
                if any(cls.lower() in (c.lower() if c else '') for c in elem_classes):
                    datetime_attr = elem.get('datetime')
                    if datetime_attr:
                        date = self._parse_date(datetime_attr)
                        if date:
                            return date, datetime_attr
                    text = elem.get_text(strip=True)
                    date = self._parse_date(text)
                    if date:
                        return date, text

        # PRIORITY 2: All <time> elements within scope
        # ONLY for single-article pages: <time> elements inside the <article> are safe.
        # For non-article pages (listings, static pages): skip generic <time> elements.
        # Rationale: Frank Bold's static pages (Partners, Donors, etc.) each have ONE
        # <time> element that is the latest newsletter sidebar item — not the page's
        # own publication date. We cannot reliably trust any <time> element on a
        # non-article page regardless of how many there are.
        time_elements = search_scope.find_all('time')
        if is_single_article_page:
            for elem in time_elements:
                datetime_attr = elem.get('datetime')
                if datetime_attr:
                    date = self._parse_date(datetime_attr)
                    if date:
                        return date, datetime_attr
                text = elem.get_text(strip=True)
                for d_pat in date_patterns:
                    match = re.search(d_pat, text)
                    if match:
                        date = self._parse_date(match.group(0))
                        if date:
                            return date, match.group(0)

        # PRIORITY 3a: Strict CMS-specific date classes (safe for ALL pages)
        # These are highly specific date class names from real CMS systems (Drupal, etc.)
        # They are specific enough not to appear on irrelevant elements.
        strict_date_class_pattern = re.compile(
            r'\b(date-display-single|date-display-start|date-display-range'
            r'|entry-date|post-date|post-timestamp|article-date|published-date'
            r'|date-published|article-timestamp|field-name-field-datum)\b',
            re.I
        )
        strict_date_elements = soup.find_all(True, class_=strict_date_class_pattern)
        for elem in strict_date_elements:
            text = elem.get_text(strip=True)
            for d_pat in date_patterns:
                match = re.search(d_pat, text)
                if match:
                    date = self._parse_date(match.group(0))
                    if date:
                        return date, match.group(0)

        # PRIORITY 3b: Broader date-related classes (only for single-article pages)
        # For listing/template pages (no single <article>), skip broad class-based search
        # because classes like "meta" appear on news listing items and give false dates.
        if is_single_article_page:
            date_elements = search_scope.find_all(
                ['span', 'div', 'p'], class_=re.compile(r'date|time|publish|meta', re.I)
            )
            for elem in date_elements:
                text = elem.get_text(strip=True)
                for d_pat in date_patterns:
                    match = re.search(d_pat, text)
                    if match:
                        date = self._parse_date(match.group(0))
                        if date:
                            return date, match.group(0)

        # PRIORITY 4: Context-marker search in scope text
        # This applies to ALL pages: only assigns a date when the year appears directly
        # next to explicit publication words (vydáno, published, posted, etc.).
        text = search_scope.get_text()
        for ctx_marker in context_markers:
            pattern = ctx_marker + r'[:\s]+(' + '|'.join(date_patterns) + r')'
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str_match = re.search('|'.join(date_patterns), match.group(0))
                if date_str_match:
                    date = self._parse_date(date_str_match.group(0))
                    if date:
                        return date, date_str_match.group(0)

        return None, None

    def _extract_date_from_gliner(self, text: str) -> Optional[str]:
        """Layer 5: Extract date using GLiNER ML model (fallback)."""
        try:
            from gliner2 import GLiNER2

            # Load model once
            if self._gliner_model is None:
                model_name = "fastino/gliner2-large-v1"
                logger.info(f"Loading GLiNER 2 model ({model_name}) for date extraction...")
                self._gliner_model = GLiNER2.from_pretrained(model_name)

            model = self._gliner_model

            # Truncate text
            text_chunk = text[:8000]

            # Extract dates
            result = model.extract_json(
                text_chunk,
                {
                    "dates": [
                        "date::str::Publication date when article or press release was published"
                    ]
                },
                threshold=0.3
            )

            # Parse result
            if result and 'dates' in result and len(result['dates']) > 0:
                date_entry = result['dates'][0]
                if isinstance(date_entry, dict) and 'date' in date_entry:
                    date_str = date_entry['date']
                elif isinstance(date_entry, str):
                    date_str = date_entry
                else:
                    return None

                return self._parse_date(date_str)

            return None

        except ImportError:
            logger.warning("GLiNER 2 not installed. Skipping Layer 5.")
            return None
        except Exception as e:
            logger.debug(f"Error in GLiNER date extraction: {e}")
            return None

    def preload_gliner_model(self):
        """Pre-load GLiNER model to speed up batch processing."""
        if self.use_gliner and self._gliner_model is None:
            try:
                from gliner2 import GLiNER2
                model_name = "fastino/gliner2-large-v1"
                logger.info(f"Pre-loading GLiNER 2 model ({model_name})...")
                self._gliner_model = GLiNER2.from_pretrained(model_name)
                logger.info("GLiNER 2 model loaded and ready.")
            except ImportError:
                logger.warning("GLiNER 2 not installed.")
            except Exception as e:
                logger.error(f"Error pre-loading GLiNER: {e}")
