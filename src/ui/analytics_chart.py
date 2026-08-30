"""
ExamShield v1.4.0 — Analytics Chart
Pure-Tkinter Canvas live analytics for the Dashboard tab.

Provides two chart widgets:
  • BreachTimelineChart  — scrolling line chart, one series per breach category
  • BreachBarChart       — horizontal bar chart with cumulative session counts
"""
import tkinter as tk
import math
import datetime
from src.config import Config

C = Config.COLORS

# ── Colour palette for each breach series ────────────────────────────────────
_SERIES_COLORS = {
    'keyboard':  '#00d4ff',   # cyan
    'processes': '#ff4757',   # red
    'network':   '#ffab40',   # amber
    'usb':       '#a855f7',   # purple
    'windows':   '#10b981',   # green
    'webcam':    '#f43f5e',   # rose
    'audio':     '#3b82f6',   # blue
    'bluetooth': '#ec4899',   # pink
}

_ALL_CATEGORIES = list(_SERIES_COLORS.keys())


# ─────────────────────────────────────────────────────────────────────────────
class BreachTimelineChart(tk.Frame):
    """
    Scrolling line chart showing per-category blocked events per minute
    for the last N minutes.
    Refreshes every `refresh_ms` milliseconds.
    """

    def __init__(self, parent, db_manager, minutes: int = 20,
                 width: int = 580, height: int = 200,
                 refresh_ms: int = 5000):
        super().__init__(parent, bg=C['card'],
                         highlightthickness=1,
                         highlightbackground=C['border'])
        self.db = db_manager
        self._minutes = minutes
        self._refresh_ms = refresh_ms

        # Internal data: list of dicts keyed by category
        self._buckets: list[dict] = []

        # Canvas
        self._canvas = tk.Canvas(self, width=width, height=height,
                                  bg=C['card'], highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Legend strip at bottom
        legend_frame = tk.Frame(self, bg=C['card'])
        legend_frame.pack(fill=tk.X, padx=8, pady=(0, 6))
        for cat, color in _SERIES_COLORS.items():
            dot = tk.Label(legend_frame, text="⬤", font=('Segoe UI', 7),
                           bg=C['card'], fg=color)
            dot.pack(side=tk.LEFT, padx=(0, 2))
            tk.Label(legend_frame, text=cat.capitalize(),
                     font=('Segoe UI', 7), bg=C['card'],
                     fg=C['text_dim']).pack(side=tk.LEFT, padx=(0, 10))

        self._running = True
        self._refresh()

    def stop(self):
        self._running = False

    def _refresh(self):
        if not self._running:
            return
        try:
            self._buckets = self._fetch_buckets()
            self._draw()
        except Exception as e:
            pass
        try:
            self.after(self._refresh_ms, self._refresh)
        except Exception:
            pass

    def _fetch_buckets(self) -> list[dict]:
        """
        Fetch blocked events from DB and bucket them by minute.
        Returns a list of dicts: [{minute_label: str, cat: count, ...}, ...]
        ordered oldest → newest.
        """
        try:
            raw = self.db.get_breach_timeline(self._minutes)
            return raw
        except Exception:
            return []

    def _draw(self):
        canvas = self._canvas
        canvas.delete('all')

        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 10 or h < 10:
            return

        pad_left = 36
        pad_right = 12
        pad_top = 14
        pad_bottom = 24

        plot_w = w - pad_left - pad_right
        plot_h = h - pad_top - pad_bottom

        buckets = self._buckets
        n = max(len(buckets), 1)

        # Find y_max across all series
        y_max = 1
        for b in buckets:
            for cat in _ALL_CATEGORIES:
                y_max = max(y_max, b.get(cat, 0))

        # Draw grid lines
        for i in range(5):
            y_val = i * y_max / 4
            y_px = pad_top + plot_h - int(plot_h * (y_val / y_max))
            canvas.create_line(pad_left, y_px, pad_left + plot_w, y_px,
                               fill=C['border'], dash=(2, 4))
            canvas.create_text(pad_left - 4, y_px, text=str(int(y_val)),
                               font=('Consolas', 7), fill=C['text_dim'],
                               anchor=tk.E)

        # X axis labels (every 5 minutes)
        step = max(1, n // 5)
        for i, b in enumerate(buckets):
            if i % step == 0 or i == n - 1:
                x_px = pad_left + int(plot_w * i / max(n - 1, 1))
                canvas.create_text(x_px, h - pad_bottom + 8,
                                   text=b.get('label', ''),
                                   font=('Consolas', 7), fill=C['text_dim'])

        # Axes
        canvas.create_line(pad_left, pad_top, pad_left, pad_top + plot_h,
                           fill=C['border_bright'], width=1)
        canvas.create_line(pad_left, pad_top + plot_h,
                           pad_left + plot_w, pad_top + plot_h,
                           fill=C['border_bright'], width=1)

        if not buckets:
            canvas.create_text(w // 2, h // 2,
                               text="No breach data yet — start an exam session",
                               font=('Segoe UI', 9), fill=C['text_dim'])
            return

        # Draw one polyline per category
        for cat, color in _SERIES_COLORS.items():
            points = []
            for i, b in enumerate(buckets):
                val = b.get(cat, 0)
                x_px = pad_left + int(plot_w * i / max(n - 1, 1))
                y_px = pad_top + plot_h - int(plot_h * (val / y_max))
                points.extend([x_px, y_px])

            if len(points) >= 4:
                canvas.create_line(*points, fill=color, width=2,
                                   smooth=True, joinstyle=tk.ROUND,
                                   capstyle=tk.ROUND)
            # Dot on last point
            if len(points) >= 2:
                lx, ly = points[-2], points[-1]
                canvas.create_oval(lx - 3, ly - 3, lx + 3, ly + 3,
                                   fill=color, outline='')

        # Chart title
        canvas.create_text(pad_left, 6, text="BREACH TIMELINE",
                           font=('Segoe UI', 7, 'bold'),
                           fill=C['primary'], anchor=tk.W)


# ─────────────────────────────────────────────────────────────────────────────
class BreachBarChart(tk.Frame):
    """
    Horizontal bar chart showing cumulative breach counts per module
    for the current/last session. Refreshes every refresh_ms ms.
    """

    def __init__(self, parent, db_manager,
                 width: int = 260, height: int = 200,
                 refresh_ms: int = 5000):
        super().__init__(parent, bg=C['card'],
                         highlightthickness=1,
                         highlightbackground=C['border'])
        self.db = db_manager
        self._refresh_ms = refresh_ms
        self._counts: dict[str, int] = {}

        self._canvas = tk.Canvas(self, width=width, height=height,
                                  bg=C['card'], highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._running = True
        self._refresh()

    def stop(self):
        self._running = False

    def push_counts(self, breach_counts: dict):
        """Called by the admin panel to push live breach_counts during lockdown."""
        self._counts = dict(breach_counts)
        self._draw()

    def _refresh(self):
        if not self._running:
            return
        try:
            # Fallback: pull from DB stats if no push
            if not self._counts:
                self._draw()
        except Exception:
            pass
        try:
            self.after(self._refresh_ms, self._refresh)
        except Exception:
            pass

    def _draw(self):
        canvas = self._canvas
        canvas.delete('all')

        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 10 or h < 10:
            return

        counts = self._counts
        if not counts:
            canvas.create_text(w // 2, h // 2,
                               text="No breach data\nStart exam to see stats",
                               font=('Segoe UI', 9), fill=C['text_dim'],
                               justify=tk.CENTER)
            return

        canvas.create_text(10, 8, text="BREACH BREAKDOWN",
                           font=('Segoe UI', 7, 'bold'),
                           fill=C['primary'], anchor=tk.W)

        items = [(k, v) for k, v in counts.items() if v >= 0]
        items.sort(key=lambda x: x[1], reverse=True)

        pad_top = 22
        pad_left = 72
        pad_right = 36
        pad_bottom = 8

        bar_area_w = w - pad_left - pad_right
        bar_area_h = h - pad_top - pad_bottom

        n = len(items)
        if n == 0:
            return

        max_val = max(v for _, v in items) or 1
        row_h = bar_area_h / n
        bar_h = max(8, min(22, row_h * 0.6))

        for i, (cat, val) in enumerate(items):
            color = _SERIES_COLORS.get(cat, C['primary'])
            cy = pad_top + row_h * i + row_h / 2

            # Label
            canvas.create_text(pad_left - 6, cy,
                               text=cat.capitalize()[:9],
                               font=('Segoe UI', 8), fill=C['text_dim'],
                               anchor=tk.E)

            # Bar background
            bx0 = pad_left
            bx1 = pad_left + bar_area_w
            by0 = cy - bar_h / 2
            by1 = cy + bar_h / 2
            canvas.create_rectangle(bx0, by0, bx1, by1,
                                    fill=C['surface_alt'], outline='')

            # Value bar
            filled_w = int(bar_area_w * (val / max_val))
            if filled_w > 0:
                canvas.create_rectangle(bx0, by0, bx0 + filled_w, by1,
                                        fill=color, outline='')
                # Subtle glow
                canvas.create_rectangle(bx0, by0 + bar_h * 0.6,
                                        bx0 + filled_w, by1,
                                        fill=_darken(color, 0.7), outline='')

            # Value label
            canvas.create_text(pad_left + bar_area_w + 4, cy,
                               text=str(val),
                               font=('Consolas', 8, 'bold'),
                               fill=color if val > 0 else C['text_dim'],
                               anchor=tk.W)


def _darken(hex_c: str, factor: float = 0.7) -> str:
    try:
        h = hex_c.lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f'#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}'
    except Exception:
        return hex_c
