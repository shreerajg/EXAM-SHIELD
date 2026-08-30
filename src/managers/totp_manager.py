"""
ExamShield v1.4.0 — TOTP Manager
Google Authenticator-compatible Two-Factor Authentication (TOTP / RFC 6238).

Usage flow:
  1. Admin enables 2FA in Settings → TOTPManager.generate_secret(username) called.
  2. QR code is shown via build_qr_image() → admin scans with Google Authenticator.
  3. On next login: after password OK, verify_code(username, code) must return True.
"""
import hmac
import base64

try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False

try:
    import qrcode
    from PIL import Image
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False


class TOTPManager:
    """Manages TOTP secret generation, QR rendering and code verification."""

    APP_NAME = "ExamShield"
    # DB key prefix: totp_secret_<username>
    _KEY_PREFIX = "totp_secret_"
    _ENABLED_KEY = "totp_enabled"

    def __init__(self, db_manager):
        self.db = db_manager

    # ── Availability ──────────────────────────────────────────────
    @staticmethod
    def is_available() -> bool:
        return PYOTP_AVAILABLE

    # ── Enable / disable ─────────────────────────────────────────
    def is_enabled(self) -> bool:
        return self.db.get_setting(self._ENABLED_KEY, "0") == "1"

    def set_enabled(self, enabled: bool):
        self.db.save_setting(self._ENABLED_KEY, "1" if enabled else "0")

    # ── Secret management ────────────────────────────────────────
    def _secret_key(self, username: str) -> str:
        return f"{self._KEY_PREFIX}{username}"

    def has_secret(self, username: str) -> bool:
        return self.db.get_setting(self._secret_key(username)) is not None

    def generate_secret(self, username: str) -> str:
        """Generate and persist a new TOTP secret. Returns the base32 secret."""
        if not PYOTP_AVAILABLE:
            raise RuntimeError("pyotp is not installed.")
        secret = pyotp.random_base32()
        self.db.save_setting(self._secret_key(username), secret)
        return secret

    def get_secret(self, username: str) -> str | None:
        """Return the stored base32 secret, or None if not enrolled."""
        return self.db.get_setting(self._secret_key(username))

    def delete_secret(self, username: str):
        """Remove stored secret (disable 2FA for user)."""
        try:
            with self.db._conn() as conn:
                conn.execute("DELETE FROM settings WHERE key=?",
                             (self._secret_key(username),))
                conn.commit()
        except Exception:
            pass

    # ── Verification ─────────────────────────────────────────────
    def verify_code(self, username: str, code: str) -> bool:
        """
        Verify a 6-digit TOTP code. Accepts ±1 time step (30 s window).
        Returns True on match, False otherwise.
        """
        if not PYOTP_AVAILABLE:
            return False
        secret = self.get_secret(username)
        if not secret:
            return False
        try:
            totp = pyotp.TOTP(secret)
            return totp.verify(code.strip(), valid_window=1)
        except Exception:
            return False

    # ── QR code generation ────────────────────────────────────────
    def get_provisioning_uri(self, username: str) -> str | None:
        """Return the otpauth:// URI for QR code generation."""
        if not PYOTP_AVAILABLE:
            return None
        secret = self.get_secret(username)
        if not secret:
            return None
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(
            name=username,
            issuer_name=self.APP_NAME
        )

    def build_qr_image(self, username: str, box_size: int = 8,
                       border: int = 4) -> "Image.Image | None":
        """
        Build a PIL Image of the QR code for the given user's secret.
        Returns None if dependencies are missing or no secret is stored.
        """
        if not QRCODE_AVAILABLE or not PYOTP_AVAILABLE:
            return None
        uri = self.get_provisioning_uri(username)
        if not uri:
            return None
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=box_size,
            border=border,
        )
        qr.add_data(uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        return img.convert("RGB")

    def get_current_code(self, username: str) -> str | None:
        """Return the current TOTP code (for testing/display only)."""
        if not PYOTP_AVAILABLE:
            return None
        secret = self.get_secret(username)
        if not secret:
            return None
        return pyotp.TOTP(secret).now()
