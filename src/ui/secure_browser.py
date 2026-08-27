"""
ExamShield - Secure Embedded Browser
Runs the exam inside a pywebview instance.
Can be executed as a standalone process to avoid blocking the main Tkinter thread.
"""
import sys
import webview
import time

class SecureBrowser:
    def __init__(self, url):
        self.url = url
        self.window = None

    def start(self):
        # Create a fullscreen, always-on-top, frameless window
        self.window = webview.create_window(
            'Secure Exam Environment',
            self.url,
            fullscreen=True,
            frameless=True,
            on_top=True
        )
        
        # Start the webview application.
        # We use the default engine (Edge Chromium / WebView2 on Windows)
        webview.start(
            private_mode=True, # no cookies/history persisted
            gui='edgechromium' # force edge chromium if available
        )

if __name__ == "__main__":
    url = "https://example.com/exam"
    if len(sys.argv) > 1:
        url = sys.argv[1]
    
    # Wait a moment for the main app to minimize/hide before showing this
    time.sleep(0.5)
    
    browser = SecureBrowser(url)
    try:
        browser.start()
    except Exception as e:
        print(f"Browser error: {e}")
        sys.exit(1)
