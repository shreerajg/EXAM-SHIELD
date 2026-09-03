"""
ExamShield v1.4.0 — Admin Panel
Sidebar-based dark control centre.
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog, filedialog
import threading, time, json, datetime, hashlib, keyboard, sys
from typing import Optional
from pynput import mouse as pynput_mouse
from src.config import Config
from src.logger import ExamShieldLogger
from src.managers.profile_manager import ProfileManager
from src.managers.audit_manager import AuditManager
from src.managers.totp_manager import TOTPManager
from src.ui.exam_timer import ExamTimer
from src.ui.analytics_chart import BreachTimelineChart, BreachBarChart

C = Config.COLORS

# ── Reusable styled widgets ────────────────────────────────────────

def styled_btn(parent, text, cmd, bg=None, fg=None, width=None, pady=9):
    bg = bg or C['surface_alt']
    fg = fg or C['text']
    kw = dict(text=text, command=cmd, bg=bg, fg=fg,
              font=('Segoe UI', 10, 'bold'), relief=tk.FLAT,
              cursor='hand2', pady=pady, padx=14, bd=0,
              activeforeground=C['text_bright'],
              activebackground=_darken(bg))
    if width:
        kw['width'] = width
    btn = tk.Button(parent, **kw)
    h = _darken(bg)
    btn.bind('<Enter>', lambda e: btn.config(bg=h))
    btn.bind('<Leave>', lambda e: btn.config(bg=bg))
    return btn

def _darken(hex_c, factor=0.72):
    try:
        h = hex_c.lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f'#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}'
    except Exception:
        return hex_c

def _lighten(hex_c, factor=1.25):
    try:
        h = hex_c.lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f'#{min(255,int(r*factor)):02x}{min(255,int(g*factor)):02x}{min(255,int(b*factor)):02x}'
    except Exception:
        return hex_c

def dark_entry(parent, var, show=None):
    e = tk.Entry(parent, textvariable=var, show=show or '',
                 font=('Segoe UI', 11), bg=C['input_bg'], fg=C['text'],
                 relief=tk.FLAT, insertbackground=C['primary'],
                 highlightthickness=2, highlightcolor=C['primary'],
                 highlightbackground=C['input_border'])
    e.bind('<FocusIn>',  lambda ev: e.config(highlightbackground=C['primary']))
    e.bind('<FocusOut>', lambda ev: e.config(highlightbackground=C['input_border']))
    return e

def section_header(parent, text, icon_color=None):
    """Premium section header with colored left-bar accent and glow dot."""
    color = icon_color or C['primary']
    f = tk.Frame(parent, bg=C['bg'])
    f.pack(fill=tk.X, padx=16, pady=(18, 6))
    row = tk.Frame(f, bg=C['bg'])
    row.pack(fill=tk.X)
    # Left accent bar (thick + colored)
    tk.Frame(row, bg=color, width=4).pack(side=tk.LEFT, fill=tk.Y, pady=1, padx=(0, 10))
    # Glow dot
    tk.Label(row, text='⬤', font=('Segoe UI', 7),
             bg=C['bg'], fg=color).pack(side=tk.LEFT, padx=(0, 6))
    tk.Label(row, text=text.upper(), font=('Segoe UI', 10, 'bold'),
             bg=C['bg'], fg=color).pack(anchor=tk.W, side=tk.LEFT)
    # Separator line
    tk.Frame(f, bg=color, height=1).pack(fill=tk.X, pady=(5, 0))

def premium_card(parent, padx=0, pady=0, accent=None):
    """A flat card frame with optional left accent border."""
    if accent:
        outer = tk.Frame(parent, bg=accent, padx=2, pady=0)
        outer.pack(fill=tk.X, padx=16, pady=(0, 8))
        inner = tk.Frame(outer, bg=C['card'], padx=padx or 14, pady=pady or 12)
        inner.pack(fill=tk.BOTH, expand=True)
        return inner
    else:
        f = tk.Frame(parent, bg=C['card'],
                     highlightthickness=1,
                     highlightbackground=C['border'],
                     padx=padx or 14, pady=pady or 12)
        f.pack(fill=tk.X, padx=16, pady=(0, 8))
        return f


class AdminPanel:
    def __init__(self, db_manager, security_manager, parent_window,
                 admin_user='admin'):
        self.db = db_manager
        self.sec = security_manager
        self.parent = parent_window
        self.admin_user = admin_user
        self.log = ExamShieldLogger(db_manager)
        self.sec.set_admin_panel(self)
        self.audit = AuditManager(db_manager)   # tamper-evident log chain
        # Backfill chain hashes for any pre-existing rows (no-op on fresh DB)
        self.audit.backfill_chain()

        self._detecting_key = False
        self._detecting_mouse = False
        self._key_hook = None
        self._mouse_listener = None
        self._detected_key = None
        self._detected_mouse = None
        self._toast_queue = []

        # Feature managers
        self.profile_manager = ProfileManager(db_manager)
        self.profile_manager.ensure_defaults()
        self.totp_manager = TOTPManager(db_manager)
        self._exam_timer: Optional[ExamTimer] = None
        self._active_profile_name = ""
        self._browser_proc = None
        # Analytics chart references (set in _build_dashboard)
        self._timeline_chart: Optional[BreachTimelineChart] = None
        self._bar_chart: Optional[BreachBarChart] = None
        # Timer control buttons (set in _build_dashboard)
        self._timer_pause_btn = None
        self._timer_extend_btn = None

        # Build window
        self.window = tk.Toplevel()
        self.window.title("Exam Shield — Control Centre")
        self.window.geometry("1100x720")
        self.window.minsize(960, 660)
        self.window.configure(bg=C['bg'])
        self._apply_dark_theme()
        self._load_persisted_settings()
        self._build_ui()
        self._center()
        self._start_auto_refresh()
        
        try:
            keyboard.add_hotkey(Config.STEALTH_MODE_KEY, self._toggle_stealth_mode)
        except Exception:
            pass

    def _toggle_stealth_mode(self):
        try:
            if self.window.state() == 'withdrawn':
                self.show()
            else:
                self.window.withdraw()
        except Exception:
            pass

    # ── Dark theme ───────────────────────────────────────────────
    def _apply_dark_theme(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', background=C['bg'], foreground=C['text'],
                        fieldbackground=C['input_bg'], borderwidth=0)
        style.configure('TFrame', background=C['bg'])
        style.configure('TLabel', background=C['bg'], foreground=C['text'])
        style.configure('TLabelframe', background=C['bg'], foreground=C['primary'])
        style.configure('TLabelframe.Label', background=C['bg'],
                        foreground=C['primary'], font=('Segoe UI', 10, 'bold'))
        style.configure('TCheckbutton', background=C['bg'], foreground=C['text'])
        style.configure('Treeview', background=C['surface'], foreground=C['text'],
                        fieldbackground=C['surface'], rowheight=26, font=('Consolas', 9))
        style.configure('Treeview.Heading', background=C['surface_alt'],
                        foreground=C['primary'], font=('Segoe UI', 10, 'bold'))
        style.map('Treeview', background=[('selected', C['primary_dark'])])
        style.configure('TScrollbar', background=C['surface'], troughcolor=C['bg'],
                        arrowcolor=C['text_dim'])

    def _load_persisted_settings(self):
        data = self.db.load_persisted_lists()
        if data['blocked_keys']:
            self.sec.blocked_keys = data['blocked_keys']
        if data['blocked_mouse']:
            self.sec.mouse_manager.blocked_buttons = data['blocked_mouse']
        if data['blocked_websites']:
            Config.BLOCKED_WEBSITES = data['blocked_websites']
        if data.get('allowed_processes') is not None:
            Config.ALLOWED_PROCESSES = data['allowed_processes']
        if data.get('suspicious_processes') is not None:
            Config.SUSPICIOUS_PROCESSES = data['suspicious_processes']
        if data.get('process_whitelist_mode') is not None:
            Config.PROCESS_WHITELIST_MODE = data['process_whitelist_mode']

    # ── Main UI (Sidebar + Content) ──────────────────────────────
    def _build_ui(self):
        # ── Top header bar (premium, 64px)
        hdr = tk.Frame(self.window, bg=C['header'], height=64)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        # Left brand area
        brand = tk.Frame(hdr, bg=C['header'])
        brand.pack(side=tk.LEFT, padx=20, fill=tk.Y)

        # Shield icon with a subtle glow background pill
        shield_pill = tk.Frame(brand, bg=C['primary_bg'], padx=8, pady=4)
        shield_pill.pack(side=tk.LEFT, padx=(0, 12), pady=14)
        tk.Label(shield_pill, text="🛡", font=('Segoe UI', 16),
                 bg=C['primary_bg'], fg=C['primary']).pack()

        title_col = tk.Frame(brand, bg=C['header'])
        title_col.pack(side=tk.LEFT, fill=tk.Y, pady=12)
        tk.Label(title_col, text="EXAM SHIELD",
                 font=('Segoe UI', 14, 'bold'), bg=C['header'],
                 fg=C['primary']).pack(anchor=tk.W)
        tk.Label(title_col, text="Control Centre  ·  Administrator",
                 font=('Segoe UI', 8), bg=C['header'],
                 fg=C['text_dim']).pack(anchor=tk.W)

        # Right: status badge + clock + user avatar
        right = tk.Frame(hdr, bg=C['header'])
        right.pack(side=tk.RIGHT, padx=20, fill=tk.Y)

        # User avatar circle (simulated with label)
        user_pill = tk.Frame(right, bg=C['accent_glow2'], padx=10, pady=4)
        user_pill.pack(side=tk.RIGHT, padx=(10, 0), pady=18)
        tk.Label(user_pill, text=f"👤  {self.admin_user}",
                 font=('Segoe UI', 9, 'bold'),
                 bg=C['accent_glow2'], fg=C['accent']).pack()

        self._clock_label = tk.Label(right, text="",
                                      font=('Consolas', 10),
                                      bg=C['header'], fg=C['text_dim'])
        self._clock_label.pack(side=tk.RIGHT, padx=(12, 0))

        # Status badge with live indicator dot
        badge_frame = tk.Frame(right, bg=C['header'])
        badge_frame.pack(side=tk.RIGHT, padx=(0, 12))
        self._status_dot = tk.Label(badge_frame, text="⬤",
                                     font=('Segoe UI', 10),
                                     bg=C['header'], fg=C['text_dim'])
        self._status_dot.pack(side=tk.LEFT, padx=(0, 4))
        self._status_badge = tk.Label(badge_frame, text="STANDBY",
                                       font=('Consolas', 10, 'bold'),
                                       bg=C['header'], fg=C['text_dim'])
        self._status_badge.pack(side=tk.LEFT)

        self._start_clock()

        # Primary accent separator
        tk.Frame(self.window, bg=C['primary'], height=2).pack(fill=tk.X)

        # Body = sidebar + content
        body = tk.Frame(self.window, bg=C['bg'])
        body.pack(fill=tk.BOTH, expand=True)

        # ── Sidebar (wider: 204px)
        sidebar = tk.Frame(body, bg=C['sidebar'], width=204)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # Sliding active indicator
        self._sliding_indicator = tk.Frame(sidebar, bg=C['primary'], width=4, height=44)
        self._sliding_indicator.place(x=0, y=-100)
        self._indicator_y = 0

        # Content area
        self._content = tk.Frame(body, bg=C['bg'])
        self._content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ── Nav section label
        self._active_page = tk.StringVar(value='dashboard')
        nav_items = [
            ('dashboard',    '⚡', 'Dashboard'),
            ('monitor',      '📊', 'Live Monitor'),
            ('dynamic_rules','🔄', 'Dynamic Rules'),
            ('custom_keys',  '⌨',  'Custom Keys'),
            ('profiles',     '🏷',  'Profiles'),
            ('settings',     '⚙',  'Settings'),
            ('logs',         '📋', 'Logs'),
        ]

        # Sidebar top brand strip
        sb_top = tk.Frame(sidebar, bg=C['sidebar'], height=50)
        sb_top.pack(fill=tk.X)
        sb_top.pack_propagate(False)
        tk.Label(sb_top, text="NAVIGATION",
                 font=('Segoe UI', 7, 'bold'),
                 bg=C['sidebar'], fg=C['text_muted'],
                 anchor=tk.W).pack(anchor=tk.W, padx=16, pady=(16, 0))

        # Sidebar divider
        tk.Frame(sidebar, bg=C['border'], height=1).pack(fill=tk.X, padx=10)

        self._nav_btns = {}
        self._nav_frames_dict = {}
        for idx, (key, icon, label) in enumerate(nav_items):
            btn_frame = tk.Frame(sidebar, bg=C['sidebar'], height=46)
            btn_frame.pack(fill=tk.X)
            btn_frame.pack_propagate(False)

            # Icon pill
            icon_bg = tk.Frame(btn_frame, bg=C['sidebar'], width=32, height=32)
            icon_bg.pack(side=tk.LEFT, padx=(12, 8), pady=7)
            icon_bg.pack_propagate(False)
            icon_lbl = tk.Label(icon_bg, text=icon, font=('Segoe UI', 11),
                                bg=C['sidebar'], fg=C['text_dim'])
            icon_lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

            btn = tk.Label(btn_frame, text=label,
                           font=('Segoe UI', 10), bg=C['sidebar'],
                           fg=C['text_dim'], cursor='hand2',
                           anchor=tk.W)
            btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

            def _click(e, k=key):
                self._nav_to(k)
            def on_enter(e, bf=btn_frame, b=btn, il=icon_lbl, k=key):
                if self._active_page.get() != k:
                    bf.config(bg=C['sidebar_hover'])
                    b.config(bg=C['sidebar_hover'], fg=C['text'])
                    il.config(bg=C['sidebar_hover'])
            def on_leave(e, bf=btn_frame, b=btn, il=icon_lbl, k=key):
                if self._active_page.get() != k:
                    bf.config(bg=C['sidebar'])
                    b.config(bg=C['sidebar'], fg=C['text_dim'])
                    il.config(bg=C['sidebar'])

            for widget in (btn_frame, btn, icon_lbl, icon_bg):
                widget.bind('<Button-1>', _click)
                widget.bind('<Enter>', on_enter)
                widget.bind('<Leave>', on_leave)

            self._nav_btns[key] = {
                'btn': btn, 'frame': btn_frame,
                'icon': icon_lbl, 'icon_bg': icon_bg, 'idx': idx
            }

        # Bottom sidebar divider + version
        tk.Frame(sidebar, bg=C['border'], height=1).pack(fill=tk.X, padx=10, pady=(8, 4))
        tk.Label(sidebar, text=f"v{Config.VERSION}",
                 font=('Consolas', 8), bg=C['sidebar'],
                 fg=C['text_muted']).pack(anchor=tk.W, padx=16, pady=(0, 8))

        # Build all page frames
        self._pages = {}
        self._pages['dashboard']    = self._build_dashboard()
        self._pages['monitor']      = self._build_monitor()
        self._pages['dynamic_rules']= self._build_dynamic_rules()
        self._pages['custom_keys']  = self._build_custom_keys()
        self._pages['profiles']     = self._build_profiles()
        self._pages['settings']     = self._build_settings()
        self._pages['logs']         = self._build_logs()

        self._nav_to('dashboard')


    def _start_clock(self):
        """Update the clock label every second."""
        def _tick():
            try:
                if not self.window.winfo_exists():
                    return
                now = datetime.datetime.now().strftime("%H:%M:%S")
                self._clock_label.config(text=f"🕐 {now}")
                self.window.after(1000, _tick)
            except Exception:
                pass
        _tick()

    def _nav_to(self, key):
        # Hide all pages
        for pg in self._pages.values():
            pg.pack_forget()
        # Reset all nav items
        for k, d in self._nav_btns.items():
            if k != key:
                d['btn'].config(bg=C['sidebar'], fg=C['text_dim'])
                d['frame'].config(bg=C['sidebar'])
                d['icon'].config(bg=C['sidebar'], fg=C['text_dim'])
                d['icon_bg'].config(bg=C['sidebar'])

        # Show selected page
        self._pages[key].pack(fill=tk.BOTH, expand=True)
        # Highlight active nav item
        d = self._nav_btns[key]
        d['btn'].config(bg=C['sidebar_active'], fg=C['primary'])
        d['frame'].config(bg=C['sidebar_active'])
        d['icon'].config(bg=C['sidebar_active'], fg=C['primary'])
        d['icon_bg'].config(bg=C['sidebar_active'])
        self._active_page.set(key)

        # Animate sliding indicator
        self.window.update_idletasks()
        target_y = self._nav_btns[key]['frame'].winfo_y()
        if target_y <= 0:
            target_y = 50 + self._nav_btns[key]['idx'] * 46

        current_y = getattr(self, '_indicator_y', target_y)

        def slide():
            if not self.window.winfo_exists(): return
            nonlocal current_y
            if abs(target_y - current_y) <= 1:
                current_y = target_y
                self._sliding_indicator.place(y=current_y)
         # ── Page: Dashboard ──────────────────────────────────────────
    def _build_dashboard(self):
        pg = tk.Frame(self._content, bg=C['bg'])

        # ── System stats row (4 big stat cards)
        section_header(pg, "System Status", C['info'])
        stats_row = tk.Frame(pg, bg=C['bg'])
        stats_row.pack(fill=tk.X, padx=16, pady=(0, 4))

        self._cpu_bar   = self._stat_card(stats_row, "CPU USAGE",   C['info'])
        self._ram_bar   = self._stat_card(stats_row, "RAM USAGE",   C['accent'])
        self._procs_card = self._stat_card(stats_row, "PROCESSES",   C['warning'], is_bar=False)
        self._mode_card  = self._stat_card(stats_row, "MODE",        C['success'],  is_bar=False)

        # ── Lockdown Control card
        section_header(pg, "Lockdown Control", C['danger'])
        ctrl_outer = tk.Frame(pg, bg=C['danger'], padx=2, pady=0)
        ctrl_outer.pack(fill=tk.X, padx=16, pady=(0, 8))
        ctrl = tk.Frame(ctrl_outer, bg=C['card'])
        ctrl.pack(fill=tk.BOTH, expand=True)

        # Status header row
        mode_hdr = tk.Frame(ctrl, bg=C['card'])
        mode_hdr.pack(fill=tk.X, padx=18, pady=(14, 6))
        self._mode_dot = tk.Label(mode_hdr, text="⬤",
                                   font=('Segoe UI', 16),
                                   bg=C['card'], fg=C['success'])
        self._mode_dot.pack(side=tk.LEFT, padx=(0, 10))
        mode_txt_col = tk.Frame(mode_hdr, bg=C['card'])
        mode_txt_col.pack(side=tk.LEFT)
        self._mode_label = tk.Label(mode_txt_col, text="LOCKDOWN: INACTIVE",
                                     font=('Segoe UI', 14, 'bold'),
                                     bg=C['card'], fg=C['success'])
        self._mode_label.pack(anchor=tk.W)
        self._mode_sub = tk.Label(mode_txt_col, text="All security modules are standby",
                                   font=('Segoe UI', 8),
                                   bg=C['card'], fg=C['text_dim'])
        self._mode_sub.pack(anchor=tk.W)

        # Module indicator chips (2-row grid)
        ind_outer = tk.Frame(ctrl, bg=C['card'])
        ind_outer.pack(fill=tk.X, padx=18, pady=(2, 10))
        self._ind = {}
        modules_def = [
            ('keyboard',      '⌨',  'Keyboard'),
            ('mouse',         '🖱', 'Mouse'),
            ('network',       '🌐', 'Network'),
            ('windows',       '🪟', 'Windows'),
            ('usb',           '💾', 'USB'),
            ('clipboard',     '📋', 'Clipboard'),
            ('vm_rdp',        '🖥', 'VM/RDP'),
            ('multi_monitor', '📺', 'Monitors'),
            ('webcam',        '📷', 'Webcam'),
            ('audio',         '🎤', 'Audio'),
        ]
        for i, (key, icon, label) in enumerate(modules_def):
            chip = tk.Frame(ind_outer, bg=C['surface'],
                            highlightthickness=1,
                            highlightbackground=C['border'],
                            padx=8, pady=5)
            chip.grid(row=i // 5, column=i % 5, padx=(0, 5), pady=(0, 4), sticky='ew')
            ind_outer.columnconfigure(i % 5, weight=1)
            inner = tk.Frame(chip, bg=C['surface'])
            inner.pack()
            tk.Label(inner, text=icon, font=('Segoe UI', 10),
                     bg=C['surface'], fg=C['text_dim']).pack(side=tk.LEFT, padx=(0, 4))
            lbl = tk.Label(inner, text=label,
                           font=('Segoe UI', 8, 'bold'), bg=C['surface'],
                           fg=C['text_dim'])
            lbl.pack(side=tk.LEFT)
            dot = tk.Label(chip, text='● OFF',
                           font=('Segoe UI', 7), bg=C['surface'],
                           fg=C['text_muted'])
            dot.pack()
            self._ind[key] = {'chip': chip, 'lbl': lbl, 'dot': dot}

        # Action buttons row
        btn_row = tk.Frame(ctrl, bg=C['card'])
        btn_row.pack(fill=tk.X, padx=18, pady=(4, 8))

        self._start_btn = styled_btn(btn_row, "🔒  START LOCKDOWN",
                                      self._show_lockdown_dialog,
                                      bg=C['success'], fg='#030d03', pady=12)
        self._start_btn.pack(side=tk.LEFT, padx=(0, 8))
        self._pulse_button(self._start_btn, C['success'])

        self._stop_btn = styled_btn(btn_row, "🔓  END LOCKDOWN",
                                     self._stop_exam,
                                     bg=C['danger'], fg='white', pady=12)
        self._stop_btn.pack(side=tk.LEFT, padx=(0, 8))
        self._stop_btn.config(state=tk.DISABLED)

        styled_btn(btn_row, "🚨  EMERGENCY STOP",
                   self._emergency_stop,
                   bg=C['warning'], fg='#0a0a0a', pady=12).pack(side=tk.LEFT)

        # ── Exam Timer widget (placed below action buttons) ─────────────────
        self._exam_timer: Optional[ExamTimer] = None
        tk.Frame(pg, bg=C['border'], height=1).pack(fill=tk.X, pady=(6, 0))
        self._timer_frame = tk.Frame(pg, bg=C['bg'])
        self._timer_frame.pack(fill=tk.X, padx=16, pady=(8, 4))
        self._exam_timer = ExamTimer(
            self._timer_frame, on_expiry=self._on_timer_expiry,
            initial_minutes=0
        )

        styled_btn(btn_row, "🔄 Refresh",
                   self._refresh_status, bg=C['surface_alt'], pady=12).pack(side=tk.RIGHT)

        # ── Timer controls row (shown when timer is active)
        timer_ctrl_row = tk.Frame(ctrl, bg=C['card'])
        timer_ctrl_row.pack(fill=tk.X, padx=18, pady=(0, 12))

        tk.Label(timer_ctrl_row, text="⏱ Timer:",
                 font=('Segoe UI', 8, 'bold'), bg=C['card'],
                 fg=C['text_dim']).pack(side=tk.LEFT, padx=(0, 6))

        self._timer_pause_btn = styled_btn(
            timer_ctrl_row, "⏸ Pause Timer",
            self._toggle_timer_pause,
            bg=C['surface_alt'], pady=6
        )
        self._timer_pause_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._timer_pause_btn.config(state=tk.DISABLED)

        self._timer_extend_btn = styled_btn(
            timer_ctrl_row, "+5 min",
            lambda: self._extend_timer(5),
            bg=C['surface_alt'], pady=6
        )
        self._timer_extend_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._timer_extend_btn.config(state=tk.DISABLED)

        styled_btn(
            timer_ctrl_row, "+10 min",
            lambda: self._extend_timer(10),
            bg=C['surface_alt'], pady=6
        ).pack(side=tk.LEFT)
        # Store reference to the +10 btn so we can disable it too
        # (last packed — find via pack_slaves)
        self._timer_extend10_btn = timer_ctrl_row.pack_slaves()[-1]

        # ── Breach Counter (color-coded pills)
        section_header(pg, "Breach Counter — Current Session", C['danger'])
        breach_row = tk.Frame(pg, bg=C['bg'])
        breach_row.pack(fill=tk.X, padx=16, pady=(0, 6))
        self._breach_cards = {}
        breach_def = [
            ('keyboard',  '⌨',  'Keystrokes',   C['info']),
            ('processes', '🔍', 'Processes',     C['danger']),
            ('network',   '🌐', 'Network',       C['warning']),
            ('usb',       '💾', 'USB',           C['accent']),
            ('windows',   '🪟', 'Windows',       C['primary']),
            ('webcam',    '📷', 'Face',          C['success']),
            ('audio',     '🎤', 'Audio',         C['warning']),
        ]
        for key, icon, label, color in breach_def:
            # Card with left color accent
            cf_outer = tk.Frame(breach_row, bg=color, padx=2)
            cf_outer.pack(side=tk.LEFT, padx=(0, 6), pady=2)
            cf = tk.Frame(cf_outer, bg=C['surface'], padx=12, pady=10)
            cf.pack(fill=tk.BOTH, expand=True)
            tk.Label(cf, text=icon, font=('Segoe UI', 13),
                     bg=C['surface'], fg=color).pack()
            count_lbl = tk.Label(cf, text='0',
                                  font=('Segoe UI', 22, 'bold'),
                                  bg=C['surface'], fg=color)
            count_lbl.pack()
            tk.Label(cf, text=label.upper(), font=('Segoe UI', 7, 'bold'),
                     bg=C['surface'], fg=C['text_dim'],
                     justify=tk.CENTER).pack()
            self._breach_cards[key] = count_lbl

        # ── Threat detection strip
        section_header(pg, "Threat Detection", C['warning'])
        tf_outer = tk.Frame(pg, bg=C['warning'], padx=2, pady=0)
        tf_outer.pack(fill=tk.X, padx=16, pady=(0, 6))
        tf = tk.Frame(tf_outer, bg=C['card'], padx=16, pady=12)
        tf.pack(fill=tk.BOTH, expand=True)
        self._threat_label = tk.Label(tf, text="🛡  No threats detected — all systems nominal",
                                       font=('Segoe UI', 10),
                                       bg=C['card'], fg=C['success'])
        self._threat_label.pack(anchor=tk.W)

        # ── Quick controls row
        section_header(pg, "Quick Module Controls", C['accent'])
        qrow = tk.Frame(pg, bg=C['bg'])
        qrow.pack(fill=tk.X, padx=16, pady=(0, 8))

        for label, cmd in [
            ("🖱  Mouse",          self._show_mouse_ctrl),
            ("🌐  Internet",       self._show_network_ctrl),
            ("🪟  Windows",        self._show_window_ctrl),
            ("💾  USB",            self._show_usb_ctrl),
            ("🔑  Password",       self._change_password),
        ]:
            styled_btn(qrow, label, cmd, bg=C['surface']).pack(
                side=tk.LEFT, padx=(0, 6), pady=4)

        # ── Session History cards
        section_header(pg, "Session History", C['primary'])
        hist_row = tk.Frame(pg, bg=C['bg'])
        hist_row.pack(fill=tk.X, padx=16, pady=(0, 8))

        self._hist_sessions = self._stat_card(hist_row, "SESSIONS",       C['primary'], is_bar=False)
        self._hist_breaches = self._stat_card(hist_row, "TOTAL BREACHES",  C['danger'],  is_bar=False)
        self._hist_last     = self._stat_card(hist_row, "LAST SESSION",    C['accent'],  is_bar=False)
        self._hist_lastb    = self._stat_card(hist_row, "LAST BREACHES",   C['warning'], is_bar=False)

        styled_btn(hist_row, "🔄",
                   self._refresh_session_history,
                   bg=C['surface'], pady=4
                   ).pack(side=tk.LEFT, padx=(8, 0), pady=8)

        styled_btn(hist_row, "📤 Export Report",
                   self._export_latest_report,
                   bg=C['surface'], pady=4
                   ).pack(side=tk.LEFT, padx=(8, 0), pady=8)
        self._refresh_session_history()

        # ── Live Analytics Charts
        section_header(pg, "Live Analytics — Breach Timeline", C['info'])
        charts_row = tk.Frame(pg, bg=C['bg'])
        charts_row.pack(fill=tk.X, padx=16, pady=(0, 12))

        # Timeline chart (wide)
        self._timeline_chart = BreachTimelineChart(
            charts_row, self.db, minutes=20,
            width=560, height=180, refresh_ms=5000
        )
        self._timeline_chart.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        # Bar chart (narrower)
        self._bar_chart = BreachBarChart(
            charts_row, self.db,
            width=240, height=180, refresh_ms=5000
        )
        self._bar_chart.pack(side=tk.LEFT, fill=tk.Y)

        return pg


    def _export_latest_report(self):
        try:
            import os, glob, shutil
            from src.config import Config
            from tkinter import filedialog, messagebox
            
            reports = glob.glob(os.path.join(Config.REPORT_DIR, '*.html'))
            if not reports:
                self._toast("No reports found", C['warning'])
                return
            latest = max(reports, key=os.path.getctime)
            
            path = filedialog.asksaveasfilename(
                defaultextension='.html',
                initialfile=os.path.basename(latest),
                filetypes=[('HTML Report', '*.html'), ('PDF Report', '*.pdf'), ('Text Report', '*.txt'), ('All', '*.*')],
                parent=self.window)
            
            if path:
                src = latest
                if path.endswith('.txt'):
                    txt_version = latest.replace('.html', '.txt')
                    if os.path.exists(txt_version):
                        src = txt_version
                    else:
                        self._toast("Text report not found for this session.", C['error'])
                        return
                elif path.endswith('.pdf'):
                    pdf_version = latest.replace('.html', '.pdf')
                    if os.path.exists(pdf_version):
                        src = pdf_version
                    else:
                        self._toast("PDF report not found (was reportlab installed?).", C['error'])
                        return
                
                shutil.copy2(src, path)
                self._toast(f"💾 Report exported to {os.path.basename(path)}", C['success'])
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror('Export Error', str(e), parent=self.window)

    def _stat_card(self, parent, label, color, is_bar=True):
        # Outer left-accent border
        outer = tk.Frame(parent, bg=color, padx=2, pady=0)
        outer.pack(side=tk.LEFT, padx=(0, 8), pady=4)
        f = tk.Frame(outer, bg=C['surface_alt'], padx=16, pady=14)
        f.pack(fill=tk.BOTH)

        # Header row: color dot + label
        hdr = tk.Frame(f, bg=C['surface_alt'])
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text='⬤', font=('Segoe UI', 7),
                 bg=C['surface_alt'], fg=color).pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(hdr, text=label, font=('Segoe UI', 8, 'bold'),
                 bg=C['surface_alt'], fg=C['text_dim']).pack(side=tk.LEFT)

        if is_bar:
            val_lbl = tk.Label(f, text="0%", font=('Segoe UI', 22, 'bold'),
                                bg=C['surface_alt'], fg=color)
            val_lbl.pack(anchor=tk.W, pady=(4, 2))
            canvas = tk.Canvas(f, bg=C['border'], height=5, width=130,
                                highlightthickness=0)
            canvas.pack(anchor=tk.W, pady=(2, 0))
            bar = canvas.create_rectangle(0, 0, 0, 5, fill=color, outline='')
            return {'label': val_lbl, 'canvas': canvas, 'bar': bar,
                    'color': color, 'width': 130}
        else:
            val_lbl = tk.Label(f, text="–",
                                font=('Segoe UI', 22, 'bold'),
                                bg=C['surface_alt'], fg=color)
            val_lbl.pack(anchor=tk.W, pady=(4, 0))
            return {'label': val_lbl}

    def _update_bar(self, bar_info, pct):
        w = bar_info.get('width', 130)
        bar_info['label'].config(text=f"{pct:.0f}%")
        
        target_w = int(w * pct / 100)
        current_w = bar_info.get('current_w', target_w)
        
        def animate():
            if not self.window.winfo_exists(): return
            nonlocal current_w
            if abs(target_w - current_w) <= 1:
                current_w = target_w
            else:
                current_w += (target_w - current_w) * 0.2
            
            bar_info['canvas'].coords(bar_info['bar'], 0, 0, int(current_w), 6)
            bar_info['current_w'] = current_w
            
            c = bar_info['color']
            if 'canvas' in bar_info:
                if pct > 85:
                    bar_info['canvas'].itemconfig(bar_info['bar'], fill=C['danger'])
                elif pct > 60:
                    bar_info['canvas'].itemconfig(bar_info['bar'], fill=C['warning'])
                else:
                    bar_info['canvas'].itemconfig(bar_info['bar'], fill=c)
            
            if int(current_w) != target_w:
                self.window.after(20, animate)
                
        animate()

    def _pulse_button(self, btn, base_color):
        import math
        self._pulse_phase = getattr(self, '_pulse_phase', 0)
        def pulse():
            try:
                if not btn.winfo_exists(): return
                self._pulse_phase += 0.1
                factor = 0.85 + 0.15 * math.sin(self._pulse_phase)
                h = base_color.lstrip('#')
                r,g,b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
                r,g,b = int(r*factor), int(g*factor), int(b*factor)
                c = f'#{r:02x}{g:02x}{b:02x}'
                # Only update if button is not currently active/pressed or disabled
                if btn.cget('state') == tk.NORMAL:
                    btn.config(bg=c)
                btn.after(50, pulse)
            except Exception:
                pass
        pulse()

    # ── Page: Live Monitor ───────────────────────────────────────
    def _build_monitor(self):
        pg = tk.Frame(self._content, bg=C['bg'])
        section_header(pg, "Real-time Security Events", C['warning'])
        af = tk.Frame(pg, bg=C['bg'])
        af.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

        cols = ('Time', 'Severity', 'Action', 'Details', 'Status')
        self._tree = ttk.Treeview(af, columns=cols, show='headings', height=22)
        for c, w in zip(cols, [90, 90, 180, 360, 100]):
            self._tree.heading(c, text=c)
            self._tree.column(c, width=w, minwidth=60)
        self._tree.tag_configure('high', foreground=C['danger'])
        self._tree.tag_configure('med',  foreground=C['warning'])
        self._tree.tag_configure('low',  foreground=C['success'])
        self._tree.tag_configure('evenrow', background=C['bg'])
        self._tree.tag_configure('oddrow', background=C['surface_alt'])

        vsb = ttk.Scrollbar(af, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        return pg

    # ── Page: Custom Blocked Keys ────────────────────────────────────────────
    def _build_custom_keys(self):
        """Manage user-defined custom blocked key combinations."""
        pg = tk.Frame(self._content, bg=C['bg'])

        section_header(pg, "Custom Blocked Keys", C['warning'])

        tk.Label(pg, text="Add custom key combinations to block during exam.\n"
                           "Example: ctrl+shift+esc, f5, ctrl+alt+del",
                 font=('Segoe UI', 9), bg=C['card'], fg=C['text_dim'],
                 justify=tk.CENTER).pack(pady=(0, 12))

        input_row = tk.Frame(pg, bg=C['card'])
        input_row.pack(fill=tk.X, padx=16, pady=(0, 8))

        key_var = tk.StringVar()
        entry = dark_entry(input_row, key_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        styled_btn(input_row, "➕  ADD", lambda: self._add_custom_key(key_var.get()),
                   bg=C['primary'], fg='#040414', width=10).pack(side=tk.LEFT)

        list_outer = premium_card(pg, accent=C['warning'])
        tk.Label(list_outer, text="CUSTOM BLOCKED KEYS", font=('Segoe UI', 9, 'bold'),
                 bg=C['card'], fg=C['warning']).pack(anchor=tk.W, pady=(0, 8))

        self._custom_keys_listbox = tk.Listbox(
            list_outer, font=('Consolas', 10), bg=C['input_bg'], fg=C['text'],
            selectbackground=C['primary'], selectforeground=C['text_bright'],
            highlightthickness=1, highlightcolor=C['primary'],
            highlightbackground=C['input_border'], relief=tk.FLAT,
            height=8, activestyle='none'
        )
        self._custom_keys_listbox.pack(fill=tk.BOTH, expand=True)

        btn_row = tk.Frame(list_outer, bg=C['card'])
        btn_row.pack(fill=tk.X, pady=(8, 0))

        styled_btn(btn_row, "🗑  REMOVE SELECTED", self._remove_custom_key,
                   bg=C['danger'], fg='white', width=14).pack(side=tk.LEFT, padx=(0, 6))
        styled_btn(btn_row, "🔄  REFRESH", self._refresh_custom_keys,
                   bg=C['surface_alt'], fg=C['text_dim'], width=10).pack(side=tk.LEFT)

        self._refresh_custom_keys()
        return pg

    # ── Custom keys callbacks ──────────────────────────────────────
    def _add_custom_key(self, combo):
        combo = combo.strip().lower()
        if not combo:
            return
        if combo in self.sec.blocked_keys:
            messagebox.showinfo("Already Blocked", f"'{combo}' is already blocked.")
            return
        valid_parts = {'ctrl', 'alt', 'shift', 'win', 'fn'}
        parts = combo.replace('+', ' ').split()
        if not all(p in valid_parts or len(p) <= 4 for p in parts):
            messagebox.showerror("Invalid Format", "Use format: ctrl+alt+del or f5")
            return
        self.sec.add_custom_blocked_key(combo)
        self._refresh_custom_keys()
        messagebox.showinfo("Success", f"'{combo}' added to blocked keys.")

    def _remove_custom_key(self):
        selection = self._custom_keys_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Select a key to remove.")
            return
        idx = selection[0]
        combo = self._custom_keys_listbox.get(idx)
        self.sec.remove_custom_blocked_key(combo)
        self._refresh_custom_keys()
        messagebox.showinfo("Removed", f"'{combo}' removed from blocked keys.")

    def _refresh_custom_keys(self):
        lb = self._custom_keys_listbox
        lb.delete(0, tk.END)
        for k in self.sec.blocked_keys:
            if k not in Config.BLOCKED_KEYS and k not in ['ctrl+shift+y', 'ctrl+shift+h']:
                lb.insert(tk.END, k)

    # ── Page: Profiles ────────────────────────────────────────────
    def _build_profiles(self):
        """Named exam profile preset manager page."""
        pg = tk.Frame(self._content, bg=C['bg'])
        section_header(pg, "Exam Profile Presets", C['accent'])

        # ── Toolbar ─────────────────────────────────────────────
        tb = tk.Frame(pg, bg=C['bg'])
        tb.pack(fill=tk.X, padx=16, pady=(0, 8))

        styled_btn(tb, '➕  New Profile',  self._new_profile_dialog,
                   bg=C['primary'], fg='#0a0a0a').pack(side=tk.LEFT, padx=(0, 6))
        styled_btn(tb, '✏️  Edit',         self._edit_profile_dialog,
                   bg=C['surface']).pack(side=tk.LEFT, padx=(0, 6))
        styled_btn(tb, '🗑  Delete',        self._delete_profile,
                   bg=C['danger'], fg='white').pack(side=tk.LEFT, padx=(0, 6))
        styled_btn(tb, '💾  Save Current', self._save_current_as_profile,
                   bg=C['surface']).pack(side=tk.LEFT, padx=(0, 6))
        # ── New in v1.2
        styled_btn(tb, '📋  Duplicate',    self._duplicate_profile,
                   bg=C['surface']).pack(side=tk.LEFT, padx=(0, 6))
        styled_btn(tb, '📤  Export',       self._export_profile,
                   bg=C['surface']).pack(side=tk.LEFT, padx=(0, 6))
        styled_btn(tb, '📥  Import',       self._import_profile,
                   bg=C['surface']).pack(side=tk.LEFT, padx=(0, 6))
        styled_btn(tb, '🔄 Refresh',       self._refresh_profiles,
                   bg=C['surface_alt']).pack(side=tk.RIGHT)

        # ── Profile list ─────────────────────────────────────────
        list_frame = tk.Frame(pg, bg=C['bg'])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))

        cols = ('Name', 'Description', 'Modules', 'Timer', 'Saved')
        self._prof_tree = ttk.Treeview(
            list_frame, columns=cols, show='headings', height=10
        )
        for col, width in zip(cols, [160, 260, 200, 60, 130]):
            self._prof_tree.heading(col, text=col)
            self._prof_tree.column(col, width=width, minwidth=50)

        vsb2 = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                              command=self._prof_tree.yview)
        self._prof_tree.configure(yscrollcommand=vsb2.set)
        self._prof_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb2.pack(side=tk.RIGHT, fill=tk.Y)
        self._prof_tree.bind('<Double-1>', lambda e: self._edit_profile_dialog())

        # ── Detail card ──────────────────────────────────────────
        section_header(pg, "Profile Details", C['info'])
        self._prof_detail = tk.Label(
            pg, text='Select a profile to see details.',
            font=('Consolas', 9), bg=C['bg'], fg=C['text_dim'],
            justify=tk.LEFT, anchor=tk.W, padx=16
        )
        self._prof_detail.pack(fill=tk.X, padx=16, pady=4)

        self._prof_tree.bind('<<TreeviewSelect>>', self._on_profile_select)

        # Populate
        self._refresh_profiles()
        return pg

    def _refresh_profiles(self):
        """Reload all profiles into the treeview."""
        try:
            for item in self._prof_tree.get_children():
                self._prof_tree.delete(item)
            for p in self.profile_manager.list_profiles():
                name  = p.get('name', '')
                desc  = p.get('description', '')
                mods  = p.get('modules', {})
                mod_str = ', '.join(k for k, v in mods.items() if v) or 'none'
                timer = str(p.get('timer_minutes', 0)) + ' min'
                saved = p.get('saved_at', '')[:16]
                self._prof_tree.insert('', tk.END, iid=name,
                                        values=(name, desc, mod_str, timer, saved))
        except Exception:
            pass

    def _on_profile_select(self, event=None):
        sel = self._prof_tree.selection()
        if not sel:
            return
        name = sel[0]
        p = self.profile_manager.load_profile(name)
        if not p:
            return
        mods  = p.get('modules', {})
        mod_lines = '\n  '.join(
            f"{'✓' if v else '✗'}  {k.capitalize()}"
            for k, v in mods.items()
        )
        detail = (
            f"Profile : {p['name']}\n"
            f"Saved   : {p.get('saved_at', '')[:19]}\n"
            f"Timer   : {p.get('timer_minutes', 0)} minutes\n"
            f"Modules :\n  {mod_lines}"
        )
        self._prof_detail.config(text=detail)

    def _new_profile_dialog(self):
        self._profile_form_dialog(edit_name=None)

    def _edit_profile_dialog(self):
        sel = self._prof_tree.selection()
        name = sel[0] if sel else None
        self._profile_form_dialog(edit_name=name)

    def _profile_form_dialog(self, edit_name=None):
        """Dialog for creating/editing a profile."""
        existing = None
        if edit_name:
            existing = self.profile_manager.load_profile(edit_name)

        dlg = tk.Toplevel(self.window)
        dlg.title('🏷️  ' + ('Edit Profile' if existing else 'New Profile'))
        dlg.geometry('500x560')
        dlg.configure(bg=C['bg'])
        dlg.transient(self.window)
        dlg.grab_set()
        self._center_dialog(dlg, 500, 560)

        tk.Label(dlg, text='Edit Profile' if existing else 'New Profile',
                 font=('Segoe UI', 15, 'bold'), bg=C['bg'],
                 fg=C['primary']).pack(pady=(18, 10))

        # Name
        nf = tk.Frame(dlg, bg=C['bg'])
        nf.pack(fill=tk.X, padx=28, pady=4)
        tk.Label(nf, text='Name:', font=('Segoe UI', 9, 'bold'),
                 bg=C['bg'], fg=C['text_dim']).pack(anchor=tk.W)
        name_var = tk.StringVar(value=existing['name'] if existing else '')
        tk.Entry(nf, textvariable=name_var, font=('Segoe UI', 11),
                 bg=C['input_bg'], fg=C['text'], relief=tk.FLAT,
                 insertbackground=C['primary'],
                 highlightthickness=1,
                 highlightbackground=C['border']).pack(fill=tk.X, ipady=5)

        # Description
        df = tk.Frame(dlg, bg=C['bg'])
        df.pack(fill=tk.X, padx=28, pady=4)
        tk.Label(df, text='Description:', font=('Segoe UI', 9, 'bold'),
                 bg=C['bg'], fg=C['text_dim']).pack(anchor=tk.W)
        desc_var = tk.StringVar(value=existing.get('description', '') if existing else '')
        tk.Entry(df, textvariable=desc_var, font=('Segoe UI', 11),
                 bg=C['input_bg'], fg=C['text'], relief=tk.FLAT,
                 insertbackground=C['primary'],
                 highlightthickness=1,
                 highlightbackground=C['border']).pack(fill=tk.X, ipady=5)

        # Modules
        mf = tk.LabelFrame(dlg, text='Modules', bg=C['bg'],
                            fg=C['primary'], font=('Segoe UI', 9, 'bold'),
                            padx=8, pady=6)
        mf.pack(fill=tk.X, padx=28, pady=8)
        existing_mods = (existing or {}).get('modules', {k: True for k in Config.SELECTIVE_BLOCKING})
        mod_vars: dict[str, tk.BooleanVar] = {}
        for key in Config.SELECTIVE_BLOCKING:
            v = tk.BooleanVar(value=existing_mods.get(key, True))
            mod_vars[key] = v
            tk.Checkbutton(mf, text=f'  {key.capitalize()}', variable=v,
                           bg=C['bg'], fg=C['text'],
                           selectcolor=C['input_bg'],
                           activebackground=C['bg']).pack(anchor=tk.W)

        # Timer
        tmf = tk.Frame(dlg, bg=C['bg'])
        tmf.pack(fill=tk.X, padx=28, pady=4)
        tk.Label(tmf, text='Timer (minutes, 0 = none):',
                 font=('Segoe UI', 9, 'bold'), bg=C['bg'],
                 fg=C['text_dim']).pack(anchor=tk.W)
        timer_var = tk.StringVar(
            value=str(existing.get('timer_minutes', 0)) if existing else '0'
        )
        tk.Entry(tmf, textvariable=timer_var, font=('Segoe UI', 11),
                 bg=C['input_bg'], fg=C['text'], width=8,
                 relief=tk.FLAT, insertbackground=C['primary']).pack(anchor=tk.W, ipady=4)

        def save():
            nm = name_var.get().strip()
            if not nm:
                messagebox.showerror('Error', 'Name cannot be empty.', parent=dlg)
                return
            try:
                mins = int(timer_var.get())
            except ValueError:
                mins = 0
            data = {
                'description': desc_var.get().strip(),
                'modules': {k: v.get() for k, v in mod_vars.items()},
                'blocked_keys': self.sec.blocked_keys[:],
                'blocked_websites': Config.BLOCKED_WEBSITES[:],
                'timer_minutes': mins,
            }
            # If name changed, delete old entry
            if edit_name and edit_name != nm:
                self.profile_manager.delete_profile(edit_name)
            self.profile_manager.save_profile(nm, data)
            self._refresh_profiles()
            self._toast(f"💾 Profile '{nm}' saved", C['success'])
            dlg.destroy()

        styled_btn(dlg, '💾  Save Profile', save,
                   bg=C['primary'], fg='#0a0a0a').pack(pady=14)

    def _delete_profile(self):
        sel = self._prof_tree.selection()
        if not sel:
            return
        name = sel[0]
        if messagebox.askyesno('Delete', f"Delete profile '{name}'?",
                                parent=self.window):
            self.profile_manager.delete_profile(name)
            self._refresh_profiles()
            self._toast(f"🗑 Profile '{name}' deleted", C['warning'])

    def _save_current_as_profile(self):
        """Snapshot the current session settings as a new profile."""
        name = simpledialog.askstring(
            'Save Profile', 'Profile name:', parent=self.window
        )
        if not name:
            return
        self.profile_manager.build_from_current(
            name=name,
            description='Saved from current session',
            modules=dict(self.sec.selective_blocking),
            blocked_keys=self.sec.blocked_keys[:],
            blocked_websites=Config.BLOCKED_WEBSITES[:],
            timer_minutes=(self._exam_timer.get_remaining_seconds() // 60
                           if self._exam_timer else 0),
        )
        self._refresh_profiles()
        self._toast(f"💾 Saved as '{name}'", C['success'])

    # ── Page: Settings ───────────────────────────────────────────
    def _build_settings(self):
        pg = tk.Frame(self._content, bg=C['bg'])
        canvas = tk.Canvas(pg, bg=C['bg'], highlightthickness=0)
        vsb = ttk.Scrollbar(pg, orient='vertical', command=canvas.yview)
        inner = tk.Frame(canvas, bg=C['bg'])
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        self._build_keyboard_settings(inner)
        self._build_mouse_settings(inner)
        self._build_network_settings(inner)
        self._build_allowed_sites_settings(inner)
        self._build_theme_settings(inner)
        self._build_advanced_settings(inner)
        self._build_2fa_settings(inner)
        return pg

    def _build_keyboard_settings(self, parent):
        f = tk.LabelFrame(parent, text="⌨  Keyboard Blocking",
                           bg=C['bg'], fg=C['primary'],
                           font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        f.pack(fill=tk.X, padx=16, pady=10)
        row = tk.Frame(f, bg=C['bg'])
        row.pack(fill=tk.X, pady=(0, 6))
        self._keys_lb = tk.Listbox(row, height=6, bg=C['input_bg'],
                                    fg=C['text'],
                                    selectbackground=C['primary_dark'],
                                    font=('Consolas', 10), relief=tk.FLAT,
                                    highlightthickness=1,
                                    highlightcolor=C['border'])
        self._keys_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        self._load_keys_list()
        btns = tk.Frame(row, bg=C['bg'])
        btns.pack(side=tk.RIGHT, fill=tk.Y)
        for t, cmd in [('🎯 Detect', self._detect_key),
                       ('⌨ Type',   self._add_key_manual),
                       ('Remove',   self._remove_key),
                       ('Reset',    self._reset_keys)]:
            styled_btn(btns, t, cmd, bg=C['surface']).pack(
                fill=tk.X, pady=2)

    def _build_mouse_settings(self, parent):
        f = tk.LabelFrame(parent, text="🖱  Mouse Blocking",
                           bg=C['bg'], fg=C['primary'],
                           font=('Segoe UI', 10, 'bold'), padx=12, pady=12)
        f.pack(fill=tk.X, padx=16, pady=10)

        # Description
        tk.Label(f, text="Choose which mouse actions to block during lockdown:",
                 font=('Segoe UI', 9), bg=C['bg'],
                 fg=C['text_dim']).pack(anchor=tk.W, pady=(0, 8))

        # ── Checkbox grid ────────────────────────────────────────
        self._mouse_flags = {
            'left':     tk.BooleanVar(value=False),
            'right':    tk.BooleanVar(value=False),
            'middle':   tk.BooleanVar(value=True),
            'double':   tk.BooleanVar(value=False),
            'side':     tk.BooleanVar(value=True),
            'scroll':   tk.BooleanVar(value=False),
        }
        options = [
            ('left',     '🖱  Left Click',        'Block primary (left) mouse button'),
            ('right',    '🖱  Right Click',       'Block context menu (right) button'),
            ('middle',   '🖱  Middle Click',      'Block scroll-wheel click'),
            ('double',   '🖱  Double Click',      'Suppress rapid double-clicks (400 ms window)'),
            ('side',     '🖱  Side / X Buttons',  'Block X1, X2, back/forward buttons'),
            ('scroll',   '↕️  Scroll Wheel',      'Block mouse scrolling'),
        ]
        grid = tk.Frame(f, bg=C['bg'])
        grid.pack(fill=tk.X, pady=(0, 10))
        for i, (key, label, tip) in enumerate(options):
            col = i % 2          # 2 columns
            row_idx = i // 2
            cell = tk.Frame(grid, bg=C['surface'], padx=10, pady=8)
            cell.grid(row=row_idx, column=col, padx=(0, 8), pady=4, sticky='ew')
            grid.columnconfigure(col, weight=1)
            var = self._mouse_flags[key]
            cb = tk.Checkbutton(
                cell, text=f"  {label}", variable=var,
                font=('Segoe UI', 10, 'bold'),
                bg=C['surface'], fg=C['text'],
                selectcolor=C['input_bg'],
                activebackground=C['surface'],
                activeforeground=C['primary'],
                command=self._sync_mouse_flags,
            )
            cb.pack(anchor=tk.W)
            tk.Label(cell, text=f"  {tip}",
                     font=('Segoe UI', 8), bg=C['surface'],
                     fg=C['text_dim']).pack(anchor=tk.W)

        # ── Status line + Apply button
        bottom = tk.Frame(f, bg=C['bg'])
        bottom.pack(fill=tk.X, pady=(4, 0))
        self._mouse_status = tk.Label(
            bottom, text="No mouse restrictions active.",
            font=('Consolas', 9), bg=C['bg'], fg=C['text_dim'])
        self._mouse_status.pack(side=tk.LEFT)
        styled_btn(bottom, '✅  Apply Mouse Settings',
                   self._apply_mouse_flags,
                   bg=C['primary'], fg='#0a0a0a').pack(side=tk.RIGHT)

        # Sync initial state from manager
        self._pull_mouse_flags_from_manager()

    def _build_network_settings(self, parent):
        f = tk.LabelFrame(parent, text="🌐  Network Blocking",
                           bg=C['bg'], fg=C['primary'],
                           font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        f.pack(fill=tk.X, padx=16, pady=10)
        self._net_var = tk.BooleanVar(value=True)
        tk.Checkbutton(f, text='Enable internet blocking',
                       variable=self._net_var, bg=C['bg'],
                       fg=C['text'], selectcolor=C['input_bg'],
                       activebackground=C['bg']).pack(anchor=tk.W)
        tk.Label(f, text='Blocked Websites:', bg=C['bg'],
                 fg=C['text']).pack(anchor=tk.W, pady=(8, 0))
        row = tk.Frame(f, bg=C['bg'])
        row.pack(fill=tk.X, pady=(4, 6))
        self._web_lb = tk.Listbox(row, height=5, bg=C['input_bg'],
                                   fg=C['text'],
                                   selectbackground=C['primary_dark'],
                                   font=('Consolas', 10), relief=tk.FLAT,
                                   highlightthickness=1,
                                   highlightcolor=C['border'])
        self._web_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        self._load_website_list()
        btns = tk.Frame(row, bg=C['bg'])
        btns.pack(side=tk.RIGHT, fill=tk.Y)
        for t, cmd in [('Add',    self._add_website),
                       ('Remove', self._remove_website)]:
            styled_btn(btns, t, cmd, bg=C['surface']).pack(fill=tk.X, pady=2)

    def _build_advanced_settings(self, parent):
        f = tk.LabelFrame(parent, text="🔧  Advanced",
                           bg=C['bg'], fg=C['primary'],
                           font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        f.pack(fill=tk.X, padx=16, pady=(0, 8))
        self._autostart_var = tk.BooleanVar()
        self._winprot_var   = tk.BooleanVar(value=True)
        self._procmon_var   = tk.BooleanVar(value=True)
        for text, var in [
            ('Auto-start lockdown on login',        self._autostart_var),
            ('Aggressive window protection',         self._winprot_var),
            ('Auto-terminate suspicious processes',  self._procmon_var),
        ]:
            tk.Checkbutton(f, text=text, variable=var, bg=C['bg'],
                           fg=C['text'], selectcolor=C['input_bg'],
                           activebackground=C['bg']).pack(anchor=tk.W)

        # Screenshot interval
        ss_row = tk.Frame(f, bg=C['bg'])
        ss_row.pack(fill=tk.X, pady=(10, 2))
        tk.Label(ss_row, text='📸  Screenshot interval (seconds):',
                 font=('Segoe UI', 9, 'bold'), bg=C['bg'],
                 fg=C['text']).pack(side=tk.LEFT, padx=(0, 8))
        saved_interval = int(self.db.get_setting(
            'screenshot_interval', str(Config.SCREENSHOT_INTERVAL_SEC)) or 60)
        self._ss_interval_var = tk.IntVar(value=saved_interval)
        spinbox = tk.Spinbox(
            ss_row, from_=10, to=300, increment=10,
            textvariable=self._ss_interval_var,
            width=6, font=('Segoe UI', 10),
            bg=C['input_bg'], fg=C['text'],
            buttonbackground=C['surface_alt'],
            relief=tk.FLAT
        )
        spinbox.pack(side=tk.LEFT)
        tk.Label(ss_row, text='(10–300 s)',
                 font=('Segoe UI', 8), bg=C['bg'],
                 fg=C['text_dim']).pack(side=tk.LEFT, padx=(6, 0))

        styled_btn(f, '💾  Save All Settings', self._save_settings,
                   bg=C['primary'], fg='#0a0a0a').pack(pady=(12, 0))

    # ── Allowed-Sites whitelist panel ─────────────────────────────
    def _build_allowed_sites_settings(self, parent):
        f = tk.LabelFrame(parent, text="✅  Allowed Websites (Whitelist)",
                           bg=C['bg'], fg=C['success'],
                           font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        f.pack(fill=tk.X, padx=16, pady=(0, 16))
        tk.Label(f,
                 text='These sites will NOT be blocked even if internet blocking is on.',
                 font=('Segoe UI', 8), bg=C['bg'],
                 fg=C['text_dim']).pack(anchor=tk.W, pady=(0, 6))
        row = tk.Frame(f, bg=C['bg'])
        row.pack(fill=tk.X)
        self._allow_lb = tk.Listbox(
            row, height=4, bg=C['input_bg'], fg='#00e676',
            selectbackground='#00e67622',
            font=('Consolas', 10), relief=tk.FLAT,
            highlightthickness=1, highlightcolor=C['border'])
        self._allow_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        self._load_allowed_list()
        btns = tk.Frame(row, bg=C['bg'])
        btns.pack(side=tk.RIGHT, fill=tk.Y)
        for t, cmd in [('Add',    self._add_allowed_site),
                       ('Remove', self._remove_allowed_site)]:
            styled_btn(btns, t, cmd, bg=C['surface']).pack(fill=tk.X, pady=2)

    # ── Theme Settings ───────────────────────────────────────────
    def _build_theme_settings(self, parent):
        f = tk.LabelFrame(parent, text="🎨  Theme & Appearance",
                           bg=C['bg'], fg=C['primary'],
                           font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        f.pack(fill=tk.X, padx=16, pady=(0, 16))
        
        tk.Label(f, text='Select Accent Theme (Applies on next restart):', bg=C['bg'],
                 fg=C['text']).pack(anchor=tk.W, pady=(0, 4))
        
        self._theme_var = tk.StringVar(value=Config.ACTIVE_THEME)
        themes = list(Config.THEMES.keys())
        theme_cb = ttk.Combobox(f, textvariable=self._theme_var,
                                values=themes, state='readonly', width=20)
        theme_cb.pack(anchor=tk.W, pady=4)
        
        def apply_theme():
            th = self._theme_var.get()
            self.db.save_setting('active_theme', th)
            self._toast(f"🎨 Theme '{th}' selected. Restart app to apply.", C['primary'])

        styled_btn(f, 'Apply Theme', apply_theme, bg=C['surface']).pack(anchor=tk.W, pady=(4, 0))

    # ── Page: Logs ───────────────────────────────────────────
    # ── 2FA Settings Card ─────────────────────────────────────────
    def _build_2fa_settings(self, parent):
        f = tk.LabelFrame(parent, text="🔐  Two-Factor Authentication (TOTP)",
                           bg=C['bg'], fg=C['primary'],
                           font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        f.pack(fill=tk.X, padx=16, pady=(0, 16))

        if not TOTPManager.is_available():
            tk.Label(f, text="⚠  pyotp not installed. Run: pip install pyotp",
                     bg=C['bg'], fg=C['warning'],
                     font=('Segoe UI', 9)).pack(anchor=tk.W)
            return

        # Status line
        status_row = tk.Frame(f, bg=C['bg'])
        status_row.pack(fill=tk.X, pady=(0, 8))

        enabled = self.totp_manager.is_enabled()
        self._2fa_status_lbl = tk.Label(
            status_row,
            text=("🟢  TOTP 2FA is ENABLED" if enabled
                  else "🔴  TOTP 2FA is DISABLED"),
            bg=C['bg'],
            fg=C['success'] if enabled else C['danger'],
            font=('Segoe UI', 9, 'bold')
        )
        self._2fa_status_lbl.pack(side=tk.LEFT)

        # Buttons
        btn_row = tk.Frame(f, bg=C['bg'])
        btn_row.pack(fill=tk.X, pady=(0, 4))

        def _toggle_2fa():
            if self.totp_manager.is_enabled():
                # Disable: confirm first
                if messagebox.askyesno(
                        "Disable 2FA",
                        "Disable Two-Factor Authentication?\n"
                        "This will remove the stored TOTP secret.",
                        parent=self.window):
                    self.totp_manager.set_enabled(False)
                    self.totp_manager.delete_secret('admin')
                    self._2fa_status_lbl.config(
                        text="🔴  TOTP 2FA is DISABLED", fg=C['danger'])
                    self._toast("🔐 2FA disabled", C['warning'])
            else:
                # Enable: generate secret + show QR
                secret = self.totp_manager.generate_secret('admin')
                self.totp_manager.set_enabled(True)
                self._2fa_status_lbl.config(
                    text="🟢  TOTP 2FA is ENABLED", fg=C['success'])
                self._toast("🔐 2FA enabled — scan QR code now!", C['success'])
                _show_qr()

        styled_btn(btn_row, "🔄  Toggle 2FA", _toggle_2fa,
                   bg=C['surface']).pack(side=tk.LEFT, padx=(0, 8))

        def _show_qr():
            img = self.totp_manager.build_qr_image('admin', box_size=7, border=3)
            if img is None:
                if not self.totp_manager.has_secret('admin'):
                    messagebox.showinfo("No Secret",
                                        "Enable 2FA first to generate a QR code.",
                                        parent=self.window)
                else:
                    messagebox.showinfo("QR Error",
                                        "Could not build QR — qrcode library missing?\n"
                                        "Run: pip install qrcode[pil]",
                                        parent=self.window)
                return

            from PIL import ImageTk
            dlg = tk.Toplevel(self.window)
            dlg.title("🔐  Scan with Google Authenticator")
            dlg.configure(bg=C['bg'])
            dlg.resizable(False, False)
            dlg.transient(self.window)
            dlg.grab_set()
            self._center_dialog(dlg, 320, 400)

            tk.Label(dlg, text="🔐  ExamShield 2FA Setup",
                     font=('Segoe UI', 12, 'bold'),
                     bg=C['bg'], fg=C['primary']).pack(pady=(16, 6))
            tk.Label(dlg,
                     text="Open Google Authenticator and scan\nthis QR code to enroll ExamShield.",
                     font=('Segoe UI', 9), bg=C['bg'],
                     fg=C['text_dim'], justify=tk.CENTER).pack(pady=(0, 10))

            tk_img = ImageTk.PhotoImage(img)
            lbl = tk.Label(dlg, image=tk_img, bg=C['bg'])
            lbl.image = tk_img   # keep reference
            lbl.pack(padx=20, pady=4)

            # Show current code (for testing)
            code = self.totp_manager.get_current_code('admin')
            tk.Label(dlg, text=f"Current code: {code}",
                     font=('Consolas', 13, 'bold'),
                     bg=C['bg'], fg=C['success']).pack(pady=6)
            tk.Label(dlg, text="(refreshes every 30 seconds)",
                     font=('Segoe UI', 8), bg=C['bg'],
                     fg=C['text_dim']).pack()

            styled_btn(dlg, "✓  Done", dlg.destroy,
                       bg=C['primary'], fg='#0a0a0a').pack(pady=12)

        styled_btn(btn_row, "📷  Show QR Code", _show_qr,
                   bg=C['surface']).pack(side=tk.LEFT)

        # Describe how it works
        tk.Label(f,
                 text=("When enabled, after entering your password you will be\n"
                       "prompted for a 6-digit code from Google Authenticator."),
                 font=('Segoe UI', 8), bg=C['bg'],
                 fg=C['text_dim'], justify=tk.LEFT).pack(anchor=tk.W, pady=(8, 0))

    # ── Timer helpers (from Dashboard) ────────────────────────────
    def _toggle_timer_pause(self):
        if not self._exam_timer or not self._exam_timer.is_running:
            return
        if self._exam_timer.is_paused:
            self._exam_timer.resume()
            if self._timer_pause_btn:
                self._timer_pause_btn.config(text="⏸ Pause Timer")
        else:
            self._exam_timer.pause()
            if self._timer_pause_btn:
                self._timer_pause_btn.config(text="▶ Resume Timer")

    def _extend_timer(self, minutes: int):
        if not self._exam_timer or not self._exam_timer.is_running:
            self._toast("No active exam timer", C['warning'])
            return
        self._exam_timer.extend(minutes)
        self._toast(f"⏱ +{minutes} min added to timer", C['success'])

    def _set_timer_btns_enabled(self, enabled: bool):
        """Enable or disable the Pause/Extend timer buttons."""
        state = tk.NORMAL if enabled else tk.DISABLED
        for btn in [self._timer_pause_btn, self._timer_extend_btn,
                    getattr(self, '_timer_extend10_btn', None)]:
            if btn:
                try:
                    btn.config(state=state)
                except Exception:
                    pass
        if not enabled and self._timer_pause_btn:
            try:
                self._timer_pause_btn.config(text="⏸ Pause Timer")
            except Exception:
                pass

    def _build_logs(self):

        pg = tk.Frame(self._content, bg=C['bg'])
        section_header(pg, "Activity Logs", C['info'])
        toolbar = tk.Frame(pg, bg=C['bg'])
        toolbar.pack(fill=tk.X, padx=16, pady=4)
        for t, cmd in [('🔄 Refresh', self._refresh_logs),
                       ('🗑 Clear',   self._clear_logs),
                       ('💾 Export',  self._export_logs)]:
            styled_btn(toolbar, t, cmd, bg=C['surface']).pack(
                side=tk.LEFT, padx=(0, 6))
        # Verify Log Integrity button (right-aligned)
        styled_btn(
            toolbar, '🔒 Verify Log Integrity',
            self._verify_log_integrity,
            bg=C['surface_alt']
        ).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Label(toolbar, text='Filter:', bg=C['bg'],
                 fg=C['text_dim']).pack(side=tk.LEFT, padx=(16, 4))
        self._filter_var = tk.StringVar(value='All')
        filt = ttk.Combobox(toolbar, textvariable=self._filter_var,
                            values=['All', 'Blocked Only',
                                    'Security Events', 'System Events'],
                            state='readonly', width=16)
        filt.pack(side=tk.LEFT)
        filt.bind('<<ComboboxSelected>>', lambda e: self._refresh_logs())

        # ── Search bar
        search_row = tk.Frame(pg, bg=C['bg'])
        search_row.pack(fill=tk.X, padx=16, pady=(4, 0))
        tk.Label(search_row, text='🔍  Search:',
                 font=('Segoe UI', 9), bg=C['bg'],
                 fg=C['text_dim']).pack(side=tk.LEFT, padx=(0, 6))
        self._log_search_var = tk.StringVar()
        search_entry = tk.Entry(
            search_row, textvariable=self._log_search_var,
            font=('Segoe UI', 10), bg=C['input_bg'], fg=C['text'],
            relief=tk.FLAT, insertbackground=C['primary'],
            highlightthickness=1, highlightcolor=C['primary'],
            highlightbackground=C['border']
        )
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        styled_btn(search_row, '✕',
                   lambda: (self._log_search_var.set(''), self._refresh_logs()),
                   bg=C['surface'], pady=4).pack(side=tk.LEFT, padx=(4, 0))
        # Live search on every keystroke
        self._log_search_var.trace_add('write', lambda *_: self._refresh_logs())

        self._stats_label = tk.Label(pg, text='', font=('Consolas', 9),
                                      bg=C['bg'], fg=C['text_dim'])
        self._stats_label.pack(anchor=tk.W, padx=16, pady=2)

        lf = tk.Frame(pg, bg=C['bg'])
        lf.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        self._logs_text = scrolledtext.ScrolledText(
            lf, wrap=tk.WORD, height=22, bg=C['surface'], fg=C['text'],
            font=('Consolas', 9), relief=tk.FLAT,
            insertbackground=C['primary'],
        )
        self._logs_text.pack(fill=tk.BOTH, expand=True)
        self._logs_text.tag_config('blocked', foreground=C['danger'])
        self._logs_text.tag_config('ok',      foreground=C['success'])
        self._logs_text.tag_config('ts',      foreground=C['text_dim'])
        self._logs_text.tag_config('match',   background='#00d4ff22',
                                               foreground=C['text_bright'])
        return pg

    # ── Page: Dynamic Rules ──────────────────────────────────────
    def _build_dynamic_rules(self):
        pg = tk.Frame(self._content, bg=C['bg'])
        canvas = tk.Canvas(pg, bg=C['bg'], highlightthickness=0)
        vsb = ttk.Scrollbar(pg, orient='vertical', command=canvas.yview)
        inner = tk.Frame(canvas, bg=C['bg'])
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        section_header(inner, "Live Updates During Exam", C['danger'])
        tk.Label(inner, text="Changes made here are applied immediately to the active exam session.",
                 font=('Segoe UI', 9), bg=C['bg'], fg=C['text_dim']).pack(anchor=tk.W, padx=16, pady=(0,10))

        # ── Process Management ───────────────────────────────────────
        f_proc = tk.LabelFrame(inner, text="🔍  Process Management",
                           bg=C['bg'], fg=C['primary'],
                           font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        f_proc.pack(fill=tk.X, padx=16, pady=10)
        
        # Mode Toggle
        mode_frame = tk.Frame(f_proc, bg=C['bg'])
        mode_frame.pack(fill=tk.X, pady=(0, 10))
        self._proc_mode_var = tk.BooleanVar(value=Config.PROCESS_WHITELIST_MODE)
        
        def toggle_mode():
            Config.PROCESS_WHITELIST_MODE = self._proc_mode_var.get()
            self.db.save_setting('process_whitelist_mode', '1' if Config.PROCESS_WHITELIST_MODE else '0')
            mode_text = "Whitelist (Strict)" if Config.PROCESS_WHITELIST_MODE else "Blacklist (Default)"
            self._toast(f"Process Mode set to: {mode_text}", C['success'])
            
        tk.Checkbutton(mode_frame, text="Enable Strict Whitelist Mode (Only allow approved apps)",
                       variable=self._proc_mode_var, command=toggle_mode,
                       bg=C['bg'], fg=C['text'], selectcolor=C['input_bg'],
                       activebackground=C['bg']).pack(anchor=tk.W)

        # Split frame for Blacklist / Whitelist
        proc_split = tk.Frame(f_proc, bg=C['bg'])
        proc_split.pack(fill=tk.BOTH, expand=True)
        
        # Left: Suspicious (Blacklist)
        left_proc = tk.Frame(proc_split, bg=C['bg'])
        left_proc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        tk.Label(left_proc, text="Suspicious Processes (Blacklist)", bg=C['bg'], fg=C['danger']).pack(anchor=tk.W)
        self._dyn_proc_lb = tk.Listbox(left_proc, height=6, bg=C['input_bg'], fg=C['text'],
                                   selectbackground=C['primary_dark'], font=('Consolas', 9),
                                   relief=tk.FLAT, highlightthickness=1, highlightcolor=C['border'])
        self._dyn_proc_lb.pack(fill=tk.BOTH, expand=True, pady=(0,4))
        
        row_proc1 = tk.Frame(left_proc, bg=C['bg'])
        row_proc1.pack(fill=tk.X)
        self._dyn_proc_var = tk.StringVar()
        proc_entry1 = dark_entry(row_proc1, self._dyn_proc_var)
        proc_entry1.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        def add_proc():
            p = self._dyn_proc_var.get().strip().lower()
            if p and p not in Config.SUSPICIOUS_PROCESSES:
                Config.SUSPICIOUS_PROCESSES.append(p)
                self.db.save_setting("suspicious_processes", json.dumps(Config.SUSPICIOUS_PROCESSES))
                self._dyn_proc_var.set('')
                self._load_dyn_proc()
                self._toast(f"Added suspicious process: {p}", C['success'])
        def rm_proc():
            sel = self._dyn_proc_lb.curselection()
            if sel:
                p = self._dyn_proc_lb.get(sel[0])
                if p in Config.SUSPICIOUS_PROCESSES:
                    Config.SUSPICIOUS_PROCESSES.remove(p)
                    self.db.save_setting("suspicious_processes", json.dumps(Config.SUSPICIOUS_PROCESSES))
                    self._load_dyn_proc()
                    self._toast(f"Removed suspicious process: {p}", C['warning'])
                    
        styled_btn(row_proc1, "+", add_proc, bg=C['surface'], width=2).pack(side=tk.LEFT, padx=2)
        styled_btn(row_proc1, "-", rm_proc, bg=C['surface'], width=2).pack(side=tk.LEFT)

        # Right: Allowed (Whitelist)
        right_proc = tk.Frame(proc_split, bg=C['bg'])
        right_proc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))
        tk.Label(right_proc, text="Allowed Processes (Whitelist)", bg=C['bg'], fg=C['success']).pack(anchor=tk.W)
        self._dyn_allow_lb = tk.Listbox(right_proc, height=6, bg=C['input_bg'], fg=C['text'],
                                   selectbackground=C['primary_dark'], font=('Consolas', 9),
                                   relief=tk.FLAT, highlightthickness=1, highlightcolor=C['border'])
        self._dyn_allow_lb.pack(fill=tk.BOTH, expand=True, pady=(0,4))

        row_proc2 = tk.Frame(right_proc, bg=C['bg'])
        row_proc2.pack(fill=tk.X)
        self._dyn_allow_var = tk.StringVar()
        proc_entry2 = dark_entry(row_proc2, self._dyn_allow_var)
        proc_entry2.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        
        def add_allow():
            p = self._dyn_allow_var.get().strip().lower()
            if p and p not in Config.ALLOWED_PROCESSES:
                Config.ALLOWED_PROCESSES.append(p)
                self.db.save_setting("allowed_processes", json.dumps(Config.ALLOWED_PROCESSES))
                self._dyn_allow_var.set('')
                self._load_dyn_allow()
                self._toast(f"Added allowed process: {p}", C['success'])
        def rm_allow():
            sel = self._dyn_allow_lb.curselection()
            if sel:
                p = self._dyn_allow_lb.get(sel[0])
                if p in Config.ALLOWED_PROCESSES:
                    Config.ALLOWED_PROCESSES.remove(p)
                    self.db.save_setting("allowed_processes", json.dumps(Config.ALLOWED_PROCESSES))
                    self._load_dyn_allow()
                    self._toast(f"Removed allowed process: {p}", C['warning'])
                    
        styled_btn(row_proc2, "+", add_allow, bg=C['surface'], width=2).pack(side=tk.LEFT, padx=2)
        styled_btn(row_proc2, "-", rm_allow, bg=C['surface'], width=2).pack(side=tk.LEFT)

        # ── Blocked Keys
        f_keys = tk.LabelFrame(inner, text="⌨  Blocked Keys",
                           bg=C['bg'], fg=C['primary'],
                           font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        f_keys.pack(fill=tk.X, padx=16, pady=10)
        
        row_keys = tk.Frame(f_keys, bg=C['bg'])
        row_keys.pack(fill=tk.X, pady=(0, 6))
        self._dyn_keys_lb = tk.Listbox(row_keys, height=6, bg=C['input_bg'], fg=C['text'],
                                   selectbackground=C['primary_dark'], font=('Consolas', 10),
                                   relief=tk.FLAT, highlightthickness=1, highlightcolor=C['border'])
        self._dyn_keys_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        
        self._dyn_key_var = tk.StringVar()
        key_entry = dark_entry(f_keys, self._dyn_key_var)
        key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        def add_key():
            k = self._dyn_key_var.get().strip().lower()
            if k and k not in self.sec.blocked_keys:
                self.sec.add_blocked_key(k)
                self._dyn_key_var.set('')
                self._load_dyn_keys()
                self._toast(f"Added key: {k}", C['success'])
        def rm_key():
            sel = self._dyn_keys_lb.curselection()
            if sel:
                k = self._dyn_keys_lb.get(sel[0])
                if k in self.sec.blocked_keys:
                    self.sec.remove_blocked_key(k)
                    self._load_dyn_keys()
                    self._toast(f"Removed key: {k}", C['warning'])

        btns_keys = tk.Frame(row_keys, bg=C['bg'])
        btns_keys.pack(side=tk.RIGHT, fill=tk.Y)
        styled_btn(btns_keys, "Add", add_key, bg=C['surface']).pack(fill=tk.X, pady=2)
        styled_btn(btns_keys, "Remove", rm_key, bg=C['surface']).pack(fill=tk.X, pady=2)

        # ── Allowed Websites
        f_web = tk.LabelFrame(inner, text="🌐  Allowed Websites",
                           bg=C['bg'], fg=C['primary'],
                           font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        f_web.pack(fill=tk.X, padx=16, pady=10)
        
        row_web = tk.Frame(f_web, bg=C['bg'])
        row_web.pack(fill=tk.X, pady=(0, 6))
        self._dyn_web_lb = tk.Listbox(row_web, height=6, bg=C['input_bg'], fg=C['text'],
                                   selectbackground=C['primary_dark'], font=('Consolas', 10),
                                   relief=tk.FLAT, highlightthickness=1, highlightcolor=C['border'])
        self._dyn_web_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        
        self._dyn_web_var = tk.StringVar()
        web_entry = dark_entry(f_web, self._dyn_web_var)
        web_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        def add_web():
            w = self._dyn_web_var.get().strip().lower()
            if w:
                if not hasattr(Config, 'ALLOWED_WEBSITES'):
                    Config.ALLOWED_WEBSITES = []
                if w not in Config.ALLOWED_WEBSITES:
                    Config.ALLOWED_WEBSITES.append(w)
                    self._dyn_web_var.set('')
                    self._load_dyn_web()
                    if hasattr(self.sec.network_manager, 'refresh_firewall_rules'):
                        self.sec.network_manager.refresh_firewall_rules()
                    self._toast(f"Allowed website: {w}", C['success'])
        def rm_web():
            sel = self._dyn_web_lb.curselection()
            if sel:
                w = self._dyn_web_lb.get(sel[0])
                if hasattr(Config, 'ALLOWED_WEBSITES') and w in Config.ALLOWED_WEBSITES:
                    Config.ALLOWED_WEBSITES.remove(w)
                    self._load_dyn_web()
                    self._toast(f"Removed allowed website: {w}", C['warning'])

        btns_web = tk.Frame(row_web, bg=C['bg'])
        btns_web.pack(side=tk.RIGHT, fill=tk.Y)
        styled_btn(btns_web, "Add", add_web, bg=C['surface']).pack(fill=tk.X, pady=2)
        styled_btn(btns_web, "Remove", rm_web, bg=C['surface']).pack(fill=tk.X, pady=2)

        self._load_dyn_proc()
        self._load_dyn_allow()
        self._load_dyn_keys()
        self._load_dyn_web()
        return pg

    def _load_dyn_proc(self):
        self._dyn_proc_lb.delete(0, tk.END)
        for p in sorted(Config.SUSPICIOUS_PROCESSES):
            self._dyn_proc_lb.insert(tk.END, p)
            
    def _load_dyn_allow(self):
        self._dyn_allow_lb.delete(0, tk.END)
        for p in sorted(Config.ALLOWED_PROCESSES):
            self._dyn_allow_lb.insert(tk.END, p)
            
    def _load_dyn_keys(self):
        self._dyn_keys_lb.delete(0, tk.END)
        for k in sorted(self.sec.blocked_keys):
            self._dyn_keys_lb.insert(tk.END, k)
            
    def _load_dyn_web(self):
        self._dyn_web_lb.delete(0, tk.END)
        sites = getattr(Config, 'ALLOWED_WEBSITES', [])
        for w in sorted(sites):
            self._dyn_web_lb.insert(tk.END, w)

    # ── Lockdown Dialog ──────────────────────────────────────────
    def _show_lockdown_dialog(self):
        dlg = tk.Toplevel(self.window)
        dlg.title('🔒 Selective Lockdown')
        dlg.geometry('520x720')
        dlg.configure(bg=C['bg'])
        dlg.transient(self.window)
        dlg.grab_set()
        self._center_dialog(dlg, 520, 720)

        tk.Label(dlg, text='Configure & Start Lockdown',
                 font=('Segoe UI', 16, 'bold'), bg=C['bg'],
                 fg=C['primary']).pack(pady=(20, 4))

        # ── Profile quick-load ────────────────────────────────────
        pf = tk.Frame(dlg, bg=C['surface'], padx=14, pady=10)
        pf.pack(fill=tk.X, padx=32, pady=(0, 8))
        tk.Label(pf, text='📂  Load Profile:', font=('Segoe UI', 9, 'bold'),
                 bg=C['surface'], fg=C['text_dim']).pack(side=tk.LEFT)
        profiles = ['(custom)'] + self.profile_manager.profile_names()
        prof_var = tk.StringVar(value='(custom)')
        prof_cb = ttk.Combobox(pf, textvariable=prof_var,
                               values=profiles, state='readonly', width=22)
        prof_cb.pack(side=tk.LEFT, padx=8)

        # Module checkboxes
        modules = [
            ('keyboard',  '⌨', 'Keyboard Blocking',
             'Block Alt+Tab, Ctrl+Alt+Del, etc.'),
            ('mouse',     '🖱', 'Mouse Restrictions',
             'Block middle, back, forward buttons'),
            ('internet',  '🌐', 'Internet Blocking',
             'Complete internet disconnection'),
            ('windows',   '🪟', 'Window Protection',
             'Prevent closing/minimising windows'),
            ('processes', '🔍', 'Process Monitor',
             'Auto-terminate suspicious processes'),
            ('usb',       '💾', 'USB Storage Lock',
             'Block USB mass storage devices'),
            ('clipboard', '📋', 'Clipboard Protection',
             'Aggressively clear clipboard to prevent copy-paste'),
            ('vm_rdp',    '🖥', 'Anti-VM & RDP',
             'Block Virtual Machines and Remote Desktop'),
            ('multi_monitor', '📺', 'Multi-Monitor Block',
             'Require disconnecting secondary displays'),
            ('webcam',    '📷', 'Webcam Proctoring',
             'Monitor face presence and multiple faces via webcam.'),
            ('audio',     '🎤', 'Audio Proctoring',
             'Monitor environment for excessive noise or talking.'),
        ]
        sel_vars: dict[str, tk.BooleanVar] = {}
        for key, icon, title, desc in modules:
            card = tk.Frame(dlg, bg=C['card'])
            card.pack(fill=tk.X, padx=32, pady=4)
            v = tk.BooleanVar(value=True)
            sel_vars[key] = v
            top = tk.Frame(card, bg=C['card'])
            top.pack(fill=tk.X, padx=14, pady=(10, 2))
            tk.Checkbutton(top, text=f"  {icon}  {title}", variable=v,
                           font=('Segoe UI', 12, 'bold'),
                           bg=C['card'], fg=C['text'],
                           selectcolor=C['input_bg'],
                           activebackground=C['card'],
                           activeforeground=C['primary']).pack(anchor=tk.W)
            tk.Label(card, text=f"      {desc}",
                     font=('Segoe UI', 9), bg=C['card'],
                     fg=C['text_dim']).pack(anchor=tk.W, padx=14,
                                            pady=(0, 8))

        # ── Timer ────────────────────────────────────────────────
        tf = tk.Frame(dlg, bg=C['surface_alt'], padx=14, pady=10)
        tf.pack(fill=tk.X, padx=32, pady=8)
        tk.Label(tf, text='⏱  Exam Duration (minutes, 0 = no timer):',
                 font=('Segoe UI', 9, 'bold'),
                 bg=C['surface_alt'], fg=C['text']).pack(anchor=tk.W)
        timer_var = tk.StringVar(value='0')
        timer_entry = tk.Entry(tf, textvariable=timer_var,
                               font=('Segoe UI', 11),
                               bg=C['input_bg'], fg=C['text'],
                               width=6, relief=tk.FLAT,
                               insertbackground=C['primary'])
        timer_entry.pack(anchor=tk.W, pady=(4, 0))

        # ── Screenshots note ──────────────────────────────────────
        from src.managers.screenshot_manager import PILLOW_AVAILABLE
        ss_color = C['success'] if PILLOW_AVAILABLE else C['text_dim']
        ss_text  = ("📸  Screenshot monitoring: ON (saves every "
                    f"{Config.SCREENSHOT_INTERVAL_SEC}s + on violations)")\
                   if PILLOW_AVAILABLE else \
                   "📸  Screenshot monitoring: DISABLED (install Pillow)"
        tk.Label(dlg, text=ss_text, font=('Segoe UI', 8),
                 bg=C['bg'], fg=ss_color).pack(padx=32, anchor=tk.W)

        # ── Apply profile to controls ─────────────────────────────
        def _apply_profile(event=None):
            name = prof_var.get()
            if name == '(custom)':
                return
            p = self.profile_manager.load_profile(name)
            if not p:
                return
            mods = p.get('modules', {})
            for k, var in sel_vars.items():
                var.set(mods.get(k, True))
            timer_var.set(str(p.get('timer_minutes', 0)))
            # Apply blocked keys/websites
            bk = p.get('blocked_keys')
            if bk is not None:
                self.sec.blocked_keys = bk
                if hasattr(self, '_keys_lb'):
                    self._load_keys_list()
            bw = p.get('blocked_websites')
            if bw is not None:
                Config.BLOCKED_WEBSITES = bw
                if hasattr(self, '_web_lb'):
                    self._load_website_list()
        prof_cb.bind('<<ComboboxSelected>>', _apply_profile)

        btn_f = tk.Frame(dlg, bg=C['bg'])
        btn_f.pack(fill=tk.X, padx=32, pady=14)

        def start():
            opts = {k: v.get() for k, v in sel_vars.items()}
            if not any(opts.values()):
                messagebox.showwarning('Empty',
                    'Select at least one module!', parent=dlg)
                return
            try:
                mins = int(timer_var.get())
                if mins < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror('Invalid Timer',
                    'Enter a non-negative integer for minutes.',
                    parent=dlg)
                return

            names = [k.title() for k, v in opts.items() if v]
            profile_name = prof_var.get()
            if profile_name == '(custom)':
                profile_name = ''
            confirm_text = ('Start lockdown with:\n\n' +
                            '\n'.join(f'  ✓ {n}' for n in names))
            if mins:
                confirm_text += f'\n\n  ⏱  Timer: {mins} minutes'
            if not messagebox.askyesno('Confirm', confirm_text, parent=dlg):
                return

            dlg.destroy()
            
            def _proceed_to_lockdown():
                self._active_profile_name = profile_name
                try:
                    self.sec.start_exam_mode(opts,
                                             profile_name=profile_name,
                                             timer_minutes=mins)
                except RuntimeError as e:
                    messagebox.showerror('Hardware Check Failed', str(e), parent=self.window)
                    return
                self._start_btn.config(state=tk.DISABLED)
                self._stop_btn.config(state=tk.NORMAL)
                self._refresh_status()
                self._toast("🔒 Lockdown ACTIVE", C['danger'])
                # H6: pin admin panel on top, block minimize
                self._enforce_topmost()

                if getattr(Config, 'USE_SECURE_BROWSER', False):
                    try:
                        import subprocess
                        url = getattr(Config, 'EXAM_URL', 'https://example.com/exam')
                        self._browser_proc = subprocess.Popen([sys.executable, "-m", "src.ui.secure_browser", url])
                    except Exception as e:
                        self.log.error("BROWSER", f"Failed to start secure browser: {e}")

                # Start floating timer if requested
                if mins > 0:
                    if self._exam_timer:
                        self._exam_timer.stop()
                    self._exam_timer = ExamTimer(
                        self.window,
                        duration_minutes=mins,
                        on_expire=self._on_timer_expire,
                        on_stop=None,
                    )
                    self._exam_timer.start()
                    # Enable timer control buttons in Dashboard
                    self._set_timer_btns_enabled(True)

            self._show_audit_dialog(opts, _proceed_to_lockdown)

        styled_btn(btn_f, '🚀  START LOCKDOWN', start,
                   bg=C['success'], fg='#0a0a0a'
                   ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        styled_btn(btn_f, 'Cancel', dlg.destroy,
                   bg=C['danger'], fg='white'
                   ).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(6, 0))

    def _show_audit_dialog(self, opts, on_success_callback):
        """Displays a Pre-Exam Environment Audit checklist before lockdown."""
        dlg = tk.Toplevel(self.window)
        dlg.title('🔍 Pre-Exam Environment Audit')
        dlg.geometry('500x450')
        dlg.configure(bg=C['bg'])
        dlg.transient(self.window)
        dlg.grab_set()
        self._center_dialog(dlg, 500, 450)

        tk.Label(dlg, text='System Pre-flight Checks',
                 font=('Segoe UI', 16, 'bold'), bg=C['bg'],
                 fg=C['primary']).pack(pady=(20, 10))

        list_frame = tk.Frame(dlg, bg=C['surface'], padx=20, pady=20)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=32, pady=10)
        
        def add_check_ui(label_text):
            f = tk.Frame(list_frame, bg=C['surface'])
            f.pack(fill=tk.X, pady=8)
            status_lbl = tk.Label(f, text='[⏳]', font=('Consolas', 12, 'bold'), bg=C['surface'], fg=C['text_dim'], width=4)
            status_lbl.pack(side=tk.LEFT)
            desc_lbl = tk.Label(f, text=label_text, font=('Segoe UI', 11), bg=C['surface'], fg=C['text'])
            desc_lbl.pack(side=tk.LEFT, padx=10)
            return status_lbl

        admin_lbl = add_check_ui("Administrator Privileges")
        vm_lbl = add_check_ui("Virtual Machine Detection")
        rdp_lbl = add_check_ui("Remote Desktop (RDP)")
        monitor_lbl = add_check_ui("Multiple Monitors Detection")

        btn_f = tk.Frame(dlg, bg=C['bg'])
        btn_f.pack(fill=tk.X, padx=32, pady=20)

        proceed_btn = styled_btn(btn_f, 'Proceed to Lockdown', lambda: [dlg.destroy(), on_success_callback()],
                                 bg=C['success'], fg='#0a0a0a')
        proceed_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        proceed_btn.config(state=tk.DISABLED)

        cancel_btn = styled_btn(btn_f, 'Cancel', dlg.destroy, bg=C['danger'], fg='white')
        cancel_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(6, 0))

        def run_checks():
            all_passed = True
            import time
            import ctypes

            # 1. Admin Check
            try:
                is_admin = ctypes.windll.shell32.IsUserAnAdmin()
            except Exception:
                is_admin = False
            
            if is_admin:
                admin_lbl.config(text='[✓]', fg=C['success'])
            else:
                admin_lbl.config(text='[✗]', fg=C['danger'])
                all_passed = False
            
            self.window.update()
            time.sleep(0.3)

            # 2. VM Check
            check_vm_rdp = opts.get('vm_rdp', True)
            if check_vm_rdp:
                is_vm = self.sec.hardware.is_virtual_machine()
                if not is_vm:
                    vm_lbl.config(text='[✓]', fg=C['success'])
                else:
                    vm_lbl.config(text='[✗]', fg=C['danger'])
                    all_passed = False
            else:
                vm_lbl.config(text='[-]', fg=C['text_dim'])
            
            self.window.update()
            time.sleep(0.3)

            # 3. RDP Check
            if check_vm_rdp:
                is_rdp = self.sec.hardware.is_rdp_session()
                if not is_rdp:
                    rdp_lbl.config(text='[✓]', fg=C['success'])
                else:
                    rdp_lbl.config(text='[✗]', fg=C['danger'])
                    all_passed = False
            else:
                rdp_lbl.config(text='[-]', fg=C['text_dim'])

            self.window.update()
            time.sleep(0.3)

            # 4. Monitors Check
            if opts.get('multi_monitor', False):
                has_multi = self.sec.hardware.has_multiple_monitors()
                if has_multi:
                    monitor_lbl.config(text='[!]', fg=C['warning'])
                    desc_lbl = tk.Label(list_frame, text="(Secondary monitors will be disabled during lockdown)", 
                                        font=('Segoe UI', 8), bg=C['surface'], fg=C['text_dim'])
                    desc_lbl.pack(fill=tk.X, padx=40)
                else:
                    monitor_lbl.config(text='[✓]', fg=C['success'])
            else:
                monitor_lbl.config(text='[-]', fg=C['text_dim'])
            
            if all_passed:
                proceed_btn.config(state=tk.NORMAL)
            else:
                tk.Label(dlg, text="Critical checks failed. Cannot proceed.", font=('Segoe UI', 9, 'bold'), fg=C['danger'], bg=C['bg']).pack(before=btn_f, pady=5)

        self.window.after(500, run_checks)

    # ── Exam controls ────────────────────────────────────────────
    def _stop_exam(self):
        pw = simpledialog.askstring('🔐 Verify', 'Enter admin password:',
                                     show='*', parent=self.window)
        if pw is None:
            return
        h = hashlib.sha256(pw.encode()).hexdigest()
        if self.db.verify_admin(self.admin_user, h):
            self._do_stop_lockdown()
            self._toast("🔓 Lockdown disabled", C['success'])
        else:
            messagebox.showerror('Denied', 'Wrong password!',
                                  parent=self.window)

    def _emergency_stop(self):
        if not messagebox.askyesno('🚨 Emergency',
                'EMERGENCY STOP?\nThis disables ALL security.',
                parent=self.window):
            return
        pw = simpledialog.askstring('🔐 Auth',
                'Admin password for EMERGENCY STOP:',
                show='*', parent=self.window)
        if pw is None:
            return
        h = hashlib.sha256(pw.encode()).hexdigest()
        if self.db.verify_admin(self.admin_user, h):
            self._do_stop_lockdown()
            self._toast("🚨 Emergency stop executed", C['warning'])
        else:
            messagebox.showerror('Denied', 'Wrong password!',
                                  parent=self.window)

    def _do_stop_lockdown(self):
        """Common teardown: stop timer, stop exam mode, show report."""
        # Stop timer if running
        if self._exam_timer:
            self._exam_timer.stop()
            self._exam_timer = None
        # Disable timer control buttons
        self._set_timer_btns_enabled(False)

        # Kill secure browser if running
        if self._browser_proc:
            try:
                self._browser_proc.terminate()
                self._browser_proc = None
            except Exception as e:
                self.log.error("BROWSER", f"Failed to kill browser proc: {e}")
        report_path = self.sec.stop_exam_mode()
        self._start_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)
        self._refresh_status()
        # Release window lock
        self._release_topmost()
        # Show report notification
        if report_path:
            self._show_report_notification(report_path)

    def _on_timer_expire(self):
        """Called by ExamTimer when countdown hits zero."""
        self.log.info("TIMER_EXPIRED", "Exam timer expired — auto-ending lockdown")
        try:
            self.window.after(3200, self._do_stop_lockdown)
            self.window.after(3200, lambda: self._toast(
                "⏱ Time's up — lockdown ended automatically", C['warning']
            ))
        except Exception:
            pass

    def _show_report_notification(self, report_path: str):
        """Pop up a small dialog telling the admin the report was saved."""
        try:
            want = messagebox.askyesno(
                '📋 Session Report Saved',
                f'Session report saved:\n\n{report_path}\n\nOpen it now?',
                parent=self.window
            )
            if want:
                import subprocess
                subprocess.Popen(['notepad.exe', report_path])
        except Exception:
            pass

    # ── Breach Counter Update ────────────────────────────────────
    def update_breach_counter(self):
        """Refresh the breach counter cards on the dashboard."""
        try:
            counts = self.sec.breach_counts
            for key, lbl in self._breach_cards.items():
                val = counts.get(key, 0)
                lbl.config(
                    text=str(val),
                    fg=C['danger'] if val > 0 else C['text_dim']
                )
        except Exception:
            pass

    # ── Topmost / Anti-Minimize Guard ──────────────────────────────────────
    def _enforce_topmost(self):
        """
        Full lockdown of the admin panel window:
          • Tk: topmost + block WM_DELETE_WINDOW + <Unmap> handler
          • Win32: strip WS_CAPTION|WS_THICKFRAME|WS_SYSMENU|WS_MIN/MAXIMIZEBOX
                   so no OS-drawn ×, no Snap Layout, no resize affordances.
          • Periodic re-apply timer: re-strips every 2 s because DWM
            composition events can silently restore styles.
          • Registers HWND as exempt in window_manager so it's never
            touched by the global enforcement loop.
        """
        try:
            self.window.attributes('-topmost', True)
            self.window.deiconify()
            self.window.lift()
            self.window.protocol('WM_DELETE_WINDOW', self._on_close_locked)
            self.window.bind('<Unmap>', self._on_unmap_locked)
        except Exception:
            pass

        # Win32 strip + exempt registration
        self._win32_strip_admin()

        # Periodic re-apply (DWM can restore styles silently)
        self._schedule_topmost_reapply()

    def _win32_strip_admin(self):
        """Strip all title-bar Win32 styles from admin panel HWND."""
        try:
            import ctypes
            hwnd = self.window.winfo_id()
            if not hwnd:
                return
            GWL_STYLE      = -16
            WS_CAPTION     = 0x00C00000
            WS_THICKFRAME  = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU     = 0x00080000
            STRIP = WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
            user32 = ctypes.windll.user32
            style  = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style & ~STRIP)
            # FRAMECHANGED + keep position/size
            SWP = 0x0002 | 0x0001 | 0x0004 | 0x0020  # NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP)
            # Exempt this HWND from global window enforcement loop
            self.sec.window_manager.add_exempt_hwnd(hwnd)
        except Exception:
            pass

    def _win32_restore_admin(self):
        """Restore default title-bar styles on admin panel HWND after lockdown."""
        try:
            import ctypes
            hwnd = self.window.winfo_id()
            if not hwnd:
                return
            GWL_STYLE      = -16
            # Standard dialog-style window: caption + thick frame + sysmenu
            WS_CAPTION     = 0x00C00000
            WS_THICKFRAME  = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU     = 0x00080000
            RESTORE = WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
            user32 = ctypes.windll.user32
            style  = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style | RESTORE)
            SWP = 0x0002 | 0x0001 | 0x0004 | 0x0020
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP)
        except Exception:
            pass

    def _schedule_topmost_reapply(self):
        """Re-apply Win32 strip every 2 s while exam mode is active."""
        def _reapply():
            if not self.window.winfo_exists():
                return
            if not self.sec.is_exam_mode:
                return
            self._win32_strip_admin()
            try:
                self.window.attributes('-topmost', True)
                self.window.lift()
            except Exception:
                pass
            self.window.after(2000, _reapply)
        try:
            self.window.after(2000, _reapply)
        except Exception:
            pass

    def _release_topmost(self):
        """Restore normal window behaviour after lockdown ends."""
        try:
            self.window.attributes('-topmost', False)
            self.window.protocol('WM_DELETE_WINDOW', self._on_close)
            self.window.unbind('<Unmap>')
        except Exception:
            pass
        # Restore Win32 title bar so admin can move/resize the panel again
        self._win32_restore_admin()

    def _on_close_locked(self):
        """Replaces WM_DELETE_WINDOW during lockdown."""
        import tkinter.messagebox as mb
        mb.showwarning(
            '🔒 Access Denied',
            'The admin panel cannot be closed during lockdown.\n\n'
            'End the exam session first.',
            parent=self.window
        )
        try:
            self.window.attributes('-topmost', True)
            self.window.deiconify()
            self.window.lift()
        except Exception:
            pass

    def _on_unmap_locked(self, event=None):
        """Fires when window is minimized/hidden during lockdown — restore immediately."""
        try:
            if not self.sec.is_exam_mode:
                return
            # Restore in the same event loop frame — no delay gap
            self.window.after(0, self.window.deiconify)
            self.window.after(0, self.window.lift)
            self.window.after(0, lambda: self.window.attributes('-topmost', True))
            # Repeat every 200 ms for 1 s to fight aggressive window managers
            for delay in (200, 400, 600, 800, 1000):
                self.window.after(
                    delay,
                    lambda: (
                        self.window.deiconify(),
                        self.window.lift(),
                        self.window.attributes('-topmost', True),
                    ) if self.window.winfo_exists() and self.sec.is_exam_mode else None
                )
        except Exception:
            pass

    # ── Status Refresh ───────────────────────────────────────────
    def _refresh_status(self):
        info = self.sec.get_system_info()
        self.update_breach_counter()
        if self.sec.is_exam_mode:
            self._mode_label.config(text='LOCKDOWN: ACTIVE', fg=C['danger'])
            self._mode_dot.config(fg=C['danger'])
            if hasattr(self, '_mode_sub'):
                self._mode_sub.config(text='All security modules are active and enforced', fg=C['danger'])
            self._status_dot.config(fg=C['danger'])
            self._status_badge.config(text='LOCKED', fg=C['danger'])
        else:
            self._mode_label.config(text='LOCKDOWN: INACTIVE', fg=C['success'])
            self._mode_dot.config(fg=C['success'])
            if hasattr(self, '_mode_sub'):
                self._mode_sub.config(text='All security modules are standby', fg=C['text_dim'])
            self._status_dot.config(fg=C['text_dim'])
            self._status_badge.config(text='STANDBY', fg=C['text_dim'])

        # CPU/RAM bars
        if hasattr(self, '_cpu_bar') and isinstance(self._cpu_bar, dict) and 'bar' in self._cpu_bar:
            self._update_bar(self._cpu_bar, info.get('cpu_percent', 0))
            self._update_bar(self._ram_bar, info.get('memory_percent', 0))
        if hasattr(self, '_procs_card'):
            self._procs_card['label'].config(
                text=str(info.get('active_processes', '–')))
        if hasattr(self, '_mode_card'):
            is_active = info.get('exam_mode', False)
            self._mode_card['label'].config(
                text='ACTIVE' if is_active else 'STANDBY',
                fg=C['danger'] if is_active else C['success'])

        # Indicators
        map_ = [('keyboard', 'hooks_active'), ('mouse', 'mouse_blocking'),
                ('network', 'internet_blocked'), ('windows', 'window_protection'),
                ('usb', 'usb_blocking'), ('clipboard', 'clipboard_blocked'),
                ('vm_rdp', 'vm_rdp_clear'), ('multi_monitor', 'single_monitor'),
                ('webcam', 'webcam_active'), ('audio', 'audio_active')]
        for key, syskey in map_:
            ind = self._ind.get(key)
            if not ind:
                continue
            active = info.get(syskey, False)
            if active:
                ind['dot'].config(text='● ON',  fg=C['success'])
                ind['lbl'].config(fg=C['text'])
                ind['chip'].config(highlightbackground=C['success_muted'])
            else:
                ind['dot'].config(text='● OFF', fg=C['text_muted'])
                ind['lbl'].config(fg=C['text_dim'])
                ind['chip'].config(highlightbackground=C['border'])


        # Threat
        if self.sec.is_exam_mode:
            sel = self.sec.selective_blocking
            threats = sum([
                sel.get('keyboard') and not info.get('hooks_active'),
                sel.get('mouse') and not info.get('mouse_blocking'),
                sel.get('internet') and not info.get('internet_blocked'),
                sel.get('windows') and not info.get('window_protection'),
                sel.get('clipboard') and not info.get('clipboard_blocked'),
                sel.get('vm_rdp') and not info.get('vm_rdp_clear'),
                sel.get('multi_monitor') and not info.get('single_monitor'),
                sel.get('webcam') and not info.get('webcam_active'),
                sel.get('audio') and not info.get('audio_active'),
            ])
            if threats == 0:
                self._threat_label.config(
                    text='🛡️  All selected modules operational',
                    fg=C['success'])
            else:
                self._threat_label.config(
                    text=f'⚠️  {threats} module(s) not responding',
                    fg=C['warning'])
        else:
            self._threat_label.config(text='🛡️  Monitoring inactive',
                                       fg=C['text_dim'])

    # ── Toast Notification ───────────────────────────────────────
    def _toast(self, msg, color=None):
        color = color or C['primary']
        try:
            t = tk.Toplevel(self.window)
            t.overrideredirect(True)
            t.attributes('-topmost', True)
            t.configure(bg=C['surface'])
            sw = t.winfo_screenwidth()
            sh = t.winfo_screenheight()
            w, h = 360, 56
            # Start off-screen below, then slide up
            start_y = sh
            end_y = sh - h - 60
            t.geometry(f'{w}x{h}+{sw - w - 20}+{start_y}')

            # Left color stripe
            stripe = tk.Frame(t, bg=color, width=5)
            stripe.pack(side=tk.LEFT, fill=tk.Y)
            inner = tk.Frame(t, bg=C['surface'], padx=12, pady=4)
            inner.pack(fill=tk.BOTH, expand=True)
            tk.Label(inner, text=msg, font=('Segoe UI', 11, 'bold'),
                     bg=C['surface'], fg=C['text'], anchor=tk.W,
                     justify=tk.LEFT).pack(fill=tk.BOTH, expand=True)
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            tk.Label(inner, text=ts, font=('Consolas', 8),
                     bg=C['surface'], fg=C['text_dim'], anchor=tk.W).pack(anchor=tk.W)

            # Slide up animation
            def _slide(y):
                if not t.winfo_exists():
                    return
                if y > end_y:
                    t.geometry(f'{w}x{h}+{sw - w - 20}+{y}')
                    t.after(12, _slide, y - 8)
            _slide(start_y)

            t.after(3500, lambda: t.destroy() if t.winfo_exists() else None)
        except Exception:
            pass

    # ── Key Detection ─────────────────────────────────────────────
    def _detect_key(self):
        if self._detecting_key:
            return
        dlg = tk.Toplevel(self.window)
        dlg.title('🎯 Detect Key Combo')
        dlg.geometry('420x200')
        dlg.configure(bg=C['bg'])
        dlg.transient(self.window)
        dlg.grab_set()
        self._center_dialog(dlg, 420, 200)
        tk.Label(dlg, text='Press the key combination to block',
                 font=('Segoe UI', 12, 'bold'), bg=C['bg'],
                 fg=C['text']).pack(pady=18)
        status = tk.Label(dlg, text='Waiting…', font=('Segoe UI', 10),
                          bg=C['bg'], fg=C['primary'])
        status.pack()
        detected = tk.Label(dlg, text='', font=('Consolas', 11, 'bold'),
                            bg=C['bg'], fg=C['success'])
        detected.pack()
        bf = tk.Frame(dlg, bg=C['bg'])
        bf.pack(pady=12)
        add_btn = styled_btn(bf, 'Add', lambda: self._finish_key_detect(dlg),
                             bg=C['success'], fg='#0a0a0a')
        add_btn.pack(side=tk.LEFT, padx=4)
        add_btn.config(state=tk.DISABLED)
        styled_btn(bf, 'Cancel', lambda: self._cancel_key_detect(dlg),
                   bg=C['danger'], fg='white').pack(side=tk.LEFT, padx=4)
        self._detecting_key = True
        self._detected_key = None

        def on_press(evt):
            if not self._detecting_key:
                return
            if evt.name in ('ctrl', 'alt', 'shift', 'cmd',
                            'left shift', 'right shift',
                            'left ctrl', 'right ctrl',
                            'left alt', 'right alt'):
                return
            mods = []
            if keyboard.is_pressed('ctrl'):  mods.append('ctrl')
            if keyboard.is_pressed('alt'):   mods.append('alt')
            if keyboard.is_pressed('shift'): mods.append('shift')
            combo = '+'.join(mods + [evt.name])
            self._detected_key = combo
            detected.config(text=f'Detected: {combo}')
            status.config(text='Got it!')
            add_btn.config(state=tk.NORMAL)

        self._key_hook = keyboard.on_press(on_press)

    def _finish_key_detect(self, dlg):
        if self._detected_key and \
                self._detected_key not in self.sec.blocked_keys:
            self.sec.add_blocked_key(self._detected_key)
            self._load_keys_list()
        self._cancel_key_detect(dlg)

    def _cancel_key_detect(self, dlg):
        self._detecting_key = False
        if self._key_hook:
            try:
                keyboard.unhook(self._key_hook)
            except Exception:
                pass
            self._key_hook = None
        dlg.destroy()

    # ── Mouse Detection ───────────────────────────────────────────
    def _detect_mouse(self):
        if self._detecting_mouse:
            return
        dlg = tk.Toplevel(self.window)
        dlg.title('🎯 Detect Mouse Button')
        dlg.geometry('420x200')
        dlg.configure(bg=C['bg'])
        dlg.transient(self.window)
        dlg.grab_set()
        self._center_dialog(dlg, 420, 200)
        tk.Label(dlg, text='Click the mouse button to block',
                 font=('Segoe UI', 12, 'bold'), bg=C['bg'],
                 fg=C['text']).pack(pady=18)
        status = tk.Label(dlg, text='Waiting…', font=('Segoe UI', 10),
                          bg=C['bg'], fg=C['primary'])
        status.pack()
        detected = tk.Label(dlg, text='', font=('Consolas', 11, 'bold'),
                            bg=C['bg'], fg=C['success'])
        detected.pack()
        bf = tk.Frame(dlg, bg=C['bg'])
        bf.pack(pady=12)
        add_btn = styled_btn(bf, 'Add',
                             lambda: self._finish_mouse_detect(dlg),
                             bg=C['success'], fg='#0a0a0a')
        add_btn.pack(side=tk.LEFT, padx=4)
        add_btn.config(state=tk.DISABLED)
        styled_btn(bf, 'Cancel',
                   lambda: self._cancel_mouse_detect(dlg),
                   bg=C['danger'], fg='white').pack(side=tk.LEFT, padx=4)
        self._detecting_mouse = True
        self._detected_mouse = None

        def on_click(x, y, button, pressed):
            if not self._detecting_mouse or not pressed:
                return False
            name = str(button).replace('Button.', '')
            self._detected_mouse = name
            detected.config(text=f'Detected: {name}')
            status.config(text='Got it!')
            add_btn.config(state=tk.NORMAL)
            return False

        self._mouse_listener = pynput_mouse.Listener(on_click=on_click)
        self._mouse_listener.start()

    def _finish_mouse_detect(self, dlg):
        if self._detected_mouse and \
                self._detected_mouse not in \
                self.sec.mouse_manager.blocked_buttons:
            self.sec.mouse_manager.add_blocked_button(self._detected_mouse)
            self._load_mouse_list()
        self._cancel_mouse_detect(dlg)

    def _cancel_mouse_detect(self, dlg):
        self._detecting_mouse = False
        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None
        dlg.destroy()

    # ── Mouse flag helpers ────────────────────────────────────────
    def _sync_mouse_flags(self):
        """Update status label whenever a checkbox changes."""
        active = [k for k, v in self._mouse_flags.items() if v.get()]
        if active:
            labels = {
                'left': 'Left', 'right': 'Right', 'middle': 'Middle',
                'double': 'DblClick', 'side': 'Side', 'scroll': 'Scroll'
            }
            txt = 'Will block: ' + ', '.join(labels.get(k, k) for k in active)
            self._mouse_status.config(text=txt, fg=C['warning'])
        else:
            self._mouse_status.config(
                text='No mouse restrictions selected.',
                fg=C['text_dim'])

    def _apply_mouse_flags(self):
        """Push checkbox state into MouseManager and restart if active."""
        flags = {k: v.get() for k, v in self._mouse_flags.items()}
        # Restart blocking with new flags if currently active
        was_active = self.sec.mouse_manager.is_active
        if was_active:
            self.sec.mouse_manager.stop_blocking()
        self.sec.mouse_manager.apply_flags(flags)
        if was_active:
            self.sec.mouse_manager.start_blocking()
        active = [k for k, v in flags.items() if v]
        if active:
            self._toast(
                f"🖱  Mouse rules applied: {', '.join(active)}",
                C['primary'])
        else:
            self._toast("🖱  All mouse restrictions cleared", C['text_dim'])
        self._sync_mouse_flags()

    def _pull_mouse_flags_from_manager(self):
        """Read current flags from manager into checkboxes."""
        try:
            flags = self.sec.mouse_manager.get_flags()
            for k, v in flags.items():
                if k in self._mouse_flags:
                    self._mouse_flags[k].set(v)
            self._sync_mouse_flags()
        except Exception:
            pass

    # ── List management ───────────────────────────────────────────
    def _load_keys_list(self):
        self._keys_lb.delete(0, tk.END)
        for k in self.sec.blocked_keys:
            self._keys_lb.insert(tk.END, k)

    def _add_key_manual(self):
        combo = simpledialog.askstring(
            'Add Key', "Key combo (e.g. 'ctrl+c'):",
            parent=self.window)
        if combo:
            self.sec.add_blocked_key(combo.strip())
            self._load_keys_list()

    def _remove_key(self):
        sel = self._keys_lb.curselection()
        if sel:
            self.sec.remove_blocked_key(self._keys_lb.get(sel[0]))
            self._load_keys_list()

    def _reset_keys(self):
        self.sec.blocked_keys = Config.BLOCKED_KEYS.copy()
        self._load_keys_list()

    def _load_mouse_list(self):
        """No-op now — mouse settings uses checkboxes, not a listbox."""
        pass

    def _add_mouse_manual(self):
        pass

    def _remove_mouse(self):
        pass

    def _load_website_list(self):
        self._web_lb.delete(0, tk.END)
        for w in Config.BLOCKED_WEBSITES:
            self._web_lb.insert(tk.END, w)

    def _add_website(self):
        site = simpledialog.askstring(
            'Add Site', "Website (e.g. example.com):",
            parent=self.window)
        if site and site.strip() not in Config.BLOCKED_WEBSITES:
            Config.BLOCKED_WEBSITES.append(site.strip())
            self._load_website_list()

    def _remove_website(self):
        sel = self._web_lb.curselection()
        if sel:
            site = self._web_lb.get(sel[0])
            if site in Config.BLOCKED_WEBSITES:
                Config.BLOCKED_WEBSITES.remove(site)
            self._load_website_list()

    # ── Settings persistence ──────────────────────────────────────
    def _save_settings(self):
        try:
            # Capture old values BEFORE saving — used for audit trail
            old_interval = self.db.get_setting('screenshot_interval',
                                               str(Config.SCREENSHOT_INTERVAL_SEC))
            old_allowed  = self.db.get_setting('allowed_websites', '[]')
            old_bulk = {
                'blocked_keys':          self.db.get_setting('blocked_keys', ''),
                'blocked_mouse_buttons': self.db.get_setting('blocked_mouse_buttons', ''),
                'blocked_websites':      self.db.get_setting('blocked_websites', ''),
                'auto_start_exam':       self.db.get_setting('auto_start_exam', ''),
                'block_internet':        self.db.get_setting('block_internet', ''),
                'window_protection':     self.db.get_setting('window_protection', ''),
                'process_monitoring':    self.db.get_setting('process_monitoring', ''),
            }

            # Screenshot interval
            interval = self._ss_interval_var.get() if hasattr(self, '_ss_interval_var') else 60
            interval = max(10, min(300, interval))
            Config.SCREENSHOT_INTERVAL_SEC = interval
            self.db.save_setting('screenshot_interval', str(interval))

            # Allowed websites whitelist
            allowed = list(self._allow_lb.get(0, tk.END)) if hasattr(self, '_allow_lb') else []
            Config.ALLOWED_WEBSITES = allowed
            self.db.save_setting('allowed_websites', json.dumps(allowed))

            new_bulk = {
                'blocked_keys':          json.dumps(self.sec.blocked_keys),
                'blocked_mouse_buttons': json.dumps(self.sec.mouse_manager.blocked_buttons),
                'blocked_websites':      json.dumps(Config.BLOCKED_WEBSITES),
                'auto_start_exam':       str(self._autostart_var.get()),
                'block_internet':        str(self._net_var.get()),
                'window_protection':     str(self._winprot_var.get()),
                'process_monitoring':    str(self._procmon_var.get()),
            }
            self.db.save_settings_bulk(new_bulk)

            # Audit trail: log every value that actually changed
            if old_interval != str(interval):
                self.db.log_settings_change(
                    'screenshot_interval', old_interval, str(interval),
                    user=self.admin_user)
            if old_allowed != json.dumps(allowed):
                self.db.log_settings_change(
                    'allowed_websites', old_allowed, json.dumps(allowed),
                    user=self.admin_user)
            for key in new_bulk:
                if old_bulk.get(key, '') != new_bulk[key]:
                    self.db.log_settings_change(
                        key, old_bulk.get(key, ''), new_bulk[key],
                        user=self.admin_user)

            self._toast("💾 Settings saved", C['success'])
        except Exception as e:
            messagebox.showerror('Error', f'Save failed: {e}',
                                  parent=self.window)

    # ── Allowed-Sites whitelist helpers ───────────────────────────
    def _load_allowed_list(self):
        """Populate the allowed-sites listbox from DB + Config."""
        raw = self.db.get_setting('allowed_websites', '[]')
        try:
            sites = json.loads(raw)
        except Exception:
            sites = []
        Config.ALLOWED_WEBSITES = sites
        self._allow_lb.delete(0, tk.END)
        for s in sites:
            self._allow_lb.insert(tk.END, s)

    def _add_allowed_site(self):
        site = simpledialog.askstring(
            'Allow Site', 'Website to whitelist (e.g. myexam.edu):',
            parent=self.window)
        if site and site.strip():
            s = site.strip().lower()
            if s not in self._allow_lb.get(0, tk.END):
                self._allow_lb.insert(tk.END, s)

    def _remove_allowed_site(self):
        sel = self._allow_lb.curselection()
        if sel:
            self._allow_lb.delete(sel[0])

    # ── Session History panel helpers ─────────────────────────────
    def _refresh_session_history(self):
        try:
            stats = self.db.get_session_stats()
            self._hist_sessions['label'].config(text=str(stats.get('sessions', 0)))
            self._hist_breaches['label'].config(text=str(stats.get('total_blocked', 0)))
            self._hist_last['label'].config(text=str(stats.get('last_session', 'N/A')))
            self._hist_lastb['label'].config(text=str(stats.get('last_breaches', 0)))
        except Exception:
            pass

    # ── Profile Duplicate / Export / Import ───────────────────────
    def _duplicate_profile(self):
        sel = self._prof_tree.selection()
        if not sel:
            self._toast("Select a profile first", C['warning'])
            return
        name = sel[0]
        data = self.profile_manager.load_profile(name)
        if data:
            new_name = f"{name} (copy)"
            self.profile_manager.save_profile(new_name, data.copy())
            self._refresh_profiles()
            self._toast(f"📋 Duplicated as '{new_name}'", C['success'])

    def _export_profile(self):
        sel = self._prof_tree.selection()
        if not sel:
            self._toast("Select a profile to export", C['warning'])
            return
        name = sel[0]
        data = self.profile_manager.load_profile(name)
        if not data:
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.json',
            initialfile=f"{name.replace(' ', '_')}.json",
            filetypes=[('JSON', '*.json'), ('All', '*.*')],
            parent=self.window)
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                self._toast(f"💾 Exported to {path}", C['success'])
            except Exception as e:
                messagebox.showerror('Export Error', str(e), parent=self.window)

    def _import_profile(self):
        path = filedialog.askopenfilename(
            filetypes=[('JSON', '*.json'), ('All', '*.*')],
            parent=self.window)
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            name = data.get('name', 'Imported Profile')
            self.profile_manager.save_profile(name, data)
            self._refresh_profiles()
            self._toast(f"📥 Imported '{name}'", C['success'])
        except Exception as e:
            messagebox.showerror('Import Error', str(e), parent=self.window)

    # ── Password change ───────────────────────────────────────────

    def _change_password(self):
        dlg = tk.Toplevel(self.window)
        dlg.title('🔑 Change Admin Password')
        dlg.geometry('420x420')
        dlg.configure(bg=C['bg'])
        dlg.transient(self.window)
        dlg.grab_set()
        self._center_dialog(dlg, 420, 420)
        tk.Label(dlg, text='Change Password',
                 font=('Segoe UI', 14, 'bold'), bg=C['bg'],
                 fg=C['primary']).pack(pady=(18, 4))
        # Static policy hint line
        policy = Config.PASSWORD_POLICY
        hint = (
            f"Min {policy['min_length']} chars | "
            "Upper + Lower + Digit + Special required"
        )
        tk.Label(dlg, text=hint, font=('Segoe UI', 8),
                 bg=C['bg'], fg=C['text_dim']).pack(pady=(0, 6))

        fields = {}
        for lbl_text in ['Current Password', 'New Password',
                          'Confirm New Password']:
            f = tk.Frame(dlg, bg=C['bg'])
            f.pack(fill=tk.X, padx=32, pady=3)
            tk.Label(f, text=lbl_text, font=('Segoe UI', 10),
                     bg=C['bg'], fg=C['text']).pack(anchor=tk.W)
            var = tk.StringVar()
            dark_entry(f, var, show='*').pack(fill=tk.X, ipady=6)
            fields[lbl_text] = var

        # ── E4: Live password strength meter ──────────────────────────────
        _STRENGTH_LABELS = ['Weak', 'Fair', 'Good', 'Strong']
        _STRENGTH_COLORS = ['#ff4757', '#ffa502', '#eccc68', '#2ed573']

        strength_frame = tk.Frame(dlg, bg=C['bg'])
        strength_frame.pack(fill=tk.X, padx=32, pady=(4, 0))
        strength_lbl = tk.Label(strength_frame, text='Strength: —',
                                 font=('Segoe UI', 8, 'bold'),
                                 bg=C['bg'], fg=C['text_dim'])
        strength_lbl.pack(anchor=tk.W, pady=(0, 3))

        bar_frame = tk.Frame(strength_frame, bg=C['bg'])
        bar_frame.pack(fill=tk.X)
        segments = []
        for _ in range(4):
            seg = tk.Frame(bar_frame, bg=C['surface'], height=6, width=60)
            seg.pack(side=tk.LEFT, padx=2)
            seg.pack_propagate(False)
            segments.append(seg)

        change_btn_ref = [None]   # filled below after button creation

        def _update_strength(*_):
            pw = fields['New Password'].get()
            score = 0
            p = Config.PASSWORD_POLICY
            if len(pw) >= p.get('min_length', 10):
                score += 1
            if re.search(r'[A-Z]', pw) and re.search(r'[a-z]', pw):
                score += 1
            if re.search(r'\d', pw):
                score += 1
            if re.search(r'[!@#$%^&*()\-_=+\[\]{}|;:,.<>?/]', pw):
                score += 1

            for i, seg in enumerate(segments):
                seg.config(bg=_STRENGTH_COLORS[score - 1] if i < score and score > 0
                           else C['surface'])

            if score == 0:
                strength_lbl.config(text='Strength: —', fg=C['text_dim'])
            else:
                lbl = _STRENGTH_LABELS[score - 1]
                strength_lbl.config(text=f'Strength: {lbl}',
                                     fg=_STRENGTH_COLORS[score - 1])

            # Enable/disable submit based on full policy pass
            if change_btn_ref[0]:
                state = 'normal' if score == 4 else 'disabled'
                change_btn_ref[0].config(state=state)

        fields['New Password'].trace_add('write', _update_strength)

        def do_change():
            cur     = fields['Current Password'].get()
            new     = fields['New Password'].get()
            confirm = fields['Confirm New Password'].get()
            if not all([cur, new, confirm]):
                messagebox.showerror('Error', 'Fill all fields', parent=dlg)
                return
            if new != confirm:
                messagebox.showerror('Error', "Passwords don't match",
                                      parent=dlg)
                return
            # change_password enforces strength policy and returns (ok, reason)
            ok, reason = self.db.change_password(self.admin_user, cur, new)
            if ok:
                self._toast("✅ Password changed", C['success'])
                self.log.info('PASSWORD_CHANGED',
                              f'Admin password updated for user={self.admin_user}')
                dlg.destroy()
            else:
                messagebox.showerror('Error', reason or 'Password change failed.',
                                      parent=dlg)

        btn = styled_btn(dlg, 'Change Password', do_change,
                         bg=C['primary'], fg='#0a0a0a')
        btn.config(state='disabled')   # disabled until strength == 4
        btn.pack(pady=14)
        change_btn_ref[0] = btn

    # ── Log integrity verification ────────────────────────────────
    def _verify_log_integrity(self):
        """Run AuditManager chain verification and show the result in a modal."""
        result = self.audit.verify_log_chain()
        if result.ok:
            icon  = "✅"
            color = C['success']
            title = "Log Integrity: OK"
            detail_lines = (
                f"Rows verified : {result.total_rows}\n"
                + (f"Pre-chain rows (skipped): {result.missing_hashes}\n"
                   if result.missing_hashes else "")
                + f"\n{result.message}"
            )
        else:
            icon  = "❌"
            color = C['danger']
            title = "Log Integrity: TAMPER DETECTED"
            detail_lines = (
                f"First broken row ID : {result.first_broken_id}\n"
                f"Index in chain      : {result.broken_at_index}\n"
                f"Total rows checked  : {result.total_rows}\n\n"
                f"{result.message}"
            )
            self.log.warning(
                "LOG_INTEGRITY_FAIL",
                f"Chain broken at row id={result.first_broken_id}"
            )

        dlg = tk.Toplevel(self.window)
        dlg.title(title)
        dlg.geometry('480x270')
        dlg.configure(bg=C['bg'])
        dlg.transient(self.window)
        dlg.grab_set()
        self._center_dialog(dlg, 480, 270)
        tk.Label(dlg,
                 text=f"{icon}  Log Chain Verification",
                 font=('Segoe UI', 14, 'bold'), bg=C['bg'],
                 fg=color).pack(pady=(18, 10))
        tk.Label(dlg, text=detail_lines,
                 font=('Consolas', 9), bg=C['bg'], fg=C['text'],
                 justify=tk.LEFT, wraplength=440).pack(padx=24)
        styled_btn(dlg, 'Close', dlg.destroy,
                   bg=C['surface']).pack(pady=14)

    # ── Quick module toggles ──────────────────────────────────────
    def _show_mouse_ctrl(self):
        flags = self.sec.mouse_manager.get_flags()
        active_list = [k for k, v in flags.items() if v]
        info = ('Blocking: ' + ', '.join(active_list)) if active_list \
               else 'No restrictions configured — set them in Settings tab'
        self._quick_toggle(
            'Mouse Blocking',
            self.sec.mouse_manager.is_active,
            lambda: self.sec.mouse_manager.start_blocking(),
            self.sec.mouse_manager.stop_blocking,
            info)

    def _show_network_ctrl(self):
        self._quick_toggle(
            'Internet Blocking',
            self.sec.network_manager.is_blocked,
            self.sec.network_manager.start_blocking,
            self.sec.network_manager.stop_blocking)

    def _show_window_ctrl(self):
        self._quick_toggle(
            'Window Protection',
            self.sec.window_manager.is_active,
            self.sec.window_manager.start_window_protection,
            self.sec.window_manager.stop_window_protection)

    def _show_usb_ctrl(self):
        self._quick_toggle(
            'USB Storage Lock',
            self.sec.usb_manager.is_active,
            self.sec.usb_manager.start_blocking,
            self.sec.usb_manager.stop_blocking)

    def _quick_toggle(self, name, is_active, start_fn, stop_fn,
                       extra_info=''):
        dlg = tk.Toplevel(self.window)
        dlg.title(f'⚡ {name}')
        dlg.geometry('440x260')
        dlg.configure(bg=C['bg'])
        dlg.transient(self.window)
        self._center_dialog(dlg, 440, 260)
        tk.Label(dlg, text=name, font=('Segoe UI', 16, 'bold'),
                 bg=C['bg'], fg=C['primary']).pack(pady=(22, 8))
        sc = C['success'] if is_active else C['danger']
        st = '🟢  ACTIVE' if is_active else '🔴  INACTIVE'
        tk.Label(dlg, text=st, font=('Segoe UI', 13),
                 bg=C['bg'], fg=sc).pack()
        if extra_info:
            tk.Label(dlg, text=extra_info, font=('Consolas', 9),
                     bg=C['bg'], fg=C['text_dim']).pack(pady=4)

        def toggle():
            if is_active:
                stop_fn()
            else:
                start_fn()
            self._refresh_status()
            dlg.destroy()

        bc = C['danger'] if is_active else C['success']
        bt = '🛑  Deactivate' if is_active else '🚀  Activate'
        styled_btn(dlg, bt, toggle, bg=bc,
                   fg='white' if is_active else '#0a0a0a').pack(pady=16)

    # ── Logs ─────────────────────────────────────────────────────
    def _refresh_logs(self):
        filt = self._filter_var.get()
        search_query = self._log_search_var.get().lower()
        logs = self.db.get_activity_logs(200, filter_type=filt)
        self._logs_text.delete('1.0', tk.END)
        for action, details, ts, blocked in logs:
            if search_query and (search_query not in action.lower() and
                                 search_query not in (details or '').lower()):
                continue
            tag = 'blocked' if blocked else 'ok'
            icon = '🚫' if blocked else '✅'
            self._logs_text.insert(tk.END, f"[{ts}] ", 'ts')
            self._logs_text.insert(tk.END,
                f"{icon} {action}: {details or '—'}\n", tag)
        self._logs_text.see(tk.END)
        stats = self.db.get_log_stats()
        self._stats_label.config(
            text=f"Total: {stats['total']}  ·  "
                 f"Blocked: {stats['blocked']}  ·  "
                 f"Allowed: {stats['allowed']}")

    def _clear_logs(self):
        if messagebox.askyesno('Confirm',
                'Delete all logs? Cannot be undone.', parent=self.window):
            self.db.clear_all_logs()
            self._logs_text.delete('1.0', tk.END)
            self._stats_label.config(
                text='Total: 0  ·  Blocked: 0  ·  Allowed: 0')
            self._toast("🗑 Logs cleared", C['warning'])

    def _export_logs(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.txt', parent=self.window,
            filetypes=[('Text', '*.txt'), ('CSV', '*.csv'),
                       ('All', '*.*')])
        if not path:
            return
        try:
            logs = self.db.get_activity_logs(5000)
            if path.endswith('.csv'):
                with open(path, 'w', encoding='utf-8', newline='') as f:
                    f.write('Timestamp,Action,Details,Status\n')
                    for a, d, t, b in logs:
                        s = 'BLOCKED' if b else 'ALLOWED'
                        f.write(f'"{t}","{a}","{d or ""}","{s}"\n')
            else:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write("EXAM SHIELD — SECURITY LOG EXPORT\n")
                    f.write("=" * 50 + "\n")
                    f.write(f"Date: "
                             f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
                    f.write(f"Entries: {len(logs)}\n")
                    f.write("=" * 50 + "\n\n")
                    for a, d, t, b in logs:
                        s = 'BLOCKED' if b else 'ALLOWED'
                        f.write(f"[{t}] {s}: {a}\n  {d or '—'}\n\n")
            self._toast(f"💾 Exported: {path[-40:]}", C['info'])
        except Exception as e:
            messagebox.showerror('Error', f'Export failed: {e}',
                                  parent=self.window)

    # ── Auto-refresh ─────────────────────────────────────────────
    def _start_auto_refresh(self):
        def loop():
            while True:
                try:
                    if not self.window.winfo_exists():
                        break
                    self.window.after(0, self._refresh_status)
                    self.window.after(0, self._update_activity)
                    time.sleep(2)
                except Exception as exc:
                    try:
                        self.log.error("AUTO_REFRESH", f"Loop error: {exc}", db=False)
                    except Exception:
                        pass
                    break
        threading.Thread(target=loop, daemon=True).start()

    def _update_activity(self):
        try:
            for item in self._tree.get_children():
                self._tree.delete(item)
            for i, (action, details, ts, blocked) in \
                    enumerate(self.db.get_activity_logs(30)):
                status = '🚫 BLOCKED' if blocked else '✅ OK'
                if blocked or any(x in action for x in
                                  ('SUSPICIOUS', 'TERMINATED')):
                    sev = '🔴 HIGH'
                    tag = 'high'
                elif any(x in action for x in ('BLOCKED', 'SECURITY')):
                    sev = '🟡 MED'
                    tag = 'med'
                else:
                    sev = '🟢 LOW'
                    tag = 'low'
                try:
                    dt = datetime.datetime.fromisoformat(
                        ts.replace('Z', '+00:00'))
                    time_str = dt.strftime('%H:%M:%S')
                except Exception:
                    time_str = ts
                bg_tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                self._tree.insert('', 0,
                    values=(time_str, sev, action,
                             details or '—', status),
                    tags=(tag, bg_tag))
        except Exception:
            pass

    # ── Helpers ───────────────────────────────────────────────────
    def _center(self):
        self.window.update_idletasks()
        w, h = 1100, 720
        x = (self.window.winfo_screenwidth() - w) // 2
        y = (self.window.winfo_screenheight() - h) // 2
        self.window.geometry(f'{w}x{h}+{x}+{y}')
        self.window.protocol('WM_DELETE_WINDOW', self._on_close)

    def _center_dialog(self, dlg, w, h):
        dlg.update_idletasks()
        x = (dlg.winfo_screenwidth() - w) // 2
        y = (dlg.winfo_screenheight() - h) // 2
        dlg.geometry(f'{w}x{h}+{x}+{y}')

    def _on_close(self):
        """Normal (non-lockdown) close: offer to minimise to tray."""
        if self.sec.is_exam_mode:
            self._on_close_locked()
            return
        if messagebox.askyesno('Confirm', 'Minimise to system tray?',
                                parent=self.window):
            self.window.withdraw()

    def show(self):
        self.window.attributes("-alpha", 0.0)
        self.window.deiconify()
        self.window.lift()
        self._refresh_status()
        self._load_keys_list()
        self._load_website_list()
        self._pull_mouse_flags_from_manager()
        
        # Fade in animation
        def fade(alpha):
            if not self.window.winfo_exists(): return
            if alpha < 1.0:
                alpha += 0.08
                self.window.attributes("-alpha", min(alpha, 1.0))
                self.window.after(16, lambda: fade(alpha))
        fade(0.0)
