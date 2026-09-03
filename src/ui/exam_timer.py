"""
ExamShield v1.4.0 — Exam Countdown Timer
Countdown widget with pause, extend, and auto-submit when time runs out.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import datetime

from src.config import Config


class ExamTimer:
    """
    Countdown timer widget for the lockdown control centre.
    - Displays remaining time in HH:MM:SS
    - Pause / Resume
    - Extend by 5/10/15 minutes (admin only)
    - Auto-submit callback when timer hits zero
    """

    def __init__(self, parent, on_expiry=None, initial_minutes: int = 0):
        self.parent = parent
        self.on_expiry = on_expiry  # callable() — called when timer expires
        self.initial_minutes = initial_minutes
        self.remaining_sec = initial_minutes * 60 if initial_minutes > 0 else 0
        self.target_sec = self.remaining_sec
        self.is_active = False
        self.is_paused = False
        self._thread = None
        self._stop_event = threading.Event()

        # Build UI
        self._frame = tk.Frame(parent, bg=Config.COLORS['card'], padx=14, pady=12)
        self._frame.pack(fill=tk.X)

        # Header
        self._header_lbl = tk.Label(
            self._frame, text="EXAM TIMER", font=('Segoe UI', 10, 'bold'),
            bg=Config.COLORS['card'], fg=Config.COLORS['primary']
        )
        self._header_lbl.pack(anchor=tk.W, pady=(0, 8))

        # Timer display — big digits
        self._time_lbl = tk.Label(
            self._frame, text="00:00:00", font=('Consolas', 28, 'bold'),
            bg=Config.COLORS['card'], fg=Config.COLORS['danger']
        )
        self._time_lbl.pack(pady=(4, 8))

        # Status indicator
        self._status_dot = tk.Label(
            self._frame, text="●", font=('Segoe UI', 10),
            bg=Config.COLORS['card'], fg=Config.COLORS['text_muted']
        )
        self._status_dot.pack(anchor=tk.W, pady=(0, 4))
        self._status_lbl = tk.Label(
            self._frame, text="Not started", font=('Segoe UI', 9),
            bg=Config.COLORS['card'], fg=Config.COLORS['text_dim']
        )
        self._status_lbl.pack(anchor=tk.W)

        # Separator
        tk.Frame(self._frame, bg=Config.COLORS['border'], height=1).pack(fill=tk.X, pady=(8, 0))

        # Control buttons
        btn_row = tk.Frame(self._frame, bg=Config.COLORS['card'])
        btn_row.pack(fill=tk.X, pady=(4, 0))

        self._start_btn = tk.Button(
            btn_row, text="▶  START", command=self.start,
            bg=Config.COLORS['success'], fg='#030d03',
            font=('Segoe UI', 9, 'bold'), relief=tk.FLAT, cursor='hand2',
            pady=6, padx=14, bd=0
        )
        self._start_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._pause_btn = tk.Button(
            btn_row, text="⏸  PAUSE", command=self.pause,
            bg=Config.COLORS['surface_alt'], fg=Config.COLORS['text_dim'],
            font=('Segoe UI', 9, 'bold'), relief=tk.FLAT, cursor='hand2',
            pady=6, padx=14, bd=0, state=tk.DISABLED
        )
        self._pause_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._resume_btn = tk.Button(
            btn_row, text="▶  RESUME", command=self.resume,
            bg=Config.COLORS['primary'], fg='#040414',
            font=('Segoe UI', 9, 'bold'), relief=tk.FLAT, cursor='hand2',
            pady=6, padx=14, bd=0, state=tk.DISABLED
        )
        self._resume_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._reset_btn = tk.Button(
            btn_row, text="⟳  RESET", command=self.reset,
            bg=Config.COLORS['surface_alt'], fg=Config.COLORS['text_dim'],
            font=('Segoe UI', 9, 'bold'), relief=tk.FLAT, cursor='hand2',
            pady=6, padx=14, bd=0, state=tk.DISABLED
        )
        self._reset_btn.pack(side=tk.LEFT, padx=(0, 6))

        # Extend buttons row
        ext_row = tk.Frame(self._frame, bg=Config.COLORS['card'])
        ext_row.pack(fill=tk.X, pady=(6, 0))

        tk.Label(ext_row, text="EXTEND BY:", font=('Segoe UI', 8, 'bold'),
                 bg=Config.COLORS['card'], fg=Config.COLORS['text_muted']
                 ).pack(side=tk.LEFT, padx=(0, 8))

        for mins in [5, 10, 15]:
            tk.Button(
                ext_row, text=f"+{mins} min", command=lambda m=mins: self.extend(m),
                bg=Config.COLORS['surface_alt'], fg=Config.COLORS['text_dim'],
                font=('Segoe UI', 8, 'bold'), relief=tk.FLAT, cursor='hand2',
                pady=4, padx=10, bd=0, state=tk.DISABLED
            ).pack(side=tk.LEFT, padx=(0, 4))

    # ── Timer control ────────────────────────────────────────────────────────
    def start(self):
        if self.is_active and not self.is_paused:
            return
        if self.remaining_sec <= 0 and self.target_sec <= 0:
            self.remaining_sec = 30 * 60  # default 30 min if not set
            self.target_sec = self.remaining_sec
        self.is_active = True
        self.is_paused = False
        self._stop_event.clear()
        self._update_button_states()
        self._status_lbl.config(text="Running", fg=Config.COLORS['success'])
        self._status_dot.config(fg=Config.COLORS['success'])
        self._time_lbl.config(fg=Config.COLORS['danger'])
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self):
        if not self.is_active or self.is_paused:
            return
        self.is_paused = True
        self._stop_event.set()
        self._update_button_states()
        self._status_lbl.config(text="Paused", fg=Config.COLORS['warning'])
        self._status_dot.config(fg=Config.COLORS['warning'])

    def resume(self):
        if not self.is_active or not self.is_paused:
            return
        self.is_paused = False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._update_button_states()
        self._status_lbl.config(text="Running", fg=Config.COLORS['success'])
        self._status_dot.config(fg=Config.COLORS['success'])

    def reset(self):
        self.stop()
        self.remaining_sec = self.target_sec
        self.is_active = False
        self.is_paused = False
        self._update_button_states()
        self._status_lbl.config(text="Reset", fg=Config.COLORS['text_dim'])
        self._status_dot.config(fg=Config.COLORS['text_muted'])
        self._set_time_display()

    def stop(self):
        """Stop timer and clean up thread."""
        self._stop_event.set()
        self.is_active = False
        self.is_paused = False
        self._update_button_states()
        self._status_lbl.config(text="Stopped", fg=Config.COLORS['danger'])
        self._status_dot.config(fg=Config.COLORS['danger'])

    def extend(self, minutes: int):
        """Add minutes to remaining time (admin action)."""
        if self.remaining_sec <= 0:
            return
        self.remaining_sec += minutes * 60
        self.target_sec = max(self.target_sec, self.remaining_sec)
        self._set_time_display()

    # ── Internal run loop ────────────────────────────────────────────────────
    def _run(self):
        while self.is_active and not self._stop_event.is_set():
            if self.is_paused:
                time.sleep(0.2)
                continue
            if self.remaining_sec <= 0:
                self._set_time_display()
                self.stop()
                # Call expiry callback on main thread
                if self.on_expiry:
                    try:
                        self.parent.after(0, self.on_expiry)
                    except Exception:
                        pass
                return
            time.sleep(1)
            self.remaining_sec -= 1
            self._set_time_display()
            # Flash when under 1 minute
            if self.remaining_sec <= 60:
                self._time_lbl.config(fg=Config.COLORS['danger'])

    # ── Display helpers ──────────────────────────────────────────────────────
    def _set_time_display(self):
        h = self.remaining_sec // 3600
        m = (self.remaining_sec % 3600) // 60
        s = self.remaining_sec % 60
        self._time_lbl.config(text=f"{h:02d}:{m:02d}:{s:02d}")

    def _update_button_states(self):
        active = self.is_active and not self.is_paused
        paused = self.is_active and self.is_paused

        self._start_btn.config(state=tk.DISABLED if active else tk.NORMAL)
        self._pause_btn.config(state=tk.NORMAL if active else tk.DISABLED)
        self._resume_btn.config(state=tk.NORMAL if paused else tk.DISABLED)
        self._reset_btn.config(state=tk.NORMAL if self.is_active else tk.DISABLED)

        for btn in self._frame.winfo_children():
            if isinstance(btn, tk.Button) and btn.cget('text').startswith('+'):
                btn.config(state=tk.NORMAL if self.is_active else tk.DISABLED)
