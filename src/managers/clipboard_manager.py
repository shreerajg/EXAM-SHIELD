import ctypes
import threading
import time
from src.logger import ExamShieldLogger

class ClipboardManager:
    """
    Prevents copy-pasting by aggressively clearing the system clipboard 
    while the exam is active. Poll interval: 100 ms for minimal paste window.
    """
    def __init__(self, db_manager):
        self.db = db_manager
        self.log = ExamShieldLogger(db_manager)
        self.is_active = False
        self._thread = None
        self._security_manager = None   # set externally if breach counting needed

    def start(self):
        if self.is_active:
            return
        self.is_active = True

        # Disable Windows 10/11 Clipboard History via Registry
        try:
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Clipboard") as key:
                winreg.SetValueEx(key, "EnableClipboardHistory", 0, winreg.REG_DWORD, 0)
        except Exception as e:
            self.log.error("CLIPBOARD", f"Failed to disable clipboard history: {e}")

        self._thread = threading.Thread(target=self._clipboard_loop, daemon=True, name="ClipboardGuard")
        self._thread.start()
        self.log.info("CLIPBOARD", "Clipboard protection started")

    def stop(self):
        self.is_active = False

        # Restore Windows 10/11 Clipboard History via Registry
        try:
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Clipboard") as key:
                winreg.SetValueEx(key, "EnableClipboardHistory", 1, winreg.REG_DWORD, 1)
        except Exception as e:
            self.log.error("CLIPBOARD", f"Failed to restore clipboard history: {e}")

        if self._thread:
            self._thread = None
        self.log.info("CLIPBOARD", "Clipboard protection stopped")

    def _clipboard_loop(self):
        CF_UNICODETEXT = 13
        while self.is_active:
            try:
                # Only attempt to clear if there is data on the clipboard.
                if ctypes.windll.user32.CountClipboardFormats() > 0:
                    if ctypes.windll.user32.OpenClipboard(None):
                        # Attempt to audit text before clearing
                        try:
                            if ctypes.windll.user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                                handle = ctypes.windll.user32.GetClipboardData(CF_UNICODETEXT)
                                if handle:
                                    ptr = ctypes.windll.kernel32.GlobalLock(handle)
                                    if ptr:
                                        text = ctypes.c_wchar_p(ptr).value
                                        ctypes.windll.kernel32.GlobalUnlock(handle)
                                        if text and str(text).strip():
                                            preview = str(text).strip().replace('\n', ' ')[:50]
                                            self.log.security(
                                                "CLIPBOARD_BLOCKED",
                                                f"Blocked copy: '{preview}...'"
                                            )
                                            # Increment breach counter if security manager present
                                            if self._security_manager is not None:
                                                try:
                                                    self._security_manager.breach_counts['keyboard'] += 1
                                                except Exception:
                                                    pass
                        except Exception:
                            pass

                        ctypes.windll.user32.EmptyClipboard()
                        ctypes.windll.user32.CloseClipboard()
            except Exception:
                # Ignore failures if another process is currently holding the clipboard open
                pass

            # 100 ms poll — reduces paste window from 500 ms to 100 ms
            time.sleep(0.1)
