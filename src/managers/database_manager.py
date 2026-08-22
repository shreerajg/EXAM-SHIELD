"""
ExamShield v1.0 — Database Manager
All DB operations: users, logs, settings, sessions, lockouts.
"""
import sqlite3
import hashlib
import hmac
import json
import os
import datetime
import secrets
from src.config import Config


# ── Password hashing (PBKDF2-HMAC-SHA256) ────────────────────────────────────
_PBKDF2_ITERATIONS = 260_000
_SALT_BYTES = 32


def hash_password(password: str) -> str:
    """Return  '<salt_hex>:<hash_hex>'  using PBKDF2-HMAC-SHA256."""
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt, _PBKDF2_ITERATIONS
    )
    return f"{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """
    Verify a password against a stored hash.
    Supports both new '<salt>:<hash>' (PBKDF2) and legacy bare-SHA256 formats.
    Returns True on match.
    """
    if ':' in stored:
        # New PBKDF2 format
        try:
            salt_hex, hash_hex = stored.split(':', 1)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(hash_hex)
            dk = hashlib.pbkdf2_hmac(
                'sha256', password.encode('utf-8'), salt, _PBKDF2_ITERATIONS
            )
            return hmac.compare_digest(dk, expected)
        except Exception:
            return False
    else:
        # Legacy SHA-256 (no salt) — accepted for migration only
        legacy = hashlib.sha256(password.encode('utf-8')).hexdigest()
        return hmac.compare_digest(legacy, stored)


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
                # Persistent lockout table (survives process restarts)
                c.execute('''CREATE TABLE IF NOT EXISTS lockouts (
                    username    TEXT PRIMARY KEY,
                    locked_until TIMESTAMP NOT NULL,
                    tier        INTEGER NOT NULL DEFAULT 1
                )''')
                conn.commit()

                # Auto-upgrade legacy SHA-256 admin password to PBKDF2
                self._migrate_legacy_passwords(c, conn)

                if not self.admin_exists():
                    self._create_default_admin(c, conn)
        except sqlite3.Error as e:
            print(f"[DB] Init error: {e}")

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)

    def _create_default_admin(self, cursor, conn):
        """Create the first admin with a random secure password (printed once)."""
        random_pw = secrets.token_urlsafe(12)
        pw_hash = hash_password(random_pw)
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
            ('admin', pw_hash),
        )
        conn.commit()
        print("=" * 60)
        print("  ExamShield — FIRST RUN")
        print(f"  Username : admin")
        print(f"  Password : {random_pw}")
        print("  ⚠  Change this password immediately after first login!")
        print("=" * 60)

    def _migrate_legacy_passwords(self, cursor, conn):
        """
        Detect any user whose password_hash is a bare 64-char hex string
        (old SHA-256 without salt). We cannot re-hash without the plaintext,
        so we leave legacy hashes in place; they will be transparently
        upgraded in verify_admin() the next time the user logs in.
        This method is a no-op placeholder for future migration logic.
        """
        pass

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

    def verify_admin(self, username: str, password: str) -> bool:
        """
        Verify admin credentials.  'password' is the RAW plaintext password.
        On success with a legacy hash, transparently upgrades to PBKDF2.
        """
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT id, password_hash FROM users WHERE username=? AND role='admin'",
                    (username,),
                ).fetchone()
                if not row:
                    return False
                user_id, stored_hash = row

                if not verify_password(password, stored_hash):
                    return False

                # Upgrade legacy SHA-256 hash to PBKDF2 transparently
                if ':' not in stored_hash:
                    new_hash = hash_password(password)
                    conn.execute(
                        "UPDATE users SET password_hash=? WHERE id=?",
                        (new_hash, user_id),
                    )

                conn.execute(
                    "UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?",
                    (user_id,),
                )
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"[DB] Verify error: {e}")
            return False

    def change_password(self, username: str, old_password: str,
                        new_password: str) -> bool:
        """Change admin password.  Both arguments are RAW plaintext. Returns True on success."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT id, password_hash FROM users WHERE username=? AND role='admin'",
                    (username,),
                ).fetchone()
                if not row:
                    return False
                user_id, stored_hash = row
                if not verify_password(old_password, stored_hash):
                    return False
                new_hash = hash_password(new_password)
                conn.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (new_hash, user_id),
                )
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"[DB] Password change error: {e}")
            return False

    # ── Persistent Lockout ───────────────────────────────────────
    _LOCKOUT_TIERS = [
        60,       # Tier 1: 1 minute
        300,      # Tier 2: 5 minutes
        1800,     # Tier 3: 30 minutes
        -1,       # Tier 4: permanent (until admin resets)
    ]

    def get_lockout(self, username: str) -> tuple[bool, int, int]:
        """
        Returns (is_locked, seconds_remaining, current_tier).
        seconds_remaining == -1 means permanent lockout.
        """
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT locked_until, tier FROM lockouts WHERE username=?",
                    (username,)
                ).fetchone()
                if not row:
                    return False, 0, 0
                locked_until_str, tier = row
                if locked_until_str == 'permanent':
                    return True, -1, tier
                locked_until = datetime.datetime.fromisoformat(locked_until_str)
                now = datetime.datetime.now()
                if now < locked_until:
                    remaining = int((locked_until - now).total_seconds())
                    return True, remaining, tier
                # Lockout expired — clean it up
                conn.execute("DELETE FROM lockouts WHERE username=?", (username,))
                conn.commit()
                return False, 0, tier
        except sqlite3.Error:
            return False, 0, 0

    def set_lockout(self, username: str, tier: int):
        """Set or escalate lockout for username at the given tier."""
        try:
            with self._conn() as conn:
                tier = max(0, min(tier, len(self._LOCKOUT_TIERS) - 1))
                duration = self._LOCKOUT_TIERS[tier]
                if duration == -1:
                    locked_until = 'permanent'
                else:
                    locked_until = (
                        datetime.datetime.now() +
                        datetime.timedelta(seconds=duration)
                    ).isoformat()
                conn.execute(
                    "INSERT OR REPLACE INTO lockouts (username, locked_until, tier) "
                    "VALUES (?, ?, ?)",
                    (username, locked_until, tier)
                )
                conn.commit()
        except sqlite3.Error as e:
            print(f"[DB] Set lockout error: {e}")

    def clear_lockout(self, username: str):
        """Remove lockout record (called on successful login)."""
        try:
            with self._conn() as conn:
                conn.execute("DELETE FROM lockouts WHERE username=?", (username,))
                conn.commit()
        except sqlite3.Error:
            pass

    def get_lockout_tier(self, username: str) -> int:
        """Return current tier (0-based) for username, or 0 if none."""
        _, _, tier = self.get_lockout(username)
        return tier

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
                sessions = conn.execute(
                    "SELECT COUNT(*) FROM activity_logs WHERE action='APP_START'"
                ).fetchone()[0]
                last_row = conn.execute(
                    "SELECT timestamp FROM activity_logs "
                    "WHERE action='EXAM_MODE_STOP' ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
                last_session = last_row[0][:16] if last_row else "N/A"
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
