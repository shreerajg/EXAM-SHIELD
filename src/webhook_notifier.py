"""
ExamShield v1.4.0 — Webhook Breach Alerts
Sends a POST to a configurable webhook URL on every blocked security event.
Useful for pushing alerts to Discord/Telegram/Slack/any webhook-compatible receiver.
"""
import json
import threading
import urllib.request
import urllib.error
from typing import Any

from src.config import Config
from src.logger import ExamShieldLogger


class WebhookNotifier:
    """
    Thread-safe webhook dispatcher.

    Configure via DB setting 'webhook_url' (string) or via an
    examshield.toml / Config override.

    Each alert is sent as a JSON payload:
        {
          "event": "BLOCKED_KEY",
          "detail": "Blocked: ctrl+alt+del",
          "severity": "warning",
          "timestamp": 1700000000.123,
          "breach_count": { ... }
        }
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self.log = ExamShieldLogger(db_manager)
        self._session = threading.local()

    # ── URL resolution ──────────────────────────────────────────────────
    def get_url(self) -> str | None:
        """Return the active webhook URL, checking DB then env then config."""
        url = self.db.get_setting('webhook_url', None)
        if url:
            return url
        import os
        return os.environ.get('EXAMSHIELD_WEBHOOK_URL', None)

    # ── Public dispatch ────────────────────────────────────────────────
    def alert(self, event: str, detail: str, severity: str = "warning",
              breach_counts: dict[str, int] | None = None):
        """
        Fire a webhook alert. Non-blocking — dispatched on a daemon thread.
        """
        url = self.get_url()
        if not url:
            return  # no webhook configured — silently skip

        payload = {
            "event": event,
            "detail": detail,
            "severity": severity,
            "timestamp": __import__('time').time(),
        }
        if breach_counts:
            payload["breach_counts"] = breach_counts

        def _send():
            try:
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "ExamShield/1.4.0",
                    },
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        body = resp.read().decode('utf-8', errors='replace')
                        if 200 <= resp.status < 300:
                            self.log.info("WEBHOOK_SENT",
                                          f"{event} → {url} [{resp.status}]")
                        else:
                            self.log.warning("WEBHOOK_FAIL",
                                             f"{event} → {url} status {resp.status}: {body[:200]}")
                except urllib.error.HTTPError as he:
                    self.log.warning("WEBHOOK_FAIL",
                                     f"{event} → {url} HTTP {he.code}: {he.read().decode('utf-8', errors='replace')[:200]}")
                except urllib.error.URLError as ue:
                    self.log.warning("WEBHOOK_FAIL",
                                     f"{event} → {url} unreachable: {ue.reason}")
            except Exception as e:
                self.log.error("WEBHOOK_ERROR", f"Unexpected webhook dispatch error: {e}")

        threading.Thread(target=_send, daemon=True).start()

    # ── Convenience wrappers for common events ────────────────────────
    def on_blocked_key(self, combo: str, breach_counts: dict[str, int]):
        self.alert("BLOCKED_KEY", f"Blocked key combo: {combo}", "warning", breach_counts)

    def on_blocked_process(self, name: str, breach_counts: dict[str, int]):
        self.alert("SUSPICIOUS_PROCESS", f"Terminated suspicious process: {name}", "danger", breach_counts)

    def on_session_start(self, profile: str, timer_min: int, modules: list[str]):
        self.alert("EXAM_START", f"Exam started | profile={profile} timer={timer_min}m modules={','.join(modules)}",
                   "info", {"modules": modules})

    def on_session_end(self, report_path: str, breach_counts: dict[str, int]):
        self.alert("EXAM_END", f"Exam ended | report={report_path} breaches={sum(breach_counts.values())}",
                   "info", breach_counts)
