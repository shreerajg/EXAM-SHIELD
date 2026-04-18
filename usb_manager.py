"""
ExamShield v1.0 — USB Manager
Blocks USB mass storage devices by disabling them via Windows registry/APIs.
"""
import ctypes
import ctypes.wintypes as wintypes
import threading
import time
import subprocess
from logger import ExamShieldLogger
from config import Config

GUID_DEVINTERFACE_VOLUME = "{53f5630d-b6bf-11d0-94f8-00aa00395901}"
GUID_DEVINTERFACE_DISK = "{53f56307-b6bf-11d0-94f8-00aa00395901}"

DBT_DEVICETYPENAME = 0x00000007
DBT_DEVTYP_VOLUME = 0x00000008
DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004

WM_DEVICECHANGE = 0x0219

DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010

class USBManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.log = ExamShieldLogger(db_manager)
        self.is_active = False
        self.blocked_devices = set()
        self._lock = threading.Lock()
        self._monitor_thread = None
        self._stop_evt = threading.Event()
        self._window = None
        self._orig_device_state = {}

    def start_blocking(self):
        with self._lock:
            if self.is_active:
                return
            self.is_active = True
        
        self._stop_evt.clear()
        self._enumerate_usb_devices()
        
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="USBMonitor"
        )
        self._monitor_thread.start()
        
        self._block_all_usb_storage()
        self.log.info("USB_BLOCKING_START", "USB storage devices blocked")

    def stop_blocking(self):
        with self._lock:
            if not self.is_active:
                return
            self.is_active = False
        
        self._stop_evt.set()
        self._unblock_all_usb_storage()
        self.log.info("USB_BLOCKING_STOP", "USB storage devices unblocked")

    def _enumerate_usb_devices(self):
        try:
            result = subprocess.run(
                ['wmic', 'diskdrive', 'get', 'DeviceID,MediaType', '/format:csv'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split('\n')[2:]:
                if line.strip() and 'USB' in line.upper():
                    parts = line.split(',')
                    if len(parts) >= 2 and parts[1]:
                        device_id = parts[1].strip()
                        if device_id not in self._orig_device_state:
                            self._orig_device_state[device_id] = 'enabled'
        except Exception as e:
            self.log.error("USB_ENUM", f"Failed: {e}")

    def _block_all_usb_storage(self):
        self._run_usb_command('disable')

    def _unblock_all_usb_storage(self):
        self._run_usb_command('enable')

    def _run_usb_command(self, action):
        try:
            ps_script = f'''
$devices = Get-PnpDevice -Class USB -Status OK | Where-Object {{$_.FriendlyName -match "USB|Mass|Storage"}}
foreach ($dev in $devices) {{
    if ("{action}" -eq "disable") {{
        Set-PnpDevice -InstanceName $dev.InstanceName -Confirm:$false -ErrorAction SilentlyContinue
    }}
}}
'''
            subprocess.run(
                ['powershell', '-Command', ps_script],
                capture_output=True, timeout=10
            )
            
            subprocess.run(
                ['diskpart', '/s', f'C:\\\\temp_usb_{action}.txt'],
                capture_output=True, timeout=5
            )
        except Exception:
            pass
    
    def _monitor_loop(self):
        try:
            wc = ctypes.windll.user32.WNDCLASSW()
            wc.lpfnWndProc = self._wnd_proc
            wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
            wc.lpszClassName = "USBMonitorClass"
            ctypes.windll.user32.RegisterClassW(ctypes.byref(wc))
            
            self._window = ctypes.windll.user32.CreateWindowExW(
                0, "USBMonitorClass", "USB Monitor", 0, 0, 0, 0, 0,
                None, wc.hInstance, None
            )
            
            msg = wintypes.MSG()
            while not self._stop_evt.is_set():
                ret = ctypes.windll.user32.PeekMessageW(
                    ctypes.byref(msg), self._window, 0, 0, 1
                )
                if ret:
                    ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                    ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    self._stop_evt.wait(0.05)
            
            if self._window:
                ctypes.windll.user32.DestroyWindow(self._window)
        except Exception as e:
            pass

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DEVICECHANGE:
            if wparam == DBT_DEVICEARRIVAL:
                if self.is_active:
                    self.log.security("USB_BLOCKED", 
                        "USB device insertion blocked", blocked=True)
                    self._block_all_usb_storage()
            elif wparam == DBT_DEVICEREMOVECOMPLETE:
                pass
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def get_status(self) -> dict:
        return {
            'active': self.is_active,
            'blocked_count': len(self.blocked_devices),
        }