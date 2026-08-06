"""
ExamShield — Watchdog Manager
Launches and manages the watchdog_worker.py child process during exam
lockdown. The child process outlives temporary interruptions to the main
process and kills escape tools if the student kills main Python process.
"""
import os
import sys
import subprocess
import tempfile
import threading
from src.logger import ExamShieldLogger


class WatchdogManager:
    def __init__(self, db_manager):
        self.db  = db_manager
        self.log = ExamShieldLogger(db_manager)
        self._proc       = None          # subprocess.Popen handle
        self._flag_file  = None          # path to lock-file
        self._alive      = False

    # ── Public API ───────────────────────────────────────────────
    def start(self):
        """Launch the watchdog child process."""
        if self._alive:
            return
        try:
            # Create a flag file — child exits when this disappears
            fd, self._flag_file = tempfile.mkstemp(
                prefix='examshield_wd_', suffix='.lock'
            )
            os.close(fd)

            worker = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'watchdog_worker.py'
            )
            self._proc = subprocess.Popen(
                [sys.executable, worker,
                 str(os.getpid()), self._flag_file],
                # Detach so it survives if main window is killed
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
            self._alive = True
            self.log.info("WATCHDOG_START",
                          f"Watchdog PID {self._proc.pid} started")
        except Exception as e:
            self.log.error("WATCHDOG_START", f"Failed: {e}")

    def stop(self):
        """Signal the watchdog to stop by removing the flag file."""
        if not self._alive:
            return
        self._alive = False

        # Delete the flag file — worker will see it and exit cleanly
        if self._flag_file and os.path.isfile(self._flag_file):
            try:
                os.remove(self._flag_file)
            except Exception:
                pass
        self._flag_file = None

        # Also terminate the process directly as a backup
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None
        self.log.info("WATCHDOG_STOP", "Watchdog terminated")

    @property
    def is_running(self) -> bool:
        if not self._alive or self._proc is None:
            return False
        return self._proc.poll() is None
