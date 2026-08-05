"""
ExamShield v1.0 — Window Manager
Enforces fullscreen on browsers, blocks window closing, monitors all windows.

Fixed issues:
  - SW_SHOWMAXIMIZED used (not SW_RESTORE then SW_MAXIMIZE — race condition)
  - WS_MINIMIZEBOX stripping scoped to real app windows only;
    system classes (Shell_TrayWnd, Progman, etc.) are never touched
  - Per-HWND exception handling so one bad window can't abort enumeration
  - SetWindowLongPtr (64-bit safe) used via ctypes instead of win32gui wrapper
  - Child-window guard: GetParent(hwnd) check skips parented sub-windows
  - Interval bumped to 1.0 s to reduce CPU overhead
"""
import threading
import ctypes
import win32gui
import win32con
import win32api
from src.logger import ExamShieldLogger

# ── Win32 helpers (64-bit safe) ──────────────────────────────────────────────
_user32 = ctypes.windll.user32

GWL_STYLE = -16

def _get_style(hwnd: int) -> int:
    return _user32.GetWindowLongPtrW(hwnd, GWL_STYLE)

def _set_style(hwnd: int, style: int) -> None:
    _user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)

def _redraw_frame(hwnd: int) -> None:
    _user32.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
        win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED
    )

# ── Browser class names (title-independent, locale-agnostic) ─────────────────
BROWSER_CLASSES = {
    'Chrome_WidgetWin_1',       # Chrome / new Edge (Chromium)
    'Chrome_WidgetWin_0',
    'MozillaWindowClass',        # Firefox
    'MozillaDialogClass',
    'IEFrame',                   # Internet Explorer / legacy Edge
    'OperaWindowClass',
    'OperaToplevelOldChrome',
}

# Browser title keywords (fallback when class name doesn't match)
BROWSER_TITLE_KEYWORDS = (
    'Chrome', 'Firefox', 'Edge', 'Opera', 'Brave', 'Internet Explorer'
)

# System/shell window classes — NEVER modify these
SYSTEM_CLASSES = {
    'Shell_TrayWnd',                         # Windows Taskbar
    'Shell_SecondaryTrayWnd',                # Multi-monitor taskbar
    'Progman',                               # Desktop
    'WorkerW',                               # Desktop wallpaper layer
    'DV2ControlHost',                        # Start menu host
    'NotifyIconOverflowWindow',              # System tray overflow
    'TopLevelWindowForOverflowXamlIsland',
    'Windows.UI.Core.CoreWindow',            # UWP shell windows
    'XamlExplorerHostIslandWindow',
    'ApplicationFrameWindow',               # UWP app frame
    'ForegroundStaging',
    'OleMainThreadWndClass',
    'tooltips_class32',                      # Tooltip bubbles
    'SysShadow',                             # Window drop-shadow
    'IME',
    'MSCTFIME UI',
}


class WindowManager:
    def __init__(self, db_manager):
        self.db_manager  = db_manager
        self.log         = ExamShieldLogger(db_manager)
        self.is_active   = False
        self._stop_event = threading.Event()
        self._thread     = None

        # Tk windows registered for close-button protection
        # These persist across start/stop so you can register early
        self._protected_tk: list = []

    # ── Public API ───────────────────────────────────────────────────────────

    def register_protected_window(self, window, name: str = "Window"):
        """
        Register a Tk window so it gets close-button protection
        whenever exam mode is active.  Safe to call before or after
        start_window_protection().
        """
        entry = {'win': window, 'name': name}
        if entry not in self._protected_tk:
            self._protected_tk.append(entry)
        if self.is_active:
            self._protect_tk(window, name)

    def start_window_protection(self):
        if self.is_active:
            return
        self.is_active = True
        self._stop_event.clear()

        # Apply close-button block to all already-registered Tk windows
        for e in self._protected_tk:
            self._protect_tk(e['win'], e['name'])

        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="WinProtect"
        )
        self._thread.start()
        self.log.info("WIN_PROTECT_START", "Window protection activated")

    def stop_window_protection(self):
        if not self.is_active:
            return
        self.is_active = False
        self._stop_event.set()

        # Restore normal close behaviour on all registered Tk windows
        for e in self._protected_tk:
            try:
                e['win'].protocol("WM_DELETE_WINDOW", e['win'].destroy)
            except Exception:
                pass
        self.log.info("WIN_PROTECT_STOP", "Window protection deactivated")

    # Keep the old name so SecurityManager still works
    def protect_window(self, window, window_name="Unknown"):
        self.register_protected_window(window, window_name)

    # ── Tk close-button block ────────────────────────────────────────────────

    def _protect_tk(self, window, name: str):
        def _blocked_close():
            self.log.security("BLOCKED_WIN_CLOSE",
                              f"Blocked close: {name}", blocked=True)
            try:
                import tkinter.messagebox as mb
                mb.showwarning(
                    "🔒  Access Denied",
                    "Window closing is disabled during exam mode.\n\n"
                    "Ask the invigilator to end the session.",
                    parent=window,
                )
            except Exception:
                pass
        try:
            window.protocol("WM_DELETE_WINDOW", _blocked_close)
        except Exception:
            pass

    # ── Monitor loop ─────────────────────────────────────────────────────────

    def _monitor_loop(self):
        while not self._stop_event.is_set():
            try:
                self._enforce_all_windows()
            except Exception as e:
                self.log.error("WIN_MONITOR", str(e), db=False)
            self._stop_event.wait(1.0)          # 1 s interval — less CPU

    def _enforce_all_windows(self):
        """
        For every real visible top-level window:
          • Browser  → force SW_SHOWMAXIMIZED + strip close/min/max buttons
          • Any app  → strip WS_MINIMIZEBOX (disable minimize button)
          • System   → skip entirely
        """
        sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        def _cb(hwnd, _):
            try:
                # ── Basic visibility / sanity checks ─────────────────
                if not win32gui.IsWindowVisible(hwnd):
                    return True

                cls   = win32gui.GetClassName(hwnd)
                title = win32gui.GetWindowText(hwnd)

                # Never touch system / shell windows
                if cls in SYSTEM_CLASSES:
                    return True

                # Skip child windows (EnumWindows returns top-level only,
                # but some utility windows have a hidden parent)
                if _user32.GetParent(hwnd) != 0:
                    return True

                # ── Classify ─────────────────────────────────────────
                is_browser = (
                    cls in BROWSER_CLASSES
                    or any(b in cls for b in ('Chrome', 'Mozilla', 'Opera'))
                    or any(kw in title for kw in BROWSER_TITLE_KEYWORDS)
                )

                current_style = _get_style(hwnd)

                if is_browser:
                    # Single call handles both restore-from-iconic and maximize
                    if win32gui.IsIconic(hwnd):
                        win32gui.ShowWindow(hwnd, win32con.SW_SHOWMAXIMIZED)
                        self.log.security(
                            "ENFORCED_FULLSCREEN",
                            f"Restored+maximized: {title or cls}",
                            blocked=False
                        )
                    else:
                        rect = win32gui.GetWindowRect(hwnd)
                        w = rect[2] - rect[0]
                        h = rect[3] - rect[1]
                        if w < sw * 0.90 or h < sh * 0.90:
                            win32gui.ShowWindow(hwnd, win32con.SW_SHOWMAXIMIZED)
                            self.log.security(
                                "ENFORCED_FULLSCREEN",
                                f"Forced max: {title or cls}",
                                blocked=False
                            )

                    # Strip all title-bar controls from browsers
                    desired_style = current_style & ~(
                        win32con.WS_MAXIMIZEBOX |
                        win32con.WS_MINIMIZEBOX |
                        win32con.WS_SYSMENU
                    )
                else:
                    # Other app windows: only remove minimize button
                    # so the student can't hide a window but can still use it
                    desired_style = current_style & ~win32con.WS_MINIMIZEBOX

                # Only write + redraw if the style actually changed
                if desired_style != current_style:
                    _set_style(hwnd, desired_style)
                    _redraw_frame(hwnd)

            except Exception:
                # Never let a single bad HWND abort the whole enumeration
                pass
            return True

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception as e:
            self.log.error("WIN_ENUM", str(e), db=False)

    # ── Force a Tk window fullscreen ─────────────────────────────────────────

    def force_fullscreen(self, window):
        if not window:
            return
        try:
            window.attributes('-fullscreen', True)
            window.attributes('-topmost', True)

            def _block(event):
                self.log.security("BLOCKED_FS_EXIT",
                                  f"Blocked {event.keysym}", blocked=True)
                return "break"

            for key in ('<F11>', '<Escape>'):
                window.bind(key, _block)
        except Exception as e:
            self.log.error("FULLSCREEN", f"Error: {e}")

    # ── Secure Browser Launcher ──────────────────────────────────────────────

    def launch_secure_browser(self, url="about:blank"):
        import os, subprocess
        chrome_args = [
            '--kiosk', '--no-default-browser-check', '--no-first-run',
            '--disable-default-apps', '--disable-popup-blocking',
            '--disable-translate', '--disable-extensions',
            '--disable-sync', '--disable-background-networking',
        ]
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for path in chrome_paths:
            if os.path.exists(path):
                subprocess.Popen([path] + chrome_args + [url])
                self.log.info("LAUNCH_BROWSER", f"Kiosk browser: {path}")
                return
        self.log.warning("LAUNCH_BROWSER", "No supported browser found")



# Additional processes whose top-level windows should be fullscreened
BROWSER_EXES = {
    'chrome.exe', 'firefox.exe', 'msedge.exe',
    'opera.exe', 'brave.exe', 'iexplore.exe',
}


class WindowManager:
    def __init__(self, db_manager):
        self.db_manager   = db_manager
        self.log          = ExamShieldLogger(db_manager)
        self.is_active    = False
        self._stop_event  = threading.Event()
        self._thread      = None

        # Tk windows registered for close-button protection
        # These persist across start/stop so you can register early
        self._protected_tk: list = []

    # ── Public API ────────────────────────────────────────────────

    def register_protected_window(self, window, name: str = "Window"):
        """
        Register a Tk window so it gets close-button protection
        whenever exam mode is active.  Safe to call before or after
        start_window_protection().
        """
        entry = {'win': window, 'name': name}
        if entry not in self._protected_tk:
            self._protected_tk.append(entry)
        if self.is_active:
            self._protect_tk(window, name)

    def start_window_protection(self):
        if self.is_active:
            return
        self.is_active = True
        self._stop_event.clear()

        # Apply close-button block to all already-registered Tk windows
        for e in self._protected_tk:
            self._protect_tk(e['win'], e['name'])

        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="WinProtect"
        )
        self._thread.start()
        self.log.info("WIN_PROTECT_START", "Window protection activated")

    def stop_window_protection(self):
        if not self.is_active:
            return
        self.is_active = False
        self._stop_event.set()

        # Restore normal close behaviour on all registered Tk windows
        for e in self._protected_tk:
            try:
                e['win'].protocol("WM_DELETE_WINDOW", e['win'].destroy)
            except Exception:
                pass
        self.log.info("WIN_PROTECT_STOP", "Window protection deactivated")

    # Keep the old name so SecurityManager still works
    def protect_window(self, window, window_name="Unknown"):
        self.register_protected_window(window, window_name)

    # ── Tk close-button block ─────────────────────────────────────

    def _protect_tk(self, window, name: str):
        def _blocked_close():
            self.log.security("BLOCKED_WIN_CLOSE",
                              f"Blocked close: {name}", blocked=True)
            try:
                import tkinter.messagebox as mb
                mb.showwarning(
                    "🔒  Access Denied",
                    "Window closing is disabled during exam mode.\n\n"
                    "Ask the invigilator to end the session.",
                    parent=window,
                )
            except Exception:
                pass
        try:
            window.protocol("WM_DELETE_WINDOW", _blocked_close)
        except Exception:
            pass

    # ── Monitor loop ──────────────────────────────────────────────

    def _monitor_loop(self):
        while not self._stop_event.is_set():
            try:
                self._enforce_all_windows()
            except Exception as e:
                self.log.error("WIN_MONITOR", str(e), db=False)
            self._stop_event.wait(0.8)

    def _enforce_all_windows(self):
        """
        For every visible top-level window:
        1. If it is a browser → force maximised + strip close/min/max buttons
        2. Always: strip the WS_MINIMIZEBOX style so the taskbar can't be
           used to minimise it to a tiny thumbnail
        """
        sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True

            cls   = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)

            is_browser = (
                cls in BROWSER_CLASSES
                or any(b in cls for b in ('Chrome', 'Mozilla', 'Opera'))
                or any(b in title for b in ('Chrome', 'Firefox', 'Edge',
                                             'Opera', 'Brave'))
            )

            if is_browser:
                if win32gui.IsIconic(hwnd):           # minimised → restore
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

                # Maximise if not already covering ≥90 % of the screen
                rect = win32gui.GetWindowRect(hwnd)
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                if w < sw * 0.90 or h < sh * 0.90:
                    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                    self.log.security(
                        "ENFORCED_FULLSCREEN",
                        f"Forced max: {title or cls}", blocked=False
                    )

            # Strip WS_MINIMIZEBOX from ALL visible windows to prevent hiding
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            if is_browser:
                new_style = style & ~(win32con.WS_MAXIMIZEBOX | win32con.WS_MINIMIZEBOX | win32con.WS_SYSMENU)
            else:
                new_style = style & ~win32con.WS_MINIMIZEBOX

            if new_style != style:
                win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, new_style)
                # Force redraw of title bar
                win32gui.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                    | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED
                )

            return True

        win32gui.EnumWindows(_cb, None)

    # ── Force a Tk window fullscreen ──────────────────────────────

    def force_fullscreen(self, window):
        if not window:
            return
        try:
            window.attributes('-fullscreen', True)
            window.attributes('-topmost', True)

            def _block(event):
                self.log.security("BLOCKED_FS_EXIT",
                                  f"Blocked {event.keysym}", blocked=True)
                return "break"

            for key in ('<F11>', '<Escape>'):
                window.bind(key, _block)
        except Exception as e:
            self.log.error("FULLSCREEN", f"Error: {e}")

    # ── Secure Browser Launcher ───────────────────────────────────

    def launch_secure_browser(self, url="about:blank"):
        import os, subprocess
        chrome_args = [
            '--kiosk', '--no-default-browser-check', '--no-first-run',
            '--disable-default-apps', '--disable-popup-blocking',
            '--disable-translate', '--disable-extensions',
            '--disable-sync', '--disable-background-networking',
        ]
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for path in chrome_paths:
            if os.path.exists(path):
                subprocess.Popen([path] + chrome_args + [url])
                self.log.info("LAUNCH_BROWSER", f"Kiosk browser: {path}")
                return
        self.log.warning("LAUNCH_BROWSER", "No supported browser found")
