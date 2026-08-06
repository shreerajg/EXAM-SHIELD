"""
ExamShield v1.0 — Exam Timer Overlay
Floating always-on-top countdown window shown during lockdown.
Auto-triggers end-of-exam callback when time reaches zero.
"""
import tkinter as tk
import datetime
import math
from src.config import Config

C = Config.COLORS


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
        self._parent = parent
        self._total_seconds = duration_minutes * 60
        self._remaining = self._total_seconds
        self._running = False
        self._on_expire = on_expire
        self._on_stop = on_stop
        self._pulse_phase = 0.0
        self._drag_x = 0
        self._drag_y = 0
        self._win = None

    # ── Window construction ──────────────────────────────────────
    def _build_window(self):
        w = tk.Toplevel(self._parent)
        w.overrideredirect(True)          # no title bar
        w.attributes('-topmost', True)
        w.attributes('-alpha', 0.92)
        w.configure(bg='#0d0d22')
        w.resizable(False, False)

        # Place bottom-right of screen
        sw = w.winfo_screenwidth()
        sh = w.winfo_screenheight()
        win_w, win_h = 220, 110
        w.geometry(f"{win_w}x{win_h}+{sw - win_w - 20}+{sh - win_h - 80}")

        self._win = w

        # ── Canvas for drawing ───────────────────────────────────
        self._canvas = tk.Canvas(w, width=win_w, height=win_h,
                                  bg='#0d0d22', highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # Border ring (decorative)
        self._ring = self._canvas.create_oval(
            8, 8, win_h - 8, win_h - 8,
            outline=C['primary'], width=2, fill=''
        )
        # Progress arc — drawn over the ring
        self._arc = self._canvas.create_arc(
            10, 10, win_h - 10, win_h - 10,
            start=90, extent=360,
            outline=C['success'], width=3,
            style=tk.ARC
        )

        # Timer text
        self._time_txt = self._canvas.create_text(
            (win_h // 2), win_h // 2,
            text="00:00:00",
            font=('Consolas', 16, 'bold'),
            fill=C['text']
        )

        # Label "EXAM TIME" at top
        self._canvas.create_text(
            win_w // 2 + 20, 16,
            text="⏱  EXAM TIME",
            font=('Segoe UI', 8, 'bold'),
            fill=C['primary']
        )

        # Status text
        self._status_txt = self._canvas.create_text(
            win_w // 2 + 20, win_h - 16,
            text="",
            font=('Segoe UI', 8),
            fill=C['text_dim']
        )

        # Stop button (small × in corner)
        stop_btn = tk.Label(w, text=" × ",
                             font=('Segoe UI', 9, 'bold'),
                             bg='#1a1a3a', fg=C['danger'],
                             cursor='hand2')
        stop_btn.place(x=win_w - 24, y=0)
        stop_btn.bind('<Button-1>', lambda e: self._user_stop())

        # Drag bindings
        self._canvas.bind('<ButtonPress-1>',   self._on_drag_start)
        self._canvas.bind('<B1-Motion>',       self._on_drag_motion)

    # ── Drag support ─────────────────────────────────────────────
    def _on_drag_start(self, event):
        self._drag_x = event.x_root - self._win.winfo_x()
        self._drag_y = event.y_root - self._win.winfo_y()

    def _on_drag_motion(self, event):
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self._win.geometry(f"+{x}+{y}")

    # ── Timer control ────────────────────────────────────────────
    def start(self):
        self._build_window()
        self._running = True
        self._remaining = self._total_seconds
        self._tick()

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

    # ── Tick (called every 1 s) ──────────────────────────────────
    def _tick(self):
        if not self._running or not self._win or not self._win.winfo_exists():
            return
        if self._remaining <= 0:
            self._on_time_up()
            return

        self._remaining -= 1
        self._redraw()
        self._win.after(1000, self._tick)

    def _redraw(self):
        if not self._win or not self._win.winfo_exists():
            return

        secs = self._remaining
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        time_str = f"{h:02d}:{m:02d}:{s:02d}"

        # Colour transitions: green → orange → red
        fraction = secs / max(self._total_seconds, 1)
        if fraction > 0.33:
            color = C['success']
            status = "In progress"
        elif fraction > 0.1:
            color = C['warning']
            status = "⚠ Running low"
        else:
            color = C['danger']
            status = "🚨 Almost done!"

        # Pulse phase for the arc outline glow effect
        self._pulse_phase += 0.15
        # Arc extent proportional to time remaining
        extent = 360 * fraction

        self._canvas.itemconfig(self._arc, extent=-extent, outline=color)
        self._canvas.itemconfig(self._time_txt, text=time_str, fill=color)
        self._canvas.itemconfig(self._status_txt, text=status, fill=color)

    def _on_time_up(self):
        """Called when the countdown reaches zero."""
        if self._win and self._win.winfo_exists():
            self._canvas.itemconfig(self._time_txt,
                                    text="TIME UP", fill=C['danger'])
            self._canvas.itemconfig(self._status_txt,
                                    text="Exam ended automatically",
                                    fill=C['warning'])
        # Delay 3 s then destroy window
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
