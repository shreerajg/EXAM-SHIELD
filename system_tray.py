"""
ExamShield v1.0 — System Tray
Runs in background, provides quick access to admin panel.
"""
import pystray
from PIL import Image, ImageDraw
import hashlib
import sys
import tkinter as tk
from tkinter import simpledialog, messagebox
from logger import ExamShieldLogger


class SystemTray:
    def __init__(self, admin_panel, security_manager, db_manager,
                 parent_window, admin_user='admin'):
        self.admin_panel = admin_panel
        self.security_manager = security_manager
        self.db_manager = db_manager
        self.parent = parent_window
        self.admin_user = admin_user
        self.log = ExamShieldLogger(db_manager)
        self.icon = None
        self.running = False

    # ── Icon ─────────────────────────────────────────────────────
    def _create_icon(self):
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Shield
        draw.polygon(
            [(32, 4), (58, 18), (58, 42), (32, 60), (6, 42), (6, 18)],
            fill='#00d4ff', outline='#0088aa',
        )
        draw.polygon(
            [(32, 12), (50, 22), (50, 38), (32, 50), (14, 38), (14, 22)],
            fill='#0a0a1a',
        )
        # Checkmark
        draw.line([(22, 30), (30, 38), (42, 22)],
                  fill='#00e676', width=3)
        return img

    # ── Menu ─────────────────────────────────────────────────────
    def _menu(self):
        items = [
            pystray.MenuItem("🛡️  Exam Shield", self._show_panel,
                             default=True),
            pystray.MenuItem("Open Admin Panel", self._show_panel),
            pystray.Menu.SEPARATOR,
        ]
        if self.security_manager.is_exam_mode:
            items.append(
                pystray.MenuItem("🔒 Stop Lockdown", self._stop_lockdown))
        else:
            items.append(
                pystray.MenuItem("🔓 Start Lockdown", self._start_lockdown))
        items += [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit (Admin)", self._exit),
        ]
        return pystray.Menu(*items)

    # ── Actions ──────────────────────────────────────────────────
    def _show_panel(self, icon=None, item=None):
        self.admin_panel.show()

    def _start_lockdown(self, icon=None, item=None):
        self.security_manager.start_exam_mode()
        self._refresh_menu()

    def _stop_lockdown(self, icon=None, item=None):
        if self._verify_password("Enter admin password to stop lockdown:"):
            self.security_manager.stop_exam_mode()
            self._refresh_menu()
            self._msg("Lockdown stopped", info=True)
        else:
            self._msg("Invalid password!", info=False)

    def _exit(self, icon=None, item=None):
        if self._verify_password("Enter admin password to exit Exam Shield:"):
            self.log.info("APP_EXIT", "Exit via tray")
            self.stop()
            sys.exit(0)
        else:
            self._msg("Invalid password!", info=False)

    # ── Helpers ──────────────────────────────────────────────────
    def _verify_password(self, prompt):
        pw = simpledialog.askstring(
            "🔐 Authentication", prompt,
            show="*", parent=self.parent)
        if not pw:
            return False
        h = hashlib.sha256(pw.encode()).hexdigest()
        return self.db_manager.verify_admin(self.admin_user, h)

    def _msg(self, text, info=True):
        fn = messagebox.showinfo if info else messagebox.showerror
        fn("Exam Shield", text, parent=self.parent)

    def _refresh_menu(self):
        if self.icon:
            self.icon.menu = self._menu()

    # ── Lifecycle ────────────────────────────────────────────────
    def run(self):
        self.running = True
        self.icon = pystray.Icon(
            "ExamShield", self._create_icon(),
            "Exam Shield", self._menu())
        self.icon.run()

    def stop(self):
        self.running = False
        if self.icon:
            self.icon.stop()
