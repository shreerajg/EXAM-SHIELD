"""
Security Manager for Exam Shield
Handles input blocking and security restrictions
"""
import keyboard
import threading
import time
import psutil
from config import Config
from mouse_manager import MouseManager
from network_manager import NetworkManager
from window_manager import WindowManager

class SecurityManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.is_exam_mode = False
        self.blocked_keys = Config.BLOCKED_KEYS.copy()
        self.monitoring_thread = None
        self.hooks_active = False
        
        # NEW: Selective blocking flags
        self.selective_blocking = Config.SELECTIVE_BLOCKING.copy()
        
        self.mouse_manager = MouseManager(db_manager)
        self.network_manager = NetworkManager(db_manager)
        self.window_manager = WindowManager(db_manager)
        
        # NEW: Admin panel reference for hotkey access
        self.admin_panel = None
    
    def set_admin_panel(self, admin_panel):
        """Set reference to admin panel for hotkey access"""
        self.admin_panel = admin_panel
    
    def start_exam_mode(self, selective_options=None):
        """Start exam mode with optional selective blocking"""
        if self.is_exam_mode:
            return
            
        self.is_exam_mode = True
        
        # Update selective blocking if provided
        if selective_options:
            self.selective_blocking.update(selective_options)
        
        # Start components based on selective blocking
        if self.selective_blocking.get('keyboard', True):
            self.setup_keyboard_hooks()
            
        if self.selective_blocking.get('processes', True):
            self.start_process_monitoring()
            
        if self.selective_blocking.get('mouse', True):
            self.mouse_manager.start_blocking()
            
        if self.selective_blocking.get('internet', True) and Config.BLOCK_INTERNET:
            self.network_manager.start_blocking()
            
        if self.selective_blocking.get('windows', True):
            self.window_manager.start_window_protection()
        
        # Log with selective options
        active_blocks = [k for k, v in self.selective_blocking.items() if v]
        self.db_manager.log_activity("EXAM_MODE_START", f"Selective restrictions: {', '.join(active_blocks)}")
        print(f"🔒 Selective exam mode activated - Active: {', '.join(active_blocks)}")

    def stop_exam_mode(self):
        if not self.is_exam_mode:
            return
            
        self.is_exam_mode = False
        self.remove_keyboard_hooks()
        self.stop_process_monitoring()
        self.mouse_manager.stop_blocking()
        self.network_manager.stop_blocking()
        self.window_manager.stop_window_protection()
        
        self.db_manager.log_activity("EXAM_MODE_STOP", "All security restrictions deactivated")
        print("🔓 Full exam mode deactivated - All restrictions removed")

    def setup_keyboard_hooks(self):
        try:
            for key_combo in self.blocked_keys:
                keyboard.add_hotkey(key_combo, self.block_key_action, args=(key_combo,), suppress=True)
            
            # FIXED: Properly register admin access hotkey
            keyboard.add_hotkey(Config.ADMIN_ACCESS_KEY, self.admin_access_requested, suppress=False)
            
            self.hooks_active = True
            print("✅ Keyboard hooks activated")
        except Exception as e:
            print(f"❌ Error setting up keyboard hooks: {e}")

    def remove_keyboard_hooks(self):
        try:
            keyboard.unhook_all()
            self.hooks_active = False
            print("✅ Keyboard hooks removed")
        except Exception as e:
            print(f"❌ Error removing keyboard hooks: {e}")

    def block_key_action(self, key_combo):
        if self.is_exam_mode:
            self.db_manager.log_activity("BLOCKED_KEY_ATTEMPT", f"Attempted to use: {key_combo}", blocked=True)
            print(f"🚫 Blocked key combination: {key_combo}")

    def admin_access_requested(self):
        """FIXED: Properly handle admin access request"""
        print("🔑 Admin access requested via hotkey")
        self.db_manager.log_activity("ADMIN_ACCESS_REQUEST", "Admin hotkey pressed")
        
        # Show admin panel if available
        if self.admin_panel:
            try:
                self.admin_panel.show()
                print("✅ Admin panel shown")
            except Exception as e:
                print(f"❌ Error showing admin panel: {e}")

    def start_process_monitoring(self):
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            return
        self.monitoring_thread = threading.Thread(target=self._monitor_processes, daemon=True)
        self.monitoring_thread.start()

    def stop_process_monitoring(self):
        if self.monitoring_thread:
            self.monitoring_thread = None

    def _monitor_processes(self):
        suspicious_processes = ['taskmgr.exe', 'cmd.exe', 'powershell.exe', 'regedit.exe', 'msconfig.exe']
        while self.is_exam_mode and self.monitoring_thread:
            try:
                for process in psutil.process_iter(['pid', 'name']):
                    try:
                        if process.info['name'].lower() in suspicious_processes:
                            self.db_manager.log_activity("SUSPICIOUS_PROCESS", f"Detected: {process.info['name']}", blocked=True)
                            try:
                                process.terminate()
                                print(f"🚫 Terminated suspicious process: {process.info['name']}")
                            except:
                                pass
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                time.sleep(2)
            except Exception as e:
                print(f"Process monitoring error: {e}")
                time.sleep(5)

    def add_blocked_key(self, key_combo):
        if key_combo not in self.blocked_keys:
            self.blocked_keys.append(key_combo)
            if self.hooks_active:
                keyboard.add_hotkey(key_combo, self.block_key_action, args=(key_combo,), suppress=True)

    def remove_blocked_key(self, key_combo):
        if key_combo in self.blocked_keys:
            self.blocked_keys.remove(key_combo)

    def get_system_info(self):
        try:
            info = {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory_percent': psutil.virtual_memory().percent,
                'active_processes': len(psutil.pids()),
                'exam_mode': self.is_exam_mode,
                'hooks_active': self.hooks_active,
                'mouse_blocking': self.mouse_manager.is_active,
                'internet_blocked': self.network_manager.is_blocked,
                'window_protection': self.window_manager.is_active
            }
            return info
        except Exception as e:
            print(f"Error getting system info: {e}")
            return {}
