"""
ExamShield v1.0 — Database Manager
All DB operations: users, logs, settings, sessions.
"""
import sqlite3
import hashlib
import json
import datetime
import os
from src.config import Config


class DatabaseManager:
    def __init__(self):
        self.db_path = Config.DATABASE_PATH
        self._init_database()

    # ── Schema ───────────────────────────────────────────────────
    def _init_database(self):
        try:
            with self._conn() as conn:
                c = conn.cursor()
                c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'admin',
                    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login    TIMESTAMP
                )''')
                c.execute('''CREATE TABLE IF NOT EXISTS activity_logs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    action     TEXT NOT NULL,
                    details    TEXT,
                    timestamp  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    blocked    BOOLEAN DEFAULT 0,
                    ip_address TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )''')
                c.execute('''CREATE TABLE IF NOT EXISTS settings (
                    key        TEXT PRIMARY KEY,
                    value      TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
                c.execute('''CREATE TABLE IF NOT EXISTS exam_sessions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_name TEXT NOT NULL,
                    admin_id     INTEGER,
                    start_time   TIMESTAMP,
                    end_time     TIMESTAMP,
                    status       TEXT DEFAULT 'inactive',
                    restrictions TEXT,
                    FOREIGN KEY (admin_id) REFERENCES users(id)
                )''')
                c.execute('''CREATE TABLE IF NOT EXISTS failed_logins (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    username   TEXT NOT NULL,
                    timestamp  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
                conn.commit()
                if not self.admin_exists():
                    self._create_default_admin(c, conn)
        except sqlite3.Error as e:
            print(f"[DB] Init error: {e}")

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)

    def _create_default_admin(self, cursor, conn):
        pw = hashlib.sha256(Config.DEFAULT_ADMIN_PASSWORD.encode()).hexdigest()
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
            (Config.DEFAULT_ADMIN_USERNAME, pw),
        )
        conn.commit()

    # ── Auth ─────────────────────────────────────────────────────
    def admin_exists(self):
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin'"
                ).fetchone()
                return row[0] > 0
        except sqlite3.Error:
            return False

    def verify_admin(self, username, password_hash):
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT id FROM users WHERE username=? AND password_hash=? AND role='admin'",
                    (username, password_hash),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?",
                        (row[0],),
                    )
                    conn.commit()
                    return True
                return False
        except sqlite3.Error as e:
            print(f"[DB] Verify error: {e}")
            return False

    def change_password(self, username, old_hash, new_hash):
        """Change admin password. Returns True on success."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT id FROM users WHERE username=? AND password_hash=? AND role='admin'",
                    (username, old_hash),
                ).fetchone()
                if not row:
                    return False
                conn.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (new_hash, row[0]),
                )
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"[DB] Password change error: {e}")
            return False

    # ── Activity Logs ────────────────────────────────────────────
    def log_activity(self, action, details=None, blocked=False, user_id=None):
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO activity_logs (user_id, action, details, blocked) VALUES (?,?,?,?)",
                    (user_id, action, details, blocked),
                )
                conn.commit()
        except sqlite3.Error as e:
            print(f"[DB] Log error: {e}")

    def get_activity_logs(self, limit=100, filter_type="All"):
        try:
            with self._conn() as conn:
                if filter_type == "Blocked Only":
                    rows = conn.execute(
                        "SELECT action, details, timestamp, blocked FROM activity_logs "
                        "WHERE blocked=1 ORDER BY timestamp DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                elif filter_type == "Security Events":
                    rows = conn.execute(
                        "SELECT action, details, timestamp, blocked FROM activity_logs "
                        "WHERE action LIKE '%BLOCKED%' OR action LIKE '%SECURITY%' OR action LIKE '%SUSPICIOUS%' "
                        "ORDER BY timestamp DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                elif filter_type == "System Events":
                    rows = conn.execute(
                        "SELECT action, details, timestamp, blocked FROM activity_logs "
                        "WHERE action LIKE '%SYSTEM%' OR action LIKE '%EXAM_MODE%' "
                        "ORDER BY timestamp DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT action, details, timestamp, blocked FROM activity_logs "
                        "ORDER BY timestamp DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                return rows
        except sqlite3.Error as e:
            print(f"[DB] Fetch logs error: {e}")
            return []

    def clear_all_logs(self):
        try:
            with self._conn() as conn:
                conn.execute("DELETE FROM activity_logs")
                conn.commit()
        except sqlite3.Error as e:
            print(f"[DB] Clear logs error: {e}")

    def search_logs(self, query: str, limit: int = 200,
                    filter_type: str = "All") -> list:
        """Full-text search across action + details columns."""
        q = f"%{query}%"
        try:
            with self._conn() as conn:
                base = (
                    "SELECT action, details, timestamp, blocked "
                    "FROM activity_logs "
                    "WHERE (action LIKE ? OR details LIKE ?) "
                )
                params: list = [q, q]
                if filter_type == "Blocked Only":
                    base += "AND blocked=1 "
                elif filter_type == "Security Events":
                    base += ("AND (action LIKE '%BLOCKED%' OR action LIKE '%SECURITY%' "
                             "OR action LIKE '%SUSPICIOUS%') ")
                elif filter_type == "System Events":
                    base += "AND (action LIKE '%SYSTEM%' OR action LIKE '%EXAM_MODE%') "
                base += "ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)
                return conn.execute(base, params).fetchall()
        except sqlite3.Error as e:
            print(f"[DB] Search logs error: {e}")
            return []

    def get_log_stats(self):
        """Return counts for dashboard display."""
        try:
            with self._conn() as conn:
                total = conn.execute("SELECT COUNT(*) FROM activity_logs").fetchone()[0]
                blocked = conn.execute(
                    "SELECT COUNT(*) FROM activity_logs WHERE blocked=1"
                ).fetchone()[0]
                return {"total": total, "blocked": blocked, "allowed": total - blocked}
        except sqlite3.Error:
            return {"total": 0, "blocked": 0, "allowed": 0}

    def get_session_stats(self) -> dict:
        """Aggregate stats for the Dashboard Session History panel."""
        try:
            with self._conn() as conn:
                total_blocked = conn.execute(
                    "SELECT COUNT(*) FROM activity_logs WHERE blocked=1"
                ).fetchone()[0]
                # Approximate session count by APP_START events
                sessions = conn.execute(
                    "SELECT COUNT(*) FROM activity_logs WHERE action='APP_START'"
                ).fetchone()[0]
                # Most recent exam stop
                last_row = conn.execute(
                    "SELECT timestamp FROM activity_logs "
                    "WHERE action='EXAM_MODE_STOP' ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
                last_session = last_row[0][:16] if last_row else "N/A"
                # Last-session breach count (breaches since last EXAM_MODE_START)
                start_row = conn.execute(
                    "SELECT timestamp FROM activity_logs "
                    "WHERE action='EXAM_MODE_START' ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
                last_breaches = 0
                if start_row:
                    last_breaches = conn.execute(
                        "SELECT COUNT(*) FROM activity_logs "
                        "WHERE blocked=1 AND timestamp >= ?",
                        (start_row[0],)
                    ).fetchone()[0]
                return {
                    "sessions": sessions,
                    "total_blocked": total_blocked,
                    "last_session": last_session,
                    "last_breaches": last_breaches,
                }
        except sqlite3.Error:
            return {"sessions": 0, "total_blocked": 0,
                    "last_session": "N/A", "last_breaches": 0}

    # ── Settings ─────────────────────────────────────────────────
    def save_setting(self, key, value):
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value, updated_at) "
                    "VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (key, value),
                )
                conn.commit()
        except sqlite3.Error as e:
            print(f"[DB] Save setting error: {e}")

    def get_setting(self, key, default=None):
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT value FROM settings WHERE key=?", (key,)
                ).fetchone()
                return row[0] if row else default
        except sqlite3.Error:
            return default

    def save_settings_bulk(self, settings_dict):
        """Save multiple settings at once."""
        try:
            with self._conn() as conn:
                for k, v in settings_dict.items():
                    conn.execute(
                        "INSERT OR REPLACE INTO settings (key, value, updated_at) "
                        "VALUES (?, ?, CURRENT_TIMESTAMP)",
                        (k, v),
                    )
                conn.commit()
        except sqlite3.Error as e:
            print(f"[DB] Bulk save error: {e}")

    def load_persisted_lists(self):
        """Load blocked keys/mouse/websites from DB, falling back to Config defaults."""
        keys_json = self.get_setting("blocked_keys")
        mouse_json = self.get_setting("blocked_mouse_buttons")
        websites_json = self.get_setting("blocked_websites")
        return {
            "blocked_keys": json.loads(keys_json) if keys_json else None,
            "blocked_mouse": json.loads(mouse_json) if mouse_json else None,
            "blocked_websites": json.loads(websites_json) if websites_json else None,
        }

    # ── Failed Login Tracking ──────────────────────────────
    def log_failed_login(self, username: str):
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO failed_logins (username) VALUES (?)",
                    (username,)
                )
                conn.commit()
        except sqlite3.Error as e:
            print(f"[DB] Failed login log error: {e}")

    def get_recent_failed_logins(self, username: str,
                                  window_sec: int = 300) -> int:
        """Count failed logins for *username* in the last window_sec seconds."""
        try:
            with self._conn() as conn:
                cutoff = datetime.datetime.now() - datetime.timedelta(seconds=window_sec)
                row = conn.execute(
                    "SELECT COUNT(*) FROM failed_logins "
                    "WHERE username=? AND timestamp >= ?",
                    (username, cutoff)
                ).fetchone()
                return row[0] if row else 0
        except sqlite3.Error:
            return 0

    def clear_failed_logins(self, username: str):
        """Clear failed login records for *username* (called on success)."""
        try:
            with self._conn() as conn:
                conn.execute("DELETE FROM failed_logins WHERE username=?",
                             (username,))
                conn.commit()
        except sqlite3.Error as e:
            print(f"[DB] Clear failed logins error: {e}")

    # ── Maintenance ────────────────────────────────────────────
    def cleanup_old_logs(self):
        try:
            cutoff = datetime.datetime.now() - datetime.timedelta(days=Config.LOG_RETENTION_DAYS)
            with self._conn() as conn:
                conn.execute("DELETE FROM activity_logs WHERE timestamp < ?", (cutoff,))
                conn.commit()
        except sqlite3.Error as e:
            print(f"[DB] Cleanup error: {e}")
