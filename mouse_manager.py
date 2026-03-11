"""
ExamShield v1.0 — Mouse Manager
Full mouse control: block left/right/middle/double-click and movement.
"""
import threading
import time
from pynput import mouse as pynput_mouse
from config import Config
from logger import ExamShieldLogger


class MouseManager:
    """
    Granular mouse blocking.
    Supported block options (each is a bool flag):
        block_left     — suppress left button press
        block_right    — suppress right button press
        block_middle   — suppress middle button press
        block_double   — suppress double-clicks (two clicks within 400 ms)
        block_side     — suppress X1/X2/side buttons
        block_movement — freeze cursor movement (teleport back to lock point)
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.log = ExamShieldLogger(db_manager)
        self.is_active = False
        self.listener = None
        self._lock = threading.Lock()

        # ── Legacy list (used by settings persistence) ──
        # We keep blocked_buttons for backwards-compat with saved settings,
        # but the real flags live below.
        self.blocked_buttons = Config.BLOCKED_MOUSE_BUTTONS.copy()

        # ── Granular flags (default = off) ──────────────
        self.block_left     = False
        self.block_right    = False
        self.block_middle   = False
        self.block_double   = False
        self.block_side     = False
        self.block_movement = False

        # Internal state for double-click detection
        self._last_click_time = 0.0
        self._double_click_threshold = 0.40   # seconds

        # For movement lock
        self._lock_pos = None   # (x, y) to snap back to

    # ── Apply flags from the checkboxes dict ──────────────────────
    def apply_flags(self, flags: dict):
        """
        flags = {
            'left': bool, 'right': bool, 'middle': bool,
            'double': bool, 'side': bool, 'movement': bool
        }
        """
        self.block_left     = flags.get('left',     False)
        self.block_right    = flags.get('right',    False)
        self.block_middle   = flags.get('middle',   False)
        self.block_double   = flags.get('double',   False)
        self.block_side     = flags.get('side',     False)
        self.block_movement = flags.get('movement', False)

        # Sync legacy list so settings save works
        self.blocked_buttons = [
            k for k in ('left', 'right', 'middle', 'double', 'side',
                         'movement')
            if flags.get(k, False)
        ]

        if self.block_movement:
            # Start controller to snap cursor back
            self._controller = pynput_mouse.Controller()
        else:
            self._controller = None

    def get_flags(self) -> dict:
        return {
            'left':     self.block_left,
            'right':    self.block_right,
            'middle':   self.block_middle,
            'double':   self.block_double,
            'side':     self.block_side,
            'movement': self.block_movement,
        }

    # ── Start / Stop ─────────────────────────────────────────────
    def start_blocking(self, flags: dict = None):
        with self._lock:
            if self.is_active:
                return
            self.is_active = True

        if flags:
            self.apply_flags(flags)
        else:
            # Keep whatever flags were already set
            pass

        try:
            self.listener = pynput_mouse.Listener(
                on_click=self._on_click,
                on_move=self._on_move,
                suppress=False,          # we suppress selectively
            )
            self.listener.start()
            enabled = [k for k, v in self.get_flags().items() if v]
            self.log.info("MOUSE_BLOCKING_START",
                          f"Blocking: {', '.join(enabled) or 'none'}")
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
        self._lock_pos = None
        self.log.info("MOUSE_BLOCKING_STOP", "Mouse blocking deactivated")

    # ── pynput callbacks ──────────────────────────────────────────
    def _on_click(self, x, y, button, pressed):
        if not self.is_active or not pressed:
            return

        name = self._button_name(button)

        # Double-click detection
        if pressed and name == 'left' and self.block_double:
            now = time.time()
            gap = now - self._last_click_time
            self._last_click_time = now
            if gap < self._double_click_threshold:
                self.log.security("BLOCKED_MOUSE",
                                  f"Double-click at ({x},{y})", blocked=True)
                return False   # suppress

        # Per-button blocking
        should_block = False
        if name == 'left'   and self.block_left:     should_block = True
        if name == 'right'  and self.block_right:    should_block = True
        if name == 'middle' and self.block_middle:   should_block = True
        if name in ('x1', 'x2', 'side') and self.block_side:
            should_block = True

        if should_block:
            self.log.security("BLOCKED_MOUSE",
                              f"Blocked {name} at ({x},{y})", blocked=True)
            return False   # suppress

    def _on_move(self, x, y):
        if not self.is_active or not self.block_movement:
            return
        # Record lock position the first time
        if self._lock_pos is None:
            self._lock_pos = (x, y)
            return
        lx, ly = self._lock_pos
        if (x, y) != (lx, ly):
            self.log.security("BLOCKED_MOUSE",
                              f"Movement blocked at ({x},{y})", blocked=True)
            try:
                self._controller.position = (lx, ly)
            except Exception:
                pass

    # ── Button name helper ────────────────────────────────────────
    def _button_name(self, button) -> str:
        mapping = {
            pynput_mouse.Button.left:   'left',
            pynput_mouse.Button.right:  'right',
            pynput_mouse.Button.middle: 'middle',
        }
        if button in mapping:
            return mapping[button]
        if hasattr(button, 'value'):
            return {8: 'x1', 9: 'x2'}.get(button.value, 'side')
        if hasattr(button, 'name'):
            return button.name
        return 'unknown'

    # ── Legacy helpers (used by old settings code) ────────────────
    def add_blocked_button(self, name):
        if name not in self.blocked_buttons:
            self.blocked_buttons.append(name)

    def remove_blocked_button(self, name):
        if name in self.blocked_buttons:
            self.blocked_buttons.remove(name)
