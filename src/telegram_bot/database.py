"""Database operations for storing and managing job postings."""
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional

class JobDatabase:
    """Manages SQLite database for job postings."""
    
    def __init__(self, db_path: str = 'jobs.db'):
        """Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        return conn
    
    def init_database(self):
        """Create database tables if they don't exist."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                title TEXT,
                description TEXT,
                contact_info TEXT,
                source_channel TEXT,
                keywords_matched TEXT,
                applied BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                applied_at TIMESTAMP
            )
        ''')
        
        # Table to track contacted users (to avoid spam)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS contacted_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                first_contacted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_contacted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                contact_count INTEGER DEFAULT 1
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def job_exists(self, job_id: str) -> bool:
        """Check if a job with the given ID already exists.
        
        Args:
            job_id: Unique job identifier (Telegram message ID)
            
        Returns:
            True if job exists, False otherwise
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT 1 FROM jobs WHERE job_id = ?', (job_id,))
        exists = cursor.fetchone() is not None
        
        conn.close()
        return exists
    
    def add_job(
        self,
        job_id: str,
        title: str,
        description: str,
        contact_info: str,
        source_channel: str,
        keywords_matched: List[str]
    ) -> bool:
        """Add a new job to the database.
        
        Args:
            job_id: Unique job identifier (Telegram message ID)
            title: Job title
            description: Job description
            contact_info: Contact information (Telegram handle, email, etc.)
            source_channel: Source channel username
            keywords_matched: List of matched Python keywords
            
        Returns:
            True if job was added, False if it already exists
        """
        if self.job_exists(job_id):
            return False
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        keywords_json = json.dumps(keywords_matched)
        
        cursor.execute('''
            INSERT INTO jobs (
                job_id, title, description, contact_info,
                source_channel, keywords_matched, applied
            ) VALUES (?, ?, ?, ?, ?, ?, 0)
        ''', (job_id, title, description, contact_info, source_channel, keywords_json))
        
        conn.commit()
        conn.close()
        return True
    
    def get_unapplied_jobs(self) -> List[Dict]:
        """Get all jobs that haven't been applied to yet.
        
        Returns:
            List of job dictionaries
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM jobs
            WHERE applied = 0
            ORDER BY created_at DESC
        ''')
        
        rows = cursor.fetchall()
        jobs = [dict(row) for row in rows]
        
        # Parse keywords_matched JSON
        for job in jobs:
            if job['keywords_matched']:
                job['keywords_matched'] = json.loads(job['keywords_matched'])
            else:
                job['keywords_matched'] = []
        
        conn.close()
        return jobs
    
    def mark_as_applied(self, job_id: str) -> bool:
        """Mark a job as applied.
        
        Args:
            job_id: Unique job identifier
            
        Returns:
            True if job was updated, False if not found
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE jobs
            SET applied = 1, applied_at = CURRENT_TIMESTAMP
            WHERE job_id = ?
        ''', (job_id,))
        
        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return updated
    
    def get_all_jobs(self, applied: Optional[bool] = None) -> List[Dict]:
        """Get all jobs, optionally filtered by applied status.
        
        Args:
            applied: If None, return all jobs. If True/False, filter by status.
            
        Returns:
            List of job dictionaries
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if applied is None:
            cursor.execute('SELECT * FROM jobs ORDER BY created_at DESC')
        else:
            cursor.execute('''
                SELECT * FROM jobs
                WHERE applied = ?
                ORDER BY created_at DESC
            ''', (1 if applied else 0,))
        
        rows = cursor.fetchall()
        jobs = [dict(row) for row in rows]
        
        # Parse keywords_matched JSON
        for job in jobs:
            if job['keywords_matched']:
                job['keywords_matched'] = json.loads(job['keywords_matched'])
            else:
                job['keywords_matched'] = []
        
        conn.close()
        return jobs
    
    def is_user_contacted(self, username: str) -> bool:
        """Check if a user has been contacted before.
        
        Args:
            username: Telegram username (without @)
            
        Returns:
            True if user was contacted before, False otherwise
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT 1 FROM contacted_users WHERE username = ?', (username,))
        exists = cursor.fetchone() is not None
        
        conn.close()
        return exists
    
    def mark_user_contacted(self, username: str) -> bool:
        """Mark a user as contacted (or update if already exists).
        
        Args:
            username: Telegram username (without @)
            
        Returns:
            True if successful
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Check if user already exists
        cursor.execute('SELECT contact_count FROM contacted_users WHERE username = ?', (username,))
        existing = cursor.fetchone()
        
        if existing:
            # Update existing record
            cursor.execute('''
                UPDATE contacted_users
                SET last_contacted_at = CURRENT_TIMESTAMP,
                    contact_count = contact_count + 1
                WHERE username = ?
            ''', (username,))
        else:
            # Insert new record
            cursor.execute('''
                INSERT INTO contacted_users (username, first_contacted_at, last_contacted_at, contact_count)
                VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
            ''', (username,))
        
        conn.commit()
        conn.close()
        return True
    
    def get_contacted_users(self) -> List[str]:
        """Get list of all contacted usernames.
        
        Returns:
            List of usernames
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT username FROM contacted_users')
        users = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return users
    
    def update_job_title(self, job_id: str, new_title: str) -> bool:
        """Update the title of an existing job.
        
        Args:
            job_id: Unique job identifier
            new_title: New title to set
            
        Returns:
            True if job was updated, False if not found
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE jobs
            SET title = ?
            WHERE job_id = ?
        ''', (new_title, job_id))
        
        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return updated
    
    def get_all_jobs_for_audit(self) -> List[Dict]:
        """Get all jobs for auditing purposes.
        
        Returns:
            List of all job dictionaries
        """
        return self.get_all_jobs()

