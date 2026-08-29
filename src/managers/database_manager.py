"""
ExamShield v1.0 — Database Manager
All DB operations: users, logs, settings, sessions, lockouts.
"""
import sqlite3
import hashlib
import hmac
import json
import os
import re
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


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate *password* against the policy defined in Config.PASSWORD_POLICY.
    Returns (ok: bool, reason: str).  reason is empty string on success.
    """
    policy = Config.PASSWORD_POLICY
    min_len = policy.get('min_length', Config.PASSWORD_MIN_LENGTH)
    if len(password) < min_len:
        return False, f"Password must be at least {min_len} characters long."
    if policy.get('require_upper') and not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter (A-Z)."
    if policy.get('require_lower') and not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter (a-z)."
    if policy.get('require_digit') and not re.search(r'\d', password):
        return False, "Password must contain at least one digit (0-9)."
    if policy.get('require_special'):
        specials = re.escape(policy.get('special_chars', '!@#$%^&*()-_=+[]{}|;:,.<>?/'))
        if not re.search(f'[{specials}]', password):
            return False, (
                "Password must contain at least one special character "
                "(e.g. !@#$%^&*)"
            )
    return True, ""


class DatabaseManager:
    def __init__(self):
        self.db_path = Config.DATABASE_PATH
        self._audit_instance = None   # lazy-init to avoid circular import
        self._init_database()

    # ── Lazy AuditManager accessor ────────────────────────────────
    @property
    def _audit(self):
        """Return the per-DatabaseManager AuditManager, creating it once."""
        if self._audit_instance is None:
            from src.managers.audit_manager import AuditManager
            self._audit_instance = AuditManager(self)
        return self._audit_instance

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
                # ── Layer 3: Tamper-evident session seal table ──────────────────────
                c.execute('''CREATE TABLE IF NOT EXISTS session_seals (
                    session_id  TEXT PRIMARY KEY,
                    seal_hash   TEXT NOT NULL,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    verified_at TIMESTAMP
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

                # E2 — Database integrity check on every startup
                result = conn.execute('PRAGMA integrity_check=fast').fetchone()
                if result and result[0] != 'ok':
                    print(f"[DB] ⚠  integrity_check returned: {result[0]}")
                    try:
                        conn.execute(
                            "INSERT INTO activity_logs (action, details, blocked) "
                            "VALUES ('DB_INTEGRITY_FAIL', ?, 1)",
                            (f"integrity_check={result[0]}",)
                        )
                        conn.commit()
                    except sqlite3.Error:
                        pass
                else:
                    print("[DB] integrity_check: ok")
        except sqlite3.Error as e:
            print(f"[DB] Init error: {e}")

    def _conn(self):
        """Open a DB connection with WAL journal mode for a smaller race window."""
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        if Config.DB_WAL_MODE:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')   # safe with WAL
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

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
                        new_password: str) -> tuple[bool, str]:
        """
        Change admin password.  Both arguments are RAW plaintext.
        Returns (True, '') on success or (False, reason_string) on failure.
        Now enforces the password-strength policy defined in Config.PASSWORD_POLICY.
        """
        # Validate new password strength before touching the DB
        ok, reason = validate_password_strength(new_password)
        if not ok:
            return False, reason
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT id, password_hash FROM users WHERE username=? AND role='admin'",
                    (username,),
                ).fetchone()
                if not row:
                    return False, "User not found."
                user_id, stored_hash = row
                if not verify_password(old_password, stored_hash):
                    return False, "Current password is incorrect."
                new_hash = hash_password(new_password)
                conn.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (new_hash, user_id),
                )
                conn.commit()
                return True, ""
        except sqlite3.Error as e:
            print(f"[DB] Password change error: {e}")
            return False, f"Database error: {e}"

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

    # ── Activity Logs ───────────────────────────────────────────
    def log_activity(self, action, details=None, blocked=False, user_id=None):
        """Insert one activity log row and immediately chain-hash it (E1)."""
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO activity_logs (user_id, action, details, blocked) VALUES (?,?,?,?)",
                    (user_id, action, details, blocked),
                )
                conn.commit()
                row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                ts_row = conn.execute(
                    "SELECT timestamp FROM activity_logs WHERE id=?", (row_id,)
                ).fetchone()
                timestamp = ts_row[0] if ts_row else ""

            # Append the HMAC chain hash for this new row (outside the above
            # 'with' block so _audit._conn() gets its own clean connection).
            try:
                self._audit.append_chain_hash(
                    row_id, action, details or "", timestamp
                )
            except Exception as ae:
                print(f"[DB] chain-hash error: {ae}")
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

    # ── Settings Change Audit ─────────────────────────────────
    def log_settings_change(self, key: str, old_value: str, new_value: str,
                            user: str = "admin") -> None:
        """
        Write a SETTINGS_CHANGE entry to the activity log.
        Called by the admin panel whenever a setting is saved.
        """
        details = f"key='{key}' | '{old_value}' → '{new_value}' | by={user}"
        self.log_activity("SETTINGS_CHANGE", details, blocked=False)

    # ── Maintenance ────────────────────────────────────────────
    def cleanup_old_logs(self):
        try:
            cutoff = datetime.datetime.now() - datetime.timedelta(days=Config.LOG_RETENTION_DAYS)
            with self._conn() as conn:
                conn.execute("DELETE FROM activity_logs WHERE timestamp < ?", (cutoff,))
                conn.commit()
        except sqlite3.Error as e:
            print(f"[DB] Cleanup error: {e}")

    # ── Layer 3: Session Integrity Seal (HMAC-SHA256) ─────────────────────────
    def record_session_seal(self, session_id: str, seal_hash: str) -> bool:
        """
        Store an HMAC-SHA256 seal for the given session_id.
        Call this at exam start so any later DB tampering can be detected.
        Returns True on success.
        """
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO session_seals (session_id, seal_hash, created_at) "
                    "VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (session_id, seal_hash),
                )
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"[DB] record_session_seal error: {e}")
            return False

    def verify_session_seal(self, session_id: str, expected_hash: str) -> bool:
        """
        Verify that the stored seal for *session_id* matches *expected_hash*.
        Updates verified_at timestamp regardless of outcome.
        Returns True if seals match (no tampering), False otherwise.
        """
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT seal_hash FROM session_seals WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                if not row:
                    return False  # seal was deleted — flag as tampered
                stored = row[0]
                match = hmac.compare_digest(stored, expected_hash)
                conn.execute(
                    "UPDATE session_seals SET verified_at=CURRENT_TIMESTAMP "
                    "WHERE session_id=?",
                    (session_id,),
                )
                conn.commit()
                return match
        except sqlite3.Error as e:
            print(f"[DB] verify_session_seal error: {e}")
            return False
