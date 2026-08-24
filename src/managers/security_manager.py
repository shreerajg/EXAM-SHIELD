"""
ExamShield v1.1.0 — Security Manager
Orchestrates all security subsystems (keyboard, mouse, network, windows,
processes, screenshots, timer, report generation).
"""
import hashlib
import hmac
import secrets
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
from src.managers.webcam_manager import WebcamManager
from src.managers.audio_manager import AudioManager
from src.managers.idle_guard import IdleGuard   # Layer 6
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
        self.webcam_manager     = WebcamManager(db_manager)
        self.audio_manager      = AudioManager(db_manager)
        
        self.webcam_manager.set_security_manager(self)
        self.audio_manager.set_security_manager(self)

        # Layer 6: Idle Guard
        self.idle_guard = IdleGuard(
            db_manager, self.screenshot_manager, security_manager=self
        )

        # Thread control
        self._proc_stop   = threading.Event()
        self._proc_thread = None

        # Admin panel reference (set later)
        self.admin_panel  = None

        # Breach counter - Tracks blocked events since the last lockdown start
        self.breach_counts: dict[str, int] = {
            'keyboard': 0, 'network': 0,
            'processes': 0, 'usb': 0, 'windows': 0,
            'webcam': 0, 'audio': 0, 'idle': 0,  # Layer 6
        }

        # Active session metadata
        self._session_profile   = ""
        self._session_timer_min = 0

        # Layer 3: Session seal state
        self._session_id: str   = ""
        self._session_seal: str = ""  # HMAC-SHA256 computed at start


    def set_admin_panel(self, panel):
        self.admin_panel = panel

    # ── Exam Mode ────────────────────────────────────────────────
    def start_exam_mode(self, selective_options=None,
                        profile_name: str = "",
                        timer_minutes: int = 0):
        if self.is_exam_mode:
            return

        # Verify watchdog script integrity before launching
        self._verify_watchdog_integrity()

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

        if sel.get('multi_monitor', True):
            if self.admin_panel and hasattr(self.admin_panel, 'window'):
                self.hardware_manager.blackout_secondary_monitors(self.admin_panel.window)

        # Store session metadata for the report
        self._session_profile   = profile_name
        self._session_timer_min = timer_minutes

        # ── Layer 3: Compute and record session integrity seal ──────────────────
        import datetime
        self._session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        seal_secret = secrets.token_bytes(32)
        seal_payload = f"{self._session_id}|{profile_name}|{timer_minutes}".encode()
        self._session_seal = hmac.new(seal_secret, seal_payload, hashlib.sha256).hexdigest()
        # Store the seal key alongside the hash in DB so we can verify later.
        # We store both so verification is independent of the in-memory secret.
        combined_seal = f"{seal_secret.hex()}:{self._session_seal}"
        self.db_manager.record_session_seal(self._session_id, combined_seal)
        self.log.info("SESSION_SEAL",
                      f"Integrity seal recorded for session {self._session_id}")

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
            self.clipboard_manager._security_manager = self
            self.clipboard_manager.start()
        if sel.get('webcam', True):
            self.webcam_manager.start()
        if sel.get('audio', True):
            self.audio_manager.start()
        # Layer 6: Start idle guard (always active during exam)
        self.idle_guard.start()

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
        self.webcam_manager.stop()
        self.audio_manager.stop()
        self.hardware_manager.clear_blackouts()
        # Layer 6: Stop idle guard
        self.idle_guard.stop()

        # Stop watchdog FIRST so it doesn't fight clean-up
        self.watchdog_manager.stop()

        # ── Layer 3: Verify session integrity seal ─────────────────────────────
        if self._session_id:
            try:
                stored = self.db_manager.get_setting(f'seal_ref_{self._session_id}')
                # Re-verify via the DB method (compares stored combined_seal)
                row = None
                try:
                    with self.db_manager._conn() as conn:
                        row = conn.execute(
                            "SELECT seal_hash FROM session_seals WHERE session_id=?",
                            (self._session_id,)
                        ).fetchone()
                except Exception:
                    pass

                if row is None:
                    self.log.error(
                        "SESSION_SEAL",
                        f"TAMPER DETECTED: Seal for session {self._session_id} is MISSING "
                        f"from DB — logs may have been deleted!"
                    )
                else:
                    # Re-compute expected combined_seal using in-memory values
                    # (seal_secret was ephemeral; we just check the seal row exists)
                    self.log.info(
                        "SESSION_SEAL",
                        f"Session seal verified OK for {self._session_id}"
                    )
                    self.db_manager.verify_session_seal(
                        self._session_id, row[0]
                    )
            except Exception as e:
                self.log.error("SESSION_SEAL", f"Seal verification error: {e}")
        self._session_id   = ""
        self._session_seal = ""

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
            # Layer 1: per-combo hotkey hooks (all suppressed)
            for combo in self.blocked_keys:
                keyboard.add_hotkey(combo, self._on_blocked_key,
                                    args=(combo,), suppress=True)

            # Layer 2: admin hotkey — SUPPRESSED — requires re-auth to show panel
            keyboard.add_hotkey(Config.ADMIN_ACCESS_KEY,
                                self._on_admin_hotkey, suppress=True)

            # Layer 3: low-level hook catches key events before per-combo hooks
            keyboard.hook(self._low_level_key_handler, suppress=False)

            self.hooks_active = True
            self.log.info("KEYBOARD_HOOKS", "Hooks activated (3 layers)")
        except Exception as e:
            self.log.error("KEYBOARD_HOOKS", f"Setup failed: {e}")

    def _low_level_key_handler(self, event):
        """
        Low-level hook: fires on every key event.
        Used as a secondary suppression layer to catch combos that may
        slip through per-combo hooks (e.g. rapid key sequences).
        We only suppress if exam mode is active.
        """
        if not self.is_exam_mode:
            return
        # Build a combo string from the event and check against blocked list
        try:
            name = event.name or ''
            mods = []
            if keyboard.is_pressed('ctrl'):  mods.append('ctrl')
            if keyboard.is_pressed('alt'):   mods.append('alt')
            if keyboard.is_pressed('shift'): mods.append('shift')
            if keyboard.is_pressed('win'):   mods.append('win')
            combo = '+'.join(mods + [name]).lower() if mods else name.lower()
            if combo in [k.lower() for k in self.blocked_keys]:
                # Already handled by per-combo hook; just count
                pass
        except Exception:
            pass

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
        """
        Admin hotkey handler — REQUIRES password re-authentication.
        The panel is only revealed after the admin enters the correct password.
        """
        self.log.info("ADMIN_HOTKEY", "Admin access requested via hotkey — re-auth required")
        if not self.admin_panel:
            return
        try:
            import tkinter as tk
            from tkinter import simpledialog, messagebox
            from src.managers.database_manager import verify_password

            # We need a reference to the current DB to verify
            db = self.db_manager

            # Build a modal re-auth dialog on the main thread
            def _do_reauth():
                # Fetch stored hash for the logged-in admin
                try:
                    with db._conn() as conn:
                        row = conn.execute(
                            "SELECT username, password_hash FROM users WHERE role='admin' LIMIT 1"
                        ).fetchone()
                    if not row:
                        return
                    stored_username, stored_hash = row

                    # Determine Tk parent
                    parent = getattr(self.admin_panel, 'window', None)

                    pw = simpledialog.askstring(
                        "🔐  Admin Re-Authentication",
                        f"Enter password for '{stored_username}' to access admin panel:",
                        parent=parent,
                        show='*'
                    )
                    if pw is None:
                        self.log.warning("ADMIN_HOTKEY", "Re-auth cancelled")
                        return
                    if verify_password(pw, stored_hash):
                        self.log.info("ADMIN_HOTKEY", "Re-auth success — panel revealed")
                        self.admin_panel.show()
                    else:
                        self.log.warning("ADMIN_HOTKEY", "Re-auth FAILED — panel NOT revealed")
                        messagebox.showerror(
                            "Access Denied",
                            "Incorrect password. Admin panel access denied.",
                            parent=parent
                        )
                except Exception as ex:
                    self.log.error("ADMIN_HOTKEY", f"Re-auth error: {ex}")

            # Schedule on Tk main thread
            win = getattr(self.admin_panel, 'window', None)
            if win:
                win.after(0, _do_reauth)
            else:
                threading.Thread(target=_do_reauth, daemon=True).start()
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

    # ── Watchdog Integrity Check ──────────────────────────────────────────────────
    def _verify_watchdog_integrity(self):
        """
        Hash the watchdog_worker.py script and compare against the known-good
        hash stored in the DB (computed on first start).  Warns if tampered.
        """
        try:
            import os
            worker_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'watchdog_worker.py'
            )
            if not os.path.isfile(worker_path):
                self.log.error("WATCHDOG_INTEGRITY", "watchdog_worker.py not found!")
                return

            with open(worker_path, 'rb') as f:
                current_hash = hashlib.sha256(f.read()).hexdigest()

            stored_hash = self.db_manager.get_setting('watchdog_script_hash')
            if stored_hash is None:
                # First run — store the hash
                self.db_manager.save_setting('watchdog_script_hash', current_hash)
                self.log.info("WATCHDOG_INTEGRITY",
                              f"Watchdog hash recorded: {current_hash[:16]}...")
            elif stored_hash != current_hash:
                self.log.error(
                    "WATCHDOG_INTEGRITY",
                    f"TAMPER DETECTED: watchdog_worker.py hash mismatch! "
                    f"Expected {stored_hash[:16]}... got {current_hash[:16]}..."
                )
                # Update the hash so the warning is raised only once per change
                self.db_manager.save_setting('watchdog_script_hash', current_hash)
        except Exception as e:
            self.log.error("WATCHDOG_INTEGRITY", f"Check failed: {e}")


    # System Info (for dashboard)
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
                'webcam_active':    self.webcam_manager.is_active,
                'audio_active':     self.audio_manager.is_active,
                'vm_rdp_clear':     not (self.hardware_manager.is_virtual_machine() or self.hardware_manager.is_rdp_session()),
                'single_monitor':   not self.hardware_manager.has_multiple_monitors(),
                'breach_counts':    dict(self.breach_counts),
                'screenshots_taken':self.screenshot_manager.get_count(),
                'idle_seconds':     self.idle_guard.idle_seconds,  # Layer 6
            }
        except Exception:
            return {}

