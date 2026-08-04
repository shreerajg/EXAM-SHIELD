"""
ExamShield v1.0 — Unified Logger
Dual-output: file + database. Every module uses this.
"""
import logging
import os
from datetime import datetime, timedelta
from config import Config


class ExamShieldLogger:
    """Singleton-style logger shared across all modules."""

    _instance = None

    def __new__(cls, db_manager=None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_manager=None):
        if self._initialized:
            # Allow late-binding the db_manager
            if db_manager and not self.db_manager:
                self.db_manager = db_manager
            return
        self._initialized = True
        self.db_manager = db_manager
        self._setup_file_logger()

    # ── File Logger ──────────────────────────────────────────────
    def _setup_file_logger(self):
        os.makedirs(Config.LOG_DIR, exist_ok=True)
        self.logger = logging.getLogger("ExamShield")
        self.logger.setLevel(logging.DEBUG)
        # Avoid duplicate handlers on reimport
        if not self.logger.handlers:
            log_file = os.path.join(
                Config.LOG_DIR,
                f"exam_shield_{datetime.now().strftime('%Y%m%d')}.log",
            )
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            fmt = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            fh.setFormatter(fmt)
            ch.setFormatter(fmt)
            self.logger.addHandler(fh)
            self.logger.addHandler(ch)

    # ── Public API ───────────────────────────────────────────────
    def info(self, action, details="", db=True):
        self.logger.info(f"[{action}] {details}")
        if db and self.db_manager:
            self.db_manager.log_activity(action, details, blocked=False)

    def warning(self, action, details="", db=True):
        self.logger.warning(f"[{action}] {details}")
        if db and self.db_manager:
            self.db_manager.log_activity(action, details, blocked=False)

    def security(self, action, details="", blocked=True):
        level = logging.WARNING if blocked else logging.INFO
        tag = "BLOCKED" if blocked else "ALLOWED"
        self.logger.log(level, f"[SECURITY:{tag}] [{action}] {details}")
        if self.db_manager:
            self.db_manager.log_activity(action, details, blocked=blocked)

    def error(self, action, details="", db=True):
        self.logger.error(f"[{action}] {details}")
        if db and self.db_manager:
            self.db_manager.log_activity(f"ERROR_{action}", details, blocked=False)

    # ── Cleanup ──────────────────────────────────────────────────
    def cleanup_old_logs(self):
        cutoff = datetime.now() - timedelta(days=Config.LOG_RETENTION_DAYS)
        if not os.path.exists(Config.LOG_DIR):
            return
        for f in os.listdir(Config.LOG_DIR):
            if f.startswith("exam_shield_") and f.endswith(".log"):
                path = os.path.join(Config.LOG_DIR, f)
                if datetime.fromtimestamp(os.path.getctime(path)) < cutoff:
                    try:
                        os.remove(path)
                        self.logger.info(f"Cleaned old log: {f}")
                    except OSError as e:
                        self.logger.error(f"Failed to clean {f}: {e}")
