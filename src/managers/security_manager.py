"""
ExamShield v1.1.0 — Security Manager
Orchestrates all security subsystems (keyboard, mouse, network, windows,
processes, screenshots, timer, report generation).
"""
import keyboard
import threading
import psutil
from src.config import Config
from src.managers.mouse_manager import MouseManager
from src.managers.network_manager import NetworkManager
from src.managers.window_manager import WindowManager
from src.managers.usb_manager import USBManager
from src.managers.screenshot_manager import ScreenshotManager
from src.managers.report_manager import ReportManager
from src.managers.watchdog_manager import WatchdogManager
from src.managers.hardware_manager import HardwareManager
from src.managers.clipboard_manager import ClipboardManager
from src.logger import ExamShieldLogger


class SecurityManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.log = ExamShieldLogger(db_manager)
        self.is_exam_mode = False
        self.blocked_keys = Config.BLOCKED_KEYS.copy()
        self.hooks_active = False
        self.selective_blocking = Config.SELECTIVE_BLOCKING.copy()

        # Sub-managers
        self.mouse_manager      = MouseManager(db_manager)
        self.network_manager    = NetworkManager(db_manager)
        self.window_manager     = WindowManager(db_manager)
        self.usb_manager        = USBManager(db_manager)
        self.screenshot_manager = ScreenshotManager(db_manager)
        self.report_manager     = ReportManager(db_manager)
        self.watchdog_manager   = WatchdogManager(db_manager)
        self.hardware_manager   = HardwareManager(db_manager)
        self.clipboard_manager  = ClipboardManager(db_manager)

        # Thread control
        self._proc_stop   = threading.Event()
        self._proc_thread = None

        # Admin panel reference (set later)
        self.admin_panel  = None

        # ── Breach counter ─────────────────────────────────────────
        # Tracks blocked events since the last lockdown start
        self.breach_counts: dict[str, int] = {
            'keyboard': 0, 'network': 0,
            'processes': 0, 'usb': 0, 'windows': 0,
        }

        # ── Active session metadata ────────────────────────────────
        self._session_profile   = ""
        self._session_timer_min = 0

    def set_admin_panel(self, panel):
        self.admin_panel = panel

    # ── Exam Mode ────────────────────────────────────────────────
    def start_exam_mode(self, selective_options=None,
                        profile_name: str = "",
                        timer_minutes: int = 0):
        if self.is_exam_mode:
            return
        self.is_exam_mode = True

        # Reset breach counters
        self.breach_counts = {k: 0 for k in self.breach_counts}

        if selective_options:
            self.selective_blocking.update(selective_options)
            
        # Hardware Pre-flight checks
        sel = self.selective_blocking
        success, err_msg = self.hardware_manager.run_preflight_checks(
            block_multi_monitor=sel.get('multi_monitor', True),
            detect_vm_rdp=sel.get('vm_rdp', True)
        )
        if not success:
            self.log.security("PREFLIGHT_FAIL", err_msg, blocked=True)
            raise RuntimeError(err_msg)

        # Store session metadata for the report
        self._session_profile   = profile_name
        self._session_timer_min = timer_minutes

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
            if self.admin_panel and hasattr(self.admin_panel, 'window'):
                self.window_manager.register_protected_window(
                    self.admin_panel.window, "Admin Panel"
                )
            self.window_manager.start_window_protection()
        if sel.get('clipboard', True):
            self.clipboard_manager.start()

        # Screenshot monitoring (always during lockdown)
        self.screenshot_manager.start(session_label=profile_name or "exam")

        # Notify report manager
        active = [k for k, v in sel.items() if v]
        self.report_manager.begin_session(
            modules=active,
            profile_name=profile_name,
            timer_minutes=timer_minutes,
        )

        # Launch watchdog (must be last — it protects everything above)
        self.watchdog_manager.start()

        self.log.info("EXAM_MODE_START",
                      f"Active modules: {', '.join(active)}"
                      + (f" | Profile: {profile_name}" if profile_name else "")
                      + (f" | Timer: {timer_minutes}m" if timer_minutes else ""))

    def stop_exam_mode(self) -> str:
        """
        Stop all security modules.
        Returns the path to the generated session report file.
        """
        if not self.is_exam_mode:
            return ""
        self.is_exam_mode = False

        self._remove_keyboard_hooks()
        self._stop_process_monitor()
        self.mouse_manager.stop_blocking()
        self.network_manager.stop_blocking()
        self.usb_manager.stop_blocking()
        self.window_manager.stop_window_protection()
        self.clipboard_manager.stop()

        # Stop watchdog FIRST so it doesn't fight clean-up
        self.watchdog_manager.stop()

        # Generate session report
        report_path = self.report_manager.end_session(
            breach_counts=dict(self.breach_counts),
            screenshots_taken=self.screenshot_manager.get_count(),
            screenshot_dir=self.screenshot_manager.get_session_dir(),
        )

        # Stop screenshot capture
        self.screenshot_manager.stop()

        # Reset selective_blocking so next session starts fresh
        self.selective_blocking = Config.SELECTIVE_BLOCKING.copy()

        self.log.info("EXAM_MODE_STOP",
                      f"All restrictions removed | Report: {report_path}")
        return report_path

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
            self.breach_counts['keyboard'] += 1
            self.log.security("BLOCKED_KEY", f"Blocked: {combo}", blocked=True)
            # Screenshot on violation
            self.screenshot_manager.capture_violation(
                reason=f"key_{combo.replace('+', '-')}"
            )
            # Notify dashboard counter + real-time toast
            if self.admin_panel and hasattr(self.admin_panel, 'window'):
                try:
                    self.admin_panel.window.after(
                        0, self.admin_panel.update_breach_counter
                    )
                    self.admin_panel.window.after(
                        0, lambda c=combo: self.admin_panel._toast(
                            f"\u2328\ufe0f  Blocked key: {c}", '#ff4757'
                        ) if hasattr(self.admin_panel, '_toast') else None
                    )
                except Exception:
                    pass

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
        targets  = Config.SUSPICIOUS_PROCESSES
        interval = Config.PROCESS_MONITOR_INTERVAL
        while self.is_exam_mode and not self._proc_stop.is_set():
            try:
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        name = proc.info['name'].lower()
                        if name in targets:
                            self.breach_counts['processes'] += 1
                            self.log.security("SUSPICIOUS_PROCESS",
                                              f"Terminated: {name}", blocked=True)
                            proc.terminate()
                            self.screenshot_manager.capture_violation(
                                reason=f"proc_{name}"
                            )
                            # Real-time breach toast
                            if self.admin_panel and hasattr(self.admin_panel, '_toast'):
                                try:
                                    self.admin_panel.window.after(
                                        0, lambda n=name: self.admin_panel._toast(
                                            f"🔍  Terminated process: {n}",
                                            '#ff4757'
                                        )
                                    )
                                    self.admin_panel.window.after(
                                        0, self.admin_panel.update_breach_counter
                                    )
                                except Exception:
                                    pass
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
                'cpu_percent':      psutil.cpu_percent(interval=0.5),
                'memory_percent':   psutil.virtual_memory().percent,
                'active_processes': len(psutil.pids()),
                'exam_mode':        self.is_exam_mode,
                'hooks_active':     self.hooks_active,
                'mouse_blocking':   self.mouse_manager.is_active,
                'internet_blocked': self.network_manager.is_blocked,
                'usb_blocking':     self.usb_manager.is_active,
                'window_protection':self.window_manager.is_active,
                'clipboard_blocked':self.clipboard_manager.is_active,
                'vm_rdp_detected':  self.hardware_manager.is_virtual_machine() or self.hardware_manager.is_rdp_session(),
                'multi_monitor':    self.hardware_manager.has_multiple_monitors(),
                'breach_counts':    dict(self.breach_counts),
                'screenshots_taken':self.screenshot_manager.get_count(),
            }
        except Exception:
            return {}
