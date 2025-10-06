"""
Mouse Manager for Exam Shield
Handles mouse button blocking and restrictions
"""

import threading
import time
from pynput import mouse
from config import Config

class MouseManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.is_active = False
        self.listener = None
        self.blocked_buttons = Config.BLOCKED_MOUSE_BUTTONS.copy()

    def start_blocking(self):
        if self.is_active:
            return
        self.is_active = True
        try:
            self.listener = mouse.Listener(
                on_click=self._on_mouse_click,
                suppress=True,
                win32_event_filter=self._win32_event_filter
            )
            self.listener.start()
            self.db_manager.log_activity("MOUSE_BLOCKING_START",
                                         f"Blocked buttons: {', '.join(self.blocked_buttons)}")
            print("✅ Mouse blocking activated")
        except Exception as e:
            print(f"❌ Error starting mouse blocking: {e}")
            self.is_active = False

    def stop_blocking(self):
        if not self.is_active:
            return
        self.is_active = False
        if self.listener:
            try:
                self.listener.stop()
                self.listener = None
                self.db_manager.log_activity("MOUSE_BLOCKING_STOP",
                                             "Mouse blocking deactivated")
                print("✅ Mouse blocking deactivated")
            except Exception as e:
                print(f"❌ Error stopping mouse blocking: {e}")

    def _win32_event_filter(self, msg, data):
        if not self.is_active:
            return True
        blocked_messages = []
        if 'middle' in self.blocked_buttons:
            blocked_messages.extend([0x0207, 0x0208])  # WM_MBUTTONDOWN, WM_MBUTTONUP
        if 'x1' in self.blocked_buttons or 'x2' in self.blocked_buttons:
            blocked_messages.extend([0x020B, 0x020C])  # WM_XBUTTONDOWN, WM_XBUTTONUP
        if 'side' in self.blocked_buttons:
            blocked_messages.extend([0x020B, 0x020C])  # Side buttons use XBUTTON messages
        if msg in blocked_messages:
            button_name = self._get_button_from_message(msg, data)
            self.db_manager.log_activity("BLOCKED_MOUSE_BUTTON",
                                         f"Blocked {button_name} mouse button", blocked=True)
            print(f"🚫 Blocked mouse button: {button_name}")
            self.listener.suppress_event()
            return False
        return True

    def _get_button_from_message(self, msg, data):
        if msg in [0x0207, 0x0208]:
            return "middle"
        elif msg in [0x020B, 0x020C]:
            if hasattr(data, 'mouseData'):
                if data.mouseData >> 16 == 1:
                    return "x1"
                elif data.mouseData >> 16 == 2:
                    return "x2"
            return "side"
        return "unknown"

    def _on_mouse_click(self, x, y, button, pressed):
        if not self.is_active or not pressed:
            return True
        button_name = self._get_button_name(button)
        if button_name in self.blocked_buttons:
            self.db_manager.log_activity("BLOCKED_MOUSE_BUTTON",
                                         f"Attempted to use: {button_name} at ({x}, {y})",
                                         blocked=True)
            print(f"🚫 Blocked mouse button: {button_name}")
            return False
        return True

    def _get_button_name(self, button):
        button_map = {
            mouse.Button.left: 'left',
            mouse.Button.right: 'right',
            mouse.Button.middle: 'middle',
        }
        if hasattr(button, 'name'):
            return button.name
        elif hasattr(button, 'value'):
            if button.value == 8:
                return 'x1'
            elif button.value == 9:
                return 'x2'
        return button_map.get(button, 'unknown')

    def add_blocked_button(self, button_name):
        if button_name not in self.blocked_buttons:
            self.blocked_buttons.append(button_name)

    def remove_blocked_button(self, button_name):
        if button_name in self.blocked_buttons:
            self.blocked_buttons.remove(button_name)
