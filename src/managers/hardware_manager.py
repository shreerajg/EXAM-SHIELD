import ctypes
import platform
import subprocess
import os
from src.logger import ExamShieldLogger

class HardwareManager:
    """
    Manages detection of Virtual Machines, RDP sessions, and multi-monitor setups.
    """
    
    def __init__(self, db_manager):
        self.db = db_manager
        self.log = ExamShieldLogger(db_manager)  # fixed: was db_manager.logger (no such attr)
        self.blackout_windows = []
        
        # Cache static properties so we don't spawn wmic on every UI refresh
        self._cached_is_vm = self._detect_virtual_machine()
        self._cached_is_rdp = self._detect_rdp_session()
    
    def has_multiple_monitors(self) -> bool:
        """Returns True if more than one display monitor is detected."""
        try:
            # SM_CMONITORS = 80
            count = ctypes.windll.user32.GetSystemMetrics(80)
            return count > 1
        except Exception as e:
            self.log.error("HARDWARE", f"Multi-monitor check failed: {e}")
            return False

    def is_rdp_session(self) -> bool:
        """Returns True if the current session is an RDP (Remote Desktop) session."""
        return self._cached_is_rdp

    def _detect_rdp_session(self) -> bool:
        try:
            # SM_REMOTESESSION = 0x1000
            is_rdp = ctypes.windll.user32.GetSystemMetrics(0x1000)
            return bool(is_rdp)
        except Exception as e:
            self.log.error("HARDWARE", f"RDP check failed: {e}")
            return False

    def is_virtual_machine(self) -> bool:
        """
        Attempts to detect if the OS is running inside a known Virtual Machine
        (VirtualBox, VMware, QEMU/KVM, Hyper-V).
        """
        return self._cached_is_vm

    def _detect_virtual_machine(self) -> bool:
        vm_indicators = [
            'virtualbox', 'vbox',
            'vmware',
            'qemu', 'kvm',
            'hyper-v'
        ]
        
        # 1. Check System BIOS version & Video BIOS via registry
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System")
            bios_ver, _ = winreg.QueryValueEx(key, "SystemBiosVersion")
            video_bios, _ = winreg.QueryValueEx(key, "VideoBiosVersion")
            winreg.CloseKey(key)
            
            combined = str(bios_ver).lower() + " " + str(video_bios).lower()
            for indicator in vm_indicators:
                if indicator in combined:
                    self.log.warning("HARDWARE", f"VM detected via BIOS: {indicator}")
                    return True
        except Exception:
            pass

        # 2. Check for known VM drivers/services
        try:
            vm_drivers = ['vboxguest.sys', 'vboxmouse.sys', 'vmtoolsd.exe', 'vmmouse.sys', 'vm3dgl.dll']
            sys32 = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32')
            drivers_path = os.path.join(sys32, 'drivers')
            for d in vm_drivers:
                if os.path.exists(os.path.join(drivers_path, d)) or os.path.exists(os.path.join(sys32, d)):
                    self.log.warning("HARDWARE", f"VM detected via drivers: {d}")
                    return True
        except Exception:
            pass

        # 3. Check MAC Address OUIs
        try:
            import uuid
            mac = uuid.getnode()
            mac_hex = f'{mac:012x}'.lower()
            vm_mac_prefixes = [
                '080027', # VirtualBox
                '000569', '000c29', '001c14', '005056', # VMware
                '00155d', # Hyper-V
                '525400', # QEMU/KVM
            ]
            for prefix in vm_mac_prefixes:
                if mac_hex.startswith(prefix):
                    self.log.warning("HARDWARE", f"VM detected via MAC OUI: {prefix}")
                    return True
        except Exception:
            pass
        
        # 4. Fallback to PowerShell Get-CimInstance (Checks Hypervisor Bit + Model)
        try:
            output = subprocess.check_output(
                ["powershell.exe", "-Command", "Get-CimInstance Win32_ComputerSystem | Select-Object Model, HypervisorPresent | ConvertTo-Json"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=5
            ).decode('utf-8', errors='ignore')
            
            import json
            data = json.loads(output)
            
            # Check CPU Hypervisor Bit
            if data.get("HypervisorPresent") is True:
                self.log.warning("HARDWARE", "VM detected via CPU Hypervisor bit")
                return True
                
            # Check System Model
            model = str(data.get("Model", "")).lower()
            for indicator in vm_indicators:
                if indicator in model:
                    self.log.warning("HARDWARE", f"VM detected via System Model: {indicator}")
                    return True
        except Exception:
            pass

        return False
        
    def blackout_secondary_monitors(self, tk_root):
        """Spawns black fullscreen windows on all secondary monitors."""
        self.clear_blackouts()
        if not self.has_multiple_monitors():
            return
            
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            
            monitors = []
            MonitorEnumProc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_double)
            
            def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
                r = lprcMonitor.contents
                monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
                return 1
                
            user32.EnumDisplayMonitors(None, None, MonitorEnumProc(callback), 0)
            
            import tkinter as tk
            for (x, y, w, h) in monitors:
                # Primary monitor is typically at (0, 0)
                if x == 0 and y == 0:
                    continue
                    
                top = tk.Toplevel(tk_root)
                top.geometry(f"{w}x{h}+{x}+{y}")
                top.overrideredirect(True)
                top.configure(bg="black")
                top.attributes("-topmost", True)
                self.blackout_windows.append(top)
                
            self.log.info("HARDWARE", f"Blacked out {len(self.blackout_windows)} secondary monitors.")
        except Exception as e:
            self.log.error("HARDWARE", f"Failed to blackout monitors: {e}")
            
    def clear_blackouts(self):
        for w in self.blackout_windows:
            try:
                w.destroy()
            except Exception:
                pass
        self.blackout_windows.clear()

    def run_preflight_checks(self, block_multi_monitor=False, detect_vm_rdp=True) -> tuple[bool, str]:
        """
        Runs hardware checks. Returns (success, error_message).
        If success is False, the exam mode should be aborted.
        """
        if detect_vm_rdp:
            if self.is_rdp_session():
                return False, "Remote Desktop (RDP) session detected. Disconnect to continue."
            if self.is_virtual_machine():
                return False, "Virtual Machine detected. Exam must be taken on a physical host."
                
        if block_multi_monitor:
            if self.has_multiple_monitors():
                return False, "Multiple monitors detected. Please disconnect extra displays."
                
        return True, "Checks passed"
