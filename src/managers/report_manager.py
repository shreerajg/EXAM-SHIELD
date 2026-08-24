"""
ExamShield v1.0 — Session Report Manager
Generates a human-readable .txt report at the end of each exam session.
"""
import os
import datetime
from typing import Optional
from src.config import Config


class ReportManager:
    """
    Collects session metadata during a lockdown and writes a final report.
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self._session_start: Optional[datetime.datetime] = None
        self._session_end: Optional[datetime.datetime] = None
        self._active_modules: list = []
        self._profile_name: str = ""
        self._timer_minutes: int = 0

    # ── Session lifecycle ────────────────────────────────────────
    def begin_session(self, modules: list,
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

        # Also produce HTML report
        self._write_html_report(ts, start_str, end_str, dur_str,
                                breach_counts, screenshots_taken,
                                screenshot_dir, blocked_events, total_events)

        return path

    # ── HTML Report ──────────────────────────────────────────────
    def _write_html_report(self, ts: str, start_str: str, end_str: str,
                            dur_str: str, breach_counts: dict,
                            screenshots_taken: int, screenshot_dir: str,
                            blocked_events: list, total_events: int):
        html_path = os.path.join(Config.REPORT_DIR, f"exam_report_{ts}.html")
        total_breaches = sum(breach_counts.values())

        # Build breach rows
        breach_rows = ""
        for key, label in [
            ('keyboard',  'Blocked Keystrokes'),
            ('network',   'Network Attempts'),
            ('processes', 'Suspicious Processes'),
            ('usb',       'USB Block Events'),
            ('windows',   'Window Violations'),
        ]:
            v = breach_counts.get(key, 0)
            color = "#ff4757" if v > 0 else "#00e676"
            breach_rows += (
                f"<tr><td>{label}</td>"
                f"<td style='color:{color};font-weight:bold;text-align:center'>{v}</td></tr>\n"
            )

        # Build event log rows (up to 200)
        event_rows = ""
        for action, details, ts_str in blocked_events[:200]:
            event_rows += (
                f"<tr>"
                f"<td style='color:#6a6a9e;font-size:11px'>{ts_str}</td>"
                f"<td style='color:#ff4757'>{action}</td>"
                f"<td>{details or '—'}</td>"
                f"</tr>\n"
            )
        if len(blocked_events) > 200:
            event_rows += (
                f"<tr><td colspan='3' style='color:#ffab40;text-align:center'>"
                f"... and {len(blocked_events) - 200} more events.</td></tr>\n"
            )

        modules_html = "".join(
            f"<span class='badge'>{m.capitalize()}</span>"
            for m in self._active_modules
        )

        timer_display = f"{self._timer_minutes} min" if self._timer_minutes else "(not used)"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ExamShield — Session Report</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', sans-serif; background: #0a0a1a;
          color: #e8e8f0; padding: 32px; }}
  h1 {{ color: #00d4ff; font-size: 24px; margin-bottom: 4px; }}
  .subtitle {{ color: #6a6a9e; font-size: 13px; margin-bottom: 28px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px;
           margin-bottom: 28px; }}
  .card {{ background: #16163a; border: 1px solid #252550;
           border-radius: 8px; padding: 20px; }}
  .card h2 {{ color: #00d4ff; font-size: 13px; text-transform: uppercase;
              letter-spacing: 1px; margin-bottom: 14px; border-bottom: 1px solid #252550;
              padding-bottom: 8px; }}
  .meta-row {{ display: flex; justify-content: space-between;
               padding: 6px 0; border-bottom: 1px solid #1a1a3a; }}
  .meta-label {{ color: #6a6a9e; font-size: 12px; }}
  .meta-val {{ font-size: 12px; font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th {{ background: #1a1a3a; color: #00d4ff; padding: 8px 12px;
        text-align: left; font-size: 11px; text-transform: uppercase; }}
  td {{ padding: 7px 12px; border-bottom: 1px solid #1a1a3a; }}
  tr:hover td {{ background: #12122a; }}
  .badge {{ display: inline-block; background: #7f5af033;
            color: #7f5af0; border: 1px solid #7f5af0;
            border-radius: 4px; padding: 2px 10px;
            font-size: 11px; margin: 2px; }}
  .total-box {{ background: #16163a; border: 2px solid #ff4757;
               border-radius: 8px; padding: 16px 24px;
               display: inline-block; margin-bottom: 20px; }}
  .total-box .num {{ font-size: 48px; font-weight: 900;
                     color: #ff4757; line-height: 1; }}
  .total-box .lbl {{ color: #6a6a9e; font-size: 13px; margin-top: 4px; }}
  .full-card {{ background: #16163a; border: 1px solid #252550;
                border-radius: 8px; padding: 20px;
                margin-bottom: 20px; }}
  .footer {{ color: #6a6a9e; font-size: 11px; margin-top: 28px;
             border-top: 1px solid #252550; padding-top: 14px; }}
</style>
</head>
<body>
  <h1>🛡️ EXAM SHIELD — Session Report</h1>
  <div class="subtitle">Generated: {datetime.datetime.now():%Y-%m-%d %H:%M:%S} &nbsp;·&nbsp; ExamShield v{Config.VERSION}</div>

  <div class="grid">
    <div class="card">
      <h2>📋 Session Info</h2>
      <div class="meta-row"><span class="meta-label">Profile</span><span class="meta-val">{self._profile_name or '(custom)'}</span></div>
      <div class="meta-row"><span class="meta-label">Start</span><span class="meta-val">{start_str}</span></div>
      <div class="meta-row"><span class="meta-label">End</span><span class="meta-val">{end_str}</span></div>
      <div class="meta-row"><span class="meta-label">Duration</span><span class="meta-val">{dur_str}</span></div>
      <div class="meta-row"><span class="meta-label">Timer set</span><span class="meta-val">{timer_display}</span></div>
      <div class="meta-row"><span class="meta-label">Screenshots</span><span class="meta-val">{screenshots_taken}</span></div>
      <div class="meta-row"><span class="meta-label">Total log entries</span><span class="meta-val">{total_events}</span></div>
    </div>
    <div class="card">
      <h2>🔧 Active Modules</h2>
      <div style="margin-top:8px">{modules_html}</div>
    </div>
  </div>

  <div class="full-card">
    <h2 style="color:#ff4757;font-size:13px;text-transform:uppercase;letter-spacing:1px;margin-bottom:16px;border-bottom:1px solid #252550;padding-bottom:8px">🚫 Breach Summary</h2>
    <div style="margin-bottom:20px">
      <div class="total-box">
        <div class="num">{total_breaches}</div>
        <div class="lbl">Total Blocked Events</div>
      </div>
    </div>
    <table>
      <tr><th>Category</th><th style="text-align:center">Count</th></tr>
      {breach_rows}
    </table>
  </div>

  {'<div class="full-card"><h2 style="color:#ffab40;font-size:13px;text-transform:uppercase;letter-spacing:1px;margin-bottom:14px;border-bottom:1px solid #252550;padding-bottom:8px">⚡ Blocked Event Log</h2><table><tr><th>Time</th><th>Action</th><th>Details</th></tr>' + event_rows + '</table></div>' if blocked_events else ''}

  <div class="footer">
    ExamShield v{Config.VERSION} &nbsp;·&nbsp; Report path: {html_path}
  </div>
</body>
</html>"""

        try:
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html)
        except Exception as e:
            print(f"[Report] HTML write failed: {e}")

    # ── PDF Report ───────────────────────────────────────────────
    def _write_pdf_report(self, ts: str, start_str: str, end_str: str,
                            dur_str: str, breach_counts: dict,
                            screenshots_taken: int, screenshot_dir: str,
                            blocked_events: list, total_events: int):
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.colors import HexColor
        except ImportError:
            print("[Report] reportlab not installed. Skipping PDF export.")
            return

        pdf_path = os.path.join(Config.REPORT_DIR, f"exam_report_{ts}.pdf")
        
        try:
            c = canvas.Canvas(pdf_path, pagesize=letter)
            width, height = letter
            
            # Title
            c.setFont("Helvetica-Bold", 16)
            c.setFillColor(HexColor("#00d4ff"))
            c.drawString(50, height - 50, "EXAM SHIELD - Session Report")
            
            c.setFont("Helvetica", 10)
            c.setFillColor(HexColor("#6a6a9e"))
            c.drawString(50, height - 65, f"Generated: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
            
            # Session Info
            c.setFont("Helvetica-Bold", 12)
            c.setFillColor(HexColor("#000000"))
            y = height - 100
            c.drawString(50, y, "Session Info")
            y -= 15
            c.setFont("Helvetica", 10)
            c.drawString(60, y, f"Profile: {self._profile_name or '(custom)'}"); y -= 12
            c.drawString(60, y, f"Start: {start_str}"); y -= 12
            c.drawString(60, y, f"End: {end_str}"); y -= 12
            c.drawString(60, y, f"Duration: {dur_str}"); y -= 12
            c.drawString(60, y, f"Timer set: {self._timer_minutes} min" if self._timer_minutes else "Timer set: (not used)"); y -= 20
            
            # Active Modules
            c.setFont("Helvetica-Bold", 12)
            c.drawString(50, y, "Active Modules"); y -= 15
            c.setFont("Helvetica", 10)
            for mod in self._active_modules:
                c.drawString(60, y, f"✓ {mod.capitalize()}"); y -= 12
            y -= 8
            
            # Breach Summary
            c.setFont("Helvetica-Bold", 12)
            c.setFillColor(HexColor("#ff4757"))
            c.drawString(50, y, "Breach Summary"); y -= 15
            c.setFont("Helvetica", 10)
            c.setFillColor(HexColor("#000000"))
            
            for key, label in [
                ('keyboard', 'Blocked Keystrokes'),
                ('network', 'Network Attempts'),
                ('processes', 'Suspicious Processes'),
                ('usb', 'USB Block Events'),
                ('windows', 'Window Violations'),
            ]:
                v = breach_counts.get(key, 0)
                c.drawString(60, y, f"{label}: {v}"); y -= 12
                
            total_breaches = sum(breach_counts.values())
            y -= 4
            c.setFont("Helvetica-Bold", 10)
            c.drawString(60, y, f"Total Blocked Events: {total_breaches}"); y -= 20
            
            c.save()
        except Exception as e:
            print(f"[Report] PDF write failed: {e}")

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
