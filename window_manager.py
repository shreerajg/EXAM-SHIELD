"""
Window Manager for Exam Shield
Handles window close blocking and fullscreen management
"""

import threading
import time
import subprocess
import psutil
import win32gui
import win32con
import win32api

class WindowManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.is_active = False
        self.blocked_windows = []
        self.monitoring_thread = None
        self.fullscreen_processes = ['chrome.exe', 'firefox.exe', 'msedge.exe', 'opera.exe']

    def start_window_protection(self):
        if self.is_active:
            return
        self.is_active = True
        self.monitoring_thread = threading.Thread(target=self._monitor_windows, daemon=True)
        self.monitoring_thread.start()
        self.db_manager.log_activity("WINDOW_PROTECTION_START", "Window close protection activated")
        print("✅ Window protection activated")

    def stop_window_protection(self):
        if not self.is_active:
            return
        self.is_active = False
        self.monitoring_thread = None
        for window in self.blocked_windows:
            try:
                window.protocol("WM_DELETE_WINDOW", window.destroy)
            except:
                pass
        self.blocked_windows.clear()
        self.db_manager.log_activity("WINDOW_PROTECTION_STOP", "Window close protection deactivated")
        print("✅ Window protection deactivated")

    def protect_window(self, window, window_name="Unknown"):
        if not self.is_active:
            return
        def blocked_close():
            self.db_manager.log_activity("BLOCKED_WINDOW_CLOSE", f"Attempted to close protected window: {window_name}", blocked=True)
            print(f"🚫 Blocked window close attempt: {window_name}")
            try:
                import tkinter.messagebox as messagebox
                messagebox.showwarning("Access Denied", "Window closing is disabled during exam mode.", parent=window)
            except:
                pass
        window.protocol("WM_DELETE_WINDOW", blocked_close)
        self.blocked_windows.append(window)

    def _monitor_windows(self):
        while self.is_active:
            try:
                self._monitor_browser_fullscreen()
                self._monitor_window_close_attempts()
                time.sleep(0.5)
            except Exception as e:
                print(f"Window monitoring error: {e}")
                time.sleep(2)

    def _monitor_browser_fullscreen(self):
        def enum_windows_callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                window_text = win32gui.GetWindowText(hwnd)
                class_name = win32gui.GetClassName(hwnd)
                browser_indicators = ['Chrome', 'Firefox', 'Edge', 'Opera']
                if any(browser in window_text or browser in class_name for browser in browser_indicators):
                    windows.append((hwnd, window_text))
            return True

        windows = []
        win32gui.EnumWindows(enum_windows_callback, windows)
        for hwnd, window_text in windows:
            rect = win32gui.GetWindowRect(hwnd)
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            if (rect[2] - rect[0] < screen_width * 0.9 or rect[3] - rect[1] < screen_height * 0.9):
                win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                style = style & ~win32con.WS_MAXIMIZEBOX & ~win32con.WS_MINIMIZEBOX & ~win32con.WS_SYSMENU
                win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
                self.db_manager.log_activity("ENFORCED_FULLSCREEN", f"Enforced fullscreen for: {window_text}", blocked=False)

    def _monitor_window_close_attempts(self):
        # Placeholder for advanced window close monitoring with Windows hooks
        pass

    def force_fullscreen(self, window):
        if not window:
            return
        try:
            window.attributes('-fullscreen', True)
            window.attributes('-topmost', True)

            def block_fullscreen_keys(event):
                blocked_keys = ['F11', 'Escape']
                if event.keysym in blocked_keys:
                    self.db_manager.log_activity("BLOCKED_FULLSCREEN_EXIT", f"Blocked {event.keysym} key to prevent fullscreen exit", blocked=True)
                    return "break"
            for key in ['<F11>', '<Escape>', '<Alt-F4>', '<Alt-Tab>']:
                window.bind(key, block_fullscreen_keys)
        except Exception as e:
            print(f"Error forcing fullscreen: {e}")

    def launch_secure_browser(self, url="about:blank"):
        try:
            chrome_args = [
                '--kiosk', '--no-default-browser-check', '--no-first-run', '--disable-default-apps',
                '--disable-popup-blocking', '--disable-translate', '--disable-background-timer-throttling',
                '--disable-renderer-backgrounding', '--disable-device-discovery-notifications', '--disable-java',
                '--disable-plugins', '--disable-extensions', '--no-experiments', '--no-pings', '--no-referrers',
                '--safebrowsing-disable-auto-update', '--disable-sync', '--metrics-recording-only',
                '--mute-audio', '--disable-background-networking', '--disable-client-side-phishing-detection',
                '--disable-hang-monitor', '--disable-prompt-on-repost', '--disable-web-resources',
                '--safebrowsing-disable-download-protection', '--disable-domain-reliability'
            ]
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
            ]
            chrome_path = None
            for path in chrome_paths:
                if os.path.exists(path):
                    chrome_path = path
                    break
            if chrome_path:
                import subprocess
                cmd = [chrome_path] + chrome_args + [url]
                subprocess.Popen(cmd)
                self.db_manager.log_activity("LAUNCHED_SECURE_BROWSER", "Launched secure browser in kiosk mode")
                print("✅ Secure browser launched")
            else:
                print("❌ Chrome not found")
        except Exception as e:
            print(f"Error launching secure browser: {e}")
