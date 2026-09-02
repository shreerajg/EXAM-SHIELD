"""
ExamShield v1.4.0 — Main Entry Point
Animated dark-mode login → Admin Panel lifecycle.
"""
import tkinter as tk
from tkinter import messagebox, simpledialog
import sys
import os
import atexit
import ctypes
import time
import threading
from src.config import Config
from src.managers.database_manager import DatabaseManager
from src.managers.totp_manager import TOTPManager
from src.ui.admin_panel import AdminPanel
from src.managers.security_manager import SecurityManager
from src.ui.system_tray import SystemTray
from src.logger import ExamShieldLogger
from src.qr_auth import QRAuth
from src.toml_config import apply_toml_to_config

# ── Single-instance mutex ─────────────────────────────────────────────────────
_MUTEX_NAME = "Global\\ExamShield_SingleInstance_Mutex"
_mutex_handle = None

def _acquire_single_instance_mutex():
    """Return True if this is the only running instance."""
    global _mutex_handle
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    last_err = ctypes.windll.kernel32.GetLastError()
    return last_err != 183  # ERROR_ALREADY_EXISTS


class ExamShield:
    def __init__(self):
        if not self._is_admin():
            self._request_admin()
            return

        self.db = DatabaseManager()
        
        active_theme = self.db.get_setting('active_theme', 'cyan')
        if active_theme in Config.THEMES:
            Config.ACTIVE_THEME = active_theme
            Config.COLORS.update(Config.THEMES[active_theme])

        self.root = tk.Tk()
        self.root.withdraw()   # hide until we fade in
        self.root.title(f"Exam Shield v{Config.VERSION}")
        self.root.geometry("500x700")
        self.root.resizable(False, False)
        self.root.overrideredirect(False)

        C = Config.COLORS
        self.root.configure(bg=C['bg'])
        self.log = ExamShieldLogger(self.db)
        self.qr_auth = QRAuth(self.db, self)
        self.security = None
        self.tray = None
        self._logged_in_user = None
        self._login_attempts = 0        # consecutive failed attempts (in-memory)
        self._locked_out = False        # True while countdown timer running

        self._build_login_ui()
        self._center()

        # Fade in
        self.root.attributes('-alpha', 0.0)
        self.root.deiconify()
        self._fade_in(0)

        self.log.info("APP_START", "ExamShield launched with admin privileges")

    # ═══════════════════════════════════════════════════════════════
    # ADMIN ELEVATION
    # ═══════════════════════════════════════════════════════════════
    @staticmethod
    def _is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False

    def _request_admin(self):
        try:
            result = messagebox.askyesno(
                "Administrator Required",
                "Exam Shield needs administrator privileges for:\n\n"
                "• Network adapter control\n"
                "• Process monitoring & termination\n"
                "• System-level keyboard/mouse hooks\n"
                "• Firewall rule management\n\n"
                "Restart with admin privileges?",
            )
            if result:
                script = os.path.abspath(__file__) if not getattr(sys, 'frozen', False) else sys.executable
                exe = sys.executable if not getattr(sys, 'frozen', False) else script
                args = f'"{script}"' if not getattr(sys, 'frozen', False) else ""
                ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
                sys.exit(0)
        except Exception as e:
            messagebox.showerror("Error", f"Elevation failed: {e}")
            sys.exit(1)

    # ═══════════════════════════════════════════════════════════════
    # FADE-IN ANIMATION
    # ═══════════════════════════════════════════════════════════════
    def _fade_in(self, step):
        steps = Config.ANIM_FADE_STEPS
        if step <= steps:
            alpha = step / steps
            try:
                self.root.attributes('-alpha', alpha)
                self.root.after(Config.ANIM_STEP_MS, self._fade_in, step + 1)
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════════
    # LOGIN UI
    # ═══════════════════════════════════════════════════════════════
    def _build_login_ui(self):
        C = Config.COLORS
        import random, math

        # ── Animated Header Canvas (richer gradient + scanlines)
        HDR_H = 230
        self._hdr_canvas = tk.Canvas(
            self.root, bg=C['bg'], height=HDR_H,
            highlightthickness=0
        )
        self._hdr_canvas.pack(fill=tk.X)

        # Deep space gradient background
        for i in range(HDR_H):
            t = i / HDR_H
            r = int(7  + t * 18)
            g = int(7  + t * 10)
            b = int(26 + t * 38)
            self._hdr_canvas.create_rectangle(
                0, i, 500, i + 1,
                fill=f'#{r:02x}{g:02x}{b:02x}', outline=''
            )

        # Subtle scanline overlay (every 3rd row, very faint)
        for i in range(0, HDR_H, 3):
            self._hdr_canvas.create_rectangle(
                0, i, 500, i + 1, fill='#00000018', outline=''
            )

        # ── Floating particles (3 colour groups, more varied)
        random.seed(77)
        self._particles = []
        colour_groups = [
            [C['primary'], C['primary_dark'], '#00d4ff88'],
            [C['accent'],  '#a07af8', '#7f5af055'],
            [C['success'], '#00e67660'],
        ]
        for g_idx, group in enumerate(colour_groups):
            for _ in range(12):
                x = random.randint(10, 490)
                y = random.randint(5, HDR_H - 5)
                r = random.choice([1, 1, 2, 2, 3])
                col = random.choice(group)
                dot = self._hdr_canvas.create_oval(
                    x - r, y - r, x + r, y + r, fill=col, outline=''
                )
                speed = 0.15 + g_idx * 0.1
                self._particles.append({
                    'id': dot, 'x': x, 'y': y,
                    'dx': random.uniform(-speed, speed),
                    'dy': random.uniform(-speed * 0.5, speed * 0.5),
                    'r': r, 'h': HDR_H,
                })
        self._animate_particles()

        # ── Shield: triple glow rings
        cx, cy = 250, 105
        self._shield_ring3 = self._hdr_canvas.create_oval(
            cx - 76, cy - 76, cx + 76, cy + 76,
            fill='', outline=C['primary_glow2'], width=1
        )
        self._shield_ring2 = self._hdr_canvas.create_oval(
            cx - 62, cy - 62, cx + 62, cy + 62,
            fill='', outline=C['primary_muted'], width=1
        )
        self._shield_ring1 = self._hdr_canvas.create_oval(
            cx - 50, cy - 50, cx + 50, cy + 50,
            fill='', outline=C['primary'], width=2
        )

        # Shield polygon (outer)
        shield_pts = [
            cx,      cy - 60,   # top
            cx + 45, cy - 32,   # upper-right
            cx + 45, cy + 18,   # lower-right
            cx,      cy + 62,   # bottom
            cx - 45, cy + 18,   # lower-left
            cx - 45, cy - 32,   # upper-left
        ]
        self._hdr_canvas.create_polygon(
            shield_pts,
            fill=C['primary'], outline=C['primary_dark'], width=2
        )
        # Inner recessed shield
        inner_pts = [
            cx,      cy - 42,
            cx + 30, cy - 22,
            cx + 30, cy + 12,
            cx,      cy + 44,
            cx - 30, cy + 12,
            cx - 30, cy - 22,
        ]
        self._hdr_canvas.create_polygon(
            inner_pts, fill=C['header'], outline='', smooth=False
        )
        # Lock icon inside shield (padlock shape via lines)
        # Shackle
        self._hdr_canvas.create_arc(
            cx - 12, cy - 26, cx + 12, cy - 4,
            start=0, extent=180, style=tk.ARC,
            outline=C['success'], width=3
        )
        # Lock body
        self._hdr_canvas.create_rectangle(
            cx - 14, cy - 10, cx + 14, cy + 18,
            fill=C['success_muted'], outline=C['success'], width=2
        )
        # Keyhole
        self._hdr_canvas.create_oval(
            cx - 4, cy - 2, cx + 4, cy + 6,
            fill=C['header'], outline=''
        )
        self._hdr_canvas.create_rectangle(
            cx - 2, cy + 4, cx + 2, cy + 14,
            fill=C['header'], outline=''
        )

        # App name & tagline
        self._hdr_canvas.create_text(
            250, HDR_H - 50,
            text="EXAM SHIELD",
            font=("Segoe UI", 18, "bold"), fill=C['primary']
        )
        self._hdr_canvas.create_text(
            250, HDR_H - 28,
            text=f"v{Config.VERSION}  ·  Secure Examination Environment",
            font=("Segoe UI", 9), fill=C['text_dim']
        )

        # Animated shield reference for pulse
        self._shield_ring1_ref = self._shield_ring1
        self._shield_ring2_ref = self._shield_ring2
        self._shield_ring3_ref = self._shield_ring3
        self._pulse_phase = 0.0
        self._animate_shield()

        # ── Separator (primary accent line)
        tk.Frame(self.root, bg=C['primary'], height=2).pack(fill=tk.X)

        # ── Login Card (with left-border accent + subtle top highlight)
        outer_card = tk.Frame(self.root, bg=C['primary'], padx=1, pady=0)
        outer_card.pack(fill=tk.X, padx=32, pady=20)

        card = tk.Frame(outer_card, bg=C['card'])
        card.pack(fill=tk.BOTH, expand=True)

        # Card header row
        card_hdr = tk.Frame(card, bg=C['surface'], height=42)
        card_hdr.pack(fill=tk.X)
        card_hdr.pack_propagate(False)
        tk.Label(card_hdr, text="🔐  Admin Authentication",
                 font=("Segoe UI", 11, "bold"),
                 bg=C['surface'], fg=C['primary']).pack(
            side=tk.LEFT, padx=16, pady=10)
        # Right: lock indicator
        self._lock_dot = tk.Label(
            card_hdr, text="⬤  SECURE",
            font=("Consolas", 8, "bold"),
            bg=C['surface'], fg=C['success']
        )
        self._lock_dot.pack(side=tk.RIGHT, padx=16)

        tk.Frame(card, bg=C['border'], height=1).pack(fill=tk.X)

        # Username field
        self._make_field(card, "USERNAME", "admin", show=None)
        self.username_var = self._last_field_var
        self._username_entry = self._last_field_entry

        # Password field
        self._make_field(card, "PASSWORD", "", show="•")
        self.password_var = self._last_field_var
        self._pw_entry = self._last_field_entry

        # ── Input validation: enforce max-length limits ────────────────────────
        # Silently truncate if the user pastes an oversized string.
        _user_max = Config.LOGIN_USERNAME_MAX_LEN   # 64 chars
        _pw_max   = Config.LOGIN_PASSWORD_MAX_LEN   # 256 chars

        def _limit_username(*_):
            v = self.username_var.get()
            if len(v) > _user_max:
                self.username_var.set(v[:_user_max])
        def _limit_password(*_):
            v = self.password_var.get()
            if len(v) > _pw_max:
                self.password_var.set(v[:_pw_max])

        self.username_var.trace_add('write', _limit_username)
        self.password_var.trace_add('write', _limit_password)

        # Strip ASCII control characters from username on focus-out
        import unicodedata
        def _sanitise_username(event=None):
            v = self.username_var.get()
            cleaned = ''.join(
                c for c in v
                if unicodedata.category(c) not in ('Cc', 'Cf', 'Co', 'Cs')
            )
            if cleaned != v:
                self.username_var.set(cleaned)
        self._username_entry.bind('<FocusOut>', _sanitise_username)

        # Attempt badge
        self._attempt_badge = tk.Label(
            card, text="",
            font=("Segoe UI", 9, "bold"),
            bg=C['card'], fg=C['danger']
        )
        self._attempt_badge.pack(pady=(2, 4))

        # Buttons
        btn_row = tk.Frame(card, bg=C['card'])
        btn_row.pack(fill=tk.X, padx=20, pady=(8, 20))

        self._login_btn = self._make_button(
            btn_row, "  🔐   SIGN IN", self._login,
            bg=C['primary'], fg='#040414'
        )
        self._login_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        self._qr_btn = self._make_button(
            btn_row, "  📷  SCAN QR", self._show_qr_dialog,
            bg=C['surface_alt'], fg=C['primary']
        )
        self._qr_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))

        self._exit_btn = self._make_button(
            btn_row, "✕  EXIT", self._exit,
            bg=C['surface_alt'], fg=C['text_dim']
        )
        self._exit_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(6, 0))

        # ── Status strip
        status_strip = tk.Frame(self.root, bg='#0c0c24')
        status_strip.pack(fill=tk.X, padx=32, pady=(0, 8))

        tk.Frame(status_strip, bg=C['border'], height=1).pack(fill=tk.X)
        inner_strip = tk.Frame(status_strip, bg='#0c0c24')
        inner_strip.pack(fill=tk.X, padx=0, pady=6)

        tk.Label(inner_strip, text="⬤",
                 font=("Segoe UI", 8), bg='#0c0c24',
                 fg=C['success']).pack(side=tk.LEFT, padx=(10, 4))
        tk.Label(inner_strip, text="Administrator Privileges Active",
                 font=("Segoe UI", 8, "bold"), bg='#0c0c24',
                 fg=C['text_dim']).pack(side=tk.LEFT)

        # Version chip on right
        ver_lbl = tk.Label(inner_strip,
                           text=f" v{Config.VERSION} ",
                           font=("Consolas", 8),
                           bg=C['primary_bg'], fg=C['primary'],
                           padx=6, pady=2)
        ver_lbl.pack(side=tk.RIGHT, padx=10)

        # ── Footer bar
        footer = tk.Frame(self.root, bg=C['surface'], height=26)
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        footer.pack_propagate(False)
        self._footer_clock = tk.Label(
            footer, text="",
            font=("Consolas", 8), bg=C['surface'], fg=C['text_dim']
        )
        self._footer_clock.pack(side=tk.RIGHT, padx=10)
        tk.Label(footer,
                 text=f"ExamShield v{Config.VERSION} · {Config.BUILD} · © 2025",
                 font=("Consolas", 8), bg=C['surface'], fg=C['text_dim']
                 ).pack(side=tk.LEFT, padx=10)
        self._tick_footer_clock()

        # Key bindings
        self._pw_entry.bind("<Return>", lambda e: self._login())
        self.root.bind("<Escape>", lambda e: self._exit())
        self._pw_entry.focus()

    def _make_field(self, parent, label, default, show=None):
        C = Config.COLORS
        f = tk.Frame(parent, bg=C['card'])
        f.pack(fill=tk.X, padx=20, pady=(8, 4))

        # Label row with accent dot
        lrow = tk.Frame(f, bg=C['card'])
        lrow.pack(fill=tk.X, pady=(0, 3))
        tk.Label(lrow, text="▸", font=("Segoe UI", 8),
                 bg=C['card'], fg=C['primary']).pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(lrow, text=label, font=("Segoe UI", 8, "bold"),
                 bg=C['card'], fg=C['text_dim']).pack(side=tk.LEFT)

        var = tk.StringVar(value=default)
        entry = tk.Entry(
            f, textvariable=var, font=("Segoe UI", 12),
            show=show or '',
            bg=C['input_bg'], fg=C['text'],
            relief=tk.FLAT, insertbackground=C['primary'],
            highlightthickness=2,
            highlightcolor=C['primary'],
            highlightbackground=C['input_border']
        )
        entry.pack(fill=tk.X, ipady=10)
        # Focus glow
        entry.bind('<FocusIn>',  lambda e: entry.config(highlightbackground=C['primary']))
        entry.bind('<FocusOut>', lambda e: entry.config(highlightbackground=C['input_border']))
        self._last_field_var = var
        self._last_field_entry = entry

    def _make_button(self, parent, text, cmd, bg, fg):
        C = Config.COLORS
        btn = tk.Button(
            parent, text=text, command=cmd,
            bg=bg, fg=fg,
            font=("Segoe UI", 11, "bold"),
            relief=tk.FLAT, cursor='hand2',
            pady=11, activebackground=C['primary_dark'],
            activeforeground=C['text_bright'], bd=0
        )
        orig_bg = bg
        hover_bg = self._darken(bg)
        def on_enter(e):
            btn.config(bg=hover_bg)
        def on_leave(e):
            btn.config(bg=orig_bg)
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        return btn

    @staticmethod
    def _darken(hex_color):
        """Return a darkened version of a hex color."""
        try:
            h = hex_color.lstrip('#')
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            r = max(0, int(r * 0.8))
            g = max(0, int(g * 0.8))
            b = max(0, int(b * 0.8))
            return f'#{r:02x}{g:02x}{b:02x}'
        except Exception:
            return hex_color

    def _animate_shield(self):
        """Pulsate the triple glow rings around the shield."""
        try:
            import math
            C = Config.COLORS
            self._pulse_phase += 0.06
            s = math.sin(self._pulse_phase)
            # Outer ring: slow breathe
            w3 = 1 + int(1.5 * abs(math.sin(self._pulse_phase * 0.5)))
            self._hdr_canvas.itemconfig(self._shield_ring3_ref, width=w3)
            # Middle ring: medium breathe, slightly offset
            w2 = 1 + int(2 * abs(math.sin(self._pulse_phase * 0.7 + 0.5)))
            self._hdr_canvas.itemconfig(self._shield_ring2_ref, width=w2)
            # Inner ring: primary glow pulse
            w1 = 2 + int(2 * abs(s))
            self._hdr_canvas.itemconfig(self._shield_ring1_ref, width=w1)
            self.root.after(Config.ANIM_STEP_MS * 2, self._animate_shield)
        except Exception:
            pass

    def _animate_particles(self):
        """Gently drift particles around the header."""
        try:
            for p in self._particles:
                p['x'] += p['dx']
                p['y'] += p['dy']
                h_max = p.get('h', 200)
                if p['x'] < 2 or p['x'] > 498: p['dx'] *= -1
                if p['y'] < 2 or p['y'] > h_max - 2: p['dy'] *= -1
                r = p['r']
                self._hdr_canvas.coords(
                    p['id'],
                    p['x'] - r, p['y'] - r,
                    p['x'] + r, p['y'] + r
                )
            self.root.after(35, self._animate_particles)
        except Exception:
            pass

    def _tick_footer_clock(self):
        """Update the footer clock each second."""
        try:
            import datetime
            now = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
            self._footer_clock.config(text=now)
            self.root.after(1000, self._tick_footer_clock)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    # AUTH
    # ═══════════════════════════════════════════════════════════════
    def _login(self):
        if self._locked_out:
            return

        user = self.username_var.get().strip()
        pw   = self.password_var.get()          # do NOT strip — passwords may have spaces

        if not user or not pw:
            self._shake_window()
            return

        # Disable button for the duration to prevent double-clicks
        self._login_btn.config(state='disabled')

        def _auth_work():
            """
            E3 — Constant-time defence.
            Record wall-clock start time, run all auth logic, then sleep the
            remaining delta up to LOGIN_MIN_DELAY_MS so timing attacks cannot
            distinguish 'bad username' from 'bad password'.
            """
            start_ns = time.monotonic_ns()
            min_ms = getattr(Config, 'LOGIN_MIN_DELAY_MS', 400)

            def _finish(fn):
                """Schedule UI update on Tk main thread after the minimum delay."""
                elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
                remaining_ms = max(0, min_ms - elapsed_ms)
                self.root.after(int(remaining_ms), fn)

            try:
                # ── Check DB-persistent lockout first ──────────────────────
                is_locked, secs_remaining, tier = self.db.get_lockout(user)
                if is_locked:
                    msg = (
                        "🔒  Account permanently locked — contact administrator"
                        if secs_remaining == -1
                        else f"🔒  Account locked — try again in {secs_remaining}s"
                    )
                    def _show_locked(m=msg):
                        self._attempt_badge.config(text=m, fg=Config.COLORS['danger'])
                        self._login_btn.config(state='normal')
                        self._shake_window()
                    _finish(_show_locked)
                    return

                # ── Verify credentials (PBKDF2 handled in DB layer) ────────
                success = self.db.verify_admin(user, pw)

                if success:
                    def _on_success():
                        self._logged_in_user = user
                        self._login_attempts = 0
                        self._attempt_badge.config(text="")
                        self.db.clear_failed_logins(user)
                        self.db.clear_lockout(user)
                        self._login_btn.config(state='normal')

                        # ── TOTP 2FA challenge (if enabled) ───────────────
                        totp_mgr = TOTPManager(self.db)
                        if totp_mgr.is_enabled() and totp_mgr.has_secret(user):
                            self._prompt_totp(user, totp_mgr)
                        else:
                            self._start_session()
                    _finish(_on_success)
                else:
                    self._login_attempts += 1
                    self.db.log_failed_login(user)
                    max_a = Config.LOGIN_MAX_ATTEMPTS
                    remaining = max_a - self._login_attempts
                    do_lockout = self._login_attempts >= max_a

                    def _on_failure(rem=remaining, do_lk=do_lockout):
                        self._shake_window()
                        self.password_var.set("")
                        self._login_btn.config(state='normal')
                        if do_lk:
                            self._start_lockout(user)
                        else:
                            C = Config.COLORS
                            self._attempt_badge.config(
                                text=f"⚠️  Failed attempt "
                                     f"{self._login_attempts}/{max_a}  "
                                     f"({rem} left before lockout)",
                                fg=C['danger']
                            )
                            messagebox.showerror(
                                "Login Failed",
                                "Invalid credentials!\nPlease try again.",
                                parent=self.root
                            )
                    _finish(_on_failure)

            except Exception as e:
                def _on_error(err=e):
                    self._login_btn.config(state='normal')
                    messagebox.showerror("Error", f"Login error: {err}",
                                         parent=self.root)
                _finish(_on_error)

        threading.Thread(target=_auth_work, daemon=True).start()

    # ── QR Code Authentication ──────────────────────────────────────────────
    def _show_qr_dialog(self):
        """Open a modal dialog displaying a QR code for phone-based auth."""
        C = Config.COLORS
        tok = self.qr_auth.get_token()
        qr_img = self.qr_auth.generate_qr_image(tok)

        dlg = tk.Toplevel(self.root)
        dlg.title("Scan to Authenticate")
        dlg.geometry("340x420")
        dlg.resizable(False, False)
        dlg.configure(bg=C['bg'])
        dlg.transient(self.root)
        dlg.grab_set()

        # Center over parent
        px = self.root.winfo_x() + (self.root.winfo_width() - 340) // 2
        py = self.root.winfo_y() + (self.root.winfo_height() - 420) // 2
        dlg.geometry(f"+{px}+{py}")

        tk.Label(dlg, text="📷  Scan this QR with your phone",
                 font=("Segoe UI", 12, "bold"), bg=C['bg'], fg=C['primary']
                 ).pack(pady=(18, 6))

        tk.Label(dlg, text="or visit on a browser:",
                 font=("Segoe UI", 9), bg=C['bg'], fg=C['text_dim']
                 ).pack(pady=(0, 4))

        tk.Label(dlg, text="http://localhost:50999/examshield://auth/XXXX",
                 font=("Consolas", 8), bg=C['bg'], fg=C['text_muted']
                 ).pack(pady=(0, 14))

        qr_lbl = tk.Label(dlg, bg=C['card'], borderwidth=2,
                          relief=tk.SOLID, highlightbackground=C['primary'])
        qr_lbl.pack(padx=16, pady=(0, 10))
        qr_photo = self.qr_auth.qr_to_tk(qr_img)
        qr_lbl.config(image=qr_photo)
        qr_lbl.image = qr_photo  # keep reference

        # Token expiry countdown
        self._qr_timer_label = tk.Label(dlg, text="Valid: 60s",
                                        font=("Consolas", 9, "bold"),
                                        bg=C['bg'], fg=C['warning'])
        self._qr_timer_label.pack(pady=(0, 8))

        tk.Button(dlg, text="✕  Close", command=dlg.destroy,
                  bg=C['surface_alt'], fg=C['text_dim'],
                  font=("Segoe UI", 10, "bold"), relief=tk.FLAT,
                  cursor='hand2', pady=8, bd=0
                  ).pack(pady=(4, 10))

        # Start countdown + refresh QR every 30s
        self._qr_dialog = dlg
        self._qr_dialog_label = qr_lbl
        self._qr_dialog_photo = qr_photo
        self._qr_countdown(60)
        self.root.after(30000, self._refresh_qr_in_dialog)

    def _qr_countdown(self, remaining):
        if remaining > 0 and hasattr(self, '_qr_timer_label'):
            self._qr_timer_label.config(text=f"Valid: {remaining}s")
            self.root.after(1000, self._qr_countdown, remaining - 1)
        else:
            if hasattr(self, '_qr_timer_label'):
                self._qr_timer_label.config(text="Expired", fg=Config.COLORS['danger'])

    def _refresh_qr_in_dialog(self):
        """Generate a fresh QR token and update the dialog image."""
        if not hasattr(self, '_qr_dialog') or not self._qr_dialog.winfo_exists():
            return
        new_img = self.qr_auth.generate_qr_image()
        new_photo = self.qr_auth.qr_to_tk(new_img)
        self._qr_dialog_label.config(image=new_photo)
        self._qr_dialog_label.image = new_photo
        self._qr_dialog_photo = new_photo
        self._qr_countdown(60)

    def _start_lockout(self, username: str):
        """Persist escalating lockout to DB AND run a UI countdown."""
        C = Config.COLORS
        self._locked_out = True
        self._login_btn.config(state=tk.DISABLED)
        self._pw_entry.config(state=tk.DISABLED)

        # Determine next tier
        current_tier = self.db.get_lockout_tier(username)
        next_tier = min(current_tier + 1, len(self.db._LOCKOUT_TIERS) - 1) \
                    if self._login_attempts > Config.LOGIN_MAX_ATTEMPTS \
                    else current_tier
        self.db.set_lockout(username, next_tier)

        duration = self.db._LOCKOUT_TIERS[next_tier]
        tier_label = ["1 min", "5 min", "30 min", "permanent"][min(next_tier, 3)]

        self.log.warning(
            "LOGIN_LOCKOUT",
            f"Account '{username}' locked (Tier {next_tier+1}: {tier_label}) "
            f"after {self._login_attempts} failed attempts"
        )

        if duration == -1:
            # Permanent lockout
            self._attempt_badge.config(
                text="🔒  Account permanently locked — contact administrator",
                fg=C['danger']
            )
            return

        def countdown(remaining):
            if remaining > 0:
                self._attempt_badge.config(
                    text=f"🔒  Too many failed attempts — locked for {remaining}s (Tier {next_tier+1})",
                    fg=C['danger']
                )
                self.root.after(1000, countdown, remaining - 1)
            else:
                self._locked_out = False
                self._login_attempts = 0
                self._login_btn.config(state=tk.NORMAL)
                self._pw_entry.config(state=tk.NORMAL)
                self._attempt_badge.config(text="", fg=C['danger'])
                self._pw_entry.focus()

        countdown(duration)

    def _shake_window(self):
        """Shake the window to indicate error."""
        orig_x = self.root.winfo_x()
        orig_y = self.root.winfo_y()
        offsets = [8, -8, 6, -6, 4, -4, 2, -2, 0]

        def do_shake(idx=0):
            if idx < len(offsets):
                self.root.geometry(f"+{orig_x + offsets[idx]}+{orig_y}")
                self.root.after(30, do_shake, idx + 1)
        do_shake()

    def _prompt_totp(self, username: str, totp_mgr: TOTPManager):
        """Show TOTP 6-digit code entry dialog. Calls _start_session on success."""
        C = Config.COLORS
        dlg = tk.Toplevel(self.root)
        dlg.title("🔐  Two-Factor Authentication")
        dlg.geometry("360x260")
        dlg.configure(bg=C['bg'])
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        # Center
        dlg.update_idletasks()
        x = (dlg.winfo_screenwidth() - 360) // 2
        y = (dlg.winfo_screenheight() - 260) // 2
        dlg.geometry(f"360x260+{x}+{y}")

        # Header
        hdr = tk.Frame(dlg, bg=C['surface'], height=48)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🔐  Two-Factor Verification",
                 font=("Segoe UI", 11, "bold"),
                 bg=C['surface'], fg=C['primary']).pack(side=tk.LEFT, padx=16, pady=12)
        tk.Frame(dlg, bg=C['border'], height=1).pack(fill=tk.X)

        # Description
        tk.Label(dlg,
                 text=f"Open Google Authenticator and enter\nthe 6-digit code for  ExamShield",
                 font=("Segoe UI", 9), bg=C['bg'],
                 fg=C['text_dim'], justify=tk.CENTER).pack(pady=(16, 8))

        # Code entry
        code_var = tk.StringVar()
        code_entry = tk.Entry(
            dlg, textvariable=code_var,
            font=("Consolas", 22, "bold"), width=8,
            justify=tk.CENTER,
            bg=C['input_bg'], fg=C['primary'],
            relief=tk.FLAT, insertbackground=C['primary'],
            highlightthickness=2,
            highlightcolor=C['primary'],
            highlightbackground=C['border']
        )
        code_entry.pack(pady=(0, 8))
        code_entry.focus()

        err_lbl = tk.Label(dlg, text="", font=("Segoe UI", 9, "bold"),
                           bg=C['bg'], fg=C['danger'])
        err_lbl.pack()

        def _verify():
            code = code_var.get().strip().replace(" ", "")
            if len(code) != 6 or not code.isdigit():
                err_lbl.config(text="Enter a 6-digit code")
                return
            if totp_mgr.verify_code(username, code):
                dlg.destroy()
                self._start_session()
            else:
                err_lbl.config(text="❌  Invalid code — try again")
                code_var.set("")
                code_entry.focus()

        code_entry.bind("<Return>", lambda e: _verify())

        btn_row = tk.Frame(dlg, bg=C['bg'])
        btn_row.pack(fill=tk.X, padx=20, pady=12)
        tk.Button(btn_row, text="  ✓  Verify  ", command=_verify,
                  font=("Segoe UI", 10, "bold"),
                  bg=C['primary'], fg='#040414',
                  relief=tk.FLAT, cursor='hand2', pady=8).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  font=("Segoe UI", 10),
                  bg=C['surface_alt'], fg=C['text_dim'],
                  relief=tk.FLAT, cursor='hand2', pady=8).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(6, 0))

    def _start_session(self):

        try:
            self.root.withdraw()
            self.security = SecurityManager(self.db)
            self.log.info("ADMIN_LOGIN", f"Session started for: {self._logged_in_user}")

            panel = AdminPanel(self.db, self.security, self.root,
                               admin_user=self._logged_in_user)
            self.tray = SystemTray(panel, self.security, self.db, self.root,
                                   admin_user=self._logged_in_user)
            threading.Thread(target=self.tray.run, daemon=True).start()

            atexit.register(self._cleanup)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to start: {e}", parent=self.root)
            self.root.deiconify()

    # ═══════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════
    def _cleanup(self):
        try:
            if self.security and self.security.is_exam_mode:
                self.security.stop_exam_mode()
            if self.tray:
                self.tray.stop()
            self.log.info("APP_CLEANUP", "Graceful shutdown complete")
        except Exception as e:
            print(f"Cleanup error: {e}")

    def _exit(self):
        if messagebox.askyesno("Exit",
                                "Close Exam Shield?\n\nAll security features will stop.",
                                parent=self.root):
            try:
                self.log.info("APP_EXIT", "User exit")
                self._cleanup()
            except Exception:
                pass
            self.root.quit()

    def _center(self):
        self.root.update_idletasks()
        w, h = 500, 700
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    # Prevent multiple simultaneous instances
    if not _acquire_single_instance_mutex():
        messagebox.showerror(
            "Already Running",
            "ExamShield is already running.\n"
            "Only one instance is allowed at a time."
        )
        sys.exit(1)
    try:
        app = ExamShield()
        if hasattr(app, 'root'):
            app.run()
    except Exception as e:
        messagebox.showerror("Fatal Error", f"Application crashed:\n{e}")
