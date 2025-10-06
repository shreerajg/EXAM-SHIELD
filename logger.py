"""
Enhanced logging system for Exam Shield
"""

import logging
import os
from datetime import datetime, timedelta
from config import Config

class ExamShieldLogger:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.setup_file_logging()

    def setup_file_logging(self):
        """Setup file-based logging"""
        logs_dir = os.path.join(os.path.dirname(__file__), "logs")
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
        self.logger = logging.getLogger("ExamShield")
        self.logger.setLevel(logging.INFO)

        log_filename = os.path.join(logs_dir, f"exam_shield_{datetime.now().strftime('%Y%m%d')}.log")
        file_handler = logging.FileHandler(log_filename)
        file_handler.setLevel(logging.INFO)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)

        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def log_security_event(self, event_type, details, blocked=False):
        """Log security-related events"""
        self.db_manager.log_activity(event_type, details, blocked)
        level = logging.WARNING if blocked else logging.INFO
        self.logger.log(level, f"SECURITY: {event_type} - {details} ({'BLOCKED' if blocked else 'ALLOWED'})")

    def log_system_event(self, event_type, details):
        self.db_manager.log_activity(f"SYSTEM_{event_type}", details)
        self.logger.info(f"SYSTEM: {event_type} - {details}")

    def log_admin_action(self, action, details):
        self.db_manager.log_activity(f"ADMIN_{action}", details)
        self.logger.info(f"ADMIN: {action} - {details}")

    def cleanup_old_logs(self):
        logs_dir = os.path.join(os.path.dirname(__file__), "logs")
        if not os.path.exists(logs_dir):
            return
        cutoff_date = datetime.now() - timedelta(days=Config.LOG_RETENTION_DAYS)

        for filename in os.listdir(logs_dir):
            if filename.startswith("exam_shield_") and filename.endswith(".log"):
                file_path = os.path.join(logs_dir, filename)
                file_date = datetime.fromtimestamp(os.path.getctime(file_path))
                if file_date < cutoff_date:
                    try:
                        os.remove(file_path)
                        self.logger.info(f"Cleaned up old log file: {filename}")
                    except OSError as e:
                        self.logger.error(f"Error cleaning up log file {filename}: {e}")
