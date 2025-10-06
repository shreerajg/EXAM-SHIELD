"""
System Tray functionality for Exam Shield
"""

import pystray
from PIL import Image, ImageDraw
import threading
import tkinter as tk
from tkinter import simpledialog, messagebox

class SystemTray:
    def __init__(self, admin_panel, security_manager):
        self.admin_panel = admin_panel
        self.security_manager = security_manager
        self.icon = None
        self.running = False

    def create_icon_image(self):
        image = Image.new('RGB', (64, 64), color='white')
        draw = ImageDraw.Draw(image)
        draw.polygon([(32, 5), (55, 20), (55, 45), (32, 59), (9, 45), (9, 20)],
                     fill='blue', outline='darkblue')
        draw.rectangle([25, 30, 39, 42], fill='white')
        draw.rectangle([27, 25, 37, 35], outline='white', width=2)
        return image

    def create_menu(self):
        menu_items = [
            pystray.MenuItem("Exam Shield", self.show_admin_panel, default=True),
            pystray.MenuItem("Show Admin Panel", self.show_admin_panel),
            pystray.Menu.SEPARATOR,
        ]
        if self.security_manager.is_exam_mode:
            menu_items.append(pystray.MenuItem("🔒 Stop Exam Mode", self.stop_exam_mode_with_password))
        else:
            menu_items.append(pystray.MenuItem("🔓 Start Exam Mode", self.start_exam_mode))
        menu_items.extend([
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit (Admin Only)", self.exit_application)
        ])
        return pystray.Menu(*menu_items)

    def show_admin_panel(self, icon=None, item=None):
        self.admin_panel.show()

    def start_exam_mode(self, icon=None, item=None):
        self.security_manager.start_exam_mode()
        if self.icon:
            self.icon.menu = self.create_menu()

    def stop_exam_mode_with_password(self, icon=None, item=None):
        root = tk.Tk()
        root.withdraw()
        password = simpledialog.askstring("Password Required",
                                          "Enter admin password to stop exam mode:",
                                          show="*", parent=root)
        if password:
            import hashlib
            from database_manager import DatabaseManager
            db_manager = DatabaseManager()
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            if db_manager.verify_admin("admin", password_hash):
                self.security_manager.stop_exam_mode()
                if self.icon:
                    self.icon.menu = self.create_menu()
                messagebox.showinfo("Success", "Exam mode stopped", parent=root)
            else:
                messagebox.showerror("Error", "Invalid password", parent=root)
        root.destroy()

    def exit_application(self, icon=None, item=None):
        root = tk.Tk()
        root.withdraw()
        password = simpledialog.askstring("Password Required",
                                          "Enter admin password to exit Exam Shield:",
                                          show="*", parent=root)
        if password:
            import hashlib
            from database_manager import DatabaseManager
            db_manager = DatabaseManager()
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            if db_manager.verify_admin("admin", password_hash):
                self.stop()
                import sys
                sys.exit(0)
            else:
                messagebox.showerror("Error", "Invalid password", parent=root)
        root.destroy()

    def run(self):
        self.running = True
        image = self.create_icon_image()
        menu = self.create_menu()
        self.icon = pystray.Icon("ExamShield", image, "Exam Shield", menu)
        self.icon.run()

    def stop(self):
        self.running = False
        if self.icon:
            self.icon.stop()
