"""
ExamShield v1.0 — Configuration
Central configuration for all modules.
"""
import os

class Config:
    # ── Application ──────────────────────────────────────────────
    APP_NAME = "Exam Shield"
    VERSION = "1.0.0"
    BUILD = "stable"

    # ── Paths ────────────────────────────────────────────────────
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATABASE_NAME = "exam_shield.db"
    DATABASE_PATH = os.path.join(BASE_DIR, DATABASE_NAME)
    LOG_DIR = os.path.join(BASE_DIR, "logs")

    # ── Default Credentials ──────────────────────────────────────
    DEFAULT_ADMIN_USERNAME = "admin"
    DEFAULT_ADMIN_PASSWORD = "admin"

    # ── Keyboard Blocking ────────────────────────────────────────
    BLOCKED_KEYS = [
        'alt+tab', 'alt+f4', 'win+d', 'win+l', 'win+r',
        'ctrl+alt+del', 'ctrl+shift+esc', 'f11', 'alt+space',
        'win+tab', 'ctrl+alt+t', 'win+e', 'win+s',
        'win+i', 'win+a', 'win+x', 'ctrl+esc',
    ]

    # ── Mouse Blocking ───────────────────────────────────────────
    BLOCKED_MOUSE_BUTTONS = ['middle', 'x1', 'x2', 'side']

    # ── Admin Hotkey ─────────────────────────────────────────────
    ADMIN_ACCESS_KEY = 'ctrl+shift+y'

    # ── Selective Blocking Defaults ──────────────────────────────
    SELECTIVE_BLOCKING = {
        'keyboard': True,
        'mouse': True,
        'internet': True,
        'windows': True,
        'processes': True,
        'usb': True,
    }

    # ── Network Blocking ─────────────────────────────────────────
    BLOCK_INTERNET = True
    BLOCKED_WEBSITES = [
        'google.com', 'www.google.com', 'google.co.in', 'www.google.co.in',
        'youtube.com', 'www.youtube.com', 'youtu.be', 'm.youtube.com',
        'facebook.com', 'www.facebook.com', 'fb.com', 'm.facebook.com',
        'twitter.com', 'www.twitter.com', 'x.com', 'www.x.com',
        'instagram.com', 'www.instagram.com',
        'tiktok.com', 'www.tiktok.com',
        'reddit.com', 'www.reddit.com',
        'discord.com', 'www.discord.com',
        'whatsapp.com', 'web.whatsapp.com',
        'telegram.org', 'web.telegram.org',
        'snapchat.com', 'www.snapchat.com',
    ]

    # ── Suspicious Processes ─────────────────────────────────────
    SUSPICIOUS_PROCESSES = [
        'taskmgr.exe', 'cmd.exe', 'powershell.exe', 'pwsh.exe',
        'regedit.exe', 'msconfig.exe', 'mmc.exe', 'devmgmt.msc',
        'control.exe',
    ]

    # ── Process Monitor Interval (seconds) ───────────────────────
    PROCESS_MONITOR_INTERVAL = 2

    # ── UI Palette ───────────────────────────────────────────────
    COLORS = {
        # Backgrounds
        'bg':           '#0a0a1a',
        'surface':      '#12122a',
        'surface_alt':  '#1a1a3a',
        'card':         '#16163a',
        'sidebar':      '#0d0d22',
        'sidebar_hover':'#1e1e42',

        # Accent
        'primary':      '#00d4ff',
        'primary_dark': '#0099bb',
        'primary_glow': '#00d4ff33',
        'accent':       '#7f5af0',
        'accent_dark':  '#6040d0',
        'accent_glow':  '#7f5af033',

        # Status
        'success':      '#00e676',
        'success_dark': '#00b050',
        'danger':       '#ff4757',
        'danger_dark':  '#cc2233',
        'warning':      '#ffab40',
        'warning_dark': '#e08000',
        'info':         '#54a0ff',

        # Text
        'text':         '#e8e8f0',
        'text_dim':     '#6a6a9e',
        'text_bright':  '#ffffff',

        # Borders / misc
        'border':       '#252550',
        'border_bright':'#3a3a70',
        'input_bg':     '#0d0d28',
        'highlight':    '#00d4ff22',

        # Sidebar item active indicator
        'sidebar_active': '#00d4ff',
    }

    # ── Fonts ────────────────────────────────────────────────────
    FONTS = {
        'heading':  ('Segoe UI', 18, 'bold'),
        'subhead':  ('Segoe UI', 13, 'bold'),
        'body':     ('Segoe UI', 10),
        'body_sm':  ('Segoe UI', 9),
        'mono':     ('Consolas', 9),
        'mono_md':  ('Consolas', 11),
        'label':    ('Segoe UI', 10, 'bold'),
        'btn':      ('Segoe UI', 11, 'bold'),
        'btn_sm':   ('Segoe UI', 9, 'bold'),
    }

    # ── Animation ────────────────────────────────────────────────
    ANIM_STEP_MS = 16           # ~60 fps
    ANIM_FADE_STEPS = 20        # steps for fade-in
    PULSE_INTERVAL_MS = 1200    # pulse beat period

    # ── Logging ──────────────────────────────────────────────────
    LOG_RETENTION_DAYS = 30
    MAX_LOG_ENTRIES = 10000