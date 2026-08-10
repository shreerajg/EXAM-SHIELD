"""
ExamShield v1.2.0 - Audio Manager
Monitors ambient audio to detect talking or excessive noise during the exam.
"""
import threading
import sounddevice as sd
import numpy as np
from src.config import Config

class AudioManager:
    def __init__(self, db_manager):
        self.db = db_manager
        self.log = db_manager.logger
        self.is_active = False
        self._thread = None
        self._stop_event = threading.Event()
        self.sustained_noise_count = 0
        self.security_manager = None

    def set_security_manager(self, sm):
        self.security_manager = sm

    def start(self):
        if self.is_active: return
        self.is_active = True
        self._stop_event.clear()
        self.sustained_noise_count = 0
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        self.log.info("AUDIO", "Audio monitoring started")

    def stop(self):
        self.is_active = False
        self._stop_event.set()
        if self._thread:
            self._thread = None
        self.log.info("AUDIO", "Audio monitoring stopped")

    def _monitor_loop(self):
        try:
            samplerate = 44100
            duration = Config.AUDIO_MONITOR_INTERVAL_SEC
            
            while self.is_active and not self._stop_event.is_set():
                # Record for a short duration
                myrecording = sd.rec(int(duration * samplerate), samplerate=samplerate, channels=1, dtype='float64')
                sd.wait() # Wait until recording is finished
                
                # Calculate RMS
                rms = np.sqrt(np.mean(myrecording**2))
                
                # Convert RMS to a somewhat arbitrary 0-100 scale for thresholding
                # This depends heavily on microphone sensitivity.
                # Just multiplying by a factor to make it readable in config
                noise_level = rms * 1000 
                
                if noise_level > Config.AUDIO_THRESHOLD:
                    self.sustained_noise_count += 1
                    if self.sustained_noise_count >= Config.AUDIO_SUSTAINED_TOLERANCE:
                        self._trigger_violation(noise_level)
                        self.sustained_noise_count = 0
                else:
                    self.sustained_noise_count = 0
                    
        except Exception as e:
            self.log.error("AUDIO", f"Error in audio monitor loop: {e}")

    def _trigger_violation(self, level):
        msg = f"High ambient noise detected (Level: {level:.1f})"
        self.log.security("AUDIO_VIOLATION", msg, blocked=True)
        if self.security_manager:
            if 'audio' not in self.security_manager.breach_counts:
                self.security_manager.breach_counts['audio'] = 0
            self.security_manager.breach_counts['audio'] += 1
            self.security_manager.screenshot_manager.capture_violation(reason="audio_noise")
            
            panel = self.security_manager.admin_panel
            if panel and hasattr(panel, 'window'):
                try:
                    panel.window.after(0, panel.update_breach_counter)
                    panel.window.after(0, lambda m=msg: panel._toast(f"🎤  {m}", '#ff4757') if hasattr(panel, '_toast') else None)
                except Exception:
                    pass
