"""
ExamShield v1.0 — Configuration
Central configuration for all modules.
"""
import os

class Config:
    # ── Application ──────────────────────────────────────────────
    APP_NAME = "Exam Shield"
    VERSION = "1.3.0"
    BUILD = "stable"

    # ── Secure Browser ───────────────────────────────────────────
    USE_SECURE_BROWSER = True
    EXAM_URL = "https://example.com/exam"

    # ── Paths ────────────────────────────────────────────────────
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATABASE_NAME = "exam_shield.db"
    # Database lives one level up (project root), next to main.py
    DATABASE_PATH = os.path.join(os.path.dirname(BASE_DIR), DATABASE_NAME)
    LOG_DIR = os.path.join(BASE_DIR, "logs")
    SCREENSHOT_DIR = os.path.join(LOG_DIR, "screenshots")
    REPORT_DIR = os.path.join(LOG_DIR, "reports")

    # ── Screenshot Monitoring ─────────────────────────────────────
    SCREENSHOT_INTERVAL_SEC = 60    # capture every N seconds during lockdown (overridable from Settings UI)

    # ── Webcam Monitoring ─────────────────────────────────────────
    WEBCAM_MONITOR_INTERVAL_SEC = 5 # check webcam every N seconds
    WEBCAM_FACE_ABSENCE_TOLERANCE = 3 # number of consecutive checks without a face before alerting

    # ── Audio Monitoring ──────────────────────────────────────────
    AUDIO_MONITOR_INTERVAL_SEC = 2
    AUDIO_THRESHOLD = 50.0 # RMS threshold for detecting speech/noise
    AUDIO_SUSTAINED_TOLERANCE = 3 # number of consecutive noisy chunks before alerting
    AUDIO_SPEECH_RECOGNITION = True # Use offline speech recognition
    AUDIO_SPEECH_LANGUAGE = "en-US"

    # ── Bluetooth Monitoring ──────────────────────────────────────
    BLUETOOTH_MONITOR_INTERVAL_SEC = 5

    # ── Login Security ────────────────────────────────────────────
    # Escalating lockout: each failed attempt beyond MAX_ATTEMPTS triggers
    # a longer lockout tier.  Tiers defined in DatabaseManager._LOCKOUT_TIERS.
    LOGIN_MAX_ATTEMPTS   = 3     # attempts allowed before FIRST lockout
    LOGIN_LOCKOUT_SEC    = 60    # Tier-1 lockout (kept for countdown display)

    # ── Default Credentials ──────────────────────────────────────
    # NOTE: No plaintext default password is stored here.
    # On first run, DatabaseManager generates a random password and prints
    # it to the console once.  The admin must change it immediately.
    DEFAULT_ADMIN_USERNAME = "admin"

    # ── Keyboard Blocking ────────────────────────────────────────
    BLOCKED_KEYS = [
        # Alt combos
        'alt+tab', 'alt+f4', 'alt+esc', 'alt+space', 'alt+enter',
        # Ctrl combos
        'ctrl+alt+del', 'ctrl+shift+esc', 'ctrl+esc',
        'ctrl+w', 'ctrl+n', 'ctrl+f4', 'ctrl+shift+n', 'ctrl+shift+t',
        # Win key combos
        'win+d', 'win+l', 'win+r', 'win+e', 'win+s', 'win+i',
        'win+a', 'win+x', 'win+tab', 'win+p', 'win+b', 'win+k',
        'win+m', 'win+h', 'win+g', 'win+u', 'win+v',
        # Win + taskbar number shortcuts (switch apps)
        'win+1', 'win+2', 'win+3', 'win+4', 'win+5',
        'win+6', 'win+7', 'win+8', 'win+9', 'win+0',
        # Ctrl+Alt+Arrow (rotate screen)
        'ctrl+alt+up', 'ctrl+alt+down', 'ctrl+alt+left', 'ctrl+alt+right',
        # Function keys
        'f11', 'f1',
        # ── Layer 1: Screen capture & DevTools ──────────────────────
        # PrintScreen variants (silent screenshots)
        'print screen',
        'alt+print screen',
        'ctrl+print screen',
        'win+print screen',
        # Snipping Tool (Win+Shift+S opens the snip overlay)
        'win+shift+s',
        # Browser DevTools — all common shortcuts
        'f12',
        'ctrl+shift+i',        # DevTools (Chrome/Edge/Firefox)
        'ctrl+shift+j',        # Console (Chrome/Edge)
        'ctrl+shift+c',        # Inspect element
        'ctrl+shift+k',        # Console (Firefox)
        # Browser save / print / view-source
        'ctrl+s',              # Save page as
        'ctrl+p',              # Print (can export page content)
        'ctrl+u',              # View page source
        # Additional browser tab/navigation shortcuts
        'ctrl+l',              # Focus address bar
        'alt+d',               # Focus address bar (IE/Edge)
        'ctrl+t',              # New tab
        'ctrl+shift+p',        # Private/Incognito window
    ]

    # ── Mouse Blocking ───────────────────────────────────────────
    BLOCKED_MOUSE_BUTTONS = ['middle', 'x1', 'x2', 'side']

    # ── Admin Hotkey ─────────────────────────────────────────────
    # SECURITY: These keys are NOT displayed anywhere in the UI.
    # The admin hotkey requires password re-authentication before revealing the panel.
    ADMIN_ACCESS_KEY = 'ctrl+shift+y'
    STEALTH_MODE_KEY = 'ctrl+shift+h'

    # ── Selective Blocking Defaults ──────────────────────────────
    SELECTIVE_BLOCKING = {
        'keyboard': True,
        'mouse': True,
        'internet': True,
        'windows': True,
        'processes': True,
        'usb': True,
        'clipboard': True,
        'vm_rdp': True,
        'multi_monitor': True,
        'webcam': True,
        'audio': True,
        'bluetooth': True,
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

    # ── Allowed Websites (whitelist, excluded from blocking) ─────
    ALLOWED_WEBSITES: list = []

    # ── Suspicious Processes ─────────────────────────────────────
    SUSPICIOUS_PROCESSES = [
        # System escape tools
        'taskmgr.exe', 'cmd.exe', 'powershell.exe', 'pwsh.exe',
        'regedit.exe', 'msconfig.exe', 'mmc.exe', 'control.exe',
        # Process / system analysis
        'procexp.exe', 'procexp64.exe', 'procmon.exe', 'procmon64.exe',
        'autoruns.exe', 'autorunsc.exe', 'tcpview.exe',
        # Debuggers / reverse-engineering
        'x32dbg.exe', 'x64dbg.exe', 'ollydbg.exe', 'windbg.exe',
        'ida64.exe', 'ida.exe', 'radare2.exe',
        # Network bypass
        'wireshark.exe', 'fiddler.exe', 'charles.exe', 'mitmproxy.exe',
        'tor.exe', 'privoxy.exe', 'proxifier.exe',
        # Remote access / screen share
        'teamviewer.exe', 'anydesk.exe', 'vnc.exe', 'vncviewer.exe',
        'ultraviewer.exe', 'radmin.exe', 'ammyy.exe',
        # Communication / AI cheating
        'discord.exe', 'slack.exe', 'zoom.exe', 'teams.exe',
        'skype.exe', 'telegram.exe', 'whatsapp.exe',
        # Dev environments
        'code.exe', 'pycharm64.exe', 'idea64.exe', 'devenv.exe',
        'notepad++.exe', 'sublime_text.exe', 'atom.exe',
        # Browsers (standalone attempts outside allowed ones)
        'tor browser.exe',
        # VPN / tunnel clients
        'openvpn.exe', 'vpnui.exe', 'nordvpn.exe', 'expressvpn.exe',
        'tunnelbear.exe', 'protonvpn.exe',
        # Clipboard extenders / macro tools
        'autohotkey.exe', 'ahk.exe', 'keypirinha.exe',
        # Screen sharing / remote input
        'rustdesk.exe', 'chrome remote desktop.exe',
        # ── Layer 2: Screen recording software ──────────────────────
        'obs32.exe', 'obs64.exe',              # OBS Studio
        'bandicam.exe',                         # Bandicam
        'fraps.exe',                            # Fraps
        'camstudio.exe',                        # CamStudio
        'flashbackrecorder.exe',                # FlashBack
        'sharex.exe',                           # ShareX (screenshot+record)
        'gyazo.exe',                            # Gyazo
        'lightshot.exe',                        # Lightshot
        'greenshot.exe',                        # Greenshot
        'screenpresso.exe',                     # Screenpresso
        'picpick.exe',                          # PicPick
        'snagit32.exe', 'snagiteditor.exe',     # TechSmith Snagit
        'recordit.exe',                         # Recordit
        'loom.exe',                             # Loom
        'camtasia.exe',                         # Camtasia
        # ── Layer 2: AI desktop assistants (cheating vectors) ──────
        'chatgpt.exe',                          # OpenAI ChatGPT desktop
        'claude.exe',                           # Anthropic Claude desktop
        'copilot.exe',                          # Microsoft Copilot
        'perplexity.exe',                       # Perplexity AI
        'cursor.exe',                           # Cursor AI IDE
        'github copilot.exe',
        # ── Layer 2: Windows scripting engines (automation bypass) ──
        'wscript.exe',                          # Windows Script Host (VBScript/JS)
        'cscript.exe',                          # Console Script Host
        'mshta.exe',                            # HTA application host
        # ── Layer 2: Additional browsers ────────────────────────────
        'vivaldi.exe',                          # Vivaldi browser
        'brave.exe',                            # Brave browser
        'msedgewebview2.exe',                   # Edge WebView2 (embedded)
        'opera.exe',                            # Opera browser
        # ── Layer 2: VM frontends (if running during exam) ──────────
        'virtualboxvm.exe', 'vmplayer.exe',
        'vmware-vmx.exe',
    ]

    # ── Process Monitor Interval (seconds) ───────────────────────
    PROCESS_MONITOR_INTERVAL = 0.5   # seconds — tight enough to catch fast attempts

    # ── Layer 6: Idle Detection ───────────────────────────────────
    # Seconds of no mouse/keyboard input before capturing an idle-absence screenshot
    IDLE_ALERT_SEC = 300             # 5 minutes default
    IDLE_COOLDOWN_SEC = 60           # minimum gap between repeated idle alerts

    # ── Layer 5: Full Internet Block ─────────────────────────────
    # When True, blocks ALL outbound traffic (IPv4 + IPv6), not just listed sites.
    # Recommended for high-security exams. Requires admin elevation (same as existing rules).
    FULL_INTERNET_BLOCK = False

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

    # ── Theme Palettes ───────────────────────────────────────────
    THEMES = {
        'cyan': {
            'primary': '#00d4ff', 'primary_dark': '#0099bb', 'primary_glow': '#00d4ff33',
            'accent': '#7f5af0', 'accent_dark': '#6040d0', 'accent_glow': '#7f5af033',
        },
        'emerald': {
            'primary': '#10b981', 'primary_dark': '#059669', 'primary_glow': '#10b98133',
            'accent': '#3b82f6', 'accent_dark': '#2563eb', 'accent_glow': '#3b82f633',
        },
        'crimson': {
            'primary': '#f43f5e', 'primary_dark': '#e11d48', 'primary_glow': '#f43f5e33',
            'accent': '#f59e0b', 'accent_dark': '#d97706', 'accent_glow': '#f59e0b33',
        },
        'amethyst': {
            'primary': '#a855f7', 'primary_dark': '#9333ea', 'primary_glow': '#a855f733',
            'accent': '#ec4899', 'accent_dark': '#db2777', 'accent_glow': '#ec489933',
        }
    }
    ACTIVE_THEME = 'cyan'

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