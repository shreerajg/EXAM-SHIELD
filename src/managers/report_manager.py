"""
ExamShield v1.0 — Session Report Manager
Generates a human-readable .txt report at the end of each exam session.
"""
import os
import datetime
from src.config import Config


class ReportManager:
    """
    Collects session metadata during a lockdown and writes a final report.
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self._session_start: datetime.datetime | None = None
        self._session_end: datetime.datetime | None = None
        self._active_modules: list[str] = []
        self._profile_name: str = ""
        self._timer_minutes: int = 0

    # ── Session lifecycle ────────────────────────────────────────
    def begin_session(self, modules: list[str],
                      profile_name: str = "",
                      timer_minutes: int = 0):
        """Call when lockdown starts."""
        self._session_start = datetime.datetime.now()
        self._session_end = None
        self._active_modules = modules[:]
        self._profile_name = profile_name
        self._timer_minutes = timer_minutes

    def end_session(self,
                    breach_counts: dict,
                    screenshots_taken: int = 0,
                    screenshot_dir: str = "") -> str:
        """
        Call when lockdown ends.
        Returns the absolute path to the written report file.
        """
        self._session_end = datetime.datetime.now()
        return self._write_report(breach_counts, screenshots_taken,
                                  screenshot_dir)

    # ── Report generation ────────────────────────────────────────
    def _write_report(self, breach_counts: dict,
                       screenshots_taken: int,
                       screenshot_dir: str) -> str:
        os.makedirs(Config.REPORT_DIR, exist_ok=True)

        ts = self._session_start.strftime("%Y%m%d_%H%M%S")
        filename = f"exam_report_{ts}.txt"
        path = os.path.join(Config.REPORT_DIR, filename)

        start_str = self._session_start.strftime("%Y-%m-%d %H:%M:%S")
        end_str   = (self._session_end.strftime("%Y-%m-%d %H:%M:%S")
                     if self._session_end else "N/A")

        duration = (self._session_end - self._session_start
                    if self._session_end else datetime.timedelta(0))
        dur_str = str(duration).split('.')[0]   # trim microseconds

        # Fetch logs for this session from DB
        logs = self.db.get_activity_logs(limit=2000)
        session_logs = [
            (a, d, t, b) for a, d, t, b in logs
            if self._is_in_session(t)
        ]
        blocked_events = [(a, d, t) for a, d, t, b in session_logs if b]
        total_events   = len(session_logs)

        lines = [
            "=" * 64,
            "           EXAM SHIELD — SESSION REPORT",
            "=" * 64,
            "",
            f"  Profile      : {self._profile_name or '(custom)'}",
            f"  Start time   : {start_str}",
            f"  End time     : {end_str}",
            f"  Duration     : {dur_str}",
            f"  Timer set    : {self._timer_minutes} min"
                            if self._timer_minutes else "  Timer set    : (not used)",
            "",
            "─" * 64,
            "  ACTIVE MODULES",
            "─" * 64,
        ]
        for mod in self._active_modules:
            lines.append(f"    ✓  {mod.capitalize()}")

        lines += [
            "",
            "─" * 64,
            "  BREACH SUMMARY",
            "─" * 64,
            f"    Blocked keystrokes       : {breach_counts.get('keyboard', 0)}",
            f"    Blocked network attempts  : {breach_counts.get('network', 0)}",
            f"    Suspicious processes      : {breach_counts.get('processes', 0)}",
            f"    USB block events          : {breach_counts.get('usb', 0)}",
            f"    Window violation attempts : {breach_counts.get('windows', 0)}",
            f"    Total blocked events      : {sum(breach_counts.values())}",
            "",
            f"    Total log entries         : {total_events}",
            "",
        ]

        if screenshots_taken:
            lines += [
                "─" * 64,
                "  SCREENSHOTS",
                "─" * 64,
                f"    Captured  : {screenshots_taken} screenshot(s)",
                f"    Saved to  : {screenshot_dir}",
                "",
            ]

        if blocked_events:
            lines += [
                "─" * 64,
                "  BLOCKED EVENTS LOG",
                "─" * 64,
            ]
            for action, details, ts_str in blocked_events[:200]:
                lines.append(f"    [{ts_str}]  {action}  —  {details or ''}")
            if len(blocked_events) > 200:
                lines.append(f"    ... and {len(blocked_events) - 200} more.")
            lines.append("")

        lines += [
            "=" * 64,
            f"  Report generated: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
            f"  ExamShield v{Config.VERSION}",
            "=" * 64,
        ]

        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        return path

    def _is_in_session(self, ts_str: str) -> bool:
        """Return True if ts_str falls within this session's window."""
        if not self._session_start:
            return True
        try:
            t = datetime.datetime.fromisoformat(ts_str.replace('Z', ''))
            end = self._session_end or datetime.datetime.now()
            return self._session_start <= t <= end
        except Exception:
            return True
