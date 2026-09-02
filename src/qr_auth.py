"""
ExamShield v1.4.0 — QR Code Authentication
Generates a QR code containing a one-time auth token.
Scanning it with a phone authenticates the admin without typing a password.
"""
import io
import qrcode
import hashlib
import hmac
import secrets
import time
from PIL import Image, ImageTk

from src.config import Config
from src.logger import ExamShieldLogger


class QRAuth:
    """
    Two-part QR auth:
      1. Admin panel generates a QR containing a short-lived token.
      2. A phone/web client POSTs that token to a local endpoint to unlock.
    For now the QR is shown in a small Tkinter popup during login as an
    alternative to typing the password.
    """

    TOKEN_TTL_SEC = 60  # QR token valid for 60 seconds

    def __init__(self, db_manager, security_manager=None):
        self.db = db_manager
        self.log = ExamShieldLogger(db_manager)
        self._token = None
        self._token_expires = 0.0
        self._current_qr_image = None  # PIL Image, kept for reuse

    # ── Token management ────────────────────────────────────────────────
    def _generate_token(self) -> str:
        """Create a new one-time token and its expiry."""
        self._token = secrets.token_hex(16)
        self._token_expires = time.monotonic() + self.TOKEN_TTL_SEC
        return self._token

    def get_token(self) -> str | None:
        """Return a valid token, generating a new one if needed."""
        if self._token is None or time.monotonic() > self._token_expires:
            return self._generate_token()
        return self._token

    def invalidate_token(self):
        """Consume the current token so it can't be reused."""
        self._token = None

    def is_token_valid(self, token: str) -> bool:
        """Check a presented token against the active one."""
        if token != self._token:
            return False
        if time.monotonic() > self._token_expires:
            return False
        return True

    # ── QR generation ────────────────────────────────────────────────────
    def generate_qr_image(self, token: str | None = None) -> Image.Image:
        """
        Generate a PIL Image containing the QR code for the given token.
        The QR encodes a scheme-less URL the companion app can call back to.
        """
        tok = token or self.get_token()
        host = "localhost"
        port = 50999  # default companion listener port
        payload = f"examshield://auth/{tok}"
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        self._current_qr_image = img
        return img

    def qr_to_tk(self, img: Image.Image) -> ImageTk.PhotoImage:
        """Convert a PIL Image to a Tkinter-compatible PhotoImage."""
        return ImageTk.PhotoImage(img)

    # ── Token verification callback ──────────────────────────────────────
    def verify_token_callback(self, token: str) -> bool:
        """
        Called when the companion app/web client POSTs a token back.
        Returns True and invalidates the token on success.
        """
        if self.is_token_valid(token):
            self.invalidate_token()
            self.log.info("QR_AUTH_SUCCESS", f"Token accepted: {token[:8]}...")
            return True
        self.log.warning("QR_AUTH_FAIL", f"Invalid or expired token presented")
        return False
