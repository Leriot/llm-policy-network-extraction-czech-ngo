"""
Storage System
Handles saving scraped data to disk in organized structure
"""

import logging
import os
import json
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse, quote
import re


logger = logging.getLogger(__name__)


class URLDatabase:
    """
    SQLite database for tracking visited URLs across scraping sessions.
    Enables fast resume by skipping already-visited URLs.
    """

    def __init__(self, db_path: str = "data/scraping_sessions.db"):
        """
        Initialize URL database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Thread-safe connection for parallel scraping
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30)
        self._create_tables()
        logger.info(f"URL database initialized at {self.db_path}")

    def _create_tables(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()

        # Table for visited URLs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS visited_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                ngo_name TEXT NOT NULL,
                session_id TEXT NOT NULL,
                visited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                content_hash TEXT,
                file_path TEXT,
                status TEXT DEFAULT 'success'
            )
        """)

        # Index for fast URL lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_url ON visited_urls(url)
        """)

        # Index for NGO-specific queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ngo ON visited_urls(ngo_name)
        """)

        self.conn.commit()

    def is_visited(self, url: str) -> bool:
        """
        Check if URL has been visited before.

        Args:
            url: URL to check

        Returns:
            True if URL was visited, False otherwise
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM visited_urls WHERE url = ?", (url,))
        return cursor.fetchone() is not None

    def mark_visited(self, url: str, ngo_name: str, session_id: str,
                     content_hash: str = None, file_path: str = None,
                     status: str = 'success'):
        """
        Mark URL as visited.

        Args:
            url: URL that was visited
            ngo_name: Name of NGO being scraped
            session_id: Current session identifier
            content_hash: Hash of page content (for deduplication)
            file_path: Path where content was saved
            status: Status of the visit (success, error, skipped)
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO visited_urls
                (url, ngo_name, session_id, content_hash, file_path, status, visited_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (url, ngo_name, session_id, content_hash, file_path, status))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error marking URL as visited: {e}")

    def get_visited_count(self, ngo_name: str = None) -> int:
        """
        Get count of visited URLs.

        Args:
            ngo_name: Optional NGO name to filter by

        Returns:
            Count of visited URLs
        """
        cursor = self.conn.cursor()
        if ngo_name:
            cursor.execute("SELECT COUNT(*) FROM visited_urls WHERE ngo_name = ?", (ngo_name,))
        else:
            cursor.execute("SELECT COUNT(*) FROM visited_urls")
        return cursor.fetchone()[0]

    def get_stats(self) -> Dict:
        """Get database statistics."""
        cursor = self.conn.cursor()

        # Total URLs
        cursor.execute("SELECT COUNT(*) FROM visited_urls")
        total = cursor.fetchone()[0]

        # URLs per NGO
        cursor.execute("""
            SELECT ngo_name, COUNT(*) as count
            FROM visited_urls
            GROUP BY ngo_name
        """)
        by_ngo = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            'total_urls': total,
            'by_ngo': by_ngo
        }

    def close(self):
        """Close database connection."""
        self.conn.close()


class StorageManager:
    """
    Manages storage of scraped content with organized directory structure.
    Uses single persistent directory per NGO for easy resuming.
    """

    def __init__(self, base_dir: str = "data", ngo_name: str = "default"):
        """
        Initialize storage manager with persistent session directory.

        Args:
            base_dir: Base directory for data storage
            ngo_name: Name of the NGO being scraped
        """
        self.base_dir = Path(base_dir)
        self.ngo_name = self._sanitize_filename(ngo_name)
        self.session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # SINGLE PERSISTENT DIRECTORY per NGO (no timestamp subdirectory)
        self.raw_dir = self.base_dir / "raw" / self.ngo_name
        self.metadata_dir = self.base_dir / "metadata" / self.ngo_name
        self.logs_dir = self.base_dir / "logs"

        self._create_directories()

        # Paths for different content types
        self.pages_dir = self.raw_dir / "pages"
        self.documents_dir = self.raw_dir / "documents"
        self.pages_dir.mkdir(exist_ok=True)
        self.documents_dir.mkdir(exist_ok=True)

        # Links and metadata storage
        self.links_file = self.raw_dir / "links.json"
        self.metadata_file = self.raw_dir / "metadata.json"
        self.progress_file = self.raw_dir / "scraping_progress.txt"
        self.url_manifest_file = self.raw_dir / "url_manifest.jsonl"

        # Load existing links if resuming
        self.links: List[Dict] = []
        if self.links_file.exists():
            try:
                with open(self.links_file, 'r', encoding='utf-8') as f:
                    self.links = json.load(f)
                logger.info(f"Resuming - loaded {len(self.links)} existing links")
            except Exception as e:
                logger.warning(f"Could not load existing links: {e}")
                self.links = []

        # Content hash tracking (for duplicate content detection)
        self.content_hashes: set = set()

        # Statistics - load from metadata if exists
        self.stats = {
            'pages_saved': 0,
            'documents_saved': 0,
            'links_extracted': 0,
            'duplicate_content': 0,
            'errors': 0,
            'session_start': self.session_timestamp,
            'last_updated': self.session_timestamp
        }

        # Load existing stats if resuming
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    existing_metadata = json.load(f)
                    if 'statistics' in existing_metadata:
                        existing_stats = existing_metadata['statistics']
                        self.stats['pages_saved'] = existing_stats.get('pages_saved', 0)
                        self.stats['documents_saved'] = existing_stats.get('documents_saved', 0)
                        self.stats['links_extracted'] = existing_stats.get('links_extracted', 0)
                        self.stats['duplicate_content'] = existing_stats.get('duplicate_content', 0)
                        self.stats['errors'] = existing_stats.get('errors', 0)
                        self.stats['session_start'] = existing_stats.get('session_start', self.session_timestamp)
                logger.info(f"Resuming - loaded existing stats: {self.stats['pages_saved']} pages")
            except Exception as e:
                logger.warning(f"Could not load existing metadata: {e}")

        # Page counter for sequential naming
        self.page_counter = len(list(self.pages_dir.glob('*.html'))) if self.pages_dir.exists() else 0

        logger.info(f"Storage initialized for {self.ngo_name} at {self.raw_dir}")

    def _create_directories(self):
        """Create necessary directory structure."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename to be safe for filesystem.

        Args:
            filename: Original filename

        Returns:
            Sanitized filename
        """
        # Remove or replace invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Remove leading/trailing spaces and dots
        filename = filename.strip('. ')
        # Limit length
        if len(filename) > 200:
            filename = filename[:200]
        return filename or 'unnamed'

    def _url_to_filename(self, url: str, extension: str = '.html') -> str:
        """
        Convert URL to a safe sequential filename.
        Format: 0001_descriptive-name.html

        Args:
            url: URL to convert
            extension: File extension to use

        Returns:
            Safe filename with sequential number
        """
        # Increment counter for sequential naming
        if extension == '.html':
            self.page_counter += 1
            sequence = f"{self.page_counter:05d}"
        else:
            # For documents, use hash-based naming
            sequence = hashlib.md5(url.encode('utf-8')).hexdigest()[:8]

        # Extract descriptive part from URL path
        parsed = urlparse(url)
        path = parsed.path or 'index'

        # Remove leading/trailing slashes
        path = path.strip('/')

        # Get last segment or full path
        if '/' in path:
            # Use last segment for clarity
            path = path.split('/')[-1]

        # Remove existing extension if present
        if '.' in path:
            path = path.rsplit('.', 1)[0]

        # Replace special chars with hyphens
        path = re.sub(r'[^a-zA-Z0-9-]', '-', path)
        # Collapse multiple hyphens
        path = re.sub(r'-+', '-', path)
        # Remove leading/trailing hyphens
        path = path.strip('-')

        # Limit length
        if len(path) > 50:
            path = path[:50].rstrip('-')

        # Handle empty path
        if not path:
            path = 'page'

        # Combine sequence number with descriptive name
        filename = f"{sequence}_{path}{extension}"

        return filename

    def _content_hash(self, content: bytes) -> str:
        """
        Create hash of content for duplicate detection.

        Args:
            content: Content bytes

        Returns:
            Hash string
        """
        return hashlib.sha256(content).hexdigest()

    def is_duplicate_content(self, content: bytes) -> bool:
        """
        Check if content has been seen before.

        Args:
            content: Content to check

        Returns:
            True if duplicate
        """
        content_hash = self._content_hash(content)
        if content_hash in self.content_hashes:
            self.stats['duplicate_content'] += 1
            return True
        self.content_hashes.add(content_hash)
        return False

    def save_page(self, url: str, content: bytes, encoding: str = 'utf-8',
                  check_duplicates: bool = True) -> Optional[str]:
        """
        Save HTML page content with sequential naming.

        Args:
            url: URL of the page
            content: Page content as bytes
            encoding: Content encoding
            check_duplicates: Whether to check for duplicate content

        Returns:
            Path to saved file or None if not saved
        """
        try:
            # Check for duplicates if requested
            if check_duplicates and self.is_duplicate_content(content):
                logger.debug(f"Duplicate content not saved: {url}")
                return None

            # Generate sequential filename
            filename = self._url_to_filename(url, '.html')
            filepath = self.pages_dir / filename

            # Save content
            with open(filepath, 'wb') as f:
                f.write(content)

            self.stats['pages_saved'] += 1
            logger.debug(f"Saved page: {filepath}")

            # Save to URL manifest for easy lookup
            self._save_url_manifest_entry(url, filename, len(content))

            # Also save metadata about this page
            self._save_page_metadata(url, filepath, len(content), encoding)

            # Update progress file
            self._update_progress()

            return str(filepath)

        except Exception as e:
            logger.error(f"Error saving page {url}: {e}")
            self.stats['errors'] += 1
            return None

    def save_document(self, url: str, content: bytes, content_type: str = None) -> Optional[str]:
        """
        Save document (PDF, DOC, etc.).

        Args:
            url: URL of the document
            content: Document content as bytes
            content_type: MIME type of the content

        Returns:
            Path to saved file or None if not saved
        """
        try:
            # Determine extension from URL or content type
            parsed = urlparse(url)
            path = parsed.path
            if '.' in path:
                extension = '.' + path.split('.')[-1].lower()
            elif content_type:
                # Map content type to extension
                type_map = {
                    'application/pdf': '.pdf',
                    'application/msword': '.doc',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
                    'application/vnd.ms-excel': '.xls',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx'
                }
                extension = type_map.get(content_type, '.bin')
            else:
                extension = '.bin'

            # Check for duplicates
            if self.is_duplicate_content(content):
                logger.debug(f"Duplicate document not saved: {url}")
                return None

            # Generate filename
            filename = self._url_to_filename(url, extension)
            filepath = self.documents_dir / filename

            # Save content
            with open(filepath, 'wb') as f:
                f.write(content)

            self.stats['documents_saved'] += 1
            logger.info(f"Saved document: {filepath}")

            # Save metadata
            self._save_document_metadata(url, filepath, len(content), content_type)

            return str(filepath)

        except Exception as e:
            logger.error(f"Error saving document {url}: {e}")
            self.stats['errors'] += 1
            return None

    def add_links(self, source_url: str, links: List[Dict], publication_date: Optional[str] = None):
        """
        Add extracted links to storage.

        Args:
            source_url: URL where links were found
            links: List of link dicts with 'url', 'text', 'type' keys
            publication_date: Publication date of the source page (ISO format)
        """
        for link in links:
            self.links.append({
                'source_url': source_url,
                'target_url': link.get('url'),
                'anchor_text': link.get('text', ''),
                'link_type': link.get('type', 'unknown'),  # internal/external
                'publication_date': publication_date or 'N/A',
                'timestamp': datetime.now().isoformat()
            })
            self.stats['links_extracted'] += 1

    def _save_url_manifest_entry(self, url: str, filename: str, size: int):
        """Save URL to manifest file for easy lookup."""
        try:
            with open(self.url_manifest_file, 'a', encoding='utf-8') as f:
                json.dump({
                    'filename': filename,
                    'url': url,
                    'size_bytes': size,
                    'saved_at': datetime.now().isoformat()
                }, f, ensure_ascii=False)
                f.write('\n')
        except Exception as e:
            logger.error(f"Error saving to URL manifest: {e}")

    def _update_progress(self):
        """Update human-readable progress file."""
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                f.write(f"=== Scraping Progress for {self.ngo_name} ===\n")
                f.write(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"\n")
                f.write(f"Pages Scraped:       {self.stats['pages_saved']}\n")
                f.write(f"Links Extracted:     {self.stats['links_extracted']}\n")
                f.write(f"Documents Saved:     {self.stats['documents_saved']}\n")
                f.write(f"Duplicate Content:   {self.stats['duplicate_content']}\n")
                f.write(f"Errors:              {self.stats['errors']}\n")
                f.write(f"\n")
                f.write(f"Session Start: {self.stats['session_start']}\n")
                f.write(f"Directory: {self.raw_dir}\n")
        except Exception as e:
            logger.error(f"Error updating progress file: {e}")

    def _save_page_metadata(self, url: str, filepath: Path, size: int, encoding: str):
        """Save metadata about a scraped page."""
        metadata_file = self.metadata_dir / 'pages_metadata.jsonl'
        with open(metadata_file, 'a', encoding='utf-8') as f:
            json.dump({
                'url': url,
                'filepath': str(filepath),
                'size_bytes': size,
                'encoding': encoding,
                'timestamp': datetime.now().isoformat()
            }, f)
            f.write('\n')

    def _save_document_metadata(self, url: str, filepath: Path, size: int, content_type: Optional[str]):
        """Save metadata about a scraped document."""
        metadata_file = self.metadata_dir / 'documents_metadata.jsonl'
        with open(metadata_file, 'a', encoding='utf-8') as f:
            json.dump({
                'url': url,
                'filepath': str(filepath),
                'size_bytes': size,
                'content_type': content_type,
                'timestamp': datetime.now().isoformat()
            }, f)
            f.write('\n')

    def save_links(self):
        """Save all collected links to JSON file."""
        try:
            with open(self.links_file, 'w', encoding='utf-8') as f:
                json.dump(self.links, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved {len(self.links)} links to {self.links_file}")
        except Exception as e:
            logger.error(f"Error saving links: {e}")
            self.stats['errors'] += 1

    def save_session_metadata(self, additional_data: Optional[Dict] = None):
        """
        Save metadata about the scraping session.

        Args:
            additional_data: Additional metadata to include
        """
        try:
            metadata = {
                'ngo_name': self.ngo_name,
                'session_timestamp': self.session_timestamp,
                'start_time': self.session_timestamp,
                'end_time': datetime.now().strftime("%Y%m%d_%H%M%S"),
                'statistics': self.stats,
                'storage_paths': {
                    'raw_dir': str(self.raw_dir),
                    'pages_dir': str(self.pages_dir),
                    'documents_dir': str(self.documents_dir),
                    'links_file': str(self.links_file)
                }
            }

            if additional_data:
                metadata.update(additional_data)

            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved session metadata to {self.metadata_file}")

        except Exception as e:
            logger.error(f"Error saving session metadata: {e}")
            self.stats['errors'] += 1

    def get_stats(self) -> Dict:
        """Get storage statistics."""
        return self.stats.copy()

    def finalize(self, additional_metadata: Optional[Dict] = None):
        """
        Finalize storage - save links and metadata.

        Args:
            additional_metadata: Additional metadata to save
        """
        logger.info("Finalizing storage...")
        self.save_links()
        self.save_session_metadata(additional_metadata)
        logger.info(f"Storage finalized. Stats: {self.stats}")
