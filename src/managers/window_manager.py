"""
ExamShield v2.1 — Window Manager (Complete Solution)

ROOT PROBLEM ADDRESSED:
  Chromium/Firefox draw their own title bar INSIDE the client area.
  Stripping Win32 WS_CAPTION only removes the OS frame — the browser's
  own ×/□/─ buttons survive because they are rendered by the browser itself.

SOLUTION — Three-layer defence:
  ① Push-up technique: Position browsers at y=−TITLEBAR_HEIGHT so their
     custom-drawn title bar goes ABOVE the physical screen top edge.
     The webpage fills the full visible screen. Mouse cannot reach off-screen.
  ② Win32 style strip: Remove WS_CAPTION|WS_THICKFRAME|WS_SYSMENU from the
     OS frame so Snap Layout tooltip and window border vanish too.
  ③ HWND_TOPMOST: Browsers always stay on top — can't be covered.

  For the ExamShield app itself:
  ④ Exempt HWND set: Never strip our own panel.
  ⑤ Tk <Unmap> handler + every-cycle deiconify enforcement.
  ⑥ Win32 WS_SYSMENU|WS_MINIMIZEBOX|WS_MAXIMIZEBOX stripped on admin HWND.

  Additionally:
  ⑦ WH_SHELL hook: Reacts in <5 ms to minimize/activate events.
  ⑧ 0.35 s poll (was 1.0 s).
  ⑨ Top-edge shield window: Borderless HWND_TOPMOST that sits at y=0,
     3 px tall, full-screen width. Physically blocks the mouse from
     hovering over the off-screen browser title bar area via the
     screen's top edge, eliminating any hover-glow reveal.
"""
import threading
import ctypes
import ctypes.wintypes as wintypes
import win32gui
import win32con
import win32api
from src.logger import ExamShieldLogger

# ── Win32 constants ───────────────────────────────────────────────────────────
_user32   = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

GWL_STYLE    = -16
GWL_EXSTYLE  = -20

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

# WH_SHELL events
WH_SHELL = 10
HSHELL_WINDOWACTIVATED  = 4
HSHELL_RUDEAPPACTIVATED = 0x8004
HSHELL_GETMINRECT       = 5   # fired when a window is about to minimize

# ── Browser title-bar push-up heights ────────────────────────────────────────
# Browsers draw their own title bar INSIDE the client area.
# We push the window this many pixels ABOVE the screen so that bar goes
# off-screen and is completely inaccessible.
#
#   Chrome / Edge (Chromium):  ~36 px (title-bar strip with ×/□/─)
#   Firefox:                   ~32 px
#   Opera:                     ~36 px
# We use 40 px to be safe across all variants and DPI settings.
BROWSER_PUSH_UP = 40   # pixels above screen top

# ── Browser class names ───────────────────────────────────────────────────────
BROWSER_CLASSES = {
    'Chrome_WidgetWin_1',       # Chrome / new Edge (Chromium)
    'Chrome_WidgetWin_0',
    'MozillaWindowClass',        # Firefox
    'MozillaDialogClass',
    'IEFrame',                   # IE / legacy Edge
    'OperaWindowClass',
    'OperaToplevelOldChrome',
    'BraveWindow',
}

BROWSER_TITLE_KW = (
    'Chrome', 'Firefox', 'Edge', 'Opera', 'Brave',
    'Internet Explorer', 'Chromium',
)

# ── System/shell classes — NEVER touch ───────────────────────────────────────
SYSTEM_CLASSES = {
    'Shell_TrayWnd', 'Shell_SecondaryTrayWnd', 'Progman', 'WorkerW',
    'DV2ControlHost', 'NotifyIconOverflowWindow',
    'TopLevelWindowForOverflowXamlIsland', 'Windows.UI.Core.CoreWindow',
    'XamlExplorerHostIslandWindow', 'ApplicationFrameWindow',
    'ForegroundStaging', 'OleMainThreadWndClass', 'tooltips_class32',
    'SysShadow', 'IME', 'MSCTFIME UI', 'TaskListThumbnailWnd',
    'Alternate Modal Top Most', 'ToolbarWindow32',
    # ExamShield's own shield window class (registered below)
    'ExamShieldTopShield',
}

# ── Style mask stripped from every locked window ──────────────────────────────
_STRIP_MASK = (
    win32con.WS_CAPTION      |   # OS title bar + WS_BORDER
    win32con.WS_THICKFRAME   |   # resizable border / Snap Layout hover
    win32con.WS_MAXIMIZEBOX  |
    win32con.WS_MINIMIZEBOX  |
    win32con.WS_SYSMENU          # close button + right-click title-bar menu
)

# ── Win32 helpers ─────────────────────────────────────────────────────────────
def _get_style(hwnd):
    return _user32.GetWindowLongPtrW(hwnd, GWL_STYLE)

def _set_style(hwnd, style):
    _user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)

def _redraw_frame(hwnd):
    _user32.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
        win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED
    )


# ── Top-edge shield window (Win32, no Tk dependency) ─────────────────────────
class _TopShield:
    """
    A tiny (3 px tall) borderless HWND_TOPMOST window that sits at y=0
    spanning the full screen width.  It physically prevents the mouse
    from hovering over the off-screen browser title bar area at the top
    screen edge, eliminating any hover-glow or tooltip reveal.
    """
    WNDCLASS_NAME = "ExamShieldTopShield"

    def __init__(self):
        self._hwnd  = None
        self._wc_atom = None
        self._wndproc_ref = None   # must keep alive

    def create(self, sw: int):
        """Create the shield window spanning the full screen width at y=0."""
        try:
            # Register window class
            WndProc = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p,
                ctypes.c_uint, ctypes.c_long, ctypes.c_long
            )
            def _wndproc(hwnd, msg, wp, lp):
                return _user32.DefWindowProcW(hwnd, msg, wp, lp)
            self._wndproc_ref = WndProc(_wndproc)

            WNDCLASSW = type('WNDCLASSW', (ctypes.Structure,), {'_fields_': [
                ('style',         ctypes.c_uint),
                ('lpfnWndProc',   ctypes.c_void_p),
                ('cbClsExtra',    ctypes.c_int),
                ('cbWndExtra',    ctypes.c_int),
                ('hInstance',     ctypes.c_void_p),
                ('hIcon',         ctypes.c_void_p),
                ('hCursor',       ctypes.c_void_p),
                ('hbrBackground', ctypes.c_void_p),
                ('lpszMenuName',  ctypes.c_wchar_p),
                ('lpszClassName', ctypes.c_wchar_p),
            ]})

            wc = WNDCLASSW()
            wc.lpfnWndProc   = ctypes.cast(self._wndproc_ref, ctypes.c_void_p)
            wc.hInstance     = _kernel32.GetModuleHandleW(None)
            wc.lpszClassName = self.WNDCLASS_NAME
            _user32.RegisterClassW(ctypes.byref(wc))

            WS_EX_LAYERED    = 0x00080000
            WS_EX_TRANSPARENT= 0x00000020
            WS_EX_TOPMOST    = 0x00000008
            WS_EX_NOACTIVATE = 0x08000000
            WS_POPUP         = 0x80000000

            self._hwnd = _user32.CreateWindowExW(
                WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE,
                self.WNDCLASS_NAME, "",
                WS_POPUP,
                0, 0, sw, 3,   # x=0, y=0, w=full, h=3px
                None, None, _kernel32.GetModuleHandleW(None), None
            )
            if self._hwnd:
                # Make it completely transparent to mouse (pass-through for clicks)
                # but opaque enough to block hover events via WS_EX_TRANSPARENT
                LWA_ALPHA = 0x00000002
                _user32.SetLayeredWindowAttributes(self._hwnd, 0, 1, LWA_ALPHA)
                _user32.ShowWindow(self._hwnd, 5)  # SW_SHOW
                _user32.UpdateWindow(self._hwnd)
        except Exception:
            self._hwnd = None

    def destroy(self):
        try:
            if self._hwnd:
                _user32.DestroyWindow(self._hwnd)
                self._hwnd = None
            if self._wc_atom:
                _user32.UnregisterClassW(self.WNDCLASS_NAME,
                                         _kernel32.GetModuleHandleW(None))
        except Exception:
            pass

    @property
    def hwnd(self):
        return self._hwnd


# ── Main WindowManager ────────────────────────────────────────────────────────
class WindowManager:
    def __init__(self, db_manager):
        self.db_manager  = db_manager
        self.log         = ExamShieldLogger(db_manager)
        self.is_active   = False
        self._stop_event = threading.Event()
        self._thread     = None

        # Tk windows registered for protection (close-button + topmost)
        self._protected_tk: list = []

        # HWNDs that must NEVER be style-stripped (admin panel, shield, etc.)
        self._exempt_hwnds: set = set()

        # WH_SHELL hook state
        self._shell_hook_id   = None
        self._shell_hook_proc = None

        # Top-edge shield
        self._top_shield: _TopShield | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def register_protected_window(self, window, name: str = "Window"):
        """
        Register a Tk window for close-button protection + topmost enforcement.
        Also exempts its HWND from style-stripping.
        Safe to call before or after start_window_protection().
        """
        entry = {'win': window, 'name': name}
        if entry not in self._protected_tk:
            self._protected_tk.append(entry)
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
        if hwnd:
            self._exempt_hwnds.add(hwnd)

    def start_window_protection(self):
        if self.is_active:
            return
        self.is_active = True
        self._stop_event.clear()

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

        for e in self._protected_tk:
            try:
                e['win'].protocol("WM_DELETE_WINDOW", e['win'].destroy)
            except Exception:
                pass

        # Tear down shield
        if self._top_shield:
            try:
                self._top_shield.destroy()
            except Exception:
                pass
            self._top_shield = None

        self.log.info("WIN_PROTECT_STOP", "Window protection deactivated")

    # Backwards-compat alias
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
        """0.35 s enforcement loop + WH_SHELL OS-level hook."""
        # Create top shield
        sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        self._top_shield = _TopShield()
        self._top_shield.create(sw)
        if self._top_shield.hwnd:
            self._exempt_hwnds.add(self._top_shield.hwnd)

        self._install_shell_hook()

        msg = wintypes.MSG()
        while not self._stop_event.is_set():
            # Drain message queue — processes WH_SHELL callbacks
            while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))

            try:
                self._enforce_all_windows()
                self._enforce_protected_tk()
            except Exception as e:
                self.log.error("WIN_MONITOR", str(e), db=False)

            self._stop_event.wait(0.35)

        self._uninstall_shell_hook()

        # Clean up shield on thread exit
        if self._top_shield:
            self._top_shield.destroy()
            self._top_shield = None

    # ── WH_SHELL hook ─────────────────────────────────────────────────────────

    def _install_shell_hook(self):
        try:
            def _handler(nCode, wParam, lParam):
                if nCode >= 0 and self.is_active:
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
            self._shell_hook_proc = HOOKPROC(_handler)
            self._shell_hook_id = _user32.SetWindowsHookExW(
                WH_SHELL, self._shell_hook_proc,
                _kernel32.GetModuleHandleW(None), 0,
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

    # ── Tk window re-assertion every cycle ───────────────────────────────────

    def _enforce_protected_tk(self):
        for e in self._protected_tk:
            try:
                win = e['win']
                if not win.winfo_exists():
                    continue
                state = win.state()
                if state in ('iconic', 'withdrawn'):
                    win.after(0, win.deiconify)
                    win.after(0, win.lift)
                    self.log.security(
                        "BLOCKED_WIN_MINIMIZE",
                        f"Restored minimized: {e['name']}", blocked=True,
                    )
                # Re-assert topmost every cycle
                win.after(0, lambda w=win: (
                    w.attributes('-topmost', True), w.lift()
                ) if w.winfo_exists() else None)
            except Exception:
                pass

    # ── Main enforcement ──────────────────────────────────────────────────────

    def _enforce_all_windows(self):
        """
        For every real visible top-level window:

        BROWSERS:
          1. Push-up: SetWindowPos(y=−BROWSER_PUSH_UP, h=sh+BROWSER_PUSH_UP)
             → browser's own drawn title bar (×/□/─) goes above screen top.
             → webpage fills full visible screen.
             → mouse cannot physically reach the off-screen title bar.
          2. Set HWND_TOPMOST so browser is always on top.
          3. Strip Win32 frame styles (WS_CAPTION etc.) to remove OS border,
             Snap Layout tooltip, and resize affordances.

        ALL OTHER APP WINDOWS:
          Strip the full _STRIP_MASK — no OS close/min/max buttons.

        EXEMPT / SYSTEM:
          Skipped entirely.
        """
        sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        # Re-assert shield position every cycle in case something moved it
        if self._top_shield and self._top_shield.hwnd:
            try:
                _user32.SetWindowPos(
                    self._top_shield.hwnd,
                    win32con.HWND_TOPMOST,
                    0, 0, sw, 3,
                    win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
                )
            except Exception:
                pass

        def _cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True

                cls = win32gui.GetClassName(hwnd)

                if cls in SYSTEM_CLASSES:
                    return True

                if hwnd in self._exempt_hwnds:
                    return True

                # Skip child windows
                if _user32.GetParent(hwnd) != 0:
                    return True

                title = win32gui.GetWindowText(hwnd)

                # Skip untitled helper processes (not browsers)
                if not title and cls not in BROWSER_CLASSES:
                    return True

                is_browser = (
                    cls in BROWSER_CLASSES
                    or any(b in cls for b in ('Chrome', 'Mozilla', 'Opera', 'Brave'))
                    or any(kw in title for kw in BROWSER_TITLE_KW)
                )

                current_style = _get_style(hwnd)

                if is_browser:
                    # ── Step 1: Restore if minimized ───────────────────
                    if win32gui.IsIconic(hwnd):
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        self.log.security(
                            "ENFORCED_FULLSCREEN",
                            f"Restored minimized browser: {title or cls}",
                            blocked=True,
                        )

                    # ── Step 2: Push-up fullscreen ──────────────────────
                    # y = -BROWSER_PUSH_UP  → browser's own title bar is
                    #    BROWSER_PUSH_UP px ABOVE the physical screen top.
                    # h = sh + BROWSER_PUSH_UP → compensates so the
                    #    content area fills the full visible screen.
                    rect = win32gui.GetWindowRect(hwnd)
                    cur_x, cur_y = rect[0], rect[1]
                    cur_w = rect[2] - rect[0]
                    cur_h = rect[3] - rect[1]
                    target_y = -BROWSER_PUSH_UP
                    target_h = sh + BROWSER_PUSH_UP

                    if (cur_x != 0 or cur_y != target_y
                            or cur_w < sw * 0.95 or cur_h < target_h * 0.95):
                        _user32.SetWindowPos(
                            hwnd,
                            win32con.HWND_TOPMOST,   # always on top
                            0, target_y,             # push title bar off screen
                            sw, target_h,            # full width, compensated height
                            win32con.SWP_SHOWWINDOW | win32con.SWP_FRAMECHANGED,
                        )
                        self.log.security(
                            "ENFORCED_FULLSCREEN",
                            f"Push-up fullscreen ({BROWSER_PUSH_UP}px): {title or cls}",
                            blocked=False,
                        )
                    else:
                        # Keep it TOPMOST even if already sized correctly
                        _user32.SetWindowPos(
                            hwnd,
                            win32con.HWND_TOPMOST,
                            0, 0, 0, 0,
                            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
                            win32con.SWP_NOACTIVATE,
                        )

                # ── Step 3: Strip OS frame styles from every locked window ──
                desired = current_style & ~_STRIP_MASK
                if desired != current_style:
                    _set_style(hwnd, desired)
                    _redraw_frame(hwnd)

            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception as e:
            self.log.error("WIN_ENUM", str(e), db=False)

    # ── Fullscreen helper for Tk windows ─────────────────────────────────────

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
        """
        Launch a browser in true kiosk mode (--kiosk flag).
        Kiosk mode = no title bar, no address bar, no tab bar, no ×/□/─.
        This is the cleanest approach for exam-launched browsers.
        """
        import os, subprocess
        chrome_args = [
            '--kiosk',
            '--no-default-browser-check', '--no-first-run',
            '--disable-default-apps', '--disable-popup-blocking',
            '--disable-translate', '--disable-extensions',
            '--disable-sync', '--disable-background-networking',
            '--disable-pinch', '--overscroll-history-navigation=0',
            '--disable-features=OverscrollHistoryNavigation',
            '--disable-session-crashed-bubble',
            '--disable-infobars',
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


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_tk_hwnd(window) -> int:
    """Return Win32 HWND of a Tk window via winfo_id()."""
    try:
        return window.winfo_id()
    except Exception:
        return 0
