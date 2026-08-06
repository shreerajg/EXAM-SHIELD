"""
ExamShield — Watchdog Worker
Standalone script launched as a child process by WatchdogManager during
exam lockdown. Monitors the parent PID and:
  1. Re-applies USBSTOR registry block every 3 s.
  2. Kills escape-tools if the parent dies unexpectedly.

Usage (internal): python src/watchdog_worker.py <parent_pid> <flag_file>
  flag_file  – path to a file that exists while lockdown is active.
               WatchdogManager deletes it on clean stop, which signals
               this worker to exit gracefully.
"""
import sys
import os
import time
import subprocess
import winreg

# ── Args ─────────────────────────────────────────────────────────
if len(sys.argv) < 3:
    sys.exit(0)

PARENT_PID  = int(sys.argv[1])
FLAG_FILE   = sys.argv[2]

# Processes to kill if parent dies mid-exam
KILL_TARGETS = [
    'taskmgr.exe', 'cmd.exe', 'powershell.exe', 'pwsh.exe',
    'regedit.exe', 'procexp.exe', 'procexp64.exe', 'procmon.exe',
]

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

def _flag_active() -> bool:
    return os.path.isfile(FLAG_FILE)

def _apply_usb_block():
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

        parent_ok = _parent_alive()
        flag_ok   = _flag_active()

        # Clean stop: flag file removed by WatchdogManager
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
