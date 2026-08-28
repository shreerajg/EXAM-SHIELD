"""
ExamShield v1.0 — Exam Timer Overlay
Floating always-on-top countdown window shown during lockdown.
Auto-triggers end-of-exam callback when time reaches zero.
"""
import tkinter as tk
import math
from src.config import Config

C = Config.COLORS

WIN_W  = 290
WIN_H  = 150
RING_X = 75   # centre-x of the arc ring area


class ExamTimer:
    """
    A compact, draggable, always-on-top countdown overlay.

    Usage:
        timer = ExamTimer(root, duration_minutes=90,
                          on_expire=callback, on_stop=stop_cb)
        timer.start()
        # ... later:
        timer.stop()
    """

    def __init__(self, parent, duration_minutes: int,
                 on_expire=None, on_stop=None):
        self._parent         = parent
        self._total_seconds  = duration_minutes * 60
        self._remaining      = self._total_seconds
        self._running        = False
        self._on_expire      = on_expire
        self._on_stop        = on_stop
        self._pulse_phase    = 0.0
        self._drag_x = self._drag_y = 0
        self._win    = None

    # ── Window construction ──────────────────────────────────────
    def _build_window(self):
        w = tk.Toplevel(self._parent)
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        w.attributes('-alpha', 0.94)
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
        r_x1, r_y1 = WIN_H * 1.25, WIN_H - 12
        self._canvas.create_oval(r_x0, r_y0, r_x1, r_y1,
                                  outline=C['border'], width=6, fill='')
        # Outer glow ring
        self._ring_glow = self._canvas.create_oval(
            r_x0 - 4, r_y0 - 4, r_x1 + 4, r_y1 + 4,
            outline=C['primary_glow'], width=4, fill=''
        )
        # Middle glow ring
        self._ring_mid = self._canvas.create_oval(
            r_x0, r_y0, r_x1, r_y1,
            outline=C['primary_muted'], width=2, fill=''
        )
        # Progress arc
        self._arc = self._canvas.create_arc(
            r_x0, r_y0, r_x1, r_y1,
            start=90, extent=360,
            outline=C['success'], width=6,
            style=tk.ARC
        )

        # Shield icon in centre of ring
        cx = (r_x0 + r_x1) // 2
        cy = (r_y0 + r_y1) // 2
        self._shield_txt = self._canvas.create_text(
            cx, cy - 8,
            text="🛡", font=('Segoe UI', 18),
            fill=C['primary']
        )

        # ── Right side — text area
        tx = RING_X + 20

        # Header label
        self._canvas.create_text(
            tx, 20, anchor=tk.W,
            text="⏱  EXAM TIMER",
            font=('Segoe UI', 8, 'bold'),
            fill=C['primary']
        )

        # Large time readout
        self._time_txt = self._canvas.create_text(
            tx, 60, anchor=tk.W,
            text="00:00:00",
            font=('Consolas', 26, 'bold'),
            fill=C['text']
        )

        # Progress % label
        self._pct_txt = self._canvas.create_text(
            tx, 92, anchor=tk.W,
            text="100%",
            font=('Segoe UI', 9),
            fill=C['text_dim']
        )

        # Status text
        self._status_txt = self._canvas.create_text(
            tx, 112, anchor=tk.W,
            text="In progress",
            font=('Segoe UI', 8),
            fill=C['success']
        )

        # Bottom progress bar (full width)
        self._canvas.create_rectangle(0, WIN_H - 6, WIN_W, WIN_H,
                                       fill=C['border'], outline='')
        self._prog_bar = self._canvas.create_rectangle(
            0, WIN_H - 6, WIN_W, WIN_H,
            fill=C['success'], outline=''
        )

        # ── Close button
        stop_btn = tk.Label(w, text=" ✕ ",
                             font=('Segoe UI', 9, 'bold'),
                             bg=C['header'], fg=C['danger'],
                             cursor='hand2')
        stop_btn.place(x=WIN_W - 28, y=4)
        stop_btn.bind('<Button-1>', lambda e: self._user_stop())

        # Drag bindings
        self._canvas.bind('<ButtonPress-1>',  self._on_drag_start)
        self._canvas.bind('<B1-Motion>',      self._on_drag_motion)

    # ── Drag support ─────────────────────────────────────────────
    def _on_drag_start(self, event):
        self._drag_x = event.x_root - self._win.winfo_x()
        self._drag_y = event.y_root - self._win.winfo_y()

    def _on_drag_motion(self, event):
        self._win.geometry(f"+{event.x_root - self._drag_x}"
                           f"+{event.y_root - self._drag_y}")

    # ── Timer control ────────────────────────────────────────────
    def start(self):
        self._build_window()
        self._running  = True
        self._remaining = self._total_seconds
        self._tick()
        self._animate_ring()

    def stop(self):
        self._running = False
        if self._win and self._win.winfo_exists():
            try:
                self._win.destroy()
            except Exception:
                pass
        self._win = None

    def _user_stop(self):
        self.stop()
        if self._on_stop:
            self._on_stop()

    # ── Tick (1 s) ───────────────────────────────────────────────
    def _tick(self):
        if not self._running or not self._win or not self._win.winfo_exists():
            return
        if self._remaining <= 0:
            self._on_time_up()
            return
        self._remaining -= 1
        self._redraw()
        self._win.after(1000, self._tick)

    # ── Animate ring pulse (independent of tick) ─────────────────
    def _animate_ring(self):
        if not self._running or not self._win or not self._win.winfo_exists():
            return
        try:
            self._pulse_phase += 0.07
            fraction = self._remaining / max(self._total_seconds, 1)
            if fraction > 0.33:
                glow_color = C['primary_glow']
            elif fraction > 0.1:
                glow_color = C['warning_muted']
            else:
                glow_color = C['danger_muted']
            w = 3 + int(2 * abs(math.sin(self._pulse_phase)))
            self._canvas.itemconfig(self._ring_glow, outline=glow_color, width=w)
            self._win.after(50, self._animate_ring)
        except Exception:
            pass

    def _redraw(self):
        if not self._win or not self._win.winfo_exists():
            return

        secs = self._remaining
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        time_str = f"{h:02d}:{m:02d}:{s:02d}"

        fraction = secs / max(self._total_seconds, 1)
        pct = int(fraction * 100)

        if fraction > 0.33:
            color, status = C['success'], "In progress"
        elif fraction > 0.1:
            color, status = C['warning'], "⚠  Running low"
        else:
            color, status = C['danger'], "🚨  Almost done!"

        extent = -360 * fraction
        self._canvas.itemconfig(self._arc, extent=extent, outline=color)
        self._canvas.itemconfig(self._time_txt, text=time_str, fill=color)
        self._canvas.itemconfig(self._pct_txt,  text=f"{pct}% remaining", fill=C['text_dim'])
        self._canvas.itemconfig(self._status_txt, text=status, fill=color)
        self._canvas.itemconfig(self._ring_mid, outline=color)
        self._canvas.itemconfig(self._shield_txt, fill=color)

        # Bottom progress bar
        bar_w = int(WIN_W * fraction)
        self._canvas.coords(self._prog_bar, 0, WIN_H - 6, max(bar_w, 0), WIN_H)
        self._canvas.itemconfig(self._prog_bar, fill=color)

    def _on_time_up(self):
        if self._win and self._win.winfo_exists():
            self._canvas.itemconfig(self._time_txt,
                                    text="TIME UP!", fill=C['danger'])
            self._canvas.itemconfig(self._status_txt,
                                    text="Exam ended automatically",
                                    fill=C['warning'])
        if self._win:
            self._win.after(3000, self.stop)
        if self._on_expire:
            self._on_expire()

    # ── Accessors ────────────────────────────────────────────────
    def get_remaining_seconds(self) -> int:
        return max(self._remaining, 0)

    def get_elapsed_seconds(self) -> int:
        return self._total_seconds - self._remaining

    @property
    def is_running(self) -> bool:
        return self._running
