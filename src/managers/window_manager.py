"""
ExamShield v2.0 — Window Manager (Full Hardened Overhaul)

What's new vs v1:
  ① Poll interval 0.35 s (was 1.0 s) — faster reaction
  ② Browser sizing: SetWindowPos with exact pixel coords (was SW_SHOWMAXIMIZED)
     → fills screen completely, no taskbar gap
  ③ WH_SHELL Win32 hook — reacts to window events in <5 ms, not 350 ms
  ④ Exempt-HWND set — our own admin panel is never style-stripped
  ⑤ ALL non-system windows get WS_CAPTION + WS_THICKFRAME + WS_SYSMENU stripped
     → no OS-drawn ×, no Snap Layout tooltip, no minimize hover effect
  ⑥ _enforce_protected_tk() called every cycle to re-deiconify Tk windows
"""
import threading
import ctypes
import ctypes.wintypes as wintypes
import win32gui
import win32con
import win32api
from src.logger import ExamShieldLogger

# ── Win32 helpers (64-bit safe) ───────────────────────────────────────────────
_user32  = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

GWL_STYLE    = -16
GWL_EXSTYLE  = -20
WS_EX_TOPMOST = 0x00000008

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

# WH_SHELL hook code — fires on window activate/create/destroy/minimize
WH_SHELL = 10
HSHELL_WINDOWCREATED    = 1
HSHELL_WINDOWDESTROYED  = 2
HSHELL_WINDOWACTIVATED  = 4
HSHELL_RUDEAPPACTIVATED = 0x8004
HSHELL_GETMINRECT       = 5   # fired when a window is being minimized


def _get_style(hwnd: int) -> int:
    return _user32.GetWindowLongPtrW(hwnd, GWL_STYLE)


def _set_style(hwnd: int, style: int) -> None:
    _user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)


def _redraw_frame(hwnd: int) -> None:
    SWP_FLAGS = (win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
                 win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED)
    _user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_FLAGS)


# ── Browser class names ───────────────────────────────────────────────────────
BROWSER_CLASSES = {
    'Chrome_WidgetWin_1',       # Chrome / new Edge (Chromium)
    'Chrome_WidgetWin_0',
    'MozillaWindowClass',        # Firefox
    'MozillaDialogClass',
    'IEFrame',                   # Internet Explorer / legacy Edge
    'OperaWindowClass',
    'OperaToplevelOldChrome',
    'BraveWindow',
}

BROWSER_TITLE_KEYWORDS = (
    'Chrome', 'Firefox', 'Edge', 'Opera', 'Brave', 'Internet Explorer',
    'Chromium',
)

# ── System/shell classes — NEVER touch these ──────────────────────────────────
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
    'TaskListThumbnailWnd',                  # Taskbar thumbnail previews
    'Alternate Modal Top Most',
    'ToolbarWindow32',
}

# ── Style bits to strip from ALL lockdown windows ────────────────────────────
# This removes: title bar, resize frame, close/min/max buttons,
# and the system menu (right-click title bar)
_STRIP_MASK = (
    win32con.WS_CAPTION      |   # title bar (includes WS_BORDER)
    win32con.WS_THICKFRAME   |   # resizable border
    win32con.WS_MAXIMIZEBOX  |   # maximize button
    win32con.WS_MINIMIZEBOX  |   # minimize button
    win32con.WS_SYSMENU          # system menu / close button
)


class WindowManager:
    def __init__(self, db_manager):
        self.db_manager  = db_manager
        self.log         = ExamShieldLogger(db_manager)
        self.is_active   = False
        self._stop_event = threading.Event()
        self._thread     = None

        # Tk windows registered for close-button protection
        self._protected_tk: list = []

        # HWNDs to never strip — add admin panel HWND here
        self._exempt_hwnds: set = set()

        # WH_SHELL hook state
        self._shell_hook_id   = None
        self._shell_hook_proc = None

    # ── Public API ────────────────────────────────────────────────────────────

    def register_protected_window(self, window, name: str = "Window"):
        """
        Register a Tk window so it gets close-button protection
        and is added to the exempt-HWND set (never style-stripped).
        Safe to call before or after start_window_protection().
        """
        entry = {'win': window, 'name': name}
        if entry not in self._protected_tk:
            self._protected_tk.append(entry)
        # Register the HWND as exempt so we never strip our own panel
        try:
            hwnd = _get_tk_hwnd(window)
            if hwnd:
                self._exempt_hwnds.add(hwnd)
        except Exception:
            pass
        if self.is_active:
            self._protect_tk(window, name)

    def add_exempt_hwnd(self, hwnd: int):
        """Add a Win32 HWND that should never be style-stripped."""
        self._exempt_hwnds.add(hwnd)

    def start_window_protection(self):
        if self.is_active:
            return
        self.is_active = True
        self._stop_event.clear()

        # Re-register exempt HWNDs for any already-registered Tk windows
        for e in self._protected_tk:
            self._protect_tk(e['win'], e['name'])
            try:
                hwnd = _get_tk_hwnd(e['win'])
                if hwnd:
                    self._exempt_hwnds.add(hwnd)
            except Exception:
                pass

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

    # ── Tk close-button block ─────────────────────────────────────────────────

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
            # Re-assert topmost in case it was lost during the dialog
            try:
                window.attributes('-topmost', True)
                window.deiconify()
                window.lift()
            except Exception:
                pass
        try:
            window.protocol("WM_DELETE_WINDOW", _blocked_close)
        except Exception:
            pass

    # ── Monitor loop ──────────────────────────────────────────────────────────

    def _monitor_loop(self):
        """
        Main enforcement loop at 0.35 s intervals.
        Also installs a WH_SHELL hook in this thread's message queue
        so we react in <5 ms to any window event (minimize, activate, create).
        """
        self._install_shell_hook()

        msg = wintypes.MSG()
        while not self._stop_event.is_set():
            # Drain the message queue (processes WH_SHELL callbacks)
            while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))

            try:
                self._enforce_all_windows()
                self._enforce_protected_tk()
            except Exception as e:
                self.log.error("WIN_MONITOR", str(e), db=False)

            self._stop_event.wait(0.35)  # 350 ms — was 1000 ms

        self._uninstall_shell_hook()

    # ── WH_SHELL hook ─────────────────────────────────────────────────────────

    def _install_shell_hook(self):
        """Install a WH_SHELL hook in the current thread to catch window events."""
        try:
            def shell_handler(nCode, wParam, lParam):
                if nCode >= 0 and self.is_active:
                    # HSHELL_GETMINRECT fires when a window is being minimized
                    # Block by immediately enforcing fullscreen on next tick
                    if wParam in (HSHELL_GETMINRECT, HSHELL_WINDOWACTIVATED,
                                  HSHELL_RUDEAPPACTIVATED):
                        try:
                            self._enforce_all_windows()
                            self._enforce_protected_tk()
                        except Exception:
                            pass
                return _user32.CallNextHookEx(
                    self._shell_hook_id, nCode, wParam, lParam
                )

            self._shell_hook_proc = HOOKPROC(shell_handler)
            self._shell_hook_id = _user32.SetWindowsHookExW(
                WH_SHELL,
                self._shell_hook_proc,
                _kernel32.GetModuleHandleW(None),
                0,
            )
        except Exception as e:
            self.log.error("SHELL_HOOK", f"Install failed: {e}", db=False)

    def _uninstall_shell_hook(self):
        try:
            if self._shell_hook_id:
                _user32.UnhookWindowsHookEx(self._shell_hook_id)
                self._shell_hook_id   = None
                self._shell_hook_proc = None
        except Exception:
            pass

    # ── Tk window re-assertion ────────────────────────────────────────────────

    def _enforce_protected_tk(self):
        """
        Re-assert topmost + deiconify on all registered Tk windows.
        Called every poll cycle so a minimized window pops back within 350 ms.
        """
        for e in self._protected_tk:
            try:
                win = e['win']
                if win.winfo_exists():
                    state = win.state()
                    if state == 'iconic' or state == 'withdrawn':
                        win.after(0, win.deiconify)
                        win.after(0, win.lift)
                        self.log.security(
                            "BLOCKED_WIN_MINIMIZE",
                            f"Restored minimized window: {e['name']}",
                            blocked=True,
                        )
                    win.after(0, lambda w=win: (
                        w.attributes('-topmost', True),
                        w.lift(),
                    ) if w.winfo_exists() else None)
            except Exception:
                pass

    # ── Main enforcement ──────────────────────────────────────────────────────

    def _enforce_all_windows(self):
        """
        For every real visible top-level window:
          • Exempt  → skip (admin panel, system classes)
          • Browser → pixel-exact fullscreen + strip entire title bar
          • Other   → strip title bar + close/min/max controls
        """
        sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        def _cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True

                # Never touch system / shell windows
                cls = win32gui.GetClassName(hwnd)
                if cls in SYSTEM_CLASSES:
                    return True

                # Never touch our exempt HWNDs (admin panel, etc.)
                if hwnd in self._exempt_hwnds:
                    return True

                # Skip child windows
                if _user32.GetParent(hwnd) != 0:
                    return True

                title = win32gui.GetWindowText(hwnd)

                # Skip windows with no title and no meaningful class
                # (many background helper processes)
                if not title and cls not in BROWSER_CLASSES:
                    return True

                # ── Classify ──────────────────────────────────────
                is_browser = (
                    cls in BROWSER_CLASSES
                    or any(b in cls for b in ('Chrome', 'Mozilla', 'Opera', 'Brave'))
                    or any(kw in title for kw in BROWSER_TITLE_KEYWORDS)
                )

                current_style = _get_style(hwnd)

                if is_browser:
                    # ── Pixel-exact fullscreen ─────────────────────
                    # SetWindowPos with exact coords is more reliable than
                    # SW_SHOWMAXIMIZED — it fills screen with no taskbar gap
                    # and works even if the window has WS_THICKFRAME stripped
                    rect = win32gui.GetWindowRect(hwnd)
                    w = rect[2] - rect[0]
                    h = rect[3] - rect[1]
                    x = rect[0]
                    y = rect[1]

                    # If minimized, restore first
                    if win32gui.IsIconic(hwnd):
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        self.log.security(
                            "ENFORCED_FULLSCREEN",
                            f"Restored minimized browser: {title or cls}",
                            blocked=True,
                        )

                    # Move + resize to full screen if not already there
                    if x != 0 or y != 0 or w < sw * 0.95 or h < sh * 0.95:
                        _user32.SetWindowPos(
                            hwnd,
                            win32con.HWND_TOP,   # z-order: on top
                            0, 0, sw, sh,
                            win32con.SWP_SHOWWINDOW | win32con.SWP_FRAMECHANGED,
                        )
                        self.log.security(
                            "ENFORCED_FULLSCREEN",
                            f"Pixel-exact fullscreen: {title or cls}",
                            blocked=False,
                        )

                # Strip the full mask from ALL lockdown windows
                desired_style = current_style & ~_STRIP_MASK
                if desired_style != current_style:
                    _set_style(hwnd, desired_style)
                    _redraw_frame(hwnd)

            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception as e:
            self.log.error("WIN_ENUM", str(e), db=False)

    # ── Force a Tk window fullscreen ──────────────────────────────────────────

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

    # ── Secure Browser Launcher ───────────────────────────────────────────────

    def launch_secure_browser(self, url="about:blank"):
        import os, subprocess
        # --kiosk launches in true kiosk mode with no title bar at all
        # Additional flags disable all chrome UI elements
        chrome_args = [
            '--kiosk',
            '--no-default-browser-check', '--no-first-run',
            '--disable-default-apps', '--disable-popup-blocking',
            '--disable-translate', '--disable-extensions',
            '--disable-sync', '--disable-background-networking',
            '--disable-pinch', '--overscroll-history-navigation=0',
            '--disable-features=OverscrollHistoryNavigation',
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


# ── Helper: get Win32 HWND from a Tk window ──────────────────────────────────

def _get_tk_hwnd(window) -> int:
    """
    Retrieve the underlying Win32 HWND from a Tk window object.
    Uses winfo_id() which returns the HWND on Windows.
    """
    try:
        return window.winfo_id()
    except Exception:
        return 0
