"""
ExamShield v1.0 — Profile Manager
Save and load named exam configuration profiles.
Each profile stores: modules, blocked keys, blocked websites, timer duration.
"""
import json
import datetime
from src.config import Config


class ProfileManager:
    """
    Wraps the DB to provide save/load/delete of named exam profiles.
    A profile is stored as a JSON blob in the 'settings' table under
    the key  'profile:<name>'.
    """

    PREFIX = "profile:"

    def __init__(self, db_manager):
        self.db = db_manager

    # ── CRUD ─────────────────────────────────────────────────────
    def save_profile(self, name: str, data: dict) -> bool:
        """
        Persist a profile.
        data keys expected:
          modules        : dict[str, bool]
          blocked_keys   : list[str]
          blocked_websites: list[str]
          timer_minutes  : int
          description    : str (optional)
        """
        if not name.strip():
            return False
        data['saved_at'] = datetime.datetime.now().isoformat()
        data['name'] = name.strip()
        key = self.PREFIX + name.strip()
        self.db.save_setting(key, json.dumps(data))
        return True

    def load_profile(self, name: str) -> dict | None:
        """Return the profile dict, or None if not found."""
        key = self.PREFIX + name.strip()
        raw = self.db.get_setting(key)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def delete_profile(self, name: str) -> bool:
        """Remove a profile from the DB."""
        try:
            with self.db._conn() as conn:
                conn.execute(
                    "DELETE FROM settings WHERE key=?",
                    (self.PREFIX + name.strip(),)
                )
                conn.commit()
            return True
        except Exception:
            return False

    def list_profiles(self) -> list[dict]:
        """Return all saved profiles as a list of dicts (sorted by name)."""
        try:
            with self.db._conn() as conn:
                rows = conn.execute(
                    "SELECT key, value FROM settings WHERE key LIKE ?",
                    (self.PREFIX + '%',)
                ).fetchall()
            profiles = []
            for _, raw in rows:
                try:
                    profiles.append(json.loads(raw))
                except Exception:
                    pass
            return sorted(profiles, key=lambda p: p.get('name', '').lower())
        except Exception:
            return []

    # ── Convenience ──────────────────────────────────────────────
    def profile_names(self) -> list[str]:
        return [p['name'] for p in self.list_profiles()]

    def build_from_current(self, name: str, description: str,
                           modules: dict, blocked_keys: list,
                           blocked_websites: list,
                           timer_minutes: int = 0) -> bool:
        """Create a profile snapshot from the current session settings."""
        data = {
            'description': description,
            'modules': modules,
            'blocked_keys': blocked_keys,
            'blocked_websites': blocked_websites,
            'timer_minutes': timer_minutes,
        }
        return self.save_profile(name, data)

    # ── Built-in defaults ────────────────────────────────────────
    def ensure_defaults(self):
        """Create sensible default profiles if none exist."""
        if self.list_profiles():
            return
        # Full lockdown
        self.save_profile("Full Lockdown", {
            'description': 'Maximum security — all modules enabled',
            'modules': {k: True for k in Config.SELECTIVE_BLOCKING},
            'blocked_keys': Config.BLOCKED_KEYS[:],
            'blocked_websites': Config.BLOCKED_WEBSITES[:],
            'timer_minutes': 180,
        })
        # Internet-only
        self.save_profile("Internet Block Only", {
            'description': 'Block internet access only',
            'modules': {
                'keyboard': False, 'mouse': False,
                'internet': True,  'windows': False,
                'processes': False, 'usb': False,
            },
            'blocked_keys': [],
            'blocked_websites': Config.BLOCKED_WEBSITES[:],
            'timer_minutes': 0,
        })
        # Practical / lab exam
        self.save_profile("Lab / Practical", {
            'description': 'Mouse free, keyboard restricted, USB blocked',
            'modules': {
                'keyboard': True, 'mouse': False,
                'internet': True, 'windows': True,
                'processes': True, 'usb': True,
            },
            'blocked_keys': Config.BLOCKED_KEYS[:],
            'blocked_websites': Config.BLOCKED_WEBSITES[:],
            'timer_minutes': 120,
        })
