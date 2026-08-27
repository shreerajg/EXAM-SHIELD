"""
ExamShield v1.3.0 - Bluetooth Manager
Monitors system for connected Bluetooth audio devices or smartwatches.
"""
import threading
import subprocess
import json
import time
from src.config import Config
from src.logger import ExamShieldLogger

class BluetoothManager:
    def __init__(self, db_manager):
        self.db = db_manager
        self.log = ExamShieldLogger(db_manager)
        self.is_active = False
        self._thread = None
        self._stop_event = threading.Event()
        self.security_manager = None
        
        # We ignore base bluetooth adapters and only look for peripherals
        self.ignored_keywords = ['intel', 'realtek', 'mediatek', 'qualcomm', 'broadcom', 'adapter', 'radio', 'enumerator']

    def set_security_manager(self, sm):
        self.security_manager = sm

    def start(self):
        if self.is_active: return
        self.is_active = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        self.log.info("BLUETOOTH", "Bluetooth monitoring started")

    def stop(self):
        self.is_active = False
        self._stop_event.set()
        if self._thread:
            self._thread = None
        self.log.info("BLUETOOTH", "Bluetooth monitoring stopped")

    def _monitor_loop(self):
        try:
            interval = getattr(Config, 'BLUETOOTH_MONITOR_INTERVAL_SEC', 5)
            
            error_count = 0
            while self.is_active and not self._stop_event.is_set():
                try:
                    # In PowerShell, we fetch Bluetooth items that are OK (connected).
                    cmd = (
                        "Get-PnpDevice -ErrorAction SilentlyContinue | "
                        "Where-Object { ($_.Class -eq 'Bluetooth' -or $_.InstanceId -match 'BTHENUM') -and $_.Status -eq 'OK' } | "
                        "Select-Object FriendlyName, InstanceId | ConvertTo-Json"
                    )
                    output = subprocess.check_output(
                        ["powershell.exe", "-Command", cmd],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        timeout=10
                    ).decode('utf-8', errors='ignore')
                    
                    if output.strip():
                        # Output could be a single dict or list of dicts
                        data = json.loads(output)
                        if isinstance(data, dict):
                            data = [data]
                            
                        for item in data:
                            name = item.get("FriendlyName", "")
                            if not name:
                                continue
                            
                            # Filter out system adapters
                            is_ignored = any(kw in name.lower() for kw in self.ignored_keywords)
                            
                            if not is_ignored:
                                self._trigger_violation(name)
                                
                    error_count = 0
                except subprocess.TimeoutExpired:
                    self.log.warning("BLUETOOTH", "Bluetooth check timeout")
                except subprocess.CalledProcessError:
                    # PowerShell command failed, possibly no Bluetooth devices or module missing
                    pass
                except Exception as loop_e:
                    error_count += 1
                    self.log.error("BLUETOOTH", f"Error checking Bluetooth: {loop_e}")
                    if error_count > 3:
                        self.log.error("BLUETOOTH", "Too many failures. Stopping bluetooth monitor.")
                        break
                        
                self._stop_event.wait(interval)
                
        except Exception as e:
            self.log.error("BLUETOOTH", f"Fatal error in bluetooth monitor: {e}")
        finally:
            self.is_active = False

    def _trigger_violation(self, device_name):
        msg = f"Unauthorized Bluetooth device connected: '{device_name}'"
        self.log.security("BLUETOOTH_VIOLATION", msg, blocked=True)
        if self.security_manager:
            if 'bluetooth' not in self.security_manager.breach_counts:
                self.security_manager.breach_counts['bluetooth'] = 0
            self.security_manager.breach_counts['bluetooth'] += 1
            self.security_manager.screenshot_manager.capture_violation(reason="bluetooth")
            
            panel = self.security_manager.admin_panel
            if panel and hasattr(panel, 'window'):
                try:
                    panel.window.after(0, panel.update_breach_counter)
                    panel.window.after(0, lambda m=msg: panel._toast(f"🎧  {m}", '#ff4757') if hasattr(panel, '_toast') else None)
                except Exception:
                    pass
