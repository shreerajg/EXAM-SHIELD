"""
Admin Panel for Exam Shield - ENHANCED WITH SELECTIVE CONTROLS
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
import threading
import json
from datetime import datetime
import keyboard
from pynput import mouse

class AdminPanel:
    def __init__(self, db_manager, security_manager, parent_window):
        self.db_manager = db_manager
        self.security_manager = security_manager
        self.parent_window = parent_window
        
        # NEW: Set admin panel reference in security manager
        self.security_manager.set_admin_panel(self)
        
        # NEW: Key/Mouse detection variables
        self.detecting_key = False
        self.detecting_mouse = False
        self.detected_key = None
        self.mouse_listener = None
        
        self.window = tk.Toplevel()
        self.window.title("Exam Shield - Admin Panel v1.1 ENHANCED")
        self.window.geometry("950x750")
        self.window.resizable(True, True)
        
        self.setup_window()
        self.setup_ui()
        self.start_auto_refresh()

    def setup_window(self):
        self.window.update_idletasks()
        x = (self.window.winfo_screenwidth() // 2) - (475)
        y = (self.window.winfo_screenheight() // 2) - (375)
        self.window.geometry(f"950x750+{x}+{y}")
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_ui(self):
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.create_control_tab()
        self.create_monitoring_tab()
        self.create_settings_tab()
        self.create_logs_tab()

    def create_control_tab(self):
        control_frame = ttk.Frame(self.notebook)
        self.notebook.add(control_frame, text="📋 Exam Control")
        
        # Status frame
        status_frame = ttk.LabelFrame(control_frame, text="System Status", padding="10")
        status_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        self.status_label = ttk.Label(status_frame, text="🔓 Exam Mode: INACTIVE", font=("Arial", 14, "bold"))
        self.status_label.pack(anchor=tk.W)
        
        self.system_info_label = ttk.Label(status_frame, text="System Info Loading...")
        self.system_info_label.pack(anchor=tk.W, pady=(5, 0))
        
        # Security status indicators
        self.security_status_frame = ttk.Frame(status_frame)
        self.security_status_frame.pack(anchor=tk.W, pady=(5, 0), fill=tk.X)
        
        ttk.Label(self.security_status_frame, text="Security Modules:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        
        indicators_frame = ttk.Frame(self.security_status_frame)
        indicators_frame.pack(anchor=tk.W, pady=(2, 0))
        
        self.keyboard_status = ttk.Label(indicators_frame, text="⚫ Keyboard", foreground="gray")
        self.keyboard_status.pack(side=tk.LEFT, padx=(0, 15))
        
        self.mouse_status = ttk.Label(indicators_frame, text="⚫ Mouse", foreground="gray")
        self.mouse_status.pack(side=tk.LEFT, padx=(0, 15))
        
        self.network_status = ttk.Label(indicators_frame, text="⚫ Network", foreground="gray")
        self.network_status.pack(side=tk.LEFT, padx=(0, 15))
        
        self.window_status = ttk.Label(indicators_frame, text="⚫ Windows", foreground="gray")
        self.window_status.pack(side=tk.LEFT, padx=(0, 15))
        
        # Control buttons
        control_buttons_frame = ttk.LabelFrame(control_frame, text="Exam Controls", padding="10")
        control_buttons_frame.pack(fill=tk.X, padx=10, pady=5)
        
        button_frame = ttk.Frame(control_buttons_frame)
        button_frame.pack(fill=tk.X)
        
        # NEW: Changed to selective lockdown
        self.start_btn = ttk.Button(button_frame, text="🔒 START SELECTIVE LOCKDOWN", 
                                   command=self.show_selective_lockdown_dialog, style="Accent.TButton")
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.stop_btn = ttk.Button(button_frame, text="🔓 END LOCKDOWN MODE",
                                  command=self.stop_exam_mode, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.emergency_btn = ttk.Button(button_frame, text="🚨 EMERGENCY STOP",
                                       command=self.emergency_stop)
        self.emergency_btn.pack(side=tk.RIGHT)
        
        # Individual feature controls (same as before)
        self.create_individual_controls(control_frame)
        
        # Threat detection
        threat_frame = ttk.LabelFrame(control_frame, text="Threat Detection", padding="10")
        threat_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.threat_label = ttk.Label(threat_frame, text="No threats detected", foreground="green")
        self.threat_label.pack(anchor=tk.W)

    def create_individual_controls(self, parent):
        """Create individual security controls"""
        features_frame = ttk.LabelFrame(parent, text="Individual Security Controls", padding="10")
        features_frame.pack(fill=tk.X, padx=10, pady=5)
        
        feature_btn_frame1 = ttk.Frame(features_frame)
        feature_btn_frame1.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(feature_btn_frame1, text="🖱️ Mouse Blocker",
                  command=self.show_mouse_controls).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(feature_btn_frame1, text="🌐 Internet Blocker",
                  command=self.show_network_controls).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(feature_btn_frame1, text="🪟 Window Guardian",
                  command=self.show_window_controls).pack(side=tk.LEFT, padx=(0, 5))
        
        feature_btn_frame2 = ttk.Frame(features_frame)
        feature_btn_frame2.pack(fill=tk.X)
        
        ttk.Button(feature_btn_frame2, text="📊 Live Monitor",
                  command=lambda: self.notebook.select(1)).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(feature_btn_frame2, text="⚙️ Settings",
                  command=lambda: self.notebook.select(2)).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(feature_btn_frame2, text="🔄 Refresh Status",
                  command=self.refresh_status).pack(side=tk.LEFT, padx=(0, 5))

    # NEW: Selective Lockdown Dialog
    def show_selective_lockdown_dialog(self):
        """Show dialog for selective lockdown options"""
        dialog = tk.Toplevel(self.window)
        dialog.title("🔒 Selective Lockdown Configuration")
        dialog.geometry("500x600")
        dialog.transient(self.window)
        dialog.grab_set()
        
        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - 250
        y = (dialog.winfo_screenheight() // 2) - 300
        dialog.geometry(f"500x600+{x}+{y}")
        
        # Title
        title_label = tk.Label(dialog, text="Select Security Modules to Activate",
                              font=("Arial", 16, "bold"), pady=20)
        title_label.pack()
        
        # Options frame
        options_frame = tk.Frame(dialog)
        options_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        # Checkboxes for each security module
        self.selective_vars = {}
        
        modules = [
            ("keyboard", "🔤 Keyboard Shortcuts Blocking", "Block Alt+Tab, Ctrl+Alt+Del, etc."),
            ("mouse", "🖱️ Mouse Button Restrictions", "Block middle, back, forward buttons"),
            ("internet", "🌐 Internet Access Blocking", "Complete internet disconnection"),
            ("windows", "🪟 Window Protection", "Prevent closing/minimizing windows"),
            ("processes", "🔍 Process Monitoring", "Auto-terminate suspicious processes")
        ]
        
        for key, title, description in modules:
            frame = tk.Frame(options_frame, relief=tk.RAISED, bd=1, padx=10, pady=10)
            frame.pack(fill=tk.X, pady=5)
            
            var = tk.BooleanVar(value=True)  # Default all to True
            self.selective_vars[key] = var
            
            check = tk.Checkbutton(frame, text=title, variable=var, font=("Arial", 12, "bold"))
            check.pack(anchor=tk.W)
            
            desc_label = tk.Label(frame, text=description, font=("Arial", 10), fg="gray")
            desc_label.pack(anchor=tk.W, padx=20)
        
        # Buttons
        button_frame = tk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=40, pady=20)
        
        start_btn = tk.Button(button_frame, text="🚀 START SELECTED LOCKDOWN",
                             command=lambda: self.start_selective_lockdown(dialog),
                             bg='#4CAF50', fg='white', font=("Arial", 12, "bold"),
                             relief=tk.FLAT, pady=10)
        start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        cancel_btn = tk.Button(button_frame, text="❌ CANCEL",
                              command=dialog.destroy,
                              bg='#F44336', fg='white', font=("Arial", 12, "bold"),
                              relief=tk.FLAT, pady=10)
        cancel_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))

    def start_selective_lockdown(self, dialog):
        """Start lockdown with selected options"""
        selected_options = {key: var.get() for key, var in self.selective_vars.items()}
        
        # Check if at least one option is selected
        if not any(selected_options.values()):
            messagebox.showwarning("No Selection", "Please select at least one security module!")
            return
        
        # Confirm selection
        selected_names = [key.title() for key, selected in selected_options.items() if selected]
        result = messagebox.askyesno("Confirm Selective Lockdown",
                                    f"Start lockdown with these modules?\n\n" + 
                                    "\n".join(f"✓ {name}" for name in selected_names))
        
        if result:
            dialog.destroy()
            try:
                self.security_manager.start_exam_mode(selected_options)
                self.start_btn.config(state=tk.DISABLED)
                self.stop_btn.config(state=tk.NORMAL)
                self.refresh_status()
                
                messagebox.showinfo("🔒 SELECTIVE LOCKDOWN ACTIVE",
                                   f"Lockdown active with:\n" + 
                                   "\n".join(f"✓ {name}" for name in selected_names))
            except Exception as e:
                messagebox.showerror("Error", f"Failed to start lockdown: {str(e)}")

    # Continue with monitoring, settings tabs (same as before)
    def create_monitoring_tab(self):
        monitor_frame = ttk.Frame(self.notebook)
        self.notebook.add(monitor_frame, text="📊 Live Monitor")
        
        activity_frame = ttk.LabelFrame(monitor_frame, text="Real-time Security Events", padding="10")
        activity_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        columns = ("Time", "Severity", "Action", "Details", "Status")
        self.activity_tree = ttk.Treeview(activity_frame, columns=columns, show="headings", height=20)
        
        for col in columns:
            self.activity_tree.heading(col, text=col)
        
        self.activity_tree.column("Time", width=120)
        self.activity_tree.column("Severity", width=80)
        self.activity_tree.column("Action", width=180)
        self.activity_tree.column("Details", width=300)
        self.activity_tree.column("Status", width=100)
        
        activity_scrollbar = ttk.Scrollbar(activity_frame, orient=tk.VERTICAL, command=self.activity_tree.yview)
        self.activity_tree.configure(yscrollcommand=activity_scrollbar.set)
        
        self.activity_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        activity_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # NEW: Enhanced settings with key/mouse detection
    def create_settings_tab(self):
        settings_frame = ttk.Frame(self.notebook)
        self.notebook.add(settings_frame, text="⚙️ Settings")
        
        canvas = tk.Canvas(settings_frame)
        scrollbar = ttk.Scrollbar(settings_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Enhanced keyboard settings with key detection
        self.create_keyboard_settings(scrollable_frame)
        self.create_mouse_settings(scrollable_frame)
        self.create_network_settings(scrollable_frame)
        self.create_advanced_settings(scrollable_frame)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def create_keyboard_settings(self, parent):
        """Enhanced keyboard settings with key detection"""
        security_frame = ttk.LabelFrame(parent, text="🔤 Keyboard Security", padding="10")
        security_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(security_frame, text="Blocked Key Combinations:").pack(anchor=tk.W)
        
        key_frame = ttk.Frame(security_frame)
        key_frame.pack(fill=tk.X, pady=(5, 10))
        
        self.blocked_keys_listbox = tk.Listbox(key_frame, height=6)
        self.blocked_keys_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        key_btn_frame = ttk.Frame(key_frame)
        key_btn_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        # NEW: Enhanced add key with detection
        ttk.Button(key_btn_frame, text="🎯 Detect Key", 
                  command=self.detect_key_combination).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(key_btn_frame, text="⌨️ Type Key", 
                  command=self.add_blocked_key).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(key_btn_frame, text="Remove Key", 
                  command=self.remove_blocked_key).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(key_btn_frame, text="Reset Default", 
                  command=self.reset_default_keys).pack(fill=tk.X)

    def create_mouse_settings(self, parent):
        """Enhanced mouse settings with button detection"""
        mouse_frame = ttk.LabelFrame(parent, text="🖱️ Mouse Security", padding="10")
        mouse_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(mouse_frame, text="Blocked Mouse Buttons:").pack(anchor=tk.W)
        
        mouse_list_frame = ttk.Frame(mouse_frame)
        mouse_list_frame.pack(fill=tk.X, pady=(5, 10))
        
        self.blocked_mouse_listbox = tk.Listbox(mouse_list_frame, height=4)
        self.blocked_mouse_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        mouse_btn_frame = ttk.Frame(mouse_list_frame)
        mouse_btn_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        # NEW: Enhanced add button with detection
        ttk.Button(mouse_btn_frame, text="🎯 Detect Click", 
                  command=self.detect_mouse_button).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(mouse_btn_frame, text="⌨️ Type Button", 
                  command=self.add_blocked_mouse).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(mouse_btn_frame, text="Remove Button", 
                  command=self.remove_blocked_mouse).pack(fill=tk.X)

    def create_network_settings(self, parent):
        """Network settings"""
        network_frame = ttk.LabelFrame(parent, text="🌐 Network Security", padding="10")
        network_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.block_internet_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(network_frame, text="Enable comprehensive internet blocking",
                       variable=self.block_internet_var).pack(anchor=tk.W)
        
        ttk.Label(network_frame, text="Blocked Websites:").pack(anchor=tk.W, pady=(10, 0))
        
        website_frame = ttk.Frame(network_frame)
        website_frame.pack(fill=tk.X, pady=(5, 10))
        
        self.blocked_websites_listbox = tk.Listbox(website_frame, height=4)
        self.blocked_websites_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        website_btn_frame = ttk.Frame(website_frame)
        website_btn_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        ttk.Button(website_btn_frame, text="Add Website", 
                  command=self.add_blocked_website).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(website_btn_frame, text="Remove Website", 
                  command=self.remove_blocked_website).pack(fill=tk.X)

    def create_advanced_settings(self, parent):
        """Advanced settings"""
        advanced_frame = ttk.LabelFrame(parent, text="🔧 Advanced Settings", padding="10")
        advanced_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        self.auto_start_var = tk.BooleanVar()
        ttk.Checkbutton(advanced_frame, text="Auto-start lockdown mode on login",
                       variable=self.auto_start_var).pack(anchor=tk.W)
        
        self.window_protection_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(advanced_frame, text="Enable aggressive window protection",
                       variable=self.window_protection_var).pack(anchor=tk.W)
        
        self.process_monitoring_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(advanced_frame, text="Enable unauthorized process termination",
                       variable=self.process_monitoring_var).pack(anchor=tk.W)
        
        ttk.Button(advanced_frame, text="💾 Save All Settings",
                  command=self.save_settings).pack(pady=(15, 0))

    # NEW: Key Detection Methods
    def detect_key_combination(self):
        """Detect key combination by listening for keypress"""
        if self.detecting_key:
            return
            
        detect_dialog = tk.Toplevel(self.window)
        detect_dialog.title("🎯 Key Detection")
        detect_dialog.geometry("400x200")
        detect_dialog.transient(self.window)
        detect_dialog.grab_set()
        
        # Center dialog
        detect_dialog.update_idletasks()
        x = (detect_dialog.winfo_screenwidth() // 2) - 200
        y = (detect_dialog.winfo_screenheight() // 2) - 100
        detect_dialog.geometry(f"400x200+{x}+{y}")
        
        tk.Label(detect_dialog, text="Press the key combination you want to block",
                font=("Arial", 12, "bold")).pack(pady=20)
        
        status_label = tk.Label(detect_dialog, text="Waiting for key combination...",
                               font=("Arial", 10), fg="blue")
        status_label.pack(pady=10)
        
        detected_label = tk.Label(detect_dialog, text="", 
                                 font=("Arial", 10, "bold"), fg="green")
        detected_label.pack(pady=5)
        
        button_frame = tk.Frame(detect_dialog)
        button_frame.pack(pady=20)
        
        add_btn = tk.Button(button_frame, text="Add Key", state=tk.DISABLED,
                           command=lambda: self.add_detected_key(detect_dialog))
        add_btn.pack(side=tk.LEFT, padx=5)
        
        cancel_btn = tk.Button(button_frame, text="Cancel", 
                              command=lambda: self.cancel_key_detection(detect_dialog))
        cancel_btn.pack(side=tk.LEFT, padx=5)
        
        self.detecting_key = True
        self.detected_key = None
        
        def on_key_event(event):
            if not self.detecting_key:
                return
                
            # Build key combination string
            modifiers = []
            if event.name in ['ctrl', 'alt', 'shift', 'cmd']:
                return  # Don't process modifier keys alone
                
            # Check for modifiers
            if keyboard.is_pressed('ctrl'):
                modifiers.append('ctrl')
            if keyboard.is_pressed('alt'):
                modifiers.append('alt')
            if keyboard.is_pressed('shift'):
                modifiers.append('shift')
            if keyboard.is_pressed('cmd'):
                modifiers.append('cmd')
                
            key_combo = '+'.join(modifiers + [event.name])
            
            self.detected_key = key_combo
            detected_label.config(text=f"Detected: {key_combo}")
            add_btn.config(state=tk.NORMAL)
            status_label.config(text="Key combination detected!")
        
        keyboard.on_press(on_key_event)

    def add_detected_key(self, dialog):
        """Add the detected key combination"""
        if self.detected_key and self.detected_key not in self.security_manager.blocked_keys:
            self.security_manager.add_blocked_key(self.detected_key)
            self.load_blocked_keys()
            messagebox.showinfo("Success", f"Added key combination: {self.detected_key}")
        
        self.cancel_key_detection(dialog)

    def cancel_key_detection(self, dialog):
        """Cancel key detection"""
        self.detecting_key = False
        keyboard.unhook_all()
        # Re-setup existing hooks if exam mode is active
        if self.security_manager.is_exam_mode:
            self.security_manager.setup_keyboard_hooks()
        dialog.destroy()

    # NEW: Mouse Detection Methods
    def detect_mouse_button(self):
        """Detect mouse button by listening for click"""
        if self.detecting_mouse:
            return
            
        detect_dialog = tk.Toplevel(self.window)
        detect_dialog.title("🎯 Mouse Detection")
        detect_dialog.geometry("400x200")
        detect_dialog.transient(self.window)
        detect_dialog.grab_set()
        
        # Center dialog
        detect_dialog.update_idletasks()
        x = (detect_dialog.winfo_screenwidth() // 2) - 200
        y = (detect_dialog.winfo_screenheight() // 2) - 100
        detect_dialog.geometry(f"400x200+{x}+{y}")
        
        tk.Label(detect_dialog, text="Click the mouse button you want to block",
                font=("Arial", 12, "bold")).pack(pady=20)
        
        status_label = tk.Label(detect_dialog, text="Waiting for mouse click...",
                               font=("Arial", 10), fg="blue")
        status_label.pack(pady=10)
        
        detected_label = tk.Label(detect_dialog, text="", 
                                 font=("Arial", 10, "bold"), fg="green")
        detected_label.pack(pady=5)
        
        button_frame = tk.Frame(detect_dialog)
        button_frame.pack(pady=20)
        
        add_btn = tk.Button(button_frame, text="Add Button", state=tk.DISABLED,
                           command=lambda: self.add_detected_mouse(detect_dialog))
        add_btn.pack(side=tk.LEFT, padx=5)
        
        cancel_btn = tk.Button(button_frame, text="Cancel", 
                              command=lambda: self.cancel_mouse_detection(detect_dialog))
        cancel_btn.pack(side=tk.LEFT, padx=5)
        
        self.detecting_mouse = True
        self.detected_mouse_button = None
        
        def on_click(x, y, button, pressed):
            if not self.detecting_mouse or not pressed:
                return False
                
            button_name = str(button).replace('Button.', '')
            self.detected_mouse_button = button_name
            
            detected_label.config(text=f"Detected: {button_name}")
            add_btn.config(state=tk.NORMAL)
            status_label.config(text="Mouse button detected!")
            
            return False  # Stop listening
        
        self.mouse_listener = mouse.Listener(on_click=on_click)
        self.mouse_listener.start()

    def add_detected_mouse(self, dialog):
        """Add the detected mouse button"""
        if (self.detected_mouse_button and 
            self.detected_mouse_button not in self.security_manager.mouse_manager.blocked_buttons):
            self.security_manager.mouse_manager.add_blocked_button(self.detected_mouse_button)
            self.load_blocked_mouse_buttons()
            messagebox.showinfo("Success", f"Added mouse button: {self.detected_mouse_button}")
        
        self.cancel_mouse_detection(dialog)

    def cancel_mouse_detection(self, dialog):
        """Cancel mouse detection"""
        self.detecting_mouse = False
        if self.mouse_listener:
            self.mouse_listener.stop()
        dialog.destroy()

    # Continue with rest of existing methods (same implementation)
    def create_logs_tab(self):
        logs_frame = ttk.Frame(self.notebook)
        self.notebook.add(logs_frame, text="📋 Security Logs")
        
        controls_frame = ttk.Frame(logs_frame)
        controls_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        ttk.Button(controls_frame, text="🔄 Refresh", command=self.refresh_logs).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(controls_frame, text="🗑️ Clear All", command=self.clear_logs).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(controls_frame, text="💾 Export", command=self.export_logs).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Label(controls_frame, text="Filter:").pack(side=tk.LEFT, padx=(20, 5))
        self.log_filter_var = tk.StringVar()
        filter_combo = ttk.Combobox(controls_frame, textvariable=self.log_filter_var,
                                   values=["All", "Blocked Only", "Security Events", "System Events"])
        filter_combo.set("All")
        filter_combo.pack(side=tk.LEFT, padx=(0, 10))
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_logs())
        
        logs_display_frame = ttk.LabelFrame(logs_frame, text="Security Activity History", padding="10")
        logs_display_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5, 10))
        
        self.logs_text = scrolledtext.ScrolledText(logs_display_frame, wrap=tk.WORD, height=25)
        self.logs_text.pack(fill=tk.BOTH, expand=True)

    # Rest of the methods remain the same...
    # [Include all the other existing methods like stop_exam_mode, refresh_status, etc.]
    
    def stop_exam_mode(self):
        password = simpledialog.askstring("🔐 SECURITY VERIFICATION",
                                        "Enter admin password to DISABLE lockdown:", show="*")
        if password:
            import hashlib
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            if self.db_manager.verify_admin("admin", password_hash):
                self.security_manager.stop_exam_mode()
                self.start_btn.config(state=tk.NORMAL)
                self.stop_btn.config(state=tk.DISABLED)
                self.refresh_status()
                messagebox.showinfo("🔓 LOCKDOWN DISABLED", "All security restrictions have been removed.")
            else:
                messagebox.showerror("❌ ACCESS DENIED", "Invalid admin password!")

    def emergency_stop(self):
        result1 = messagebox.askyesno("🚨 EMERGENCY STOP",
                                     "This is an EMERGENCY STOP procedure.\n\nAre you sure you want to proceed?")
        if not result1:
            return
            
        result2 = messagebox.askyesno("⚠️ FINAL WARNING",
                                     "This will IMMEDIATELY disable ALL security.\n\nCONFIRM EMERGENCY STOP?")
        if not result2:
            return
            
        password = simpledialog.askstring("🔐 EMERGENCY AUTH",
                                         "Enter admin password for EMERGENCY STOP:", show="*")
        if password:
            import hashlib
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            if self.db_manager.verify_admin("admin", password_hash):
                try:
                    self.security_manager.stop_exam_mode()
                    self.start_btn.config(state=tk.NORMAL)
                    self.stop_btn.config(state=tk.DISABLED)
                    self.refresh_status()
                    messagebox.showwarning("🚨 EMERGENCY STOP EXECUTED",
                                          "Emergency stop completed.\nAll security systems disabled.")
                except Exception as e:
                    messagebox.showerror("Error", f"Emergency stop failed: {str(e)}")
            else:
                messagebox.showerror("❌ ACCESS DENIED", "Invalid admin password!")

    def refresh_status(self):
        # Update main exam mode status
        if self.security_manager.is_exam_mode:
            self.status_label.config(text="🔒 LOCKDOWN MODE: ACTIVE", foreground="red")
        else:
            self.status_label.config(text="🔓 LOCKDOWN MODE: INACTIVE", foreground="green")
        
        # Update system info
        system_info = self.security_manager.get_system_info()
        info_text = f"CPU: {system_info.get('cpu_percent', 0):.1f}% | " \
                   f"RAM: {system_info.get('memory_percent', 0):.1f}% | " \
                   f"Processes: {system_info.get('active_processes', 0)}"
        self.system_info_label.config(text=info_text)
        
        # Update individual security module indicators
        if system_info.get('hooks_active', False):
            self.keyboard_status.config(text="✅ Keyboard", foreground="green")
        else:
            self.keyboard_status.config(text="⚫ Keyboard", foreground="gray")
            
        if system_info.get('mouse_blocking', False):
            self.mouse_status.config(text="✅ Mouse", foreground="green")
        else:
            self.mouse_status.config(text="⚫ Mouse", foreground="gray")
            
        if system_info.get('internet_blocked', False):
            self.network_status.config(text="✅ Network", foreground="green")
        else:
            self.network_status.config(text="⚫ Network", foreground="gray")
            
        if system_info.get('window_protection', False):
            self.window_status.config(text="✅ Windows", foreground="green")
        else:
            self.window_status.config(text="⚫ Windows", foreground="gray")
        
        # Update threat detection
        if self.security_manager.is_exam_mode:
            active_threats = sum([
                not system_info.get('hooks_active', False),
                not system_info.get('mouse_blocking', False),
                not system_info.get('internet_blocked', False),
                not system_info.get('window_protection', False)
            ])
            
            if active_threats == 0:
                self.threat_label.config(text="🛡️ All security systems operational", foreground="green")
            else:
                self.threat_label.config(text=f"⚠️ {active_threats} security modules inactive", foreground="orange")
        else:
            self.threat_label.config(text="ℹ️ Security monitoring inactive", foreground="blue")

    # Individual control dialogs (simplified versions)
    def show_mouse_controls(self):
        mouse_window = tk.Toplevel(self.window)
        mouse_window.title("🖱️ Mouse Security Controls")
        mouse_window.geometry("500x400")
        mouse_window.transient(self.window)
        
        ttk.Label(mouse_window, text="Mouse Button Blocking System", font=("Arial", 14, "bold")).pack(pady=15)
        
        status = "🟢 ACTIVE" if self.security_manager.mouse_manager.is_active else "🔴 INACTIVE"
        ttk.Label(mouse_window, text=f"Status: {status}", font=("Arial", 12)).pack(pady=5)
        
        control_frame = ttk.LabelFrame(mouse_window, text="Controls", padding="20")
        control_frame.pack(pady=20, padx=20, fill=tk.BOTH)
        
        if not self.security_manager.mouse_manager.is_active:
            ttk.Button(control_frame, text="🚀 Activate Mouse Blocking",
                      command=lambda: [self.toggle_mouse_blocking(True), mouse_window.destroy()]).pack(pady=10)
        else:
            ttk.Button(control_frame, text="🛑 Deactivate Mouse Blocking",
                      command=lambda: [self.toggle_mouse_blocking(False), mouse_window.destroy()]).pack(pady=10)
        
        info_frame = ttk.LabelFrame(mouse_window, text="Information", padding="15")
        info_frame.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)
        
        blocked_buttons = ", ".join(self.security_manager.mouse_manager.blocked_buttons)
        ttk.Label(info_frame, text=f"Blocked Buttons: {blocked_buttons}").pack(anchor=tk.W)

    def show_network_controls(self):
        network_window = tk.Toplevel(self.window)
        network_window.title("🌐 Network Security Controls")
        network_window.geometry("500x400")
        network_window.transient(self.window)
        
        ttk.Label(network_window, text="Internet Blocking System", font=("Arial", 14, "bold")).pack(pady=15)
        
        status = "🟢 BLOCKED" if self.security_manager.network_manager.is_blocked else "🔴 ALLOWED"
        ttk.Label(network_window, text=f"Internet Access: {status}", font=("Arial", 12)).pack(pady=5)
        
        control_frame = ttk.LabelFrame(network_window, text="Controls", padding="20")
        control_frame.pack(pady=20, padx=20, fill=tk.BOTH)
        
        if not self.security_manager.network_manager.is_blocked:
            ttk.Button(control_frame, text="🚀 Activate Internet Blocking",
                      command=lambda: [self.toggle_internet_blocking(True), network_window.destroy()]).pack(pady=10)
        else:
            ttk.Button(control_frame, text="🛑 Restore Internet Access",
                      command=lambda: [self.toggle_internet_blocking(False), network_window.destroy()]).pack(pady=10)

    def show_window_controls(self):
        window_control = tk.Toplevel(self.window)
        window_control.title("🪟 Window Guardian Controls")
        window_control.geometry("500x400")
        window_control.transient(self.window)
        
        ttk.Label(window_control, text="Window Protection System", font=("Arial", 14, "bold")).pack(pady=15)
        
        status = "🟢 ACTIVE" if self.security_manager.window_manager.is_active else "🔴 INACTIVE"
        ttk.Label(window_control, text=f"Status: {status}", font=("Arial", 12)).pack(pady=5)

    def toggle_mouse_blocking(self, enable):
        if enable:
            self.security_manager.mouse_manager.start_blocking()
            messagebox.showinfo("✅ Activated", "Mouse blocking is now active!")
        else:
            self.security_manager.mouse_manager.stop_blocking()
            messagebox.showinfo("✅ Deactivated", "Mouse blocking has been disabled.")
        self.refresh_status()

    def toggle_internet_blocking(self, enable):
        if enable:
            messagebox.showinfo("⏳ Processing", "Activating comprehensive internet blocking...\nThis may take a moment.")
            self.security_manager.network_manager.start_blocking()
            messagebox.showinfo("✅ Activated", "Internet blocking is now active!")
        else:
            self.security_manager.network_manager.stop_blocking()
            messagebox.showinfo("✅ Restored", "Internet access has been restored.")
        self.refresh_status()

    def toggle_window_protection(self, enable):
        if enable:
            self.security_manager.window_manager.start_window_protection()
            messagebox.showinfo("✅ Activated", "Window protection is now active!")
        else:
            self.security_manager.window_manager.stop_window_protection()
            messagebox.showinfo("✅ Deactivated", "Window protection has been disabled.")
        self.refresh_status()

    # Additional required methods...
    def load_blocked_keys(self):
        self.blocked_keys_listbox.delete(0, tk.END)
        for key in self.security_manager.blocked_keys:
            self.blocked_keys_listbox.insert(tk.END, key)

    def add_blocked_key(self):
        key_combo = simpledialog.askstring("Add Blocked Key", "Enter key combination (e.g., 'ctrl+c'):")
        if key_combo:
            self.security_manager.add_blocked_key(key_combo)
            self.load_blocked_keys()

    def remove_blocked_key(self):
        selection = self.blocked_keys_listbox.curselection()
        if selection:
            key_combo = self.blocked_keys_listbox.get(selection[0])
            self.security_manager.remove_blocked_key(key_combo)
            self.load_blocked_keys()

    def reset_default_keys(self):
        from config import Config
        self.security_manager.blocked_keys = Config.BLOCKED_KEYS.copy()
        self.load_blocked_keys()

    def load_blocked_mouse_buttons(self):
        self.blocked_mouse_listbox.delete(0, tk.END)
        for button in self.security_manager.mouse_manager.blocked_buttons:
            self.blocked_mouse_listbox.insert(tk.END, button)

    def add_blocked_mouse(self):
        button = simpledialog.askstring("Add Blocked Mouse Button", "Enter mouse button (middle, x1, x2, side):")
        if button and button not in self.security_manager.mouse_manager.blocked_buttons:
            self.security_manager.mouse_manager.add_blocked_button(button)
            self.load_blocked_mouse_buttons()

    def remove_blocked_mouse(self):
        selection = self.blocked_mouse_listbox.curselection()
        if selection:
            button = self.blocked_mouse_listbox.get(selection[0])
            self.security_manager.mouse_manager.remove_blocked_button(button)
            self.load_blocked_mouse_buttons()

    def load_blocked_websites(self):
        self.blocked_websites_listbox.delete(0, tk.END)
        from config import Config
        for website in Config.BLOCKED_WEBSITES:
            self.blocked_websites_listbox.insert(tk.END, website)

    def add_blocked_website(self):
        website = simpledialog.askstring("Add Blocked Website", "Enter website (e.g., example.com):")
        if website:
            from config import Config
            if website not in Config.BLOCKED_WEBSITES:
                Config.BLOCKED_WEBSITES.append(website)
                self.load_blocked_websites()

    def remove_blocked_website(self):
        selection = self.blocked_websites_listbox.curselection()
        if selection:
            website = self.blocked_websites_listbox.get(selection[0])
            from config import Config
            if website in Config.BLOCKED_WEBSITES:
                Config.BLOCKED_WEBSITES.remove(website)
                self.load_blocked_websites()

    def save_settings(self):
        try:
            self.db_manager.save_setting("auto_start_exam", str(self.auto_start_var.get()))
            blocked_keys_json = json.dumps(self.security_manager.blocked_keys)
            self.db_manager.save_setting("blocked_keys", blocked_keys_json)
            blocked_mouse_json = json.dumps(self.security_manager.mouse_manager.blocked_buttons)
            self.db_manager.save_setting("blocked_mouse_buttons", blocked_mouse_json)
            self.db_manager.save_setting("block_internet", str(self.block_internet_var.get()))
            self.db_manager.save_setting("window_protection", str(self.window_protection_var.get()))
            self.db_manager.save_setting("process_monitoring", str(self.process_monitoring_var.get()))
            messagebox.showinfo("✅ Success", "All settings saved successfully!")
        except Exception as e:
            messagebox.showerror("❌ Error", f"Failed to save settings: {str(e)}")

    def refresh_logs(self):
        logs = self.db_manager.get_activity_logs(100)
        self.logs_text.delete(1.0, tk.END)
        
        filter_type = self.log_filter_var.get()
        for log in logs:
            action, details, timestamp, blocked = log
            status = "BLOCKED" if blocked else "ALLOWED"
            
            if filter_type == "Blocked Only" and not blocked:
                continue
            elif filter_type == "Security Events" and not any(x in action for x in ["BLOCKED", "SECURITY", "SUSPICIOUS"]):
                continue
            elif filter_type == "System Events" and not any(x in action for x in ["SYSTEM", "EXAM_MODE"]):
                continue
            
            log_line = f"[{timestamp}] {action}: {details or 'N/A'} - {status}\n"
            self.logs_text.insert(tk.END, log_line)
        
        self.logs_text.see(tk.END)

    def clear_logs(self):
        result = messagebox.askyesno("⚠️ Confirm", "Clear all activity logs?\n\nThis action cannot be undone.")
        if result:
            try:
                self.logs_text.delete(1.0, tk.END)
                messagebox.showinfo("✅ Success", "Display logs cleared!")
            except Exception as e:
                messagebox.showerror("❌ Error", f"Failed to clear logs: {str(e)}")

    def export_logs(self):
        from tkinter import filedialog
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                logs = self.db_manager.get_activity_logs(1000)
                if filename.endswith('.csv'):
                    with open(filename, 'w', newline='') as f:
                        f.write("Timestamp,Action,Details,Status\n")
                        for log in logs:
                            action, details, timestamp, blocked = log
                            status = "BLOCKED" if blocked else "ALLOWED"
                            details_clean = details if details else "N/A"
                            f.write(f'"{timestamp}","{action}","{details_clean}","{status}"\n')
                else:
                    with open(filename, 'w') as f:
                        f.write("EXAM SHIELD SECURITY LOGS\n")
                        f.write("=" * 50 + "\n")
                        f.write(f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"Total Entries: {len(logs)}\n")
                        f.write("=" * 50 + "\n\n")
                        
                        for log in logs:
                            action, details, timestamp, blocked = log
                            status = "BLOCKED" if blocked else "ALLOWED"
                            f.write(f"[{timestamp}] {status}: {action}\n")
                            f.write(f"Details: {details or 'No additional details'}\n\n")
                
                messagebox.showinfo("✅ Success", f"Logs exported successfully to:\n{filename}")
            except Exception as e:
                messagebox.showerror("❌ Error", f"Export failed: {str(e)}")

    def start_auto_refresh(self):
        def refresh_loop():
            while True:
                try:
                    if self.window.winfo_exists():
                        self.window.after(0, self.refresh_status)
                        if hasattr(self, 'activity_tree'):
                            self.window.after(0, self.update_activity_feed)
                    threading.Event().wait(2)
                except:
                    break
        
        refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
        refresh_thread.start()

    def update_activity_feed(self):
        try:
            for item in self.activity_tree.get_children():
                self.activity_tree.delete(item)
            
            logs = self.db_manager.get_activity_logs(20)
            
            for log in logs:
                action, details, timestamp, blocked = log
                status = "🚫 BLOCKED" if blocked else "✅ ALLOWED"
                
                if blocked or "SUSPICIOUS" in action or "TERMINATED" in action:
                    severity = "🔴 HIGH"
                elif "BLOCKED" in action or "SECURITY" in action:
                    severity = "🟡 MED"
                else:
                    severity = "🟢 LOW"
                
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    time_str = dt.strftime("%H:%M:%S")
                except:
                    time_str = timestamp
                
                self.activity_tree.insert("", 0, values=(time_str, severity, action, details or "No details", status))
        except Exception as e:
            pass

    def on_close(self):
        result = messagebox.askyesno("⚠️ Confirm Exit",
                                    "Close Admin Panel?\n\nThe system will continue running in the background.\n"
                                    "Access it again from the system tray.")
        if result:
            self.window.withdraw()

    def show(self):
        self.window.deiconify()
        self.window.lift()
        self.refresh_status()
        self.load_blocked_keys()
        self.load_blocked_mouse_buttons()
        self.load_blocked_websites()
