"""
ExamShield v1.0 — Window Manager
Enforces fullscreen, blocks window closing, monitors browsers.
"""
import os
import threading
import time
import subprocess
import psutil
import win32gui
import win32con
import win32api
from logger import ExamShieldLogger


class WindowManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.log = ExamShieldLogger(db_manager)
        self.is_active = False
        self.blocked_windows = []
        self._stop_event = threading.Event()
        self._thread = None
        self.fullscreen_processes = ['chrome.exe', 'firefox.exe', 'msedge.exe', 'opera.exe']

    # ── Start / Stop ─────────────────────────────────────────────
    def start_window_protection(self):
        if self.is_active:
            return
        self.is_active = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        self.log.info("WIN_PROTECT_START", "Window protection activated")

    def stop_window_protection(self):
        if not self.is_active:
            return
        self.is_active = False
        self._stop_event.set()
        for win in self.blocked_windows:
            try:
                win.protocol("WM_DELETE_WINDOW", win.destroy)
            except Exception:
                pass
        self.blocked_windows.clear()
        self.log.info("WIN_PROTECT_STOP", "Window protection deactivated")

    # ── Protect a Tk window ──────────────────────────────────────
    def protect_window(self, window, window_name="Unknown"):
        if not self.is_active:
            return

        def blocked_close():
            self.log.security("BLOCKED_WIN_CLOSE",
                              f"Blocked close: {window_name}", blocked=True)
            try:
                import tkinter.messagebox as mb
                mb.showwarning("Access Denied",
                               "Window closing is disabled during exam mode.",
                               parent=window)
            except Exception:
                pass

        window.protocol("WM_DELETE_WINDOW", blocked_close)
        self.blocked_windows.append(window)

    # ── Monitor Loop ─────────────────────────────────────────────
    def _monitor_loop(self):
        while not self._stop_event.is_set():
            try:
                self._enforce_browser_fullscreen()
            except Exception as e:
                self.log.error("WIN_MONITOR", f"Error: {e}", db=False)
            self._stop_event.wait(0.5)

    def _enforce_browser_fullscreen(self):
        """Force browser windows to maximised + remove close/min buttons."""
        windows = []

        def _cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
                browsers = ['Chrome', 'Firefox', 'Edge', 'Opera']
                if any(b in title or b in cls for b in browsers):
                    windows.append((hwnd, title))
            return True

        win32gui.EnumWindows(_cb, None)

        sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        for hwnd, title in windows:
            rect = win32gui.GetWindowRect(hwnd)
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            if w < sw * 0.9 or h < sh * 0.9:
                win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                style &= ~(win32con.WS_MAXIMIZEBOX | win32con.WS_MINIMIZEBOX | win32con.WS_SYSMENU)
                win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
                self.log.security("ENFORCED_FULLSCREEN",
                                  f"Forced fullscreen: {title}", blocked=False)

    # ── Force a Tk window fullscreen ─────────────────────────────
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

    # ── Secure Browser Launcher ──────────────────────────────────
    def launch_secure_browser(self, url="about:blank"):
        chrome_args = [
            '--kiosk', '--no-default-browser-check', '--no-first-run',
            '--disable-default-apps', '--disable-popup-blocking',
            '--disable-translate', '--disable-extensions',
            '--disable-sync', '--disable-background-networking',
        ]
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for path in chrome_paths:
            if os.path.exists(path):
                subprocess.Popen([path] + chrome_args + [url])
                self.log.info("LAUNCH_BROWSER", "Secure kiosk browser started")
                return
        self.log.warning("LAUNCH_BROWSER", "Chrome not found")
