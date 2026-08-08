import ctypes
import threading
import time

class ClipboardManager:
    """
    Prevents copy-pasting by aggressively clearing the system clipboard 
    while the exam is active.
    """
    def __init__(self, db_manager):
        self.db = db_manager
        self.log = db_manager.logger
        self.is_active = False
        self._thread = None

    def start(self):
        if self.is_active:
            return
        self.is_active = True
        self._thread = threading.Thread(target=self._clipboard_loop, daemon=True, name="ClipboardGuard")
        self._thread.start()
        self.log.info("CLIPBOARD", "Clipboard protection started")

    def stop(self):
        self.is_active = False
        if self._thread:
            self._thread = None
        self.log.info("CLIPBOARD", "Clipboard protection stopped")

    def _clipboard_loop(self):
        while self.is_active:
            try:
                # Only attempt to clear if there is data on the clipboard.
                # This prevents constant locking and high CPU usage.
                if ctypes.windll.user32.CountClipboardFormats() > 0:
                    # Associate clipboard with the current task (None = current task)
                    if ctypes.windll.user32.OpenClipboard(None):
                        ctypes.windll.user32.EmptyClipboard()
                        ctypes.windll.user32.CloseClipboard()
            except Exception:
                # Ignore failures if another process is currently holding the clipboard open
                pass
            
            # Tighter interval for better protection, safely skipping if empty
            time.sleep(0.5)
