"""
Exam Shield - Main Application Entry Point
Enhanced Version with Advanced Security Features
"""
import tkinter as tk
from tkinter import messagebox
import sys
import os
import hashlib
import ctypes
import subprocess
from database_manager import DatabaseManager
from admin_panel import AdminPanel
from security_manager import SecurityManager
from system_tray import SystemTray
import threading

class ExamShield:
    def __init__(self):
        if not self.is_admin():
            self.restart_as_admin()
            return
            
        self.root = tk.Tk()
        self.root.title("Exam Shield v1.1 - Admin Login")
        self.root.geometry("450x600")
        self.root.resizable(False, False)
        self.root.configure(bg='#f5f5f5')
        
        self.db_manager = DatabaseManager()
        self.security_manager = None
        self.system_tray = None
        
        self.setup_ui()
        self.center_window()

    def is_admin(self):
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False

    def restart_as_admin(self):
        try:
            result = messagebox.askyesno(
                "Administrator Privileges Required",
                "Exam Shield requires administrator privileges to function properly.\n\n"
                "This is needed for:\n"
                "• Network adapter control\n"
                "• Process monitoring & termination\n"
                "• System-level keyboard/mouse hooks\n"
                "• Firewall rule management\n\n"
                "Click 'Yes' to restart with admin privileges, or 'No' to exit."
            )
            
            if result:
                if getattr(sys, 'frozen', False):
                    script_path = sys.executable
                else:
                    script_path = os.path.abspath(__file__)
                
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas",
                    sys.executable if not getattr(sys, 'frozen', False) else script_path,
                    f'"{script_path}"' if not getattr(sys, 'frozen', False) else "",
                    None, 1
                )
                sys.exit(0)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to restart with admin privileges: {e}")
            sys.exit(1)

    def center_window(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - 225
        y = (self.root.winfo_screenheight() // 2) - 300
        self.root.geometry(f"450x600+{x}+{y}")

    def setup_ui(self):
        # Header section
        header_frame = tk.Frame(self.root, bg='#2196F3', height=120)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)
        
        # Title
        title_label = tk.Label(header_frame, text="🛡️", font=("Arial", 36), bg='#2196F3', fg='white')
        title_label.pack(pady=(15, 5))
        
        app_title = tk.Label(header_frame, text="EXAM SHIELD", font=("Arial", 18, "bold"), bg='#2196F3', fg='white')
        app_title.pack()
        
        subtitle = tk.Label(header_frame, text="Advanced Secure Exam Environment v1.1 [ADMIN MODE]",
                           font=("Arial", 10), bg='#2196F3', fg='#E3F2FD')
        subtitle.pack(pady=(2, 15))
        
        # Main content area
        content_frame = tk.Frame(self.root, bg='#f5f5f5')
        content_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=40)
        
        # Login form
        form_frame = tk.Frame(content_frame, bg='white', relief=tk.RAISED, bd=2)
        form_frame.pack(fill=tk.X)
        
        # Form header
        form_header = tk.Label(form_frame, text="Admin Login Required", font=("Arial", 14, "bold"),
                              bg='white', fg='#333', pady=20)
        form_header.pack()
        
        # Username section
        username_frame = tk.Frame(form_frame, bg='white')
        username_frame.pack(fill=tk.X, padx=30, pady=(0, 15))
        
        tk.Label(username_frame, text="Username", font=("Arial", 11), bg='white', fg='#666').pack(anchor=tk.W, pady=(0, 5))
        
        self.username_var = tk.StringVar(value="admin")
        username_entry = tk.Entry(username_frame, textvariable=self.username_var,
                                 font=("Arial", 12), width=30, relief=tk.SOLID, bd=1,
                                 highlightthickness=2, highlightcolor='#2196F3')
        username_entry.pack(fill=tk.X, ipady=8)
        
        # Password section
        password_frame = tk.Frame(form_frame, bg='white')
        password_frame.pack(fill=tk.X, padx=30, pady=(0, 25))
        
        tk.Label(password_frame, text="Password", font=("Arial", 11), bg='white', fg='#666').pack(anchor=tk.W, pady=(0, 5))
        
        self.password_var = tk.StringVar()
        password_entry = tk.Entry(password_frame, textvariable=self.password_var,
                                 font=("Arial", 12), width=30, show="*", relief=tk.SOLID, bd=1,
                                 highlightthickness=2, highlightcolor='#2196F3')
        password_entry.pack(fill=tk.X, ipady=8)
        
        # Buttons section
        button_frame = tk.Frame(form_frame, bg='white')
        button_frame.pack(fill=tk.X, padx=30, pady=(0, 30))
        
        login_btn = tk.Button(button_frame, text="🔐 LOGIN", command=self.login,
                             bg='#4CAF50', fg='white', font=("Arial", 12, "bold"),
                             relief=tk.FLAT, cursor='hand2', width=15, pady=10)
        login_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        cancel_btn = tk.Button(button_frame, text="❌ EXIT", command=self.exit_app,
                              bg='#F44336', fg='white', font=("Arial", 12, "bold"),
                              relief=tk.FLAT, cursor='hand2', width=15, pady=10)
        cancel_btn.pack(side=tk.RIGHT)
        
        # Info section
        info_frame = tk.Frame(content_frame, bg='#f5f5f5')
        info_frame.pack(fill=tk.X, pady=(20, 0))
        
        if not self.db_manager.admin_exists():
            info_box = tk.Frame(info_frame, bg='#E8F5E8', relief=tk.SOLID, bd=1)
            info_box.pack(fill=tk.X, pady=10)
            
            info_text = tk.Label(info_box, text="ℹ️ First Time Setup\nDefault: admin / admin",
                                font=("Arial", 10), bg='#E8F5E8', fg='#2E7D32',
                                justify=tk.CENTER, pady=15)
            info_text.pack()
        
        # Admin privileges confirmed box
        admin_confirmed_box = tk.Frame(info_frame, bg='#C8E6C9', relief=tk.SOLID, bd=1)
        admin_confirmed_box.pack(fill=tk.X, pady=(10, 0))
        
        admin_confirmed_label = tk.Label(admin_confirmed_box,
                                        text="✅ Administrator Privileges Confirmed\nAll security features available",
                                        font=("Arial", 9, "bold"), bg='#C8E6C9', fg='#2E7D32',
                                        justify=tk.CENTER, pady=10)
        admin_confirmed_label.pack()
        
        # Features info box
        features_box = tk.Frame(info_frame, bg='#E3F2FD', relief=tk.SOLID, bd=1)
        features_box.pack(fill=tk.X, pady=(10, 0))
        
        features_title = tk.Label(features_box, text="🔒 Security Features",
                                 font=("Arial", 10, "bold"), bg='#E3F2FD', fg='#1976D2')
        features_title.pack(pady=(10, 5))
        
        features_list = [
            "• Advanced keyboard shortcut blocking",
            "• Mouse button restriction & suppression",
            "• Multi-layer internet/website blocking",
            "• Process monitoring & auto-termination",
            "• Window protection & fullscreen enforcement",
            "• Real-time security event logging"
        ]
        
        for feature in features_list:
            feature_label = tk.Label(features_box, text=feature, font=("Arial", 8),
                                    bg='#E3F2FD', fg='#1976D2', anchor='w')
            feature_label.pack(fill=tk.X, padx=15)
        
        # FIXED: Updated admin shortcut info to Ctrl+Shift+Y
        shortcut_box = tk.Frame(info_frame, bg='#FFF3E0', relief=tk.SOLID, bd=1)
        shortcut_box.pack(fill=tk.X, pady=(10, 0))
        
        shortcut_label = tk.Label(shortcut_box,
                                 text="🔑 Emergency Admin Access: Ctrl+Shift+Y\n"
                                      "Use this shortcut during lockdown to access admin panel",
                                 font=("Arial", 9), bg='#FFF3E0', fg='#F57C00',
                                 justify=tk.CENTER, pady=10)
        shortcut_label.pack()
        
        tk.Label(features_box, text="", bg='#E3F2FD').pack(pady=(0, 10))  # Spacer
        
        # Version info
        version_label = tk.Label(content_frame, 
                                text="Version 1.1 - Enhanced Security Suite [Administrator Mode]",
                                font=("Arial", 8), bg='#f5f5f5', fg='#999')
        version_label.pack(side=tk.BOTTOM, pady=(20, 0))
        
        # Bind events
        password_entry.bind("<Return>", lambda e: self.login())
        username_entry.bind("<Return>", lambda e: password_entry.focus())
        self.root.bind("<Escape>", lambda e: self.exit_app())
        
        # Set initial focus
        if self.username_var.get():
            password_entry.focus()
        else:
            username_entry.focus()

    def login(self):
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        
        if not username:
            messagebox.showerror("Error", "Please enter username")
            return
        if not password:
            messagebox.showerror("Error", "Please enter password")
            return
        
        try:
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            if self.db_manager.verify_admin(username, password_hash):
                self.start_admin_session()
            else:
                messagebox.showerror("Login Failed", "Invalid username or password!")
                self.password_var.set("")
        except Exception as e:
            messagebox.showerror("Error", f"Login error: {str(e)}")

    def start_admin_session(self):
        try:
            self.root.withdraw()
            
            self.security_manager = SecurityManager(self.db_manager)
            
            self.db_manager.log_activity("ADMIN_LOGIN_SUCCESS", 
                                        f"Admin logged in with elevated privileges")
            
            admin_panel = AdminPanel(self.db_manager, self.security_manager, self.root)
            
            self.system_tray = SystemTray(admin_panel, self.security_manager)
            tray_thread = threading.Thread(target=self.system_tray.run, daemon=True)
            tray_thread.start()
            
            # FIXED: Updated success message to show Ctrl+Shift+Y
            messagebox.showinfo("🔒 Exam Shield Loaded",
                               "Exam Shield loaded successfully!\n\n"
                               "✅ All security modules initialized\n"
                               "✅ Admin panel ready\n"
                               "✅ System tray active\n"
                               "✅ Administrator privileges confirmed\n\n"
                               "🔑 Emergency Admin Access: Ctrl+Shift+Y\n"
                               "Use this during lockdown to access admin panel")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start: {str(e)}")
            self.root.deiconify()

    def exit_app(self):
        if messagebox.askyesno("Exit", "Close Exam Shield?\n\nThis will terminate all security features."):
            try:
                self.db_manager.log_activity("APPLICATION_EXIT", "Exam Shield closed by user")
            except:
                pass
            self.root.quit()

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    try:
        app = ExamShield()
        if hasattr(app, 'root'):
            app.run()
    except Exception as e:
        messagebox.showerror("Startup Error", f"Application failed to start:\n{str(e)}")
