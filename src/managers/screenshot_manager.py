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
        self.count = 0          # screenshots taken this session
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

    # ── Core snap ────────────────────────────────────────────────
    def _snap(self, reason: str = "periodic"):
        if not self.session_dir or not PILLOW_AVAILABLE:
            return
        try:
            ts = datetime.datetime.now().strftime("%H%M%S_%f")[:12]
            filename = f"{ts}_{reason}.png"
            path = os.path.join(self.session_dir, filename)
            img = ImageGrab.grab()
            img.save(path, "PNG", optimize=True)
            with self._lock:
                self.count += 1
                # ── Layer 4: Append entry to session manifest ─────────────────
                self._append_manifest(filename, path, reason)
        except Exception as e:
            print(f"[Screenshot] Capture failed: {e}")

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
