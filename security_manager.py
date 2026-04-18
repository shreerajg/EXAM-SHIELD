"""
ExamShield v1.0 — Security Manager
Orchestrates all security subsystems (keyboard, mouse, network, windows, processes).
"""
import keyboard
import threading
import psutil
from config import Config
from mouse_manager import MouseManager
from network_manager import NetworkManager
from window_manager import WindowManager
from usb_manager import USBManager
from logger import ExamShieldLogger


class SecurityManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.log = ExamShieldLogger(db_manager)
        self.is_exam_mode = False
        self.blocked_keys = Config.BLOCKED_KEYS.copy()
        self.hooks_active = False
        self.selective_blocking = Config.SELECTIVE_BLOCKING.copy()

        # Sub-managers
        self.mouse_manager = MouseManager(db_manager)
        self.network_manager = NetworkManager(db_manager)
        self.window_manager = WindowManager(db_manager)
        self.usb_manager = USBManager(db_manager)

        # Thread control
        self._proc_stop = threading.Event()
        self._proc_thread = None

        # Admin panel reference (set later)
        self.admin_panel = None

    def set_admin_panel(self, panel):
        self.admin_panel = panel

    # ── Exam Mode ────────────────────────────────────────────────
    def start_exam_mode(self, selective_options=None):
        if self.is_exam_mode:
            return
        self.is_exam_mode = True

        if selective_options:
            self.selective_blocking.update(selective_options)

        sel = self.selective_blocking
        if sel.get('keyboard', True):
            self._setup_keyboard_hooks()
        if sel.get('processes', True):
            self._start_process_monitor()
        if sel.get('mouse', True):
            self.mouse_manager.start_blocking()
        if sel.get('internet', True) and Config.BLOCK_INTERNET:
            self.network_manager.start_blocking()
        if sel.get('usb', True):
            self.usb_manager.start_blocking()
        if sel.get('windows', True):
            # Register the admin panel window BEFORE starting so it gets
            # protected immediately when protection activates
            if self.admin_panel and hasattr(self.admin_panel, 'window'):
                self.window_manager.register_protected_window(
                    self.admin_panel.window, "Admin Panel"
                )
            self.window_manager.start_window_protection()

        active = [k for k, v in sel.items() if v]
        self.log.info("EXAM_MODE_START",
                       f"Active modules: {', '.join(active)}")

    def stop_exam_mode(self):
        if not self.is_exam_mode:
            return
        self.is_exam_mode = False

        self._remove_keyboard_hooks()
        self._stop_process_monitor()
        self.mouse_manager.stop_blocking()
        self.network_manager.stop_blocking()
        self.usb_manager.stop_blocking()
        self.window_manager.stop_window_protection()

        # Reset selective_blocking so next session starts fresh
        self.selective_blocking = Config.SELECTIVE_BLOCKING.copy()

        self.log.info("EXAM_MODE_STOP", "All restrictions removed")

    # ── Keyboard ─────────────────────────────────────────────────
    def _setup_keyboard_hooks(self):
        try:
            for combo in self.blocked_keys:
                keyboard.add_hotkey(combo, self._on_blocked_key,
                                    args=(combo,), suppress=True)
            keyboard.add_hotkey(Config.ADMIN_ACCESS_KEY,
                                self._on_admin_hotkey, suppress=False)
            self.hooks_active = True
            self.log.info("KEYBOARD_HOOKS", "Hooks activated")
        except Exception as e:
            self.log.error("KEYBOARD_HOOKS", f"Setup failed: {e}")

    def _remove_keyboard_hooks(self):
        try:
            keyboard.unhook_all()
            self.hooks_active = False
            self.log.info("KEYBOARD_HOOKS", "Hooks removed")
        except Exception as e:
            self.log.error("KEYBOARD_HOOKS", f"Removal failed: {e}")

    def _on_blocked_key(self, combo):
        if self.is_exam_mode:
            self.log.security("BLOCKED_KEY", f"Blocked: {combo}", blocked=True)

    def _on_admin_hotkey(self):
        self.log.info("ADMIN_HOTKEY", "Admin access requested via hotkey")
        if self.admin_panel:
            try:
                self.admin_panel.show()
            except Exception as e:
                self.log.error("ADMIN_HOTKEY", f"Show failed: {e}")

    # ── Process Monitoring ───────────────────────────────────────
    def _start_process_monitor(self):
        if self._proc_thread and self._proc_thread.is_alive():
            return
        self._proc_stop.clear()
        self._proc_thread = threading.Thread(
            target=self._process_monitor_loop, daemon=True
        )
        self._proc_thread.start()

    def _stop_process_monitor(self):
        self._proc_stop.set()
        self._proc_thread = None

    def _process_monitor_loop(self):
        targets = Config.SUSPICIOUS_PROCESSES
        interval = Config.PROCESS_MONITOR_INTERVAL
        while self.is_exam_mode and not self._proc_stop.is_set():
            try:
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        name = proc.info['name'].lower()
                        if name in targets:
                            self.log.security("SUSPICIOUS_PROCESS",
                                              f"Terminated: {name}", blocked=True)
                            proc.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception as e:
                self.log.error("PROC_MONITOR", f"Error: {e}", db=False)
            self._proc_stop.wait(interval)

    # ── Key list management ──────────────────────────────────────
    def add_blocked_key(self, combo):
        if combo not in self.blocked_keys:
            self.blocked_keys.append(combo)
            if self.hooks_active:
                keyboard.add_hotkey(combo, self._on_blocked_key,
                                    args=(combo,), suppress=True)

    def remove_blocked_key(self, combo):
        if combo in self.blocked_keys:
            self.blocked_keys.remove(combo)

    # ── System Info (for dashboard) ──────────────────────────────
    def get_system_info(self):
        try:
            return {
                'cpu_percent': psutil.cpu_percent(interval=0.5),
                'memory_percent': psutil.virtual_memory().percent,
                'active_processes': len(psutil.pids()),
                'exam_mode': self.is_exam_mode,
                'hooks_active': self.hooks_active,
                'mouse_blocking': self.mouse_manager.is_active,
                'internet_blocked': self.network_manager.is_blocked,
                'usb_blocking': self.usb_manager.is_active,
                'window_protection': self.window_manager.is_active,
            }
        except Exception:
            return {}
