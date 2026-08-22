"""
ExamShield — Watchdog Worker
Standalone script launched as a child process by WatchdogManager during
exam lockdown. Monitors the parent PID and:
  1. Validates HMAC signature of the flag file on every cycle.
  2. Re-applies USBSTOR registry + service block every 3 s.
  3. Kills escape-tools if the parent dies unexpectedly.

Usage (internal):
    python src/watchdog_worker.py <parent_pid> <flag_file> <secret_hex>

  flag_file  – path to a file that exists while lockdown is active.
               WatchdogManager deletes it on clean stop, which signals
               this worker to exit gracefully.
  secret_hex – HMAC-SHA256 secret used to validate the flag file token.
               If the token doesn't match, the flag file has been spoofed.
"""
import sys
import os
import time
import hmac
import hashlib
import subprocess
import winreg

# ── Args ─────────────────────────────────────────────────────────
if len(sys.argv) < 4:
    sys.exit(0)

PARENT_PID  = int(sys.argv[1])
FLAG_FILE   = sys.argv[2]
SECRET_HEX  = sys.argv[3]

try:
    SECRET_KEY = bytes.fromhex(SECRET_HEX)
except Exception:
    sys.exit(1)

# Expanded list — mirrors Config.SUSPICIOUS_PROCESSES
KILL_TARGETS = [
    'taskmgr.exe', 'cmd.exe', 'powershell.exe', 'pwsh.exe',
    'regedit.exe', 'procexp.exe', 'procexp64.exe', 'procmon.exe',
    'procmon64.exe', 'autoruns.exe', 'x32dbg.exe', 'x64dbg.exe',
    'wireshark.exe', 'fiddler.exe', 'teamviewer.exe', 'anydesk.exe',
    'discord.exe', 'zoom.exe', 'teams.exe', 'skype.exe',
    'openvpn.exe', 'nordvpn.exe', 'expressvpn.exe',
    'autohotkey.exe', 'ahk.exe', 'rustdesk.exe',
]

# ── HMAC validation ───────────────────────────────────────────────
def _expected_token() -> str:
    """Return the HMAC-SHA256 hex digest of the flag file path."""
    return hmac.new(SECRET_KEY, FLAG_FILE.encode('utf-8'), hashlib.sha256).hexdigest()

def _flag_valid() -> bool:
    """
    Returns True if:
      1. The flag file exists.
      2. Its content matches the expected HMAC token (proves it wasn't spoofed).
    """
    if not os.path.isfile(FLAG_FILE):
        return False
    try:
        with open(FLAG_FILE, 'r') as f:
            token = f.read().strip()
        expected = _expected_token()
        return hmac.compare_digest(token, expected)
    except Exception:
        return False

# ── Helpers ──────────────────────────────────────────────────────
def _parent_alive() -> bool:
    try:
        import ctypes
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, PARENT_PID)
        if not handle:
            return False
        ret = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
        ctypes.windll.kernel32.CloseHandle(handle)
        return ret != 0   # 0 = WAIT_OBJECT_0 means process has exited
    except Exception:
        return False

def _apply_usb_block():
    """Re-apply both registry WriteProtect and service-disable for USBSTOR."""
    # Registry WriteProtect
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\StorageDevicePolicies",
            0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
        )
        val, _ = winreg.QueryValueEx(key, "WriteProtect")
        if val != 1:
            winreg.SetValueEx(key, "WriteProtect", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
    except Exception:
        try:
            key = winreg.CreateKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\StorageDevicePolicies"
            )
            winreg.SetValueEx(key, "WriteProtect", 0, winreg.REG_DWORD, 1)
            winreg.CloseKey(key)
        except Exception:
            pass

    # USBSTOR Start registry key (4 = disabled)
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\USBSTOR",
            0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
        )
        val, _ = winreg.QueryValueEx(key, "Start")
        if val != 4:
            winreg.SetValueEx(key, "Start", 0, winreg.REG_DWORD, 4)
        winreg.CloseKey(key)
    except Exception:
        pass

def _kill_escape_tools():
    """Kill known escape processes using taskkill (no psutil dependency)."""
    for name in KILL_TARGETS:
        try:
            subprocess.run(
                ['taskkill', '/F', '/IM', name],
                capture_output=True, timeout=3
            )
        except Exception:
            pass

# ── Main loop ────────────────────────────────────────────────────
def main():
    check_interval = 2.5   # seconds between each pass

    while True:
        time.sleep(check_interval)

        flag_ok   = _flag_valid()
        parent_ok = _parent_alive()

        # Clean stop: flag file removed OR HMAC invalid (spoofed) — exit gracefully
        if not flag_ok:
            sys.exit(0)

        # Re-apply USB block every cycle
        _apply_usb_block()

        # Parent died unexpectedly during lockdown
        if not parent_ok:
            # Emergency: kill escape tools since keyboard hooks are gone
            _kill_escape_tools()
            # Wait a moment and check again — parent might respawn
            time.sleep(10)
            if not _parent_alive():
                # Still dead — clean up flag and exit
                try:
                    os.remove(FLAG_FILE)
                except Exception:
                    pass
                sys.exit(0)

if __name__ == '__main__':
    main()
