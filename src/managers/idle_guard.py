"""
ExamShield — Idle Guard (Layer 6)
Detects student absence by tracking last mouse/keyboard activity via the
Win32 GetLastInputInfo API. When idle for longer than Config.IDLE_ALERT_SEC,
captures a violation screenshot and logs a STUDENT_IDLE security event.

A cooldown (Config.IDLE_COOLDOWN_SEC) prevents flooding logs when the
student remains idle — alerts fire once per cooldown window.
"""
import ctypes
import ctypes.wintypes as wintypes
import threading
import time
from src.config import Config
from src.logger import ExamShieldLogger


class IdleGuard:
    """
    Polls GetLastInputInfo every second to compute idle time.
    When idle exceeds the configured threshold, fires a violation screenshot
    and logs STUDENT_IDLE.  Respects a cooldown so repeated alerts do not
    flood the log while the student is still absent.
    """

    def __init__(self, db_manager, screenshot_manager, security_manager=None):
        self.db_manager         = db_manager
        self.screenshot_manager = screenshot_manager
        self.security_manager   = security_manager   # optional: for breach counter + toast
        self.log                = ExamShieldLogger(db_manager)

        self.is_active   = False
        self._stop_event = threading.Event()
        self._thread     = None

        # Tracks the last time we fired an idle alert (avoids spam)
        self._last_alert_time: float = 0.0

    # ── Public API ────────────────────────────────────────────────
    def start(self):
        """Start idle monitoring."""
        if self.is_active:
            return
        self.is_active = True
        self._stop_event.clear()
        self._last_alert_time = 0.0
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="IdleGuard"
        )
        self._thread.start()
        self.log.info("IDLE_GUARD_START",
                      f"Idle guard started (threshold={Config.IDLE_ALERT_SEC}s, "
                      f"cooldown={Config.IDLE_COOLDOWN_SEC}s)")

    def stop(self):
        """Stop idle monitoring."""
        if not self.is_active:
            return
        self.is_active = False
        self._stop_event.set()
        self._thread = None
        self.log.info("IDLE_GUARD_STOP", "Idle guard stopped")

    # ── Idle time query ───────────────────────────────────────────
    @staticmethod
    def get_idle_seconds() -> float:
        """
        Return the number of seconds since the last mouse or keyboard input,
        using the Win32 GetLastInputInfo API.
        Returns 0.0 on any error (fail-safe: don't false-alarm on API failure).
        """
        try:
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.UINT),
                    ("dwTime", wintypes.DWORD),
                ]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                return 0.0

            # GetTickCount returns milliseconds since system boot
            tick_now  = ctypes.windll.kernel32.GetTickCount()
            idle_ms   = tick_now - lii.dwTime
            # Handle 32-bit tick rollover (~49.7 days uptime)
            if idle_ms < 0:
                idle_ms += 2 ** 32
            return idle_ms / 1000.0
        except Exception:
            return 0.0

    # ── Monitor loop ──────────────────────────────────────────────
    def _monitor_loop(self):
        threshold = Config.IDLE_ALERT_SEC
        cooldown  = Config.IDLE_COOLDOWN_SEC

        while self.is_active and not self._stop_event.is_set():
            try:
                idle_sec = self.get_idle_seconds()

                if idle_sec >= threshold:
                    now = time.monotonic()
                    # Only fire if outside cooldown window
                    if now - self._last_alert_time >= cooldown:
                        self._last_alert_time = now
                        self._fire_idle_alert(idle_sec)

            except Exception:
                pass

            # Poll every second — fine-grained enough, low CPU cost
            self._stop_event.wait(1.0)

    def _fire_idle_alert(self, idle_sec: float):
        """Called when the student has been idle beyond the threshold."""
        idle_min = idle_sec / 60.0
        self.log.security(
            "STUDENT_IDLE",
            f"Student idle for {idle_sec:.0f}s ({idle_min:.1f} min) — possible absence",
            blocked=False,
        )
        # Capture violation screenshot
        if self.screenshot_manager and self.screenshot_manager.is_active:
            self.screenshot_manager.capture_violation(reason="idle_absence")

        # Increment breach counter + show dashboard toast (best-effort)
        if self.security_manager is not None:
            try:
                # Re-use 'windows' breach bucket as closest semantic match
                self.security_manager.breach_counts.setdefault('idle', 0)
                self.security_manager.breach_counts['idle'] += 1
            except Exception:
                pass
            try:
                panel = self.security_manager.admin_panel
                if panel and hasattr(panel, 'window') and panel.window:
                    panel.window.after(
                        0,
                        lambda s=idle_sec: panel._toast(
                            f"⏱️  Student idle: {s:.0f}s — possible absence",
                            '#ffab40',
                        ) if hasattr(panel, '_toast') else None,
                    )
                    panel.window.after(0, panel.update_breach_counter)
            except Exception:
                pass

    # ── Accessor ──────────────────────────────────────────────────
    @property
    def idle_seconds(self) -> float:
        """Current idle duration in seconds (live read, works even when stopped)."""
        return self.get_idle_seconds()
