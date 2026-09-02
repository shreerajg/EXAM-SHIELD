"""
ExamShield v1.0 — Screenshot Manager
Periodic and violation-triggered screenshot capture during exam lockdown.
"""
import hashlib
import json
import os
import threading
import datetime

try:
    from PIL import ImageGrab
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

from src.config import Config


class ScreenshotManager:
    """
    Captures screenshots periodically and on demand (e.g. on security violations).
    Saves images to  logs/screenshots/<session_date>/  folder.
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self.is_active = False
        self._stop_event = threading.Event()
        self._thread = None
        self.session_dir = None
        self.session_id = ""        # short label burned into watermark
        self.count = 0              # screenshots taken this session
        self._lock = threading.Lock()

    # ── Session lifecycle ────────────────────────────────────────
    def start(self, session_label: str = ""):
        if not PILLOW_AVAILABLE:
            print("[Screenshot] Pillow not installed — screenshots disabled.")
            return False
        if self.is_active:
            return True

        # Create session folder
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        label = session_label.replace(" ", "_") or "session"
        folder = os.path.join(Config.SCREENSHOT_DIR, f"{ts}_{label}")
        os.makedirs(folder, exist_ok=True)
        self.session_dir = folder
        self.session_id = label[:8]   # first 8 chars used in watermark
        self.count = 0
        self.is_active = True
        self._stop_event.clear()

        # Start periodic capture thread
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True
        )
        self._thread.start()
        return True

    def stop(self):
        self.is_active = False
        self._stop_event.set()
        self._thread = None

    # ── Periodic capture loop ────────────────────────────────────
    def _capture_loop(self):
        interval = Config.SCREENSHOT_INTERVAL_SEC
        while self.is_active and not self._stop_event.is_set():
            self._snap(reason="periodic")
            self._stop_event.wait(interval)

    # ── On-demand capture (call from security violations) ────────
    def capture_violation(self, reason: str = "violation"):
        """Capture immediately due to a security event."""
        if self.is_active and PILLOW_AVAILABLE:
            threading.Thread(
                target=self._snap, args=(reason,), daemon=True
            ).start()

    # ── Core snap ───────────────────────────────────────────
    def _snap(self, reason: str = "periodic"):
        if not self.session_dir or not PILLOW_AVAILABLE:
            return
        try:
            ts = datetime.datetime.now().strftime("%H%M%S_%f")[:12]
            filename = f"{ts}_{reason}.png"
            path = os.path.join(self.session_dir, filename)
            img = Imagegrab.grab()

            img = self._watermark(img, reason)

            if Config.SCREENSHOT_BLUR:
                img = self._blur(img)

            img.save(path, "PNG", optimize=True)
            with self._lock:
                self.count += 1
                # ── Layer 4: Append entry to session manifest ─────────────
                self._append_manifest(filename, path, reason)
        except Exception as e:
            print(f"[Screenshot] Capture failed: {e}")

    # ── E6: Watermark helper ────────────────────────────────────
    def _watermark(self, img, reason: str):
        """
        Burn a semi-transparent provenance strip onto the bottom-right corner:
            Session : <session_id>   Time : HH:MM:SS   Reason : <reason>
        Falls back gracefully if Pillow fonts or ImageDraw are unavailable.
        """
        try:
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(img, 'RGBA')

            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            text = (
                f" Session: {self.session_id}  │  "
                f"{now_str}  │  {reason} "
            )

            # Try loading a monospace font; fall back to default
            try:
                font = ImageFont.truetype("cour.ttf", 14)
            except Exception:
                try:
                    font = ImageFont.truetype("DejaVuSansMono.ttf", 14)
                except Exception:
                    font = ImageFont.load_default()

            # Measure text bounding box
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            img_w, img_h = img.size
            pad = 6
            x = img_w - text_w - pad * 2
            y = img_h - text_h - pad * 2

            # Semi-transparent dark background pill
            draw.rectangle(
                [x - pad, y - pad, img_w, img_h],
                fill=(0, 0, 0, 160)
            )
            # White text
            draw.text((x, y), text, fill=(220, 220, 220, 255), font=font)
        except Exception:
            pass  # never crash the screenshot capture
        return img

    # ── Privacy blur ─────────────────────────────────────────────
    def _blur(self, img):
        """Apply GaussianBlur to screenshot for privacy (only if enabled)."""
        from PIL import ImageFilter
        if not getattr(Config, 'SCREENSHOT_BLUR', False):
            return img
        radius = 8
        return img.filter(ImageFilter.GaussianBlur(radius))

    def _append_manifest(self, filename: str, path: str, reason: str):
        """
        Layer 4: Append a tamper-evident entry to session_manifest.json.
        Each entry contains the filename, SHA-256 hash of the saved PNG,
        the capture timestamp, and the trigger reason.
        """
        try:
            # Compute SHA-256 of the saved image file
            sha256 = ""
            try:
                with open(path, 'rb') as f:
                    sha256 = hashlib.sha256(f.read()).hexdigest()
            except Exception:
                pass

            entry = {
                "filename":  filename,
                "sha256":    sha256,
                "timestamp": datetime.datetime.now().isoformat(),
                "reason":    reason,
            }

            manifest_path = os.path.join(self.session_dir, "session_manifest.json")
            # Load existing entries or start fresh
            entries = []
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as mf:
                        entries = json.load(mf)
                except Exception:
                    entries = []
            entries.append(entry)
            with open(manifest_path, 'w', encoding='utf-8') as mf:
                json.dump(entries, mf, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Screenshot] Manifest update failed: {e}")

    # ── Accessors ────────────────────────────────────────────────
    @property
    def available(self) -> bool:
        return PILLOW_AVAILABLE

    def get_session_dir(self) -> str:
        return self.session_dir or ""

    def get_count(self) -> int:
        with self._lock:
            return self.count
