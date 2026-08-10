"""
ExamShield v1.2.0 - Webcam Manager
Monitors webcam for face presence and absence during the exam.
"""
import threading
import time
from src.config import Config

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

class WebcamManager:
    def __init__(self, db_manager):
        self.db = db_manager
        self.log = db_manager.logger
        self.is_active = False
        self._thread = None
        self._stop_event = threading.Event()
        self.absence_count = 0
        self.multiple_face_count = 0
        
        if CV2_AVAILABLE:
            self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        else:
            self.face_cascade = None
        

        # We need a reference to security manager or admin panel to trigger violations.
        self.security_manager = None
    
    def set_security_manager(self, sm):
        self.security_manager = sm
        
    def start(self):
        if not CV2_AVAILABLE:
            self.log.error("WEBCAM", "OpenCV not installed. Webcam monitoring disabled.")
            return
            
        if self.is_active: return
        self.is_active = True
        self._stop_event.clear()
        self.absence_count = 0
        self.multiple_face_count = 0
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        self.log.info("WEBCAM", "Webcam monitoring started")
        
    def stop(self):
        self.is_active = False
        self._stop_event.set()
        if self._thread:
            self._thread = None
        self.log.info("WEBCAM", "Webcam monitoring stopped")
            
    def _monitor_loop(self):
        cap = None
        try:
            # Try to find a working camera index
            camera_index = -1
            for i in range(3): # Check indices 0, 1, 2
                temp_cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) # Using DirectShow on Windows is often more stable
                if temp_cap.isOpened():
                    camera_index = i
                    temp_cap.release()
                    break
            
            if camera_index == -1:
                # Try without CAP_DSHOW just in case
                for i in range(3):
                    temp_cap = cv2.VideoCapture(i)
                    if temp_cap.isOpened():
                        camera_index = i
                        temp_cap.release()
                        break

            if camera_index == -1:
                self.log.error("WEBCAM", "No usable webcam found. Webcam monitoring disabled.")
                self.is_active = False
                return

            cap = cv2.VideoCapture(camera_index)
            # Give camera time to warm up
            time.sleep(1)
            
            interval = Config.WEBCAM_MONITOR_INTERVAL_SEC
            
            error_count = 0
            while self.is_active and not self._stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    error_count += 1
                    self.log.error("WEBCAM", f"Failed to grab frame (Attempt {error_count})")
                    if error_count > 5:
                        self.log.error("WEBCAM", "Too many camera failures. Stopping webcam monitor.")
                        break
                    self._stop_event.wait(interval)
                    continue
                
                # Reset error count on successful read
                error_count = 0
                    
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                # Optimize parameters for stability (scaleFactor, minNeighbors)
                faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(40, 40))
                
                num_faces = len(faces)
                
                if num_faces == 0:
                    self.absence_count += 1
                    if self.absence_count >= Config.WEBCAM_FACE_ABSENCE_TOLERANCE:
                        self._trigger_violation("absence")
                        self.absence_count = 0 # reset after trigger
                elif num_faces > 1:
                    self.multiple_face_count += 1
                    if self.multiple_face_count >= Config.WEBCAM_FACE_ABSENCE_TOLERANCE:
                        self._trigger_violation("multiple_faces")
                        self.multiple_face_count = 0
                else:
                    self.absence_count = 0
                    self.multiple_face_count = 0
                    
                self._stop_event.wait(interval)
                
        except Exception as e:
            self.log.error("WEBCAM", f"Error in webcam monitor loop: {e}")
        finally:
            if cap and cap.isOpened():
                cap.release()
            self.is_active = False

    def _trigger_violation(self, reason):
        msg = "Face not detected" if reason == "absence" else "Multiple faces detected"
        self.log.security("WEBCAM_VIOLATION", msg, blocked=True)
        if self.security_manager:
            # We can use the security manager's breach counter logic
            if 'webcam' not in self.security_manager.breach_counts:
                self.security_manager.breach_counts['webcam'] = 0
            self.security_manager.breach_counts['webcam'] += 1
            self.security_manager.screenshot_manager.capture_violation(reason=f"webcam_{reason}")
            
            panel = self.security_manager.admin_panel
            if panel and hasattr(panel, 'window'):
                try:
                    panel.window.after(0, panel.update_breach_counter)
                    panel.window.after(0, lambda m=msg: panel._toast(f"📷  {m}", '#ff4757') if hasattr(panel, '_toast') else None)
                except Exception:
                    pass
