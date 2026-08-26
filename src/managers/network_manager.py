"""
ExamShield v1.0 — Network Manager
Blocks internet by modifying hosts file + DNS + Windows Firewall, with robust restoration.

Layer 5: IPv6 outbound firewall rule added alongside IPv4 rule so that dual-stack
         and IPv6-only connections are also blocked during exam lockdown.
"""
import hashlib
import os
import shutil
import platform
import subprocess
import threading
import time
import socket
import ipaddress
import socketserver
import dnslib
from src.config import Config
from src.logger import ExamShieldLogger

class DNSProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        try:
            request = dnslib.DNSRecord.parse(data)
            qname = str(request.q.qname).lower().rstrip('.')
            
            allowed = False
            allowed_sites = getattr(Config, 'ALLOWED_WEBSITES', [])
            for site in allowed_sites:
                site_lower = site.lower().rstrip('.')
                if site_lower.startswith('*.'):
                    suffix = site_lower[2:]
                    if qname == suffix or qname.endswith('.' + suffix):
                        allowed = True
                        break
                elif qname == site_lower:
                    allowed = True
                    break
                    
            if allowed:
                # Forward query to public DNS
                proxy_req = request.send('8.8.8.8', 53, timeout=3)
                reply = dnslib.DNSRecord.parse(proxy_req)
                
                # Punch hole in firewall dynamically
                ips = []
                for rr in reply.rr:
                    if rr.rtype in (1, 28): # A, AAAA
                        ip = str(rr.rdata)
                        ips.append(ip)
                if ips:
                    self.server.network_manager._add_dynamic_firewall_rule(ips)
                    
                sock.sendto(reply.pack(), self.client_address)
            else:
                # Blocked: Return 127.0.0.1
                reply = request.reply()
                reply.add_answer(*dnslib.RR.fromZone(f"{qname} 60 A 127.0.0.1"))
                sock.sendto(reply.pack(), self.client_address)
        except Exception as e:
            if hasattr(self, 'server') and hasattr(self.server, 'network_manager'):
                self.server.network_manager.log.error("DNS_PROXY", f"Error handling DNS request: {e}")

class DNSProxyServer(socketserver.UDPServer):
    def __init__(self, server_address, RequestHandlerClass, network_manager):
        super().__init__(server_address, RequestHandlerClass)
        self.network_manager = network_manager



class NetworkManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.log = ExamShieldLogger(db_manager)
        self.is_blocked = False
        self.hosts_path = self._hosts_path()
        self._original_content = None
        self._backup_path = None
        self._guard_thread = None
        self._stop_event = threading.Event()
        self.allowed_dynamic_ips = set()
        self._dns_server = None
        self._dns_thread = None
        self._fw_lock = threading.Lock()

    @staticmethod
    def _hosts_path():
        s = platform.system().lower()
        if s == "windows":
            return r"C:\Windows\System32\drivers\etc\hosts"
        return "/etc/hosts"

    # ── Public API ───────────────────────────────────────────────
    def start_blocking(self):
        if self.is_blocked:
            return
        try:
            # Clear previous dynamic IPs
            self.allowed_dynamic_ips.clear()
            
            # Start local DNS Proxy
            self._dns_server = DNSProxyServer(('127.0.0.1', 53), DNSProxyHandler, self)
            self._dns_thread = threading.Thread(target=self._dns_server.serve_forever, daemon=True)
            self._dns_thread.start()
            
            self._set_dns_loopback()
            self._add_firewall_rules()       # second-layer: Windows Firewall (IPv4)
            self._add_firewall_rules_v6()    # Layer 5: Windows Firewall (IPv6)
            
            self.is_blocked = True
            self._stop_event.clear()
            self.log.info("NET_BLOCK_START",
                          "Internet blocking activated (DNS Proxy + firewall IPv4+IPv6)")
        except Exception as e:
            self.log.error("NET_BLOCK", f"Start failed: {e}")

    def stop_blocking(self):
        if not self.is_blocked:
            return
        self.is_blocked = False
        self._stop_event.set()
        try:
            if self._dns_server:
                self._dns_server.shutdown()
                self._dns_server.server_close()
                self._dns_server = None
                
            self._restore_dns()
            self._flush_dns()
            self._remove_firewall_rules()    # clean up IPv4 rule
            self._remove_firewall_rules_v6() # Layer 5: clean up IPv6 rule
            self.log.info("NET_BLOCK_STOP", "Internet access restored")
        except Exception as e:
            self.log.error("NET_BLOCK", f"Stop failed: {e}")

    # ── Hosts file ops ───────────────────────────────────────────
    _MARKER_START = "# ===== EXAM SHIELD BLOCK START ====="
    _MARKER_END   = "# ===== EXAM SHIELD BLOCK END ====="

    def _backup_hosts(self):
        try:
            if os.path.exists(self.hosts_path):
                with open(self.hosts_path, 'r', encoding='utf-8', errors='replace') as f:
                    self._original_content = f.read()
                self._backup_path = self.hosts_path + ".examshield.bak"
                shutil.copy2(self.hosts_path, self._backup_path)
            else:
                self._original_content = ""
        except Exception as e:
            self.log.error("NET_BACKUP", f"Hosts backup failed: {e}")
            self._original_content = ""

    def _write_blocked_hosts(self):
        sites = Config.BLOCKED_WEBSITES
        expanded_sites = set()
        for site in sites:
            expanded_sites.add(site)
            expanded_sites.add(f"www.{site}")
            expanded_sites.add(f"m.{site}")
            
        lines = [self._MARKER_START]
        for site in sorted(expanded_sites):
            lines.append(f"127.0.0.1 {site}")
            lines.append(f"::1 {site}")
            
        allowed_sites = getattr(Config, 'ALLOWED_WEBSITES', [])
        for site in allowed_sites:
            try:
                ip = socket.gethostbyname(site)
                lines.append(f"{ip} {site}")
                lines.append(f"{ip} www.{site}")
            except Exception:
                pass
                
        lines.append(self._MARKER_END)
        block = "\n".join(lines)
        try:
            content = (self._original_content or "") + "\n\n" + block + "\n"
            with open(self.hosts_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            self.log.error("NET_HOSTS", f"Write failed: {e}")

    def _restore_hosts(self):
        try:
            if self._original_content is not None:
                with open(self.hosts_path, 'w', encoding='utf-8') as f:
                    f.write(self._original_content)
            elif self._backup_path and os.path.exists(self._backup_path):
                shutil.copy2(self._backup_path, self.hosts_path)
            # Cleanup backup
            if self._backup_path and os.path.exists(self._backup_path):
                os.remove(self._backup_path)
                self._backup_path = None
        except Exception as e:
            self.log.error("NET_RESTORE", f"Hosts restore failed: {e}")

    # ── DNS ──────────────────────────────────────────────────────
    def _set_dns_loopback(self):
        if platform.system().lower() != "windows":
            return
        ps_cmd = "Get-NetAdapter | Where-Object Status -eq 'Up' | Set-DnsClientServerAddress -ServerAddresses ('127.0.0.1')"
        subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True)

    def _restore_dns(self):
        if platform.system().lower() != "windows":
            return
        ps_cmd = "Get-NetAdapter | Where-Object Status -eq 'Up' | Set-DnsClientServerAddress -ResetServerAddresses"
        subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True)

    def _flush_dns(self):
        if platform.system().lower() == "windows":
            subprocess.run(['ipconfig', '/flushdns'], capture_output=True, text=True)

    # ── File Permission Lock ──────────────────────────────────────
    def _lock_hosts_file(self):
        """Remove write permission from hosts file for all non-SYSTEM users."""
        try:
            subprocess.run(
                ['icacls', self.hosts_path,
                 '/deny', 'Users:(W)',
                 '/deny', 'Authenticated Users:(W)'],
                capture_output=True, timeout=8
            )
            self.log.info("NET_HOSTS_LOCK", "Hosts file write-locked")
        except Exception as e:
            self.log.error("NET_HOSTS_LOCK", f"Lock failed: {e}")

    def _unlock_hosts_file(self):
        """Restore write permission to hosts file."""
        try:
            subprocess.run(
                ['icacls', self.hosts_path,
                 '/remove:d', 'Users',
                 '/remove:d', 'Authenticated Users'],
                capture_output=True, timeout=8
            )
            self.log.info("NET_HOSTS_UNLOCK", "Hosts file write-unlocked")
        except Exception as e:
            self.log.error("NET_HOSTS_UNLOCK", f"Unlock failed: {e}")

    # ── Guard Thread ─────────────────────────────────────────────────────
    _hosts_hash: str = ''

    def _hash_hosts(self) -> str:
        """Return SHA-256 hex digest of the current hosts file."""
        try:
            with open(self.hosts_path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return ''

    def _guard_loop(self):
        """Re-apply hosts blocking if someone tampers with the file (0.5 s interval)."""
        while not self._stop_event.is_set():
            try:
                current_hash = self._hash_hosts()
                # Tamper detected: either marker removed OR content changed
                if current_hash != self._hosts_hash:
                    with open(self.hosts_path, 'r',
                              encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    if self._MARKER_START not in content:
                        self.log.warning("NET_GUARD",
                                         "Re-applied tampered hosts block (marker removed)")
                    else:
                        self.log.warning("NET_GUARD",
                                         "Re-applied tampered hosts block (hash mismatch)")
                    self._write_blocked_hosts()
                    self._lock_hosts_file()
                    self._hosts_hash = self._hash_hosts()
            except Exception:
                pass
            self._stop_event.wait(0.5)   # 0.5 s tight guard

    # ── Windows Firewall — IPv4 (second-layer) ────────────────────────────────
    _FW_RULE_NAME    = "ExamShield_BlockOutbound"
    _FW_RULE_NAME_V6 = "ExamShield_BlockOutboundV6"  # Layer 5

    def _add_dynamic_firewall_rule(self, ips):
        new_ips = []
        with self._fw_lock:
            for ip in ips:
                if ip not in self.allowed_dynamic_ips:
                    self.allowed_dynamic_ips.add(ip)
                    new_ips.append(ip)
        if new_ips:
            threading.Thread(target=self._add_firewall_rules, daemon=True).start()

    def refresh_firewall_rules(self):
        """Re-evaluate ALLOWED_WEBSITES and update the firewall rules if blocked."""
        if self.is_blocked:
            threading.Thread(target=self._add_firewall_rules, daemon=True).start()

    def _add_firewall_rules(self):
        """
        Block all outbound non-loopback IPv4 traffic via Windows Firewall.
        This is a second layer on top of the DNS proxy.
        """
        if platform.system().lower() != 'windows':
            return
            
        with self._fw_lock:
            try:
                # Remove any stale rule first
                self._remove_firewall_rules_internal()
                
                allowed_ips = set(self.allowed_dynamic_ips)
                allowed_sites = getattr(Config, 'ALLOWED_WEBSITES', [])
                for site in allowed_sites:
                    try:
                        allowed_ips.add(socket.gethostbyname(site))
                    except Exception:
                        pass
            
            networks = [ipaddress.IPv4Network('0.0.0.0/0')]
            exclude_cidrs = [ipaddress.IPv4Network('127.0.0.0/8')]
            for ip in allowed_ips:
                exclude_cidrs.append(ipaddress.IPv4Network(f'{ip}/32'))
                
            for exc in exclude_cidrs:
                new_networks = []
                for net in networks:
                    if exc.overlaps(net):
                        new_networks.extend(net.address_exclude(exc))
                    else:
                        new_networks.append(net)
                networks = new_networks
                
            ranges = []
            for net in sorted(networks, key=lambda x: x.network_address):
                if net.prefixlen == 32:
                    ranges.append(str(net.network_address))
                else:
                    ranges.append(f'{net.network_address}-{net.broadcast_address}')
            remoteip = ','.join(ranges)

            subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                 f'name={self._FW_RULE_NAME}',
                 'dir=out', 'action=block',
                 f'remoteip={remoteip}',
                 'protocol=any', 'enable=yes', 'profile=any'],
                capture_output=True, timeout=15
            )
            self.log.info("NET_FW", f"Firewall IPv4 rule '{self._FW_RULE_NAME}' added")
        except Exception as e:
            self.log.error("NET_FW", f"Firewall IPv4 rule add failed: {e}")
            
    def _remove_firewall_rules(self):
        """Thread-safe wrapper to remove the ExamShield IPv4 outbound block rule."""
        if platform.system().lower() != 'windows':
            return
        with self._fw_lock:
            self._remove_firewall_rules_internal()

    def _remove_firewall_rules_internal(self):
        """Internal method to remove the IPv4 rule (assumes lock is acquired)."""
        try:
            subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'delete', 'rule',
                 f'name={self._FW_RULE_NAME}'],
                capture_output=True, timeout=15
            )
            self.log.info("NET_FW", f"Firewall IPv4 rule '{self._FW_RULE_NAME}' removed")
        except Exception as e:
            self.log.error("NET_FW", f"Firewall IPv4 rule remove failed: {e}")

    # ── Layer 5: IPv6 Firewall Block ──────────────────────────────────────────
    def _add_firewall_rules_v6(self):
        """
        Block ALL outbound IPv6 traffic via Windows Firewall.
        The existing IPv4 rule left IPv6 entirely open; this closes that gap.
        Students could otherwise reach IPv6-only hosts or dual-stack services
        via their IPv6 address, bypassing the hosts file + IPv4 firewall.
        """
        if platform.system().lower() != 'windows':
            return
        try:
            self._remove_firewall_rules_v6()  # purge stale rule first
            subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                 f'name={self._FW_RULE_NAME_V6}',
                 'dir=out', 'action=block',
                 'protocol=any',
                 'remoteip=::/0',          # all IPv6 destinations
                 'enable=yes', 'profile=any'],
                capture_output=True, timeout=15
            )
            self.log.info("NET_FW", f"Firewall IPv6 rule '{self._FW_RULE_NAME_V6}' added")
        except Exception as e:
            self.log.error("NET_FW", f"Firewall IPv6 rule add failed: {e}")

    def _remove_firewall_rules_v6(self):
        """Remove the ExamShield IPv6 outbound block rule."""
        if platform.system().lower() != 'windows':
            return
        try:
            subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'delete', 'rule',
                 f'name={self._FW_RULE_NAME_V6}'],
                capture_output=True, timeout=15
            )
            self.log.info("NET_FW", f"Firewall IPv6 rule '{self._FW_RULE_NAME_V6}' removed")
        except Exception as e:
            self.log.error("NET_FW", f"Firewall IPv6 rule remove failed: {e}")

    # ── Helpers ──────────────────────────────────────────────────────
    def get_blocked_websites(self):
        return Config.BLOCKED_WEBSITES
