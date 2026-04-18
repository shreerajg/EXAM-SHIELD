"""
ExamShield v1.0 — Mouse Manager
Uses a Win32 WH_MOUSE_LL low-level hook for reliable, process-agnostic
mouse blocking. pynput suppress=False + return False does NOT actually
block events — only a proper LL hook can intercept at OS level.
"""
import ctypes
import ctypes.wintypes as wintypes
import threading
import time
from logger import ExamShieldLogger
from config import Config

# ── Win32 constants ───────────────────────────────────────────────
WH_MOUSE_LL      = 14
WM_MOUSEMOVE     = 0x0200
WM_LBUTTONDOWN   = 0x0201
WM_LBUTTONUP     = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN   = 0x0204
WM_RBUTTONUP     = 0x0205
WM_RBUTTONDBLCLK = 0x0206
WM_MBUTTONDOWN   = 0x0207
WM_MBUTTONUP     = 0x0208
WM_MBUTTONDBLCLK = 0x0209
WM_XBUTTONDOWN   = 0x020B
WM_XBUTTONUP     = 0x020C

HC_ACTION = 0

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt",          wintypes.POINT),
        ("mouseData",   wintypes.DWORD),
        ("flags",       wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MouseManager:
    """
    Granular mouse blocking via a Win32 WH_MOUSE_LL hook.
    Flags:
        block_left     – suppress left-button press/release
        block_right    – suppress right-button press/release
        block_middle   – suppress middle-button press/release
        block_double   – suppress double-click messages
        block_side     – suppress X1/X2 (back/forward) buttons
        block_movement – warp cursor back to lock point on any move
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.log = ExamShieldLogger(db_manager)
        self.is_active = False
        self.blocked_buttons = []   # backwards-compat legacy list

        # Granular flags
        self.block_left     = False
        self.block_right    = False
        self.block_middle   = False
        self.block_double   = False
        self.block_side     = False
        self.block_movement = False

        # Internal
        self._lock        = threading.Lock()
        self._hook_id     = None
        self._hook_proc   = None   # must keep a reference or GC kills it
        self._hook_thread = None
        self._stop_evt    = threading.Event()
        self._lock_pos    = None   # (x, y) for movement lock

    # ── Public flag API ───────────────────────────────────────────
    def apply_flags(self, flags: dict):
        """Push checkbox dict into blocking flags."""
        self.block_left     = bool(flags.get('left',     False))
        self.block_right    = bool(flags.get('right',    False))
        self.block_middle   = bool(flags.get('middle',   False))
        self.block_double   = bool(flags.get('double',   False))
        self.block_side     = bool(flags.get('side',     False))
        self.block_movement = bool(flags.get('movement', False))
        self.blocked_buttons = [k for k, v in flags.items() if v]

    def get_flags(self) -> dict:
        return {
            'left':     self.block_left,
            'right':    self.block_right,
            'middle':   self.block_middle,
            'double':   self.block_double,
            'side':     self.block_side,
            'movement': self.block_movement,
        }

    # ── Start / Stop ──────────────────────────────────────────────
    def start_blocking(self, flags: dict = None):
        with self._lock:
            if self.is_active:
                return
            self.is_active = True

        if flags:
            self.apply_flags(flags)

        self._stop_evt.clear()
        self._lock_pos = None

        self._hook_thread = threading.Thread(
            target=self._hook_loop, daemon=True, name="MouseHook"
        )
        self._hook_thread.start()

        enabled = [k for k, v in self.get_flags().items() if v]
        self.log.info("MOUSE_BLOCKING_START",
                      f"Blocking: {', '.join(enabled) or 'none'}")

    def stop_blocking(self):
        with self._lock:
            if not self.is_active:
                return
            self.is_active = False

        self._stop_evt.set()
        # Post WM_QUIT to unblock GetMessage in the hook thread
        self._post_quit()
        self._lock_pos = None
        self.log.info("MOUSE_BLOCKING_STOP", "Mouse blocking deactivated")

    # ── Win32 hook thread ─────────────────────────────────────────
    def _hook_loop(self):
        """Install the LL hook then pump messages until stop is signalled."""

        def low_level_handler(nCode, wParam, lParam):
            if nCode == HC_ACTION and self.is_active:
                if self._should_block(wParam, lParam):
                    # Returning non-zero blocks the event from passing on
                    return 1
            return ctypes.windll.user32.CallNextHookEx(
                self._hook_id, nCode, wParam, lParam
            )

        self._hook_proc = HOOKPROC(low_level_handler)
        self._hook_id = ctypes.windll.user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self._hook_proc,
            ctypes.windll.kernel32.GetModuleHandleW(None),
            0,
        )

        if not self._hook_id:
            self.log.error("MOUSE_HOOK", "SetWindowsHookExW failed")
            with self._lock:
                self.is_active = False
            return

        msg = wintypes.MSG()
        while not self._stop_evt.is_set():
            ret = ctypes.windll.user32.PeekMessageW(
                ctypes.byref(msg), None, 0, 0, 1  # PM_REMOVE = 1
            )
            if ret:
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
            else:
                # Yield so we don't spin 100 % CPU
                self._stop_evt.wait(0.005)

        ctypes.windll.user32.UnhookWindowsHookEx(self._hook_id)
        self._hook_id   = None
        self._hook_proc = None

    def _post_quit(self):
        """Post WM_QUIT to the hook thread to unblock its message loop."""
        try:
            if self._hook_thread and self._hook_thread.is_alive():
                tid = ctypes.windll.kernel32.GetThreadId(
                    ctypes.c_void_p(self._hook_thread.ident)
                )
                ctypes.windll.user32.PostThreadMessageW(tid, 0x0012, 0, 0)
        except Exception:
            pass

    # ── Block decision ────────────────────────────────────────────
    def _should_block(self, wParam, lParam) -> bool:
        msg = wParam

        # Movement
        if msg == WM_MOUSEMOVE and self.block_movement:
            data = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            x, y = data.pt.x, data.pt.y
            if self._lock_pos is None:
                self._lock_pos = (x, y)
                return False   # let this first position through
            lx, ly = self._lock_pos
            if (x, y) != (lx, ly):
                self.log.security("BLOCKED_MOUSE",
                                  f"Movement blocked at ({x},{y})",
                                  blocked=True)
                # Warp cursor back
                ctypes.windll.user32.SetCursorPos(lx, ly)
                return True
            return False

        # Left button
        if msg in (WM_LBUTTONDOWN, WM_LBUTTONUP) and self.block_left:
            self.log.security("BLOCKED_MOUSE", "Left click blocked",
                              blocked=True)
            return True

        # Double-click (left)
        if msg == WM_LBUTTONDBLCLK and (self.block_double or self.block_left):
            self.log.security("BLOCKED_MOUSE", "Double-click blocked",
                              blocked=True)
            return True

        # Right button
        if msg in (WM_RBUTTONDOWN, WM_RBUTTONUP) and self.block_right:
            self.log.security("BLOCKED_MOUSE", "Right click blocked",
                              blocked=True)
            return True
        if msg == WM_RBUTTONDBLCLK and self.block_right:
            return True

        # Middle button
        if msg in (WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK) \
                and self.block_middle:
            self.log.security("BLOCKED_MOUSE", "Middle click blocked",
                              blocked=True)
            return True

        # Side / X buttons
        if msg in (WM_XBUTTONDOWN, WM_XBUTTONUP) and self.block_side:
            self.log.security("BLOCKED_MOUSE", "Side button blocked",
                              blocked=True)
            return True

        return False

    # ── Legacy helpers ────────────────────────────────────────────
    def add_blocked_button(self, name):
        if name not in self.blocked_buttons:
            self.blocked_buttons.append(name)

    def remove_blocked_button(self, name):
        if name in self.blocked_buttons:
            self.blocked_buttons.remove(name)
