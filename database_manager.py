"""
GROUP A73, A74, A77
Database Manager for Exam Shield
Handles all database operations with automatic creation :)
"""

import sqlite3
import hashlib
import datetime
import os
from config import Config

class DatabaseManager:
    def __init__(self):
        self.db_path = Config.DATABASE_PATH
        self.init_database()

    def init_database(self):
        """Initialize database and create tables if they don't exist"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'admin',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_login TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS activity_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        action TEXT NOT NULL,
                        details TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        blocked BOOLEAN DEFAULT FALSE,
                        ip_address TEXT,
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS exam_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_name TEXT NOT NULL,
                        admin_id INTEGER,
                        start_time TIMESTAMP,
                        end_time TIMESTAMP,
                        status TEXT DEFAULT 'inactive',
                        restrictions TEXT,
                        FOREIGN KEY (admin_id) REFERENCES users(id)
                    )
                ''')
                conn.commit()
                if not self.admin_exists():
                    self.create_default_admin()
        except sqlite3.Error as e:
            print(f"Database initialization error: {e}")

    def admin_exists(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
                count = cursor.fetchone()[0]
                return count > 0
        except sqlite3.Error:
            return False

    def create_default_admin(self):
        try:
            password_hash = hashlib.sha256(Config.DEFAULT_PASSWORD.encode()).hexdigest()
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
                               (Config.DEFAULT_USERNAME, password_hash))
                conn.commit()
            print("Default admin created successfully")
        except sqlite3.Error as e:
            print(f"Error creating admin user: {e}")

    def verify_admin(self, username, password_hash):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE username=? AND password_hash=? AND role='admin'",
                               (username, password_hash))
                row = cursor.fetchone()
                if row:
                    cursor.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (row[0],))
                    conn.commit()
                    return True
                return False
        except sqlite3.Error as e:
            print(f"Login verification error: {e}")
            return False

    def log_activity(self, action, details=None, blocked=False, user_id=None):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO activity_logs (user_id, action, details, blocked) VALUES (?, ?, ?, ?)",
                               (user_id, action, details, blocked))
                conn.commit()
        except sqlite3.Error as e:
            print(f"Activity logging error: {e}")

    def get_activity_logs(self, limit=100):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT action, details, timestamp, blocked FROM activity_logs ORDER BY timestamp DESC LIMIT ?",
                               (limit,))
                return cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Error fetching logs: {e}")
            return []

    def save_setting(self, key, value):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                               (key, value))
                conn.commit()
        except sqlite3.Error as e:
            print(f"Settings save error: {e}")

    def get_setting(self, key, default=None):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
                row = cursor.fetchone()
                return row[0] if row else default
        except sqlite3.Error as e:
            print(f"Settings fetch error: {e}")
            return default

    def cleanup_old_logs(self):
        try:
            cutoff_date = datetime.datetime.now() - datetime.timedelta(days=Config.LOG_RETENTION_DAYS)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM activity_logs WHERE timestamp < ?", (cutoff_date,))
                conn.commit()
        except sqlite3.Error as e:
            print(f"Log cleanup error: {e}")
