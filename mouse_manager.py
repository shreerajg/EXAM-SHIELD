"""
ExamShield v1.0 — Mouse Manager
Low-level mouse button suppression via pynput.
"""
import threading
from pynput import mouse as pynput_mouse
from config import Config
from logger import ExamShieldLogger


class MouseManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.log = ExamShieldLogger(db_manager)
        self.is_active = False
        self.listener = None
        self.blocked_buttons = Config.BLOCKED_MOUSE_BUTTONS.copy()
        self._lock = threading.Lock()

    # ── Start / Stop ─────────────────────────────────────────────
    def start_blocking(self):
        with self._lock:
            if self.is_active:
                return
            self.is_active = True
        try:
            self.listener = pynput_mouse.Listener(
                on_click=self._on_click,
                suppress=True,
                win32_event_filter=self._win32_filter,
            )
            self.listener.start()
            self.log.info("MOUSE_BLOCKING_START",
                          f"Blocking: {', '.join(self.blocked_buttons)}")
        except Exception as e:
            self.log.error("MOUSE_BLOCKING", f"Start failed: {e}")
            with self._lock:
                self.is_active = False

    def stop_blocking(self):
        with self._lock:
            if not self.is_active:
                return
            self.is_active = False
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None
        self.log.info("MOUSE_BLOCKING_STOP", "Mouse blocking deactivated")

    # ── Win32 low-level filter ───────────────────────────────────
    def _win32_filter(self, msg, data):
        if not self.is_active:
            return True
        blocked_msgs = set()
        if 'middle' in self.blocked_buttons:
            blocked_msgs.update({0x0207, 0x0208})
        if any(b in self.blocked_buttons for b in ('x1', 'x2', 'side')):
            blocked_msgs.update({0x020B, 0x020C})
        if msg in blocked_msgs:
            btn = self._button_from_msg(msg, data)
            self.log.security("BLOCKED_MOUSE", f"Blocked {btn} button", blocked=True)
            self.listener.suppress_event()
            return False
        return True

    def _button_from_msg(self, msg, data):
        if msg in (0x0207, 0x0208):
            return "middle"
        if msg in (0x020B, 0x020C):
            if hasattr(data, 'mouseData'):
                hi = data.mouseData >> 16
                if hi == 1:
                    return "x1"
                if hi == 2:
                    return "x2"
            return "side"
        return "unknown"

    # ── pynput callback ──────────────────────────────────────────
    def _on_click(self, x, y, button, pressed):
        if not self.is_active or not pressed:
            return True
        name = self._button_name(button)
        if name in self.blocked_buttons:
            self.log.security("BLOCKED_MOUSE",
                              f"Blocked {name} at ({x},{y})", blocked=True)
            return False
        return True

    def _button_name(self, button):
        mapping = {
            pynput_mouse.Button.left: 'left',
            pynput_mouse.Button.right: 'right',
            pynput_mouse.Button.middle: 'middle',
        }
        if button in mapping:
            return mapping[button]
        if hasattr(button, 'value'):
            return {8: 'x1', 9: 'x2'}.get(button.value, 'unknown')
        if hasattr(button, 'name'):
            return button.name
        return 'unknown'

    # ── Dynamic list management ──────────────────────────────────
    def add_blocked_button(self, name):
        if name not in self.blocked_buttons:
            self.blocked_buttons.append(name)

    def remove_blocked_button(self, name):
        if name in self.blocked_buttons:
            self.blocked_buttons.remove(name)
