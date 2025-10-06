"""
Configuration settings for Exam Shield
"""
import os

class Config:
    # Application settings
    APP_NAME = "Exam Shield"
    VERSION = "1.1.0"
    
    # Database settings
    DATABASE_NAME = "exam_shield.db"
    DATABASE_PATH = os.path.join(os.path.dirname(__file__), DATABASE_NAME)
    
    # Security settings
    DEFAULT_ADMIN_USERNAME = "admin"
    DEFAULT_ADMIN_PASSWORD = "admin"
    
    # Blocked keys
    BLOCKED_KEYS = [
        'alt+tab', 'alt+f4', 'win+d', 'win+l', 'win+r',
        'ctrl+alt+del', 'ctrl+shift+esc', 'f11', 'alt+space',
        'win+tab', 'ctrl+alt+t'
    ]
    
    # Blocked mouse buttons
    BLOCKED_MOUSE_BUTTONS = [
        'middle', 'x1', 'x2', 'side'
    ]
    
    # FIXED: Changed admin access key to Ctrl+Shift+Y
    ADMIN_ACCESS_KEY = 'ctrl+shift+y'
    
    # NEW: Individual blocking control flags
    SELECTIVE_BLOCKING = {
        'keyboard': True,
        'mouse': True,
        'internet': True,
        'windows': True,
        'processes': True
    }
    
    # Network blocking settings
    BLOCK_INTERNET = True
    BLOCKED_WEBSITES = [
        'google.com', 'facebook.com', 'youtube.com', 'twitter.com',
        'instagram.com', 'tiktok.com', 'reddit.com', 'discord.com'
    ]
    
    # UI Colors
    COLORS = {
        'primary': '#2196F3',
        'secondary': '#FFC107',
        'success': '#4CAF50',
        'danger': '#F44336',
        'warning': '#FF9800',
        'info': '#00BCD4',
        'light': '#F5F5F5',
        'dark': '#212121'
    }
    
    # Logging settings
    LOG_RETENTION_DAYS = 30
    MAX_LOG_ENTRIES = 10000
