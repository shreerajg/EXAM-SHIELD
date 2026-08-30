"""
ExamShield v1.4.0 — Exam Timer Overlay (Enhanced)

New in v1.4:
  • Pause / Resume  — freeze/unfreeze the countdown
  • Extend Time     — add minutes to the running timer
  • Warning thresholds  — pulsing orange at ≤10 min, flashing red at ≤5 min
  • Overtime mode   — after time-up, counts UP in red showing +MM:SS overage
"""
import tkinter as tk
import math
from src.config import Config

C = Config.COLORS

WIN_W  = 300
WIN_H  = 175
RING_X = 75

# Warning thresholds (seconds)
_WARN_ORANGE = 10 * 60    # ≤ 10 minutes → orange
_WARN_RED    =  5 * 60    # ≤  5 minutes → red flashing


class ExamTimer:
    """
    A compact, draggable, always-on-top countdown overlay.

    Usage:
        timer = ExamTimer(root, duration_minutes=90,
                          on_expire=callback, on_stop=stop_cb)
        timer.start()

    New API:
        timer.pause()           — freeze countdown
        timer.resume()          — unfreeze countdown
        timer.toggle_pause()    — flip pause state
        timer.extend(minutes)   — add minutes to remaining time
        timer.is_paused         — property
        timer.is_overtime       — property
    """

    def __init__(self, parent, duration_minutes: int,
                 on_expire=None, on_stop=None):
        self._parent          = parent
        self._total_seconds   = duration_minutes * 60
        self._remaining       = self._total_seconds
        self._running         = False
        self._paused          = False
        self._overtime        = False          # True once time reaches 0
        self._overtime_secs   = 0             # counts up after expiry
        self._on_expire       = on_expire
        self._on_stop         = on_stop
        self._pulse_phase     = 0.0
        self._flash_state     = False          # for red flashing
        self._drag_x = self._drag_y = 0
        self._win    = None
        self._warned_10 = False
        self._warned_5  = False

    # ── Properties ───────────────────────────────────────────────
    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def is_overtime(self) -> bool:
        return self._overtime

    # ── Window construction ──────────────────────────────────────
    def _build_window(self):
        w = tk.Toplevel(self._parent)
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        w.attributes('-alpha', 0.95)
        w.configure(bg=C['header'])
        w.resizable(False, False)

        sw = w.winfo_screenwidth()
        sh = w.winfo_screenheight()
        w.geometry(f"{WIN_W}x{WIN_H}+{sw - WIN_W - 24}+{sh - WIN_H - 80}")
        self._win = w

        # ── Main canvas
        self._canvas = tk.Canvas(w, width=WIN_W, height=WIN_H,
                                  bg=C['header'], highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # Outer border rectangle
        self._canvas.create_rectangle(1, 1, WIN_W - 2, WIN_H - 2,
                                       outline=C['border_bright'], width=1, fill='')
        # Top accent line
        self._canvas.create_rectangle(0, 0, WIN_W, 2,
                                       fill=C['primary'], outline='')

        # ── Arc ring (background track)
        r_x0, r_y0 = 10, 12
        r_x1, r_y1 = WIN_H * 1.15, WIN_H - 34
        self._canvas.create_oval(r_x0, r_y0, r_x1, r_y1,
                                  outline=C['border'], width=6, fill='')
        self._ring_glow = self._canvas.create_oval(
            r_x0 - 4, r_y0 - 4, r_x1 + 4, r_y1 + 4,
            outline=C['primary_glow'], width=4, fill=''
        )
        self._ring_mid = self._canvas.create_oval(
            r_x0, r_y0, r_x1, r_y1,
            outline=C['primary_muted'], width=2, fill=''
        )
        self._arc = self._canvas.create_arc(
            r_x0, r_y0, r_x1, r_y1,
            start=90, extent=360,
            outline=C['success'], width=6,
            style=tk.ARC
        )

        # Shield / pause icon in ring centre
        cx = (r_x0 + r_x1) // 2
        cy = (r_y0 + r_y1) // 2
        self._shield_txt = self._canvas.create_text(
            cx, cy - 8, text="🛡", font=('Segoe UI', 16), fill=C['primary']
        )

        # ── Right side — text area
        tx = int(r_x1) + 14

        self._canvas.create_text(
            tx, 18, anchor=tk.W,
            text="⏱  EXAM TIMER",
            font=('Segoe UI', 7, 'bold'),
            fill=C['primary']
        )

        self._time_txt = self._canvas.create_text(
            tx, 52, anchor=tk.W,
            text="00:00:00",
            font=('Consolas', 22, 'bold'),
            fill=C['text']
        )
        self._pct_txt = self._canvas.create_text(
            tx, 80, anchor=tk.W,
            text="100%",
            font=('Segoe UI', 8),
            fill=C['text_dim']
        )
        self._status_txt = self._canvas.create_text(
            tx, 96, anchor=tk.W,
            text="In progress",
            font=('Segoe UI', 7),
            fill=C['success']
        )

        # Bottom progress bar
        self._canvas.create_rectangle(0, WIN_H - 6, WIN_W, WIN_H,
                                       fill=C['border'], outline='')
        self._prog_bar = self._canvas.create_rectangle(
            0, WIN_H - 6, WIN_W, WIN_H,
            fill=C['success'], outline=''
        )

        # ── Control button strip (bottom)
        btn_y = WIN_H - 32
        btn_bg = C['surface_alt']

        # Close / stop button (top-right)
        stop_btn = tk.Label(w, text=" ✕ ",
                             font=('Segoe UI', 8, 'bold'),
                             bg=C['header'], fg=C['danger'], cursor='hand2')
        stop_btn.place(x=WIN_W - 28, y=4)
        stop_btn.bind('<Button-1>', lambda e: self._user_stop())

        # Pause / Resume button
        self._pause_lbl = tk.Label(
            w, text="⏸ Pause",
            font=('Segoe UI', 8, 'bold'),
            bg=btn_bg, fg=C['warning'],
            cursor='hand2', padx=6, pady=2, relief=tk.FLAT
        )
        self._pause_lbl.place(x=int(r_x1) + 14, y=btn_y)
        self._pause_lbl.bind('<Button-1>', lambda e: self.toggle_pause())

        # +5 min extend button
        ext_btn = tk.Label(
            w, text="+5 min",
            font=('Segoe UI', 8, 'bold'),
            bg=btn_bg, fg=C['success'],
            cursor='hand2', padx=6, pady=2, relief=tk.FLAT
        )
        ext_btn.place(x=int(r_x1) + 78, y=btn_y)
        ext_btn.bind('<Button-1>', lambda e: self.extend(5))

        # Hover effects
        for lbl, hover_fg in [(self._pause_lbl, C['text_bright']),
                               (ext_btn, C['text_bright'])]:
            lbl.bind('<Enter>',
                     lambda e, l=lbl, h=_lighten(btn_bg): l.config(bg=h))
            lbl.bind('<Leave>',
                     lambda e, l=lbl, bg=btn_bg: l.config(bg=bg))

        # Drag bindings (on canvas only — buttons handle their own clicks)
        self._canvas.bind('<ButtonPress-1>',  self._on_drag_start)
        self._canvas.bind('<B1-Motion>',      self._on_drag_motion)

    # ── Drag support ─────────────────────────────────────────────
    def _on_drag_start(self, event):
        self._drag_x = event.x_root - self._win.winfo_x()
        self._drag_y = event.y_root - self._win.winfo_y()

    def _on_drag_motion(self, event):
        self._win.geometry(f"+{event.x_root - self._drag_x}"
                           f"+{event.y_root - self._drag_y}")

    # ── Timer control ─────────────────────────────────────────────
    def start(self):
        self._build_window()
        self._running   = True
        self._paused    = False
        self._overtime  = False
        self._overtime_secs = 0
        self._warned_10 = False
        self._warned_5  = False
        self._remaining = self._total_seconds
        self._tick()
        self._animate_ring()

    def stop(self):
        self._running = False
        self._paused  = False
        if self._win and self._win.winfo_exists():
            try:
                self._win.destroy()
            except Exception:
                pass
        self._win = None

    def pause(self):
        """Freeze the countdown."""
        if not self._running or self._paused:
            return
        self._paused = True
        self._update_pause_btn()
        self._canvas.itemconfig(self._shield_txt, text="⏸")
        self._canvas.itemconfig(self._status_txt,
                                text="⏸  Paused",
                                fill=C['warning'])

    def resume(self):
        """Resume the countdown after a pause."""
        if not self._running or not self._paused:
            return
        self._paused = False
        self._update_pause_btn()
        self._canvas.itemconfig(self._shield_txt, text="🛡")

    def toggle_pause(self):
        if self._paused:
            self.resume()
        else:
            self.pause()

    def extend(self, minutes: int):
        """Add *minutes* to the remaining time (also adjusts total)."""
        extra = minutes * 60
        self._remaining     += extra
        self._total_seconds += extra
        # Reset "almost done" warnings so they can fire again
        self._warned_5  = False
        self._warned_10 = False
        if self._overtime:
            # Coming back from overtime
            self._overtime = False
            self._overtime_secs = 0

    def _update_pause_btn(self):
        if self._pause_lbl and self._win and self._win.winfo_exists():
            try:
                if self._paused:
                    self._pause_lbl.config(text="▶ Resume", fg=C['success'])
                else:
                    self._pause_lbl.config(text="⏸ Pause", fg=C['warning'])
            except Exception:
                pass

    def _user_stop(self):
        self.stop()
        if self._on_stop:
            self._on_stop()

    # ── Tick (1 s) ───────────────────────────────────────────────
    def _tick(self):
        if not self._running or not self._win or not self._win.winfo_exists():
            return

        if not self._paused:
            if self._overtime:
                self._overtime_secs += 1
            elif self._remaining > 0:
                self._remaining -= 1
                self._check_warnings()
            else:
                self._on_time_up()
                return

        self._redraw()
        self._win.after(1000, self._tick)

    def _check_warnings(self):
        """Fire one-shot toasts at 10-min and 5-min thresholds."""
        secs = self._remaining
        if not self._warned_10 and secs <= _WARN_ORANGE:
            self._warned_10 = True
            self._fire_warning_toast("⚠  10 minutes remaining!", C['warning'])
        if not self._warned_5 and secs <= _WARN_RED:
            self._warned_5  = True
            self._fire_warning_toast("🚨  5 minutes remaining!", C['danger'])

    def _fire_warning_toast(self, msg: str, color: str):
        """Flash the overlay border briefly to grab attention."""
        if not self._win or not self._win.winfo_exists():
            return
        # Flash border color 3 times
        def _flash(count):
            if count <= 0 or not self._win or not self._win.winfo_exists():
                return
            try:
                on = count % 2 == 0
                self._canvas.itemconfig(
                    self._ring_glow,
                    outline=color if on else C['border'],
                    width=6 if on else 2
                )
                self._win.after(200, lambda: _flash(count - 1))
            except Exception:
                pass
        _flash(6)

    # ── Animate ring pulse ────────────────────────────────────────
    def _animate_ring(self):
        if not self._running or not self._win or not self._win.winfo_exists():
            return
        try:
            self._pulse_phase += 0.07
            fraction = self._remaining / max(self._total_seconds, 1)

            if self._overtime:
                glow_color = C['danger_muted']
            elif self._paused:
                glow_color = C['warning_muted']
            elif fraction > 0.33:
                glow_color = C['primary_glow']
            elif fraction > (10 * 60 / max(self._total_seconds, 1)):
                glow_color = C['warning_muted']
            else:
                # Flashing below 5 min
                self._flash_state = not self._flash_state
                glow_color = C['danger_muted'] if self._flash_state else C['danger_glow'] if hasattr(C, 'danger_glow') else '#ff475720'

            w = 3 + int(2 * abs(math.sin(self._pulse_phase)))
            self._canvas.itemconfig(self._ring_glow, outline=glow_color, width=w)
            self._win.after(50, self._animate_ring)
        except Exception:
            pass

    def _redraw(self):
        if not self._win or not self._win.winfo_exists():
            return

        if self._overtime:
            ot = self._overtime_secs
            h = ot // 3600; m = (ot % 3600) // 60; s = ot % 60
            time_str = f"+{h:02d}:{m:02d}:{s:02d}"
            color, status = C['danger'], "🚨  OVERTIME"
            fraction = 0.0
            pct_text = "TIME UP!"
        elif self._paused:
            secs = self._remaining
            h = secs // 3600; m = (secs % 3600) // 60; s = secs % 60
            time_str = f"{h:02d}:{m:02d}:{s:02d}"
            fraction = secs / max(self._total_seconds, 1)
            pct_text = f"{int(fraction * 100)}% remaining"
            color, status = C['warning'], "⏸  Paused"
        else:
            secs = self._remaining
            h = secs // 3600; m = (secs % 3600) // 60; s = secs % 60
            time_str = f"{h:02d}:{m:02d}:{s:02d}"
            fraction = secs / max(self._total_seconds, 1)
            pct_text = f"{int(fraction * 100)}% remaining"

            if fraction > (10 * 60 / max(self._total_seconds, 1)):
                color, status = C['success'], "In progress"
            elif fraction > (5 * 60 / max(self._total_seconds, 1)):
                color, status = C['warning'], "⚠  Running low"
            else:
                color, status = C['danger'], "🚨  Almost done!"

        extent = -360 * fraction if not self._overtime else 0
        self._canvas.itemconfig(self._arc, extent=extent, outline=color)
        self._canvas.itemconfig(self._time_txt, text=time_str, fill=color)
        self._canvas.itemconfig(self._pct_txt,  text=pct_text, fill=C['text_dim'])
        self._canvas.itemconfig(self._status_txt, text=status, fill=color)
        self._canvas.itemconfig(self._ring_mid, outline=color)
        if not self._paused:
            self._canvas.itemconfig(self._shield_txt,
                                    text="⏰" if self._overtime else "🛡",
                                    fill=color)

        # Bottom progress bar
        bar_w = int(WIN_W * fraction)
        self._canvas.coords(self._prog_bar, 0, WIN_H - 6, max(bar_w, 0), WIN_H)
        self._canvas.itemconfig(self._prog_bar, fill=color)

    def _on_time_up(self):
        """Switch to overtime mode instead of just stopping."""
        self._overtime = True
        self._overtime_secs = 0
        if self._win and self._win.winfo_exists():
            self._canvas.itemconfig(self._time_txt,
                                    text="+00:00:00", fill=C['danger'])
            self._canvas.itemconfig(self._status_txt,
                                    text="🚨  OVERTIME",
                                    fill=C['danger'])
        if self._on_expire:
            self._on_expire()
        # Continue ticking in overtime mode
        self._win.after(1000, self._tick)

    # ── Accessors ────────────────────────────────────────────────
    def get_remaining_seconds(self) -> int:
        return max(self._remaining, 0)

    def get_elapsed_seconds(self) -> int:
        return self._total_seconds - self._remaining

    @property
    def is_running(self) -> bool:
        return self._running


def _lighten(hex_c: str, factor: float = 1.3) -> str:
    try:
        h = hex_c.lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (f'#{min(255,int(r*factor)):02x}'
                f'{min(255,int(g*factor)):02x}'
                f'{min(255,int(b*factor)):02x}')
    except Exception:
        return hex_c
