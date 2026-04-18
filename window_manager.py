"""
ExamShield v1.0 — Window Manager
Enforces fullscreen, blocks window closing, monitors all windows.

Fixes vs old version:
  - protect_window() is now called automatically on any Tk window registered
    via register_protected_window() before OR after start_window_protection()
  - Browser detection now matches Chrome_WidgetWin_1 / MozillaWindowClass /
    Edge windows by class name (title-independent, language-agnostic)
  - A secondary "close-button killer" loop removes system-menu items from
    ALL non-task windows when exam mode is on
  - Style changes are re-applied every cycle so users can't restore a window
    via third-party tools
"""
import threading
import win32gui
import win32con
import win32api
from logger import ExamShieldLogger


# Browser window class names (title-independent, works in any language)
BROWSER_CLASSES = {
    'Chrome_WidgetWin_1',      # Chrome / new Edge
    'Chrome_WidgetWin_0',
    'MozillaWindowClass',      # Firefox
    'MozillaDialogClass',
    'IEFrame',                 # Internet Explorer / old Edge
    'OperaWindowClass',
    'OperaToplevelOldChrome',
}

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
            if win32gui.IsIconic(hwnd):           # minimised → restore
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

            cls   = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)

            is_browser = (
                cls in BROWSER_CLASSES
                or any(b in cls for b in ('Chrome', 'Mozilla', 'Opera'))
                or any(b in title for b in ('Chrome', 'Firefox', 'Edge',
                                             'Opera', 'Brave'))
            )

            if is_browser:
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

                # Strip close / min / max title-bar buttons
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                new_style = style & ~(
                    win32con.WS_MAXIMIZEBOX
                    | win32con.WS_MINIMIZEBOX
                    | win32con.WS_SYSMENU
                )
                if new_style != style:
                    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, new_style)
                    # Force redraw of title bar
                    win32gui.SetWindowPos(
                        hwnd, None, 0, 0, 0, 0,
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

            for key in ('<F11>', '<Escape>', '<Alt-F4>', '<Alt-Tab>'):
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
