import ctypes
import platform
import subprocess
import os

class HardwareManager:
    """
    Manages detection of Virtual Machines, RDP sessions, and multi-monitor setups.
    """
    
    def __init__(self, db_manager):
        self.db = db_manager
        self.log = db_manager.logger
    
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
        vm_indicators = [
            'virtualbox', 'vbox',
            'vmware',
            'qemu', 'kvm',
            'hyper-v'
        ]
        
        # Check System BIOS version & Video BIOS via registry
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
        
        # Fallback to WMI if available (slow but accurate)
        try:
            output = subprocess.check_output(
                ["wmic", "computersystem", "get", "model"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=3
            ).decode('utf-8', errors='ignore').lower()
            
            for indicator in vm_indicators:
                if indicator in output:
                    self.log.warning("HARDWARE", f"VM detected via WMIC: {indicator}")
                    return True
        except Exception:
            pass

        return False

    def run_preflight_checks(self, block_multi_monitor=True, detect_vm_rdp=True) -> tuple[bool, str]:
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
