"""
ExamShield v1.0 — Network Manager
Blocks internet by modifying hosts file + DNS, with robust restoration.
"""
import os
import shutil
import platform
import subprocess
import threading
import time
from config import Config
from logger import ExamShieldLogger


class NetworkManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.log = ExamShieldLogger(db_manager)
        self.is_blocked = False
        self.hosts_path = self._hosts_path()
        self._original_content = None
        self._backup_path = None
        self._guard_thread = None
        self._stop_event = threading.Event()

    @staticmethod
    def _hosts_path():
        s = platform.system().lower()
        if s == "windows":
            return r"C:\Windows\System32\drivers\etc\hosts"
        return "/etc/hosts"

    # ── Public API ───────────────────────────────────────────────
    def start_blocking(self):
        if self.is_blocked or not self.hosts_path:
            return
        try:
            self._backup_hosts()
            self._write_blocked_hosts()
            self._set_dns_loopback()
            self.is_blocked = True
            self._stop_event.clear()
            self._guard_thread = threading.Thread(
                target=self._guard_loop, daemon=True
            )
            self._guard_thread.start()
            self.log.info("NET_BLOCK_START", "Internet blocking activated")
        except Exception as e:
            self.log.error("NET_BLOCK", f"Start failed: {e}")

    def stop_blocking(self):
        if not self.is_blocked:
            return
        self.is_blocked = False
        self._stop_event.set()
        try:
            self._restore_hosts()
            self._restore_dns()
            self._flush_dns()
            self.log.info("NET_BLOCK_STOP", "Internet access restored")
        except Exception as e:
            self.log.error("NET_BLOCK", f"Stop failed: {e}")

    # ── Hosts file ops ───────────────────────────────────────────
    _MARKER_START = "# ===== EXAM SHIELD BLOCK START ====="
    _MARKER_END   = "# ===== EXAM SHIELD BLOCK END ====="

    def _backup_hosts(self):
        try:
            if os.path.exists(self.hosts_path):
                with open(self.hosts_path, 'r', encoding='utf-8', errors='replace') as f:
                    self._original_content = f.read()
                self._backup_path = self.hosts_path + ".examshield.bak"
                shutil.copy2(self.hosts_path, self._backup_path)
            else:
                self._original_content = ""
        except Exception as e:
            self.log.error("NET_BACKUP", f"Hosts backup failed: {e}")
            self._original_content = ""

    def _write_blocked_hosts(self):
        sites = Config.BLOCKED_WEBSITES
        lines = [self._MARKER_START]
        for site in sites:
            lines.append(f"127.0.0.1 {site}")
            lines.append(f"::1 {site}")
        lines.append(self._MARKER_END)
        block = "\n".join(lines)
        try:
            content = (self._original_content or "") + "\n\n" + block + "\n"
            with open(self.hosts_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            self.log.error("NET_HOSTS", f"Write failed: {e}")

    def _restore_hosts(self):
        try:
            if self._original_content is not None:
                with open(self.hosts_path, 'w', encoding='utf-8') as f:
                    f.write(self._original_content)
            elif self._backup_path and os.path.exists(self._backup_path):
                shutil.copy2(self._backup_path, self.hosts_path)
            # Cleanup backup
            if self._backup_path and os.path.exists(self._backup_path):
                os.remove(self._backup_path)
                self._backup_path = None
        except Exception as e:
            self.log.error("NET_RESTORE", f"Hosts restore failed: {e}")

    # ── DNS ──────────────────────────────────────────────────────
    def _set_dns_loopback(self):
        if platform.system().lower() != "windows":
            return
        for iface in ("Wi-Fi", "Ethernet", "Local Area Connection"):
            subprocess.run(
                ['netsh', 'interface', 'ip', 'set', 'dns',
                 f'name="{iface}"', 'source=static', 'addr=127.0.0.1'],
                capture_output=True, text=True
            )

    def _restore_dns(self):
        if platform.system().lower() != "windows":
            return
        for iface in ("Wi-Fi", "Ethernet", "Local Area Connection"):
            subprocess.run(
                ['netsh', 'interface', 'ip', 'set', 'dns',
                 f'name="{iface}"', 'source=dhcp'],
                capture_output=True, text=True
            )

    def _flush_dns(self):
        if platform.system().lower() == "windows":
            subprocess.run(['ipconfig', '/flushdns'], capture_output=True, text=True)

    # ── Guard Thread ─────────────────────────────────────────────
    def _guard_loop(self):
        """Re-apply hosts blocking if someone tampers with the file."""
        while not self._stop_event.is_set():
            try:
                with open(self.hosts_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                if self._MARKER_START not in content:
                    self._write_blocked_hosts()
                    self.log.warning("NET_GUARD", "Re-applied tampered hosts block")
            except Exception:
                pass
            self._stop_event.wait(5)

    # ── Helpers ──────────────────────────────────────────────────
    def get_blocked_websites(self):
        return Config.BLOCKED_WEBSITES
