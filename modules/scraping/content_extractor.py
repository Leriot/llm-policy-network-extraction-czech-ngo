"""
Content Extractor
Extracts links, metadata, and structured content from HTML pages
"""

import logging
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import re
from datetime import datetime


logger = logging.getLogger(__name__)


class ContentExtractor:
    """
    Extracts structured content from HTML pages.
    Focuses on links, metadata, and semantic content.
    """

    def __init__(self, base_url: str, preload_gliner: bool = False, extract_dates: bool = False):
        """
        Initialize content extractor.

        Args:
            base_url: Base URL for resolving relative links
            preload_gliner: If True, pre-load GLiNER model at initialization
            extract_dates: If True, extract dates during scraping (Module 1). If False, skip date extraction (dates handled in Module 2)
        """
        self.base_url = base_url
        self.base_domain = self._extract_domain(base_url)
        self._gliner_model = None
        self.extract_dates = extract_dates  # Control whether to extract dates

        # Pre-load GLiNER model if requested (for faster date extraction during scraping)
        if preload_gliner:
            self.preload_gliner_model()

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.lower()

    def extract_links(self, html: str, source_url: str) -> List[Dict]:
        """
        Extract all links from HTML with metadata.

        Args:
            html: HTML content
            source_url: URL of the page (for resolving relative links)

        Returns:
            List of link dictionaries with url, text, and type
        """
        links = []
        seen_urls = set()

        try:
            soup = BeautifulSoup(html, 'html.parser')

            for anchor in soup.find_all('a', href=True):
                href = anchor.get('href', '').strip()

                if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                    continue

                # Resolve relative URLs
                absolute_url = urljoin(source_url, href)

                # Skip duplicates in this page
                if absolute_url in seen_urls:
                    continue
                seen_urls.add(absolute_url)

                # Determine if internal or external
                link_domain = self._extract_domain(absolute_url)
                is_internal = (link_domain == self.base_domain or
                              link_domain.endswith(f'.{self.base_domain}'))

                # Extract anchor text
                anchor_text = anchor.get_text(strip=True)

                # Extract title attribute if available
                title = anchor.get('title', '')

                links.append({
                    'url': absolute_url,
                    'text': anchor_text,
                    'title': title,
                    'type': 'internal' if is_internal else 'external'
                })

            logger.debug(f"Extracted {len(links)} links from {source_url}")

        except Exception as e:
            logger.error(f"Error extracting links from {source_url}: {e}")

        return links

    def extract_metadata(self, html: str, url: str) -> Dict:
        """
        Extract metadata from HTML page.

        Args:
            html: HTML content
            url: URL of the page

        Returns:
            Dictionary with metadata
        """
        metadata = {
            'url': url,
            'title': None,
            'description': None,
            'keywords': None,
            'author': None,
            'published_date': None,
            'modified_date': None,
            'language': None,
            'og_type': None,
            'og_title': None,
            'og_description': None,
        }

        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Title
            title_tag = soup.find('title')
            if title_tag:
                metadata['title'] = title_tag.get_text(strip=True)

            # Meta tags
            for meta in soup.find_all('meta'):
                name = meta.get('name', '').lower()
                property_attr = meta.get('property', '').lower()
                content = meta.get('content', '').strip()

                if not content:
                    continue

                # Standard meta tags
                if name == 'description':
                    metadata['description'] = content
                elif name == 'keywords':
                    metadata['keywords'] = content
                elif name == 'author':
                    metadata['author'] = content
                elif name in ('date', 'pubdate', 'publishdate', 'publication_date'):
                    metadata['published_date'] = self._parse_date(content)
                elif name in ('last-modified', 'modified', 'updated'):
                    metadata['modified_date'] = self._parse_date(content)
                elif name == 'language':
                    metadata['language'] = content

                # Open Graph tags
                elif property_attr == 'og:type':
                    metadata['og_type'] = content
                elif property_attr == 'og:title':
                    metadata['og_title'] = content
                elif property_attr == 'og:description':
                    metadata['og_description'] = content

            # DATE EXTRACTION - Only if enabled (disabled for Module 1, enabled for Module 2)
            if self.extract_dates:
                # 1. URL Date (Layer 1 - High Precision)
                if not metadata['published_date']:
                    metadata['published_date'] = self._extract_date_from_url(url)
                    if metadata['published_date']:
                        logger.debug(f"Date found in URL: {metadata['published_date']}")

                # 2. JSON-LD Date (Layer 2 - High Precision)
                if not metadata['published_date']:
                    metadata['published_date'] = self._extract_date_from_json_ld(soup)
                    if metadata['published_date']:
                        logger.debug(f"Date found in JSON-LD: {metadata['published_date']}")

                # 3. Meta Tags (Existing)
                if not metadata['published_date']:
                    for meta in soup.find_all('meta'):
                        name = meta.get('name', '').lower()
                        content = meta.get('content', '').strip()
                        if not content: continue

                        if name in ('date', 'pubdate', 'publishdate', 'publication_date', 'article:published_time'):
                            metadata['published_date'] = self._parse_date(content)
                            if metadata['published_date']:
                                logger.debug(f"Date found in Meta Tag ({name}): {metadata['published_date']}")
                                break

                # 4. Content Heuristics (Layer 3 - Context Aware)
                if not metadata['published_date']:
                    metadata['published_date'] = self._extract_date_from_content(soup)
                    if metadata['published_date']:
                        logger.debug(f"Date found via Content Heuristics: {metadata['published_date']}")

                # 5. GLiNER Model (Layer 4 - Fallback)
                # Use GLiNER for date extraction to enable date-based filtering during scraping
                if not metadata['published_date']:
                    # Extract text content first
                    text_content = self.extract_text_content(html)
                    if text_content:
                        metadata['published_date'] = self._extract_date_from_gliner(text_content)
                        if metadata['published_date']:
                            logger.debug(f"Date found via GLiNER: {metadata['published_date']}")

            # Language from html tag
            if not metadata['language']:
                html_tag = soup.find('html')
                if html_tag:
                    metadata['language'] = html_tag.get('lang', '')

            logger.debug(f"Extracted metadata from {url}")

        except Exception as e:
            logger.error(f"Error extracting metadata from {url}: {e}")

        return metadata

    def _parse_date(self, date_string: str) -> Optional[str]:
        """
        Parse date string to ISO format.

        Args:
            date_string: Date string to parse

        Returns:
            ISO formatted date string or None
        """
        if not date_string:
            return None
            
        # Common date formats
        formats = [
            '%Y-%m-%d',
            '%Y/%m/%d',
            '%d.%m.%Y',
            '%d/%m/%Y',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%d %H:%M:%S',
            '%B %d, %Y',  # Month DD, YYYY
        ]

        # Clean string
        date_string = date_string.strip()
        
        # Handle ISO format with timezone that python < 3.7 might struggle with or just general cleanup
        # simplistic approach for now
        if 'T' in date_string and '+' in date_string:
             # split timezone if needed or let datetime handle it
             pass

        for fmt in formats:
            try:
                dt = datetime.strptime(date_string, fmt)
                return dt.date().isoformat()
            except (ValueError, AttributeError):
                continue
        
        # Try dateutil if available (not in requirements, so stick to stdlib for now)
        return None

    def _extract_date_from_url(self, url: str) -> Optional[str]:
        """
        Layer 1: Extract date from URL.
        
        Args:
            url: Page URL
            
        Returns:
            ISO date string or None
        """
        # Patterns: /2025/01/15/, /2025/01/, /2025-01-15
        patterns = [
            r'/(\d{4})/(\d{1,2})/(\d{1,2})/',
            r'/(\d{4})/(\d{1,2})/', # Year/Month only - default to 01? No, maybe return None if day missing? 
                                    # Let's accept YYYY/MM and default to 1st for filtering purposes? 
                                    # Better to be precise. Let's stick to full dates or YYYY-MM-DD
            r'[-/](\d{4})-(\d{1,2})-(\d{1,2})[-/]',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                groups = match.groups()
                if len(groups) == 3:
                    try:
                        return f"{groups[0]}-{int(groups[1]):02d}-{int(groups[2]):02d}"
                    except ValueError:
                        continue
        return None

    def _extract_date_from_json_ld(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Layer 2: Extract date from JSON-LD structured data.
        
        Args:
            soup: BeautifulSoup object
            
        Returns:
            ISO date string or None
        """
        import json
        
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if not isinstance(data, dict):
                    continue
                    
                # Check for datePublished or dateModified
                # Common schemas: NewsArticle, BlogPosting, Article
                if 'datePublished' in data:
                    return self._parse_date(data['datePublished'])
                if 'dateModified' in data:
                    return self._parse_date(data['dateModified'])
                    
                # Handle graph (list of objects)
                if '@graph' in data:
                    for item in data['@graph']:
                        if 'datePublished' in item:
                            return self._parse_date(item['datePublished'])
                            
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
                
        return None

    def _extract_date_from_content(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Layer 3: Extract publication date from common HTML patterns with context.
        Prioritizes dates near keywords like "Published", "Vydáno", etc.

        Args:
            soup: BeautifulSoup object

        Returns:
            ISO date string or None
        """
        # Context markers (Czech and English)
        # We look for these words followed by a date
        context_markers = [
            r'vydáno', r'publikováno', r'aktualizováno', r'zveřejněno', r'datum',
            r'published', r'posted', r'updated', r'date'
        ]
        
        context_pattern = r'(' + '|'.join(context_markers) + r')[:\s]+'
        
        # Date patterns
        date_patterns = [
            # Czech: d. m. YYYY or d.m.YYYY
            r'(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})',
            # ISO: YYYY-MM-DD
            r'(\d{4})-(\d{1,2})-(\d{1,2})',
            # Slash: DD/MM/YYYY
            r'(\d{1,2})/(\d{1,2})/(\d{4})'
        ]
        
        # 1. Search for specific time/date elements first (high confidence)
        time_elements = soup.find_all(['time', 'span', 'div', 'p'], class_=re.compile(r'date|time|publish|meta', re.I))
        for elem in time_elements:
            # Check datetime attribute
            datetime_attr = elem.get('datetime')
            if datetime_attr:
                date = self._parse_date(datetime_attr)
                if date:
                    return date
            
            # Check text content with strict context
            text = elem.get_text(strip=True)
            # If the element is explicitly a "date" class, we might be less strict with context,
            # but to avoid "event dates" vs "pub dates", let's still look for patterns.
            
            for d_pat in date_patterns:
                # Check if text matches date pattern directly
                match = re.search(d_pat, text)
                if match:
                    # If it's a <time> tag or class has 'pub', trust it more
                    if elem.name == 'time' or 'pub' in str(elem.get('class', '')).lower():
                         return self._parse_date(match.group(0))
        
        # 2. Search full text for Context + Date (to distinguish from random dates)
        # We limit search to the first few paragraphs or header area to avoid picking up footer dates or unrelated dates
        # But for simplicity/robustness, let's search the text but require the context marker.
        
        text = soup.get_text(" ", strip=True)[:5000] # Limit to first 5000 chars to focus on header/intro
        
        for d_pat in date_patterns:
            # Regex: Context marker + optional chars + date
            # e.g. "Vydáno: 15. 1. 2025"
            full_pattern = context_pattern + r'.{0,20}?' + d_pat
            
            match = re.search(full_pattern, text, re.IGNORECASE)
            if match:
                # The date groups are the last ones in the match
                # We need to extract the date part. 
                # re.search returns the whole match. We can extract the date string from the date pattern part.
                
                # Let's just extract the date part from the matched string
                date_str_match = re.search(d_pat, match.group(0))
                if date_str_match:
                    return self._parse_date(date_str_match.group(0))

        return None

    def preload_gliner_model(self):
        """
        Pre-load GLiNER 2 model at initialization to avoid loading delays during scraping.
        This keeps the model in memory for the entire session.
        """
        try:
            from gliner2 import GLiNER2

            model_name = "fastino/gliner2-large-v1"

            if self._gliner_model is None:
                try:
                    logger.info(f"Pre-loading GLiNER 2 model ({model_name}) for date extraction...")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    print(f"Pre-loading GLiNER 2 model ({model_name}) for date extraction...")

                self._gliner_model = GLiNER2.from_pretrained(model_name)

                try:
                    logger.info("GLiNER 2 model loaded and ready.")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    print("GLiNER 2 model loaded and ready.")
        except ImportError:
            logger.warning("GLiNER 2 not installed. Date extraction Layer 4 will be unavailable.")
        except Exception as e:
            logger.error(f"Error pre-loading GLiNER 2 model: {e}")

    def _extract_date_from_gliner(self, text: str) -> Optional[str]:
        """
        Layer 4: Extract date using GLiNER 2 model (Fallback).

        Args:
            text: Text content to analyze

        Returns:
            ISO date string or None
        """
        try:
            # Use pre-loaded model if available, otherwise load now
            if self._gliner_model is None:
                from gliner2 import GLiNER2
                model_name = "fastino/gliner2-large-v1"

                try:
                    logger.info(f"Loading GLiNER 2 model ({model_name}) for date extraction...")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    print(f"Loading GLiNER 2 model ({model_name}) for date extraction...")

                self._gliner_model = GLiNER2.from_pretrained(model_name)

            model = self._gliner_model

            # Truncate text to fit context window (approx 2048 tokens -> ~8000 chars)
            # We focus on the beginning of the text where dates usually are
            text_chunk = text[:8000]

            # Use GLiNER2's extract_json API for structured extraction
            result = model.extract_json(
                text_chunk,
                {
                    "dates": [
                        "date::str::Publication date when article or press release was published"
                    ]
                },
                threshold=0.3
            )

            # Extract first date found
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
            logger.warning("GLiNER 2 not installed. Skipping Layer 4.")
            return None
        except Exception as e:
            logger.error(f"Error in GLiNER date extraction: {e}")
            return None

    def extract_text_content(self, html: str) -> str:
        """
        Extract main text content from HTML, removing scripts, styles, etc.
        
        Args:
            html: HTML content
            
        Returns:
            Plain text content
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Remove script and style elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                element.decompose()

            # Get text
            text = soup.get_text(separator=' ', strip=True)

            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text)

            return text

        except Exception as e:
            logger.error(f"Error extracting text content: {e}")
            return ""

    def identify_page_type(self, html: str, url: str) -> str:
        """
        Identify the type of page based on URL and content.
        
        Args:
            html: HTML content
            url: Page URL
            
        Returns:
            Page type string
        """
        url_lower = url.lower()

        # URL-based identification
        if any(pattern in url_lower for pattern in ['/publikace', '/publications', '/vyrocni-zpravy']):
            return 'publications'
        elif any(pattern in url_lower for pattern in ['/tiskove-zpravy', '/press-release', '/press']):
            return 'press_release'
        elif any(pattern in url_lower for pattern in ['/aktuality', '/news', '/clanky', '/articles']):
            return 'news'
        elif any(pattern in url_lower for pattern in ['/akce', '/events', '/udalosti']):
            return 'events'
        elif any(pattern in url_lower for pattern in ['/o-nas', '/about', '/team', '/lide', '/people']):
            return 'about'
        elif any(pattern in url_lower for pattern in ['/kontakt', '/contact']):
            return 'contact'
        elif any(pattern in url_lower for pattern in ['/kampane', '/campaigns']):
            return 'campaign'
        elif any(pattern in url_lower for pattern in ['/projekty', '/projects']):
            return 'projects'

        # Content-based identification
        try:
            soup = BeautifulSoup(html, 'html.parser')
            title = soup.find('title')
            title_text = title.get_text().lower() if title else ''

            if any(word in title_text for word in ['publikace', 'publication', 'report', 'zpráva']):
                return 'publications'
            elif any(word in title_text for word in ['tisková zpráva', 'press release']):
                return 'press_release'
            elif any(word in title_text for word in ['aktuality', 'news', 'article']):
                return 'news'

        except Exception as e:
            logger.debug(f"Error in content-based page type identification: {e}")

        return 'general'

    def extract_document_links(self, html: str, source_url: str,
                               extensions: List[str] = None) -> List[Dict]:
        """
        Extract links to documents (PDFs, DOCs, etc.).

        Args:
            html: HTML content
            source_url: URL of the page
            extensions: List of file extensions to look for

        Returns:
            List of document link dictionaries
        """
        if extensions is None:
            extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx']

        documents = []
        seen_urls = set()

        try:
            soup = BeautifulSoup(html, 'html.parser')

            for anchor in soup.find_all('a', href=True):
                href = anchor.get('href', '').strip()

                if not href:
                    continue

                # Resolve relative URLs
                absolute_url = urljoin(source_url, href)

                # Check if it's a document
                url_lower = absolute_url.lower()
                is_document = any(url_lower.endswith(ext) for ext in extensions)

                if is_document and absolute_url not in seen_urls:
                    seen_urls.add(absolute_url)

                    # Extract anchor text
                    anchor_text = anchor.get_text(strip=True)

                    # Determine document type
                    doc_type = next((ext for ext in extensions if url_lower.endswith(ext)), 'unknown')

                    documents.append({
                        'url': absolute_url,
                        'text': anchor_text,
                        'type': doc_type,
                        'source_page': source_url
                    })

            if documents:
                logger.info(f"Found {len(documents)} document links on {source_url}")

        except Exception as e:
            logger.error(f"Error extracting document links from {source_url}: {e}")

        return documents

    def extract_personnel_info(self, html: str) -> List[Dict]:
        """
        Extract personnel information from about/team pages.

        Args:
            html: HTML content

        Returns:
            List of personnel dictionaries with name, role, etc.
        """
        personnel = []

        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Look for common personnel section patterns
            # This is a simple heuristic-based approach
            potential_sections = soup.find_all(['div', 'section', 'article'],
                                              class_=re.compile(r'team|staff|people|person|member', re.I))

            for section in potential_sections:
                # Look for names (usually in headings or strong tags)
                names = section.find_all(['h2', 'h3', 'h4', 'strong', 'b'])

                for name_elem in names:
                    name = name_elem.get_text(strip=True)

                    # Skip if too short or too long
                    if len(name) < 3 or len(name) > 100:
                        continue

                    # Look for role/position (often in nearby elements)
                    role = ''
                    next_elem = name_elem.find_next(['p', 'div', 'span'])
                    if next_elem:
                        role = next_elem.get_text(strip=True)[:200]

                    personnel.append({
                        'name': name,
                        'role': role
                    })

            if personnel:
                logger.debug(f"Extracted {len(personnel)} personnel records")

        except Exception as e:
            logger.error(f"Error extracting personnel info: {e}")

        return personnel
