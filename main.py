"""
ExamShield v1.0 — Main Entry Point
Animated dark-mode login → Admin Panel lifecycle.
"""
import tkinter as tk
from tkinter import messagebox
import sys
import os
import atexit
import hashlib
import ctypes
import threading
from src.config import Config
from src.managers.database_manager import DatabaseManager
from src.ui.admin_panel import AdminPanel
from src.managers.security_manager import SecurityManager
from src.ui.system_tray import SystemTray
from src.logger import ExamShieldLogger


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
        self.security = None
        self.tray = None
        self._logged_in_user = None
        self._login_attempts = 0        # consecutive failed attempts
        self._locked_out = False        # True while lockout timer running

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

        # ── Animated Header Canvas
        self._hdr_canvas = tk.Canvas(
            self.root, bg=C['surface'], height=200,
            highlightthickness=0
        )
        self._hdr_canvas.pack(fill=tk.X)

        # Gradient-like bands (simulated)
        for i in range(200):
            ratio = i / 200
            r = int(12 + ratio * 14)
            g = int(10 + ratio * 8)
            b = int(36 + ratio * 26)
            color = f'#{r:02x}{g:02x}{b:02x}'
            self._hdr_canvas.create_rectangle(0, i, 500, i+1, fill=color, outline=color)

        # Floating particles (static glowing dots)
        import random
        random.seed(42)
        self._particles = []
        for _ in range(22):
            x = random.randint(10, 490)
            y = random.randint(5, 195)
            r = random.choice([1, 1, 2, 2, 3])
            col = random.choice([C['primary'], C['accent'], C['primary_dark'], '#ffffff33'])
            dot = self._hdr_canvas.create_oval(x-r, y-r, x+r, y+r, fill=col, outline='')
            self._particles.append({'id': dot, 'x': x, 'y': y,
                                    'dx': random.uniform(-0.4, 0.4),
                                    'dy': random.uniform(-0.2, 0.2),
                                    'r': r})
        self._animate_particles()

        # Shield glow aura
        self._shield_aura = self._hdr_canvas.create_oval(
            170, 20, 330, 160, fill='', outline=C['primary'], width=1
        )
        self._shield_aura2 = self._hdr_canvas.create_oval(
            180, 30, 320, 150, fill='', outline=C['primary_dark'], width=1
        )

        # Shield icon (Canvas polygon)
        cx, cy = 250, 90
        pts = [
            cx, cy - 56,          # top
            cx + 42, cy - 30,     # upper-right
            cx + 42, cy + 16,     # lower-right
            cx, cy + 58,          # bottom
            cx - 42, cy + 16,     # lower-left
            cx - 42, cy - 30,     # upper-left
        ]
        self._shield_outer = self._hdr_canvas.create_polygon(
            pts, fill=C['primary'], outline=C['primary_dark'], width=2, smooth=False
        )
        inner_pts = [
            cx, cy - 38,
            cx + 28, cy - 20,
            cx + 28, cy + 10,
            cx, cy + 40,
            cx - 28, cy + 10,
            cx - 28, cy - 20,
        ]
        self._hdr_canvas.create_polygon(
            inner_pts, fill=C['surface'], outline='', smooth=False
        )
        # Checkmark inside shield
        self._hdr_canvas.create_line(
            cx - 14, cy + 2, cx - 2, cy + 14,
            cx + 16, cy - 12,
            fill=C['success'], width=3, joinstyle=tk.ROUND, capstyle=tk.ROUND
        )

        # App name & subtitle
        self._hdr_canvas.create_text(
            250, 157, text="EXAM SHIELD",
            font=("Segoe UI", 17, "bold"), fill=C['primary']
        )
        self._hdr_canvas.create_text(
            250, 177, text=f"v{Config.VERSION}  •  Secure Exam Environment",
            font=("Segoe UI", 9), fill=C['text_dim']
        )

        # Start pulse animation
        self._pulse_phase = 0
        self._animate_shield()

        # ── Separator
        sep = tk.Frame(self.root, bg=C['primary'], height=2)
        sep.pack(fill=tk.X)

        # ── Form Card
        card = tk.Frame(self.root, bg=C['card'])
        card.pack(fill=tk.X, padx=32, pady=24)

        tk.Label(card, text="Admin Login", font=("Segoe UI", 14, "bold"),
                 bg=C['card'], fg=C['text']).pack(pady=(18, 14))

        # Username
        self._make_field(card, "USERNAME", "admin", show=None)
        self.username_var = self._last_field_var

        # Password
        self._make_field(card, "PASSWORD", "", show="•")
        self.password_var = self._last_field_var
        self._pw_entry = self._last_field_entry

        # ── Attempt badge (hidden by default)
        self._attempt_badge = tk.Label(
            card, text="",
            font=("Segoe UI", 9, "bold"),
            bg=C['card'], fg=C['danger']
        )
        self._attempt_badge.pack(pady=(0, 4))

        # Buttons
        btn_row = tk.Frame(card, bg=C['card'])
        btn_row.pack(fill=tk.X, padx=20, pady=(16, 20))

        self._login_btn = self._make_button(
            btn_row, "   🔐  LOGIN", self._login,
            bg=C['success'], fg='#0a0a0a'
        )
        self._login_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        self._exit_btn = self._make_button(
            btn_row, "EXIT", self._exit,
            bg=C['danger'], fg='white'
        )
        self._exit_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(6, 0))

        # ── Info Footer
        info = tk.Frame(self.root, bg=C['bg'])
        info.pack(fill=tk.X, padx=32, pady=(0, 8))

        if not self.db.admin_exists():
            hint = tk.Frame(info, bg='#1a3316')
            hint.pack(fill=tk.X, pady=3)
            tk.Label(hint, text="ℹ️  First run — Default credentials: admin / admin",
                     font=("Segoe UI", 9), bg='#1a3316', fg=C['success'],
                     pady=7).pack()

        admin_row = tk.Frame(info, bg='#131330')
        admin_row.pack(fill=tk.X, pady=3)
        tk.Label(admin_row, text="✅  Administrator Privileges Active",
                 font=("Segoe UI", 9, "bold"), bg='#131330', fg=C['success'],
                 pady=6).pack()

        hotkey_row = tk.Frame(info, bg=C['surface_alt'])
        hotkey_row.pack(fill=tk.X, pady=3)
        tk.Label(hotkey_row,
                 text=f"🔑  Emergency Admin Hotkey:  {Config.ADMIN_ACCESS_KEY.upper()}",
                 font=("Consolas", 9), bg=C['surface_alt'], fg=C['warning'],
                 pady=6).pack()

        # ── Footer
        footer = tk.Frame(self.root, bg=C['surface'], height=28)
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        footer.pack_propagate(False)
        self._footer_clock = tk.Label(
            footer,
            text="",
            font=("Consolas", 8), bg=C['surface'], fg=C['text_dim']
        )
        self._footer_clock.pack(side=tk.RIGHT, padx=10)
        tk.Label(footer,
                 text=f"ExamShield v{Config.VERSION} · {Config.BUILD} · © 2025",
                 font=("Consolas", 8), bg=C['surface'], fg=C['text_dim']
                 ).pack(side=tk.LEFT, padx=10)
        self._tick_footer_clock()

        # ── Key bindings
        self._pw_entry.bind("<Return>", lambda e: self._login())
        self.root.bind("<Escape>", lambda e: self._exit())

        self._pw_entry.focus()

    def _make_field(self, parent, label, default, show=None):
        C = Config.COLORS
        f = tk.Frame(parent, bg=C['card'])
        f.pack(fill=tk.X, padx=20, pady=4)
        tk.Label(f, text=label, font=("Segoe UI", 8, "bold"),
                 bg=C['card'], fg=C['text_dim']).pack(anchor=tk.W, pady=(4, 2))

        var = tk.StringVar(value=default)
        entry = tk.Entry(
            f, textvariable=var, font=("Segoe UI", 12),
            show=show or '',
            bg=C['input_bg'], fg=C['text'],
            relief=tk.FLAT, insertbackground=C['primary'],
            highlightthickness=2,
            highlightcolor=C['primary'],
            highlightbackground=C['border']
        )
        entry.pack(fill=tk.X, ipady=9)
        self._last_field_var = var
        self._last_field_entry = entry

    def _make_button(self, parent, text, cmd, bg, fg):
        C = Config.COLORS
        btn = tk.Button(
            parent, text=text, command=cmd,
            bg=bg, fg=fg,
            font=("Segoe UI", 11, "bold"),
            relief=tk.FLAT, cursor='hand2',
            pady=10, activebackground=C['primary_dark'],
            activeforeground='white', bd=0
        )
        # Hover bindings
        orig_bg = bg
        hover_bg = self._darken(bg)
        btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg))
        btn.bind("<Leave>", lambda e: btn.config(bg=orig_bg))
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
        """Pulsate the shield aura."""
        try:
            import math
            C = Config.COLORS
            self._pulse_phase += 0.08
            alpha_val = 0.35 + 0.35 * math.sin(self._pulse_phase)
            width_val = 1 + int(2 * abs(math.sin(self._pulse_phase)))
            self._hdr_canvas.itemconfig(self._shield_aura, width=width_val)
            # Inner aura glow offset
            glow_r = int(6 * abs(math.sin(self._pulse_phase)))
            self.root.after(Config.ANIM_STEP_MS * 2, self._animate_shield)
        except Exception:
            pass

    def _animate_particles(self):
        """Gently drift particles around the header."""
        try:
            for p in self._particles:
                p['x'] += p['dx']
                p['y'] += p['dy']
                # Bounce off edges
                if p['x'] < 2 or p['x'] > 498:  p['dx'] *= -1
                if p['y'] < 2 or p['y'] > 198:  p['dy'] *= -1
                r = p['r']
                self._hdr_canvas.coords(p['id'],
                    p['x']-r, p['y']-r, p['x']+r, p['y']+r)
            self.root.after(40, self._animate_particles)
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
        pw = self.password_var.get().strip()
        if not user:
            self._shake_window()
            return
        if not pw:
            self._shake_window()
            return
        try:
            h = hashlib.sha256(pw.encode()).hexdigest()
            if self.db.verify_admin(user, h):
                self._logged_in_user = user
                self._login_attempts = 0
                self._attempt_badge.config(text="")
                self.db.clear_failed_logins(user)
                self._start_session()
            else:
                self._login_attempts += 1
                self.db.log_failed_login(user)
                self._shake_window()
                self.password_var.set("")
                max_a = Config.LOGIN_MAX_ATTEMPTS
                remaining = max_a - self._login_attempts
                if self._login_attempts >= max_a:
                    self._start_lockout()
                else:
                    self._attempt_badge.config(
                        text=f"⚠️  Failed attempt {self._login_attempts}/{max_a}  "
                             f"({remaining} left before lockout)"
                    )
                    messagebox.showerror(
                        "Login Failed",
                        "Invalid credentials!\nPlease try again.",
                        parent=self.root
                    )
        except Exception as e:
            messagebox.showerror("Error", f"Login error: {e}", parent=self.root)

    def _start_lockout(self):
        """Lock the login UI for LOGIN_LOCKOUT_SEC seconds."""
        self._locked_out = True
        self._login_btn.config(state=tk.DISABLED)
        self._pw_entry.config(state=tk.DISABLED)
        secs = Config.LOGIN_LOCKOUT_SEC
        self.log.warning("LOGIN_LOCKOUT",
            f"Account locked for {secs}s after {Config.LOGIN_MAX_ATTEMPTS} failed attempts")

        def countdown(remaining):
            if remaining > 0:
                self._attempt_badge.config(
                    text=f"🔒  Too many failed attempts — locked for {remaining}s",
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

        countdown(secs)

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
    try:
        app = ExamShield()
        if hasattr(app, 'root'):
            app.run()
    except Exception as e:
        messagebox.showerror("Fatal Error", f"Application crashed:\n{e}")
