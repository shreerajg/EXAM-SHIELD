"""
ExamShield v1.0 — Admin Panel
Sidebar-based dark control centre.
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog, filedialog
import threading, time, json, datetime, hashlib, keyboard
from pynput import mouse as pynput_mouse
from config import Config
from logger import ExamShieldLogger

C = Config.COLORS

# ── Reusable styled widgets ────────────────────────────────────────

def styled_btn(parent, text, cmd, bg=None, fg=None, width=None, pady=8):
    bg = bg or C['surface_alt']
    fg = fg or C['text']
    kw = dict(text=text, command=cmd, bg=bg, fg=fg,
              font=('Segoe UI', 10, 'bold'), relief=tk.FLAT,
              cursor='hand2', pady=pady, bd=0,
              activeforeground='white', activebackground=C['primary_dark'])
    if width:
        kw['width'] = width
    btn = tk.Button(parent, **kw)
    h = _darken(bg)
    btn.bind('<Enter>', lambda e: btn.config(bg=h))
    btn.bind('<Leave>', lambda e: btn.config(bg=bg))
    return btn

def _darken(hex_c):
    try:
        h = hex_c.lstrip('#')
        r,g,b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        return f'#{int(r*.75):02x}{int(g*.75):02x}{int(b*.75):02x}'
    except Exception:
        return hex_c

def dark_entry(parent, var, show=None):
    e = tk.Entry(parent, textvariable=var, show=show or '',
                 font=('Segoe UI', 11), bg=C['input_bg'], fg=C['text'],
                 relief=tk.FLAT, insertbackground=C['primary'],
                 highlightthickness=2, highlightcolor=C['primary'],
                 highlightbackground=C['border'])
    return e

def section_header(parent, text):
    f = tk.Frame(parent, bg=C['bg'])
    f.pack(fill=tk.X, padx=16, pady=(14, 4))
    tk.Label(f, text=text, font=('Segoe UI', 12, 'bold'),
             bg=C['bg'], fg=C['primary']).pack(anchor=tk.W)
    tk.Frame(f, bg=C['border'], height=1).pack(fill=tk.X, pady=(2, 0))


class AdminPanel:
    def __init__(self, db_manager, security_manager, parent_window,
                 admin_user='admin'):
        self.db = db_manager
        self.sec = security_manager
        self.parent = parent_window
        self.admin_user = admin_user
        self.log = ExamShieldLogger(db_manager)
        self.sec.set_admin_panel(self)

        self._detecting_key = False
        self._detecting_mouse = False
        self._key_hook = None
        self._mouse_listener = None
        self._detected_key = None
        self._detected_mouse = None
        self._toast_queue = []

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

    # ── Main UI (Sidebar + Content) ──────────────────────────────
    def _build_ui(self):
        # Top header bar
        hdr = tk.Frame(self.window, bg=C['surface'], height=52)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🛡️  EXAM SHIELD — CONTROL CENTRE",
                 font=('Segoe UI', 14, 'bold'), bg=C['surface'],
                 fg=C['primary']).pack(side=tk.LEFT, padx=18)
        self._status_badge = tk.Label(hdr, text="⬤  STANDBY",
                                       font=('Consolas', 11, 'bold'),
                                       bg=C['surface'], fg=C['text_dim'])
        self._status_badge.pack(side=tk.RIGHT, padx=18)
        tk.Label(hdr, text=f"User: {self.admin_user}",
                 font=('Segoe UI', 9), bg=C['surface'],
                 fg=C['text_dim']).pack(side=tk.RIGHT, padx=4)

        # Separator
        tk.Frame(self.window, bg=C['primary'], height=2).pack(fill=tk.X)

        # Body = sidebar + content
        body = tk.Frame(self.window, bg=C['bg'])
        body.pack(fill=tk.BOTH, expand=True)

        # Sidebar
        sidebar = tk.Frame(body, bg=C['sidebar'], width=180)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # Content area
        self._content = tk.Frame(body, bg=C['bg'])
        self._content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Nav items
        self._nav_frames = {}
        self._active_page = tk.StringVar(value='dashboard')
        nav_items = [
            ('dashboard', '⚡', 'Dashboard'),
            ('monitor',   '📊', 'Live Monitor'),
            ('settings',  '⚙️',  'Settings'),
            ('logs',      '📋', 'Logs'),
        ]
        tk.Label(sidebar, text="NAVIGATION", font=('Segoe UI', 8, 'bold'),
                 bg=C['sidebar'], fg=C['text_dim']).pack(
            anchor=tk.W, padx=14, pady=(20, 6))

        self._nav_btns = {}
        for key, icon, label in nav_items:
            btn_frame = tk.Frame(sidebar, bg=C['sidebar'])
            btn_frame.pack(fill=tk.X, pady=1)
            indicator = tk.Frame(btn_frame, bg=C['sidebar'], width=4)
            indicator.pack(side=tk.LEFT, fill=tk.Y)
            btn = tk.Label(btn_frame, text=f"  {icon}  {label}",
                           font=('Segoe UI', 10), bg=C['sidebar'],
                           fg=C['text_dim'], cursor='hand2',
                           anchor=tk.W, pady=12)
            btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
            btn.bind('<Button-1>', lambda e, k=key: self._nav_to(k))
            btn.bind('<Enter>', lambda e, b=btn, i=indicator:
                     (b.config(bg=C['sidebar_hover'], fg=C['text']),
                      i.config(bg=C['border_bright'])))
            btn_frame.bind('<Enter>', lambda e, b=btn, i=indicator:
                           (b.config(bg=C['sidebar_hover'], fg=C['text']),
                            i.config(bg=C['border_bright'])))
            self._nav_btns[key] = {'btn': btn, 'ind': indicator,
                                    'frame': btn_frame}

        # Build all page frames (hidden by default)
        self._pages = {}
        self._pages['dashboard'] = self._build_dashboard()
        self._pages['monitor']   = self._build_monitor()
        self._pages['settings']  = self._build_settings()
        self._pages['logs']      = self._build_logs()

        # Show initial page
        self._nav_to('dashboard')

    def _nav_to(self, key):
        # Hide all pages
        for pg in self._pages.values():
            pg.pack_forget()
        # Reset all nav items
        for k, d in self._nav_btns.items():
            d['btn'].config(bg=C['sidebar'], fg=C['text_dim'])
            d['ind'].config(bg=C['sidebar'])
            d['frame'].config(bg=C['sidebar'])
        # Show selected
        self._pages[key].pack(fill=tk.BOTH, expand=True)
        self._nav_btns[key]['btn'].config(bg=C['sidebar_hover'],
                                           fg=C['primary'])
        self._nav_btns[key]['ind'].config(bg=C['primary'])
        self._active_page.set(key)

    # ── Page: Dashboard ──────────────────────────────────────────
    def _build_dashboard(self):
        pg = tk.Frame(self._content, bg=C['bg'])

        # System stats row
        section_header(pg, "System Status")
        stats_row = tk.Frame(pg, bg=C['bg'])
        stats_row.pack(fill=tk.X, padx=16, pady=(0, 8))

        self._cpu_bar = self._stat_card(stats_row, "CPU", C['info'])
        self._ram_bar = self._stat_card(stats_row, "RAM", C['accent'])
        self._procs_card = self._stat_card(stats_row, "PROCESSES", C['warning'],
                                            is_bar=False)
        self._mode_card = self._stat_card(stats_row, "MODE", C['success'],
                                           is_bar=False)

        # Lockdown control
        section_header(pg, "Lockdown Control")
        ctrl = tk.Frame(pg, bg=C['card'])
        ctrl.pack(fill=tk.X, padx=16, pady=(0, 8))

        self._mode_label = tk.Label(ctrl, text="🔓  LOCKDOWN: INACTIVE",
                                     font=('Segoe UI', 15, 'bold'),
                                     bg=C['card'], fg=C['success'])
        self._mode_label.pack(anchor=tk.W, padx=20, pady=(14, 4))

        # Module indicators
        ind_row = tk.Frame(ctrl, bg=C['card'])
        ind_row.pack(fill=tk.X, padx=20, pady=(4, 12))
        self._ind = {}
        for key, icon, label in [('keyboard', '⌨', 'Keyboard'),
                                   ('mouse',    '🖱', 'Mouse'),
                                   ('network',  '🌐', 'Network'),
                                   ('windows',  '🪟', 'Windows')]:
            card = tk.Frame(ind_row, bg=C['surface'], padx=12, pady=8)
            card.pack(side=tk.LEFT, padx=(0, 8))
            lbl = tk.Label(card, text=f"⬤  {icon} {label}",
                           font=('Segoe UI', 9), bg=C['surface'],
                           fg=C['text_dim'])
            lbl.pack()
            self._ind[key] = lbl

        # Buttons row
        btn_row = tk.Frame(ctrl, bg=C['card'])
        btn_row.pack(fill=tk.X, padx=20, pady=(0, 16))

        self._start_btn = styled_btn(btn_row, "🔒  START LOCKDOWN",
                                      self._show_lockdown_dialog,
                                      bg=C['success'], fg='#0a0a0a')
        self._start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._stop_btn = styled_btn(btn_row, "🔓  END LOCKDOWN",
                                     self._stop_exam,
                                     bg=C['danger'], fg='white')
        self._stop_btn.pack(side=tk.LEFT, padx=(0, 8))
        self._stop_btn.config(state=tk.DISABLED)

        styled_btn(btn_row, "🚨  EMERGENCY STOP",
                   self._emergency_stop,
                   bg=C['warning'], fg='#0a0a0a').pack(side=tk.LEFT)

        styled_btn(btn_row, "🔄 Refresh",
                   self._refresh_status, bg=C['surface_alt']).pack(side=tk.RIGHT)

        # Threat detection
        section_header(pg, "Threat Detection")
        tf = tk.Frame(pg, bg=C['card'], padx=16, pady=12)
        tf.pack(fill=tk.X, padx=16, pady=(0, 8))
        self._threat_label = tk.Label(tf, text="🛡️  No threats detected",
                                       font=('Segoe UI', 10),
                                       bg=C['card'], fg=C['success'])
        self._threat_label.pack(anchor=tk.W)

        # Quick controls
        section_header(pg, "Quick Module Controls")
        qrow = tk.Frame(pg, bg=C['bg'])
        qrow.pack(fill=tk.X, padx=16, pady=(0, 8))

        for label, cmd in [
            ("🖱  Mouse",          self._show_mouse_ctrl),
            ("🌐  Internet",       self._show_network_ctrl),
            ("🪟  Windows",        self._show_window_ctrl),
            ("🔑  Password",       self._change_password),
        ]:
            styled_btn(qrow, label, cmd, bg=C['surface']).pack(
                side=tk.LEFT, padx=(0, 6), pady=4)

        return pg

    def _stat_card(self, parent, label, color, is_bar=True):
        f = tk.Frame(parent, bg=C['surface_alt'], padx=14, pady=10)
        f.pack(side=tk.LEFT, padx=(0, 8), pady=4)
        tk.Label(f, text=label, font=('Segoe UI', 8, 'bold'),
                 bg=C['surface_alt'], fg=C['text_dim']).pack(anchor=tk.W)
        if is_bar:
            val_lbl = tk.Label(f, text="0%", font=('Segoe UI', 16, 'bold'),
                                bg=C['surface_alt'], fg=color)
            val_lbl.pack(anchor=tk.W)
            canvas = tk.Canvas(f, bg=C['bg'], height=6, width=120,
                                highlightthickness=0)
            canvas.pack(anchor=tk.W, pady=(4, 0))
            bar = canvas.create_rectangle(0, 0, 0, 6, fill=color, outline='')
            return {'label': val_lbl, 'canvas': canvas, 'bar': bar,
                    'color': color}
        else:
            val_lbl = tk.Label(f, text="–",
                                font=('Segoe UI', 16, 'bold'),
                                bg=C['surface_alt'], fg=color)
            val_lbl.pack(anchor=tk.W)
            return {'label': val_lbl}

    def _update_bar(self, bar_info, pct):
        w = 120
        bar_info['label'].config(text=f"{pct:.0f}%")
        bar_info['canvas'].coords(bar_info['bar'], 0, 0, int(w * pct / 100), 6)

    # ── Page: Live Monitor ───────────────────────────────────────
    def _build_monitor(self):
        pg = tk.Frame(self._content, bg=C['bg'])
        section_header(pg, "Real-time Security Events")
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

        vsb = ttk.Scrollbar(af, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        return pg

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
        self._build_advanced_settings(inner)
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
            'movement': tk.BooleanVar(value=False),
        }
        options = [
            ('left',     '🖱  Left Click',        'Block primary (left) mouse button'),
            ('right',    '🖱  Right Click',       'Block context menu (right) button'),
            ('middle',   '🖱  Middle Click',      'Block scroll-wheel click'),
            ('double',   '🖱  Double Click',      'Suppress rapid double-clicks (400 ms window)'),
            ('side',     '🖱  Side / X Buttons',  'Block X1, X2, back/forward buttons'),
            ('movement', '🔒  Block All Movement','Lock cursor in place — student cannot move mouse'),
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
        f.pack(fill=tk.X, padx=16, pady=(0, 16))
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
        styled_btn(f, '💾  Save All Settings', self._save_settings,
                   bg=C['primary'], fg='#0a0a0a').pack(pady=(12, 0))

    # ── Page: Logs ───────────────────────────────────────────────
    def _build_logs(self):
        pg = tk.Frame(self._content, bg=C['bg'])
        section_header(pg, "Activity Logs")
        toolbar = tk.Frame(pg, bg=C['bg'])
        toolbar.pack(fill=tk.X, padx=16, pady=4)
        for t, cmd in [('🔄 Refresh', self._refresh_logs),
                       ('🗑 Clear',   self._clear_logs),
                       ('💾 Export',  self._export_logs)]:
            styled_btn(toolbar, t, cmd, bg=C['surface']).pack(
                side=tk.LEFT, padx=(0, 6))
        tk.Label(toolbar, text='Filter:', bg=C['bg'],
                 fg=C['text_dim']).pack(side=tk.LEFT, padx=(16, 4))
        self._filter_var = tk.StringVar(value='All')
        filt = ttk.Combobox(toolbar, textvariable=self._filter_var,
                            values=['All', 'Blocked Only',
                                    'Security Events', 'System Events'],
                            state='readonly', width=16)
        filt.pack(side=tk.LEFT)
        filt.bind('<<ComboboxSelected>>', lambda e: self._refresh_logs())

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
        return pg

    # ── Lockdown Dialog ──────────────────────────────────────────
    def _show_lockdown_dialog(self):
        dlg = tk.Toplevel(self.window)
        dlg.title('🔒 Selective Lockdown')
        dlg.geometry('500x580')
        dlg.configure(bg=C['bg'])
        dlg.transient(self.window)
        dlg.grab_set()
        self._center_dialog(dlg, 500, 580)

        tk.Label(dlg, text='Select Security Modules',
                 font=('Segoe UI', 16, 'bold'), bg=C['bg'],
                 fg=C['primary']).pack(pady=(24, 16))

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
            ('usb',      '💾', 'USB Storage Lock',
             'Block USB mass storage devices'),
        ]
        sel_vars = {}
        for key, icon, title, desc in modules:
            card = tk.Frame(dlg, bg=C['card'])
            card.pack(fill=tk.X, padx=32, pady=5)
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
                                            pady=(0, 10))

        btn_f = tk.Frame(dlg, bg=C['bg'])
        btn_f.pack(fill=tk.X, padx=32, pady=20)

        def start():
            opts = {k: v.get() for k, v in sel_vars.items()}
            if not any(opts.values()):
                messagebox.showwarning('Empty',
                    'Select at least one module!', parent=dlg)
                return
            names = [k.title() for k, v in opts.items() if v]
            if messagebox.askyesno('Confirm',
                    'Start lockdown with:\n\n' +
                    '\n'.join(f'  ✓ {n}' for n in names), parent=dlg):
                dlg.destroy()
                self.sec.start_exam_mode(opts)
                self._start_btn.config(state=tk.DISABLED)
                self._stop_btn.config(state=tk.NORMAL)
                self._refresh_status()
                self._toast("🔒 Lockdown ACTIVE", C['danger'])

        styled_btn(btn_f, '🚀  START LOCKDOWN', start,
                   bg=C['success'], fg='#0a0a0a'
                   ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        styled_btn(btn_f, 'Cancel', dlg.destroy,
                   bg=C['danger'], fg='white'
                   ).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(6, 0))

    # ── Exam controls ────────────────────────────────────────────
    def _stop_exam(self):
        pw = simpledialog.askstring('🔐 Verify', 'Enter admin password:',
                                     show='*', parent=self.window)
        if pw is None:
            return
        h = hashlib.sha256(pw.encode()).hexdigest()
        if self.db.verify_admin(self.admin_user, h):
            self.sec.stop_exam_mode()
            self._start_btn.config(state=tk.NORMAL)
            self._stop_btn.config(state=tk.DISABLED)
            self._refresh_status()
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
            self.sec.stop_exam_mode()
            self._start_btn.config(state=tk.NORMAL)
            self._stop_btn.config(state=tk.DISABLED)
            self._refresh_status()
            self._toast("🚨 Emergency stop executed", C['warning'])
        else:
            messagebox.showerror('Denied', 'Wrong password!',
                                  parent=self.window)

    # ── Status Refresh ───────────────────────────────────────────
    def _refresh_status(self):
        info = self.sec.get_system_info()
        if self.sec.is_exam_mode:
            self._mode_label.config(text='🔒  LOCKDOWN: ACTIVE',
                                     fg=C['danger'])
            self._status_badge.config(text='⬤  LOCKED', fg=C['danger'])
        else:
            self._mode_label.config(text='🔓  LOCKDOWN: INACTIVE',
                                     fg=C['success'])
            self._status_badge.config(text='⬤  STANDBY', fg=C['text_dim'])

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
                ('network', 'internet_blocked'), ('windows', 'window_protection')]
        for key, syskey in map_:
            active = info.get(syskey, False)
            lbl_text = self._ind[key].cget('text').split(' ', 1)[1]
            self._ind[key].config(
                text=f"🟢  {lbl_text}" if active else f"⬤  {lbl_text}",
                fg=C['success'] if active else C['text_dim'])

        # Threat
        if self.sec.is_exam_mode:
            sel = self.sec.selective_blocking
            threats = sum([
                sel.get('keyboard') and not info.get('hooks_active'),
                sel.get('mouse') and not info.get('mouse_blocking'),
                sel.get('internet') and not info.get('internet_blocked'),
                sel.get('windows') and not info.get('window_protection'),
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
            t.configure(bg=color)
            sw = t.winfo_screenwidth()
            sh = t.winfo_screenheight()
            w, h = 320, 48
            t.geometry(f'{w}x{h}+{sw - w - 20}+{sh - h - 60}')
            tk.Label(t, text=msg, font=('Segoe UI', 11, 'bold'),
                     bg=color, fg='#0a0a0a', padx=16).pack(
                expand=True, fill=tk.BOTH)
            t.after(2800, t.destroy)
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
                'double': 'DblClick', 'side': 'Side', 'movement': 'Movement'
            }
            txt = 'Will block: ' + ', '.join(labels[k] for k in active)
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
            self.db.save_settings_bulk({
                'blocked_keys':
                    json.dumps(self.sec.blocked_keys),
                'blocked_mouse_buttons':
                    json.dumps(self.sec.mouse_manager.blocked_buttons),
                'blocked_websites':
                    json.dumps(Config.BLOCKED_WEBSITES),
                'auto_start_exam': str(self._autostart_var.get()),
                'block_internet':  str(self._net_var.get()),
                'window_protection': str(self._winprot_var.get()),
                'process_monitoring': str(self._procmon_var.get()),
            })
            self._toast("💾 Settings saved", C['success'])
        except Exception as e:
            messagebox.showerror('Error', f'Save failed: {e}',
                                  parent=self.window)

    # ── Password change ───────────────────────────────────────────
    def _change_password(self):
        dlg = tk.Toplevel(self.window)
        dlg.title('🔑 Change Admin Password')
        dlg.geometry('420x300')
        dlg.configure(bg=C['bg'])
        dlg.transient(self.window)
        dlg.grab_set()
        self._center_dialog(dlg, 420, 300)
        tk.Label(dlg, text='Change Password',
                 font=('Segoe UI', 14, 'bold'), bg=C['bg'],
                 fg=C['primary']).pack(pady=(18, 14))
        fields = {}
        for lbl_text in ['Current Password', 'New Password',
                          'Confirm New Password']:
            f = tk.Frame(dlg, bg=C['bg'])
            f.pack(fill=tk.X, padx=32, pady=4)
            tk.Label(f, text=lbl_text, font=('Segoe UI', 10),
                     bg=C['bg'], fg=C['text']).pack(anchor=tk.W)
            var = tk.StringVar()
            dark_entry(f, var, show='*').pack(fill=tk.X, ipady=6)
            fields[lbl_text] = var

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
            if len(new) < 4:
                messagebox.showerror('Error', 'Min 4 characters', parent=dlg)
                return
            if self.db.change_password(
                    self.admin_user,
                    hashlib.sha256(cur.encode()).hexdigest(),
                    hashlib.sha256(new.encode()).hexdigest()):
                self._toast("✅ Password changed", C['success'])
                self.log.info('PASSWORD_CHANGED', 'Admin password updated')
                dlg.destroy()
            else:
                messagebox.showerror('Error', 'Current password incorrect',
                                      parent=dlg)

        styled_btn(dlg, 'Change Password', do_change,
                   bg=C['primary'], fg='#0a0a0a').pack(pady=14)

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
        logs = self.db.get_activity_logs(200, filter_type=filt)
        self._logs_text.delete('1.0', tk.END)
        for action, details, ts, blocked in logs:
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
                except Exception:
                    break
        threading.Thread(target=loop, daemon=True).start()

    def _update_activity(self):
        try:
            for item in self._tree.get_children():
                self._tree.delete(item)
            for action, details, ts, blocked in \
                    self.db.get_activity_logs(30):
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
                self._tree.insert('', 0,
                    values=(time_str, sev, action,
                             details or '—', status),
                    tags=(tag,))
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
        if messagebox.askyesno('Confirm', 'Minimise to system tray?',
                                parent=self.window):
            self.window.withdraw()

    def show(self):
        self.window.deiconify()
        self.window.lift()
        self._refresh_status()
        self._load_keys_list()
        self._load_website_list()
        self._pull_mouse_flags_from_manager()
