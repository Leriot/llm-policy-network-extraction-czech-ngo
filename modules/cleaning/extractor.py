"""
Content Extractor - Clean Text Extraction from HTML
====================================================

Extracts clean text from HTML using:
1. Template-based boilerplate removal (global + section-specific)
2. trafilatura extraction (primary method)
3. BeautifulSoup extraction (fallback method)

Combines multi-level template detection with powerful extraction libraries.
"""

import logging
import re
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Try to import trafilatura
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False
    logger.warning("trafilatura not installed - only BeautifulSoup extraction available")


class ContentExtractor:
    """
    Extracts clean text from HTML with multi-level boilerplate removal.
    """

    def __init__(self, config: Dict):
        """
        Initialize content extractor.

        Args:
            config: Configuration dict from cleaning_config.yaml
        """
        self.config = config

        # Extraction method preferences
        self.primary_method = config['extraction'].get('primary', 'trafilatura')
        self.fallback_method = config['extraction'].get('fallback', 'beautifulsoup')

        # Boilerplate terms
        self.junk_terms = config['boilerplate'].get('junk_terms', [])
        self.safe_terms = config['boilerplate'].get('safe_terms', [])
        self.link_density_threshold = config['boilerplate'].get('link_density_threshold', 0.6)

        # Minimum word count
        self.min_word_count = config['output'].get('min_word_count', 0)

        # Priority content terms (checked FIRST before largest block)
        self.priority_content_terms = config['boilerplate'].get('priority_content_terms', [])

        # Statistics
        self.stats = {
            'trafilatura_success': 0,
            'beautifulsoup_success': 0,
            'failed_extractions': 0,
            'total_processed': 0
        }

    def _read_html_with_encoding(self, html_path: Path) -> str:
        """
        Read HTML file with proper encoding detection.

        Detects charset from HTML meta tag or tries common encodings.
        Essential for Czech text with diacritics (ř, ž, ě, etc.)

        Args:
            html_path: Path to HTML file

        Returns:
            HTML content as string with proper encoding
        """
        # Read as bytes first
        raw_bytes = html_path.read_bytes()

        # Try to detect charset from HTML meta tag
        charset = None
        charset_match = re.search(rb'charset=["\']?([^"\' >]+)', raw_bytes[:2000], re.IGNORECASE)
        if charset_match:
            charset = charset_match.group(1).decode('ascii', errors='ignore').strip()

        # Also check for XML declaration encoding
        if not charset:
            xml_match = re.search(rb'<\?xml[^>]+encoding=["\']?([^"\' >]+)', raw_bytes[:500], re.IGNORECASE)
            if xml_match:
                charset = xml_match.group(1).decode('ascii', errors='ignore').strip()

        # List of encodings to try (in order)
        encodings_to_try = []

        if charset:
            # Normalize charset name
            charset_lower = charset.lower()
            if charset_lower in ('windows-1250', 'cp1250', 'win-1250'):
                encodings_to_try.append('windows-1250')
            elif charset_lower in ('iso-8859-2', 'latin2', 'iso_8859-2'):
                encodings_to_try.append('iso-8859-2')
            else:
                encodings_to_try.append(charset)

        # Always try these common encodings for Czech
        encodings_to_try.extend(['utf-8', 'windows-1250', 'iso-8859-2', 'cp1250'])

        # Remove duplicates while preserving order
        seen = set()
        unique_encodings = []
        for enc in encodings_to_try:
            if enc.lower() not in seen:
                seen.add(enc.lower())
                unique_encodings.append(enc)

        # Try each encoding
        for encoding in unique_encodings:
            try:
                decoded = raw_bytes.decode(encoding)
                # Verify it has reasonable content (not mojibake)
                # Check if common Czech diacritics or ASCII are present
                if any(c in decoded for c in 'aeioubcdfghjklmnpqrstvwxyz'):
                    return decoded
            except (UnicodeDecodeError, LookupError):
                continue

        # Fallback: decode with errors='replace' to avoid data loss
        logger.warning(f"Could not detect encoding for {html_path.name}, using UTF-8 with replacement")
        return raw_bytes.decode('utf-8', errors='replace')

    def _is_safe_signature(self, signature: str) -> bool:
        """
        Check if a template signature should be protected (not removed).

        Signatures matching safe_terms like 'content', 'article', 'main'
        should NOT be removed as they typically contain the main content.
        """
        sig_lower = signature.lower()
        for safe_term in self.safe_terms:
            if safe_term in sig_lower:
                return True
        return False

    def remove_template_elements(self, soup: BeautifulSoup, templates: Dict,
                                  url_path: str) -> BeautifulSoup:
        """
        Remove template elements from BeautifulSoup object.

        NOTE: Template-based removal is DISABLED because it was too aggressive
        and removed content containers. We now rely on:
        1. Heuristic cleaning (nav/footer/sidebar removal)
        2. Largest content block selection

        This is a no-op function that returns soup unchanged.
        """
        # Template removal disabled - too aggressive and removes content
        # Some boilerplate is acceptable; heuristic cleaning handles the rest
        return soup

    def apply_heuristic_cleaning(self, soup: BeautifulSoup) -> BeautifulSoup:
        """
        Apply heuristic-based cleaning (from filter_content.py approach).

        Args:
            soup: BeautifulSoup object

        Returns:
            Cleaned BeautifulSoup object
        """
        # Remove standard junk tags
        for tag in soup(['script', 'style', 'noscript', 'iframe', 'svg', 'form',
                        'button', 'input', 'select', 'textarea']):
            tag.decompose()

        # Collect elements to remove (avoid modifying during iteration)
        elements_to_remove = []

        # Remove by role attribute
        for elem in soup.find_all(True):
            try:
                if elem.get('role') in ['banner', 'navigation', 'contentinfo', 'search', 'complementary']:
                    elements_to_remove.append(elem)
                    continue

                # Check class and id for boilerplate terms
                if not hasattr(elem, 'attrs') or elem.attrs is None:
                    continue

                elem_id = elem.get('id')
                elem_class = elem.get('class')

                id_str = str(elem_id).lower() if elem_id else ''
                class_str = " ".join(elem_class).lower() if elem_class else ''

                # Skip if safe term present
                if any(safe in class_str for safe in self.safe_terms) or \
                   any(safe in id_str for safe in self.safe_terms):
                    continue

                # Mark for removal if junk term present
                if any(junk in id_str for junk in self.junk_terms) or \
                   any(junk in class_str for junk in self.junk_terms):
                    elements_to_remove.append(elem)
            except Exception:
                continue

        # Remove marked elements
        for elem in elements_to_remove:
            try:
                elem.decompose()
            except Exception:
                pass

        # Link density check - remove navigation-heavy blocks
        # BUT protect containers that contain content elements
        elements_to_remove = []
        for container in soup.find_all(['div', 'ul', 'section', 'aside']):
            try:
                text_len = len(container.get_text(strip=True))
                if text_len < 10:
                    continue

                link_len = sum(len(a.get_text(strip=True)) for a in container.find_all('a'))

                if text_len > 0:
                    density = link_len / text_len
                    if density > self.link_density_threshold:
                        # Check if this container has safe-term content inside
                        container_classes = ' '.join(container.get('class', [])).lower()
                        has_safe_content = any(safe in container_classes for safe in self.safe_terms)

                        # Also check if any child element has safe terms
                        if not has_safe_content:
                            for child in container.find_all(True):
                                child_classes = ' '.join(child.get('class', [])).lower() if child.get('class') else ''
                                if any(safe in child_classes for safe in self.safe_terms):
                                    has_safe_content = True
                                    break

                        if not has_safe_content:
                            elements_to_remove.append(container)
            except Exception:
                continue

        for elem in elements_to_remove:
            try:
                elem.decompose()
            except Exception:
                pass

        return soup

    def extract_with_trafilatura(self, html: str, config_options: Dict) -> Optional[str]:
        """
        Extract content using trafilatura library.

        Args:
            html: HTML content
            config_options: trafilatura options from config

        Returns:
            Clean text or None if extraction failed
        """
        if not TRAFILATURA_AVAILABLE:
            return None

        try:
            text = trafilatura.extract(
                html,
                no_fallback=config_options.get('no_fallback', False),
                include_comments=config_options.get('include_comments', False),
                include_tables=config_options.get('include_tables', True),
                include_links=config_options.get('include_links', False),
                deduplicate=config_options.get('deduplicate', True)
            )

            if text and len(text.strip()) > 0:
                self.stats['trafilatura_success'] += 1
                return text.strip()

            return None

        except Exception as e:
            logger.debug(f"trafilatura extraction failed: {e}")
            return None

    def extract_with_beautifulsoup(self, soup: BeautifulSoup) -> str:
        """
        Extract content using BeautifulSoup (fallback method).

        Strategy:
        1. FIRST: Look for priority content terms (single-post, article-content, etc.)
        2. THEN: Fall back to semantic tags (main, article)
        3. FINALLY: Pick largest content block from safe terms

        Args:
            soup: BeautifulSoup object (already cleaned)

        Returns:
            Clean text
        """
        try:
            # PRIORITY: Check for specific content classes first
            # These are strong indicators of actual article content
            # Collect all matches and pick the most specific (smallest reasonable one)
            priority_candidates = []
            for priority_term in self.priority_content_terms:
                for elem in soup.find_all(class_=lambda x, term=priority_term: x and term in str(x).lower()):
                    # Skip body and html tags - too generic
                    if elem.name in ['body', 'html']:
                        continue
                    text = elem.get_text(strip=True)
                    if len(text) > 100:  # Must have substantial content
                        priority_candidates.append((elem, len(text), priority_term))

            if priority_candidates:
                # Sort by text length ascending - prefer smaller, more specific elements
                priority_candidates.sort(key=lambda x: x[1])
                best_elem, text_len, term = priority_candidates[0]
                logger.debug(f"Found priority content: {term} with {text_len} chars")
                text = best_elem.get_text(strip=True)
                text = re.sub(r'\s+', ' ', text).strip()
                if text:
                    self.stats['beautifulsoup_success'] += 1
                return text

            candidates = []

            # Collect all potential content areas

            # 1. Semantic HTML5 tags
            for tag_name in ['main', 'article', 'section']:
                for elem in soup.find_all(tag_name):
                    text = elem.get_text(strip=True)
                    if len(text) > 50:  # Only consider if has substantial text
                        candidates.append((elem, len(text)))

            # 2. Elements with safe terms in class/id
            for safe_term in self.safe_terms:
                # By class
                for elem in soup.find_all(class_=lambda x: x and safe_term in str(x).lower()):
                    text = elem.get_text(strip=True)
                    if len(text) > 50:
                        candidates.append((elem, len(text)))
                # By id
                for elem in soup.find_all(id=lambda x: x and safe_term in str(x).lower()):
                    text = elem.get_text(strip=True)
                    if len(text) > 50:
                        candidates.append((elem, len(text)))

            # 3. Large div/section blocks as fallback
            for elem in soup.find_all(['div', 'section']):
                text = elem.get_text(strip=True)
                if len(text) > 200:  # Higher threshold for generic containers
                    candidates.append((elem, len(text)))

            # Pick the candidate with the most text
            if candidates:
                # Sort by text length, pick largest
                candidates.sort(key=lambda x: x[1], reverse=True)
                main_content = candidates[0][0]
                logger.debug(f"Selected content block with {candidates[0][1]} chars")
            else:
                main_content = soup

            # Extract text
            text = main_content.get_text(separator=' ', strip=True)

            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text).strip()

            if text:
                self.stats['beautifulsoup_success'] += 1

            return text

        except Exception as e:
            logger.error(f"BeautifulSoup extraction failed: {e}")
            return ""

    def extract_content(self, html_path: Path, url: str,
                       templates: Optional[Dict] = None) -> Dict[str, any]:
        """
        Extract clean text from HTML file.

        Full pipeline:
        1. Parse HTML with BeautifulSoup
        2. Remove template elements (global + section-specific)
        3. Apply heuristic cleaning (link density, boilerplate)
        4. Try trafilatura extraction (primary)
        5. Fallback to BeautifulSoup extraction if needed
        6. Validate output

        Args:
            html_path: Path to HTML file
            url: Original URL (for section template matching)
            templates: Template signatures (optional)

        Returns:
            Dict with extracted content and metadata
        """
        self.stats['total_processed'] += 1

        try:
            # Read HTML with proper encoding detection
            html_content = self._read_html_with_encoding(html_path)

            # Parse with BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')

            # Extract URL path for section template matching
            parsed_url = urlparse(url)
            url_path = parsed_url.path.strip('/')
            if url_path:
                url_path = '/' + '/'.join(url_path.split('/')[:1]) + '/'  # First path segment
            else:
                url_path = '/'

            # Step 1: Remove template elements
            if templates:
                soup = self.remove_template_elements(soup, templates, url_path)

            # Step 2: Apply heuristic cleaning
            soup = self.apply_heuristic_cleaning(soup)

            # Step 3: Try primary extraction method (trafilatura)
            clean_text = None
            extraction_method = None

            if self.primary_method == 'trafilatura' and TRAFILATURA_AVAILABLE:
                # Convert cleaned soup back to HTML for trafilatura
                cleaned_html = str(soup)
                trafilatura_options = self.config['extraction'].get('trafilatura_options', {})
                clean_text = self.extract_with_trafilatura(cleaned_html, trafilatura_options)

                if clean_text:
                    extraction_method = 'trafilatura'

            # Step 4: Fallback to BeautifulSoup if needed
            if not clean_text:
                clean_text = self.extract_with_beautifulsoup(soup)
                extraction_method = 'beautifulsoup'

            # Step 5: Validate output
            if not clean_text or len(clean_text.strip()) < self.min_word_count:
                self.stats['failed_extractions'] += 1
                logger.warning(f"Extraction failed or too short for {html_path.name}")

                return {
                    'file': html_path.name,
                    'url': url,
                    'text': clean_text or "",
                    'word_count': 0,
                    'extraction_method': extraction_method,
                    'success': False
                }

            # Success
            word_count = len(clean_text.split())

            return {
                'file': html_path.name,
                'url': url,
                'text': clean_text,
                'word_count': word_count,
                'extraction_method': extraction_method,
                'success': True
            }

        except Exception as e:
            logger.error(f"Error extracting content from {html_path.name}: {e}")
            self.stats['failed_extractions'] += 1

            return {
                'file': html_path.name,
                'url': url,
                'text': "",
                'word_count': 0,
                'extraction_method': None,
                'success': False,
                'error': str(e)
            }

    def get_stats(self) -> Dict:
        """Get extraction statistics."""
        return self.stats
