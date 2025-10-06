"""
Network Manager for Exam Shield - ENHANCED VERSION
FIXED: Proper restoration of internet access after lockdown
"""

import os
import subprocess
import platform
import shutil
import socket
import threading
import time     
from datetime import datetime
from config import Config

class NetworkManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.is_blocked = False
        self.hosts_backup = None
        self.original_hosts_content = None  # FIXED: Store original content
        self.hosts_path = self._get_hosts_path()
        self.blocking_thread = None
        self.dns_servers_backup = None
        
    def _get_hosts_path(self):
        """Get the system hosts file path"""
        system = platform.system().lower()
        if system == "windows":
            return r"C:\Windows\System32\drivers\etc\hosts"
        elif system in ["linux", "darwin"]:
            return "/etc/hosts"
        else:
            return None

    def start_blocking(self):
        """ENHANCED: Start internet blocking with proper backup"""
        if self.is_blocked or not self.hosts_path:
            return

        try:
            # FIXED: Create proper backup of original hosts file
            self._backup_original_hosts()
            
            # Block via hosts file
            self._modify_hosts_file()
            
            # Additional DNS blocking
            self._block_dns()
            
            self.is_blocked = True
            self.blocking_thread = threading.Thread(target=self._continuous_blocking, daemon=True)
            self.blocking_thread.start()
            
            self.db_manager.log_activity("INTERNET_BLOCKING_START", "Aggressive internet blocking activated")
            print("🚫 Enhanced internet blocking activated")
            
        except Exception as e:
            print(f"❌ Error starting internet blocking: {e}")

    def stop_blocking(self):
        """FIXED: Properly restore internet access"""
        if not self.is_blocked:
            return
            
        try:
            self.is_blocked = False
            
            # FIXED: Restore original hosts file content
            self._restore_original_hosts()
            
            # Restore DNS settings
            self._restore_dns()
            
            # Flush DNS cache
            self._flush_dns_cache()
            
            self.db_manager.log_activity("INTERNET_BLOCKING_STOP", "Internet access fully restored")
            print("✅ Internet access fully restored")
            
        except Exception as e:
            print(f"❌ Error stopping internet blocking: {e}")

    def _backup_original_hosts(self):
        """FIXED: Create proper backup of original hosts file"""
        try:
            if os.path.exists(self.hosts_path):
                with open(self.hosts_path, 'r') as f:
                    self.original_hosts_content = f.read()
                
                # Also create physical backup file
                backup_path = self.hosts_path + ".exam_shield_backup"
                shutil.copy2(self.hosts_path, backup_path)
                self.hosts_backup = backup_path
                
                print("✅ Original hosts file backed up successfully")
            else:
                self.original_hosts_content = ""
                print("⚠️ Hosts file doesn't exist, will create new one")
                
        except Exception as e:
            print(f"❌ Error backing up hosts file: {e}")
            self.original_hosts_content = ""

    def _restore_original_hosts(self):
        """FIXED: Restore original hosts file content"""
        try:
            if self.original_hosts_content is not None:
                # Write back original content
                with open(self.hosts_path, 'w') as f:
                    f.write(self.original_hosts_content)
                print("✅ Original hosts file content restored")
            elif self.hosts_backup and os.path.exists(self.hosts_backup):
                # Fallback to backup file
                shutil.copy2(self.hosts_backup, self.hosts_path)
                print("✅ Hosts file restored from backup")
            
            # Clean up backup file
            if self.hosts_backup and os.path.exists(self.hosts_backup):
                os.remove(self.hosts_backup)
                self.hosts_backup = None
                
        except Exception as e:
            print(f"❌ Error restoring hosts file: {e}")

    def _modify_hosts_file(self):
        """Enhanced hosts file modification"""
        try:
            blocked_entries = []
            
            # FIXED: Add comprehensive blocking including Google and YouTube
            comprehensive_blocked_sites = [
                'google.com', 'www.google.com', 'google.co.in', 'www.google.co.in',
                'youtube.com', 'www.youtube.com', 'youtu.be', 'm.youtube.com',
                'facebook.com', 'www.facebook.com', 'fb.com', 'm.facebook.com',
                'twitter.com', 'www.twitter.com', 'x.com', 'www.x.com',
                'instagram.com', 'www.instagram.com',
                'tiktok.com', 'www.tiktok.com',
                'reddit.com', 'www.reddit.com',
                'discord.com', 'www.discord.com',
                'whatsapp.com', 'web.whatsapp.com',
                'telegram.org', 'web.telegram.org'
            ]
            
            # Add blocked entries
            for site in comprehensive_blocked_sites:
                blocked_entries.append(f"127.0.0.1 {site}")
                blocked_entries.append(f"::1 {site}")
            
            # Read current hosts content or use original
            current_content = self.original_hosts_content if self.original_hosts_content else ""
            
            # Add exam shield blocking section
            new_content = current_content + "\n\n# EXAM SHIELD BLOCKING - DO NOT EDIT\n"
            new_content += "\n".join(blocked_entries)
            new_content += "\n# END EXAM SHIELD BLOCKING\n"
            
            # Write new content
            with open(self.hosts_path, 'w') as f:
                f.write(new_content)
                
            print(f"✅ Blocked {len(comprehensive_blocked_sites)} websites in hosts file")
            
        except Exception as e:
            print(f"❌ Error modifying hosts file: {e}")

    def _block_dns(self):
        """Additional DNS blocking measures"""
        try:
            # Change DNS to non-functional servers
            if platform.system().lower() == "windows":
                subprocess.run([
                    'netsh', 'interface', 'ip', 'set', 'dns', 
                    'name="Local Area Connection"', 'source=static', 'addr=127.0.0.1'
                ], capture_output=True, text=True)
                
                subprocess.run([
                    'netsh', 'interface', 'ip', 'set', 'dns', 
                    'name="Wi-Fi"', 'source=static', 'addr=127.0.0.1'
                ], capture_output=True, text=True)
                
            print("✅ DNS blocking applied")
        except Exception as e:
            print(f"⚠️ DNS blocking failed: {e}")

    def _restore_dns(self):
        """Restore original DNS settings"""
        try:
            if platform.system().lower() == "windows":
                # Restore to automatic DNS
                subprocess.run([
                    'netsh', 'interface', 'ip', 'set', 'dns', 
                    'name="Local Area Connection"', 'source=dhcp'
                ], capture_output=True, text=True)
                
                subprocess.run([
                    'netsh', 'interface', 'ip', 'set', 'dns', 
                    'name="Wi-Fi"', 'source=dhcp'
                ], capture_output=True, text=True)
                
            print("✅ DNS settings restored")
        except Exception as e:
            print(f"⚠️ DNS restoration failed: {e}")

    def _flush_dns_cache(self):
        """Flush DNS cache to ensure changes take effect"""
        try:
            if platform.system().lower() == "windows":
                subprocess.run(['ipconfig', '/flushdns'], capture_output=True, text=True)
            elif platform.system().lower() == "linux":
                subprocess.run(['sudo', 'systemctl', 'restart', 'systemd-resolved'], capture_output=True, text=True)
            elif platform.system().lower() == "darwin":
                subprocess.run(['sudo', 'dscacheutil', '-flushcache'], capture_output=True, text=True)
                
            print("✅ DNS cache flushed")
        except Exception as e:
            print(f"⚠️ DNS cache flush failed: {e}")

    def _continuous_blocking(self):
        """Continuous monitoring and blocking"""
        while self.is_blocked:
            try:
                # Re-apply hosts file blocking if modified
                self._verify_hosts_blocking()
                time.sleep(5)
            except Exception as e:
                print(f"Continuous blocking error: {e}")
                time.sleep(10)

    def _verify_hosts_blocking(self):
        """Verify hosts file still contains blocking entries"""
        try:
            with open(self.hosts_path, 'r') as f:
                content = f.read()
            
            if "EXAM SHIELD BLOCKING" not in content:
                # Re-apply blocking if removed
                self._modify_hosts_file()
                print("🔄 Re-applied hosts file blocking")
                
        except Exception as e:
            print(f"Error verifying hosts blocking: {e}")

    def is_internet_blocked(self):
        """Check if internet is currently blocked"""
        return self.is_blocked

    def get_blocked_websites(self):
        """Get list of currently blocked websites"""
        return Config.BLOCKED_WEBSITES
