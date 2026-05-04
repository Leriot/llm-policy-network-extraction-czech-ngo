"""
Session Management System for Web Scraper

Handles tracking of scraping sessions, allowing resume functionality,
checkpoint management, and run state persistence.
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class SessionStatus(Enum):
    """Possible session states"""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class SessionManager:
    """Manages scraping sessions and their state"""

    def __init__(self, db_path: str = "data/scraping_sessions.db"):
        """
        Initialize session manager

        Args:
            db_path: Path to SQLite database for session tracking
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.current_session_id: Optional[str] = None
        self._init_database()

    def _init_database(self):
        """Initialize the session tracking database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    organization TEXT,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    status TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    total_pages_scraped INTEGER DEFAULT 0,
                    total_pages_skipped INTEGER DEFAULT 0,
                    total_errors INTEGER DEFAULT 0,
                    config_snapshot TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Create checkpoints table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    pages_scraped INTEGER,
                    queue_size INTEGER,
                    checkpoint_data TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
            """)

            # Create index for faster lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_status
                ON sessions(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_org
                ON sessions(organization)
            """)

            conn.commit()
            logger.debug(f"Session database initialized at {self.db_path}")

    def create_session(
        self,
        organization: Optional[str] = None,
        config: Optional[Dict] = None,
        notes: Optional[str] = None
    ) -> str:
        """
        Create a new scraping session

        Args:
            organization: Name of organization being scraped (None = all)
            config: Configuration snapshot for this session
            notes: Optional notes about this session

        Returns:
            session_id: Unique identifier for this session
        """
        # Generate session ID: YYYYMMDD_HHMMSS_org
        timestamp = datetime.now()
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")

        if organization:
            # Clean organization name for filesystem
            org_clean = organization.replace(" ", "_").replace("/", "-")
            session_id = f"{timestamp_str}_{org_clean}"
        else:
            session_id = f"{timestamp_str}_all_orgs"

        # Create output directory
        output_dir = Path("data") / "runs" / session_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Store session in database
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            config_json = json.dumps(config) if config else None
            now_iso = timestamp.isoformat()

            cursor.execute("""
                INSERT INTO sessions (
                    session_id, organization, start_time, status,
                    output_dir, config_snapshot, notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                organization,
                now_iso,
                SessionStatus.IN_PROGRESS.value,
                str(output_dir),
                config_json,
                notes,
                now_iso,
                now_iso
            ))

            conn.commit()

        self.current_session_id = session_id
        logger.info(f"Created new session: {session_id}")
        logger.info(f"Output directory: {output_dir}")

        return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get session details

        Args:
            session_id: Session identifier

        Returns:
            Dictionary with session details or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM sessions WHERE session_id = ?
            """, (session_id,))

            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def list_sessions(
        self,
        organization: Optional[str] = None,
        status: Optional[SessionStatus] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List scraping sessions

        Args:
            organization: Filter by organization (None = all)
            status: Filter by status (None = all)
            limit: Maximum number of sessions to return

        Returns:
            List of session dictionaries
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT * FROM sessions WHERE 1=1"
            params = []

            if organization:
                query += " AND organization = ?"
                params.append(organization)

            if status:
                query += " AND status = ?"
                params.append(status.value)

            query += " ORDER BY start_time DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)

            return [dict(row) for row in cursor.fetchall()]

    def update_session_status(
        self,
        session_id: str,
        status: SessionStatus,
        stats: Optional[Dict[str, int]] = None
    ):
        """
        Update session status

        Args:
            session_id: Session identifier
            status: New status
            stats: Optional statistics to update
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            update_fields = ["status = ?", "updated_at = ?"]
            params = [status.value, datetime.now().isoformat()]

            # If marking as completed or failed, set end_time
            if status in [SessionStatus.COMPLETED, SessionStatus.FAILED]:
                update_fields.append("end_time = ?")
                params.append(datetime.now().isoformat())

            # Update statistics if provided
            if stats:
                if 'total_pages_scraped' in stats:
                    update_fields.append("total_pages_scraped = ?")
                    params.append(stats['total_pages_scraped'])
                if 'total_pages_skipped' in stats:
                    update_fields.append("total_pages_skipped = ?")
                    params.append(stats['total_pages_skipped'])
                if 'total_errors' in stats:
                    update_fields.append("total_errors = ?")
                    params.append(stats['total_errors'])

            params.append(session_id)

            query = f"""
                UPDATE sessions
                SET {', '.join(update_fields)}
                WHERE session_id = ?
            """

            cursor.execute(query, params)
            conn.commit()

            logger.info(f"Session {session_id} status updated to {status.value}")

    def save_checkpoint(
        self,
        session_id: str,
        pages_scraped: int,
        queue_size: int,
        checkpoint_data: Optional[Dict] = None
    ):
        """
        Save a checkpoint for the current session

        Args:
            session_id: Session identifier
            pages_scraped: Number of pages scraped so far
            queue_size: Current size of URL queue
            checkpoint_data: Additional checkpoint data to save
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            data_json = json.dumps(checkpoint_data) if checkpoint_data else None

            cursor.execute("""
                INSERT INTO checkpoints (
                    session_id, timestamp, pages_scraped,
                    queue_size, checkpoint_data
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                session_id,
                datetime.now().isoformat(),
                pages_scraped,
                queue_size,
                data_json
            ))

            conn.commit()
            logger.debug(f"Checkpoint saved for session {session_id}")

    def get_latest_checkpoint(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the most recent checkpoint for a session

        Args:
            session_id: Session identifier

        Returns:
            Dictionary with checkpoint data or None
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM checkpoints
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (session_id,))

            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_resumable_sessions(self) -> List[Dict[str, Any]]:
        """
        Get list of sessions that can be resumed

        Returns:
            List of in-progress or interrupted sessions
        """
        return self.list_sessions(
            status=SessionStatus.IN_PROGRESS
        ) + self.list_sessions(
            status=SessionStatus.INTERRUPTED
        )

    def delete_session(self, session_id: str, delete_files: bool = False):
        """
        Delete a session from the database

        Args:
            session_id: Session identifier
            delete_files: If True, also delete output files
        """
        session = self.get_session(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found")
            return

        # Delete from database
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Delete checkpoints first (foreign key)
            cursor.execute("""
                DELETE FROM checkpoints WHERE session_id = ?
            """, (session_id,))

            # Delete session
            cursor.execute("""
                DELETE FROM sessions WHERE session_id = ?
            """, (session_id,))

            conn.commit()

        # Delete output files if requested
        if delete_files and session['output_dir']:
            output_dir = Path(session['output_dir'])
            if output_dir.exists():
                import shutil
                shutil.rmtree(output_dir)
                logger.info(f"Deleted output directory: {output_dir}")

        logger.info(f"Session {session_id} deleted")

    def get_session_summary(self, session_id: str) -> str:
        """
        Get a human-readable summary of a session

        Args:
            session_id: Session identifier

        Returns:
            Formatted summary string
        """
        session = self.get_session(session_id)
        if not session:
            return f"Session {session_id} not found"

        start_time = datetime.fromisoformat(session['start_time'])
        duration = "In progress"

        if session['end_time']:
            end_time = datetime.fromisoformat(session['end_time'])
            duration_seconds = (end_time - start_time).total_seconds()
            hours = int(duration_seconds // 3600)
            minutes = int((duration_seconds % 3600) // 60)
            duration = f"{hours}h {minutes}m"

        summary = f"""
Session: {session['session_id']}
Status: {session['status']}
Organization: {session['organization'] or 'All'}
Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}
Duration: {duration}
Pages Scraped: {session['total_pages_scraped']}
Pages Skipped: {session['total_pages_skipped']}
Errors: {session['total_errors']}
Output: {session['output_dir']}
"""

        if session['notes']:
            summary += f"Notes: {session['notes']}\n"

        return summary.strip()

    def get_organization_history(self, organization: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get scraping history for a specific organization

        Args:
            organization: Organization name
            limit: Maximum number of sessions to return

        Returns:
            List of session dictionaries, most recent first
        """
        return self.list_sessions(organization=organization, limit=limit)

    def get_organization_stats(self, organization: str) -> Dict[str, Any]:
        """
        Get aggregate statistics for an organization

        Args:
            organization: Organization name

        Returns:
            Dictionary with statistics
        """
        sessions = self.list_sessions(organization=organization, limit=1000)

        if not sessions:
            return {
                'total_sessions': 0,
                'completed_sessions': 0,
                'total_pages_scraped': 0,
                'last_scrape_date': None,
                'last_successful_scrape': None
            }

        completed = [s for s in sessions if s['status'] == 'completed']

        total_pages = sum(s['total_pages_scraped'] for s in sessions)

        # Get most recent scrape
        last_scrape = sessions[0] if sessions else None
        last_scrape_date = datetime.fromisoformat(last_scrape['start_time']) if last_scrape else None

        # Get most recent successful scrape
        last_successful = completed[0] if completed else None
        last_successful_date = datetime.fromisoformat(last_successful['start_time']) if last_successful else None

        return {
            'total_sessions': len(sessions),
            'completed_sessions': len(completed),
            'total_pages_scraped': total_pages,
            'last_scrape_date': last_scrape_date,
            'last_successful_scrape': last_successful_date
        }

    def get_all_organizations(self) -> List[str]:
        """
        Get list of all organizations that have been scraped

        Returns:
            List of organization names
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT organization
                FROM sessions
                WHERE organization IS NOT NULL
                ORDER BY organization
            """)
            return [row[0] for row in cursor.fetchall()]
