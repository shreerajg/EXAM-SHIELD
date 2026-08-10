"""
ExamShield v1.2.0 - Audio Manager
Monitors ambient audio to detect talking or excessive noise during the exam.
"""
import threading
from src.config import Config

try:
    import sounddevice as sd
    import numpy as np
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

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
        if not AUDIO_AVAILABLE:
            self.log.error("AUDIO", "Dependencies missing (sounddevice/numpy). Audio monitoring disabled.")
            return
            
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
            
            # Check if there's any default input device
            try:
                device_info = sd.query_devices(kind='input')
                if not device_info:
                    self.log.error("AUDIO", "No default audio input device found. Audio monitoring disabled.")
                    self.is_active = False
                    return
            except Exception as e:
                self.log.error("AUDIO", f"Failed to query audio devices: {e}. Audio monitoring disabled.")
                self.is_active = False
                return

            error_count = 0
            while self.is_active and not self._stop_event.is_set():
                try:
                    # Record for a short duration
                    myrecording = sd.rec(int(duration * samplerate), samplerate=samplerate, channels=1, dtype='float64')
                    sd.wait() # Wait until recording is finished
                    
                    # Reset error count on success
                    error_count = 0
                    
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
                        
                except sd.PortAudioError as pe:
                    error_count += 1
                    self.log.error("AUDIO", f"Audio recording error: {pe} (Attempt {error_count})")
                    if error_count > 3:
                        self.log.error("AUDIO", "Too many audio failures. Stopping audio monitor.")
                        break
                    self._stop_event.wait(duration)
                except Exception as loop_e:
                    self.log.error("AUDIO", f"Unexpected error in audio loop: {loop_e}")
                    self._stop_event.wait(duration)
                    
        except Exception as e:
            self.log.error("AUDIO", f"Fatal error in audio monitor: {e}")
        finally:
            self.is_active = False

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
