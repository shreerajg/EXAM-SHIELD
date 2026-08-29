"""
ExamShield v1.0 — Audit Manager
Tamper-evident HMAC-SHA256 log chaining.

How it works
------------
Each activity_log row gets a `chain_hash` column computed as:

    HMAC-SHA256(key=CHAIN_SECRET,
                msg=f"{prev_chain_hash}|{action}|{details}|{timestamp}")

where `prev_chain_hash` for the first row is the well-known genesis value.

`verify_log_chain()` re-walks the entire log in insertion order and re-computes
each expected hash.  If any row has been deleted, reordered, or its content
edited, the chain will break at that point.

The CHAIN_SECRET is a per-installation key stored in the DB as a setting
(`audit_chain_secret`).  It is generated once on first use.
"""
import hashlib
import hmac
import sqlite3
import secrets
from dataclasses import dataclass
from src.config import Config

# Genesis value: the "previous hash" for the very first log row.
_GENESIS_HASH = "0" * 64


@dataclass
class AuditVerifyResult:
    ok: bool                     # True = chain intact
    total_rows: int = 0
    first_broken_id: int = -1   # -1 if chain is intact
    broken_at_index: int = -1   # 0-based index in result set
    missing_hashes: int = 0     # rows with no chain_hash stored yet
    message: str = ""


class AuditManager:
    """
    Manages the tamper-evident HMAC log chain for ExamShield activity logs.

    Usage
    -----
        audit = AuditManager(db_manager)
        audit.append_chain_hash(row_id, action, details, timestamp)
        result = audit.verify_log_chain()
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self._secret: bytes = self._load_or_create_secret()
        self._ensure_chain_column()

    # -- Schema ---------------------------------------------------------------
    def _ensure_chain_column(self):
        """Add `chain_hash` column to activity_logs if it does not exist."""
        try:
            with self.db._conn() as conn:
                existing = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(activity_logs)"
                    ).fetchall()
                }
                if 'chain_hash' not in existing:
                    conn.execute(
                        "ALTER TABLE activity_logs ADD COLUMN chain_hash TEXT"
                    )
                    conn.commit()
        except sqlite3.Error as e:
            print(f"[AuditManager] Schema error: {e}")

    # -- Secret key management ------------------------------------------------
    def _load_or_create_secret(self) -> bytes:
        """
        Load the per-install HMAC secret from DB settings, or generate
        and store a new one if this is the first run.
        """
        stored = self.db.get_setting('audit_chain_secret')
        if stored:
            try:
                return bytes.fromhex(stored)
            except ValueError:
                pass  # corrupt value — regenerate below
        secret = secrets.token_bytes(32)
        self.db.save_setting('audit_chain_secret', secret.hex())
        return secret

    # -- Chain computation ----------------------------------------------------
    def _compute_hash(self, prev_hash: str, action: str,
                      details: str, timestamp: str) -> str:
        """Return HMAC-SHA256 hex digest for one log row."""
        msg = f"{prev_hash}|{action}|{details or ''}|{timestamp}"
        return hmac.new(
            self._secret,
            msg.encode('utf-8', errors='replace'),
            hashlib.sha256
        ).hexdigest()

    def append_chain_hash(self, row_id: int, action: str,
                          details: str, timestamp: str) -> None:
        """
        Compute and store the chain_hash for the row identified by *row_id*.
        Call this immediately after inserting a new log row.
        """
        try:
            with self.db._conn() as conn:
                prev_row = conn.execute(
                    "SELECT chain_hash FROM activity_logs "
                    "WHERE id < ? ORDER BY id DESC LIMIT 1",
                    (row_id,)
                ).fetchone()
                prev_hash = (prev_row[0] or _GENESIS_HASH) if prev_row else _GENESIS_HASH
                new_hash = self._compute_hash(prev_hash, action, details, timestamp)
                conn.execute(
                    "UPDATE activity_logs SET chain_hash=? WHERE id=?",
                    (new_hash, row_id)
                )
                conn.commit()
        except sqlite3.Error as e:
            print(f"[AuditManager] append_chain_hash error: {e}")

    # -- Verification ---------------------------------------------------------
    def verify_log_chain(self) -> AuditVerifyResult:
        """
        Walk every activity_log row in insertion order and verify the HMAC chain.
        Returns an AuditVerifyResult describing the outcome.
        """
        try:
            with self.db._conn() as conn:
                rows = conn.execute(
                    "SELECT id, action, details, timestamp, chain_hash "
                    "FROM activity_logs ORDER BY id ASC"
                ).fetchall()
        except sqlite3.Error as e:
            return AuditVerifyResult(ok=False, message=f"DB read error: {e}")

        if not rows:
            return AuditVerifyResult(ok=True, total_rows=0,
                                     message="No log rows — chain trivially valid.")

        prev_hash = _GENESIS_HASH
        missing = 0

        for idx, (row_id, action, details, timestamp, stored_hash) in enumerate(rows):
            if stored_hash is None:
                # Row predates chain; seed forward from computed value
                missing += 1
                prev_hash = self._compute_hash(
                    prev_hash, action or '', details or '', timestamp or ''
                )
                continue

            expected = self._compute_hash(
                prev_hash, action or '', details or '', timestamp or ''
            )
            if not hmac.compare_digest(expected, stored_hash):
                return AuditVerifyResult(
                    ok=False,
                    total_rows=len(rows),
                    first_broken_id=row_id,
                    broken_at_index=idx,
                    missing_hashes=missing,
                    message=(
                        f"Chain broken at row id={row_id} (index {idx}). "
                        "Log may have been tampered with."
                    )
                )
            prev_hash = stored_hash

        return AuditVerifyResult(
            ok=True,
            total_rows=len(rows),
            missing_hashes=missing,
            message=(
                f"Chain intact across {len(rows)} rows"
                + (f" ({missing} pre-chain rows skipped)." if missing else ".")
            )
        )

    def backfill_chain(self) -> int:
        """
        Compute and store chain_hash for any rows missing it.
        Returns the number of rows updated.
        """
        try:
            with self.db._conn() as conn:
                rows = conn.execute(
                    "SELECT id, action, details, timestamp, chain_hash "
                    "FROM activity_logs ORDER BY id ASC"
                ).fetchall()
        except sqlite3.Error:
            return 0

        prev_hash = _GENESIS_HASH
        updated = 0
        try:
            with self.db._conn() as conn:
                for row_id, action, details, timestamp, stored_hash in rows:
                    expected = self._compute_hash(
                        prev_hash, action or '', details or '', timestamp or ''
                    )
                    if stored_hash is None:
                        conn.execute(
                            "UPDATE activity_logs SET chain_hash=? WHERE id=?",
                            (expected, row_id)
                        )
                        updated += 1
                    prev_hash = stored_hash if stored_hash else expected
                conn.commit()
        except sqlite3.Error as e:
            print(f"[AuditManager] backfill error: {e}")

        return updated
