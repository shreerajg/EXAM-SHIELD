import os
import shutil
import glob
from src.logger import ExamShieldLogger

class BrowserManager:
    """
    Responsible for clearing browser cache, history, and cookies for
    common browsers (Chrome, Edge, Firefox) to prevent students from
    accessing previously saved data during the exam.
    """
    def __init__(self, db_manager):
        self.db = db_manager
        self.log = ExamShieldLogger(db_manager)

    def clear_all(self):
        """Clears data for all supported browsers."""
        self.log.info("BROWSER_MANAGER", "Starting browser data wipe...")
        cleared_chrome = self.clear_chrome()
        cleared_edge = self.clear_edge()
        cleared_firefox = self.clear_firefox()
        
        self.log.info("BROWSER_MANAGER", 
            f"Browser wipe complete. Chrome: {cleared_chrome}, Edge: {cleared_edge}, Firefox: {cleared_firefox}"
        )

    def _delete_path(self, path):
        if not os.path.exists(path):
            return False
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
            return True
        except Exception as e:
            self.log.error("BROWSER_MANAGER", f"Failed to delete {path}: {e}", db=False)
            return False

    def clear_chrome(self):
        local_app_data = os.environ.get('LOCALAPPDATA', '')
        if not local_app_data:
            return False
        
        chrome_default = os.path.join(local_app_data, 'Google', 'Chrome', 'User Data', 'Default')
        paths_to_clear = [
            os.path.join(chrome_default, 'Cache'),
            os.path.join(chrome_default, 'Code Cache'),
            os.path.join(chrome_default, 'Network', 'Cookies'),
            os.path.join(chrome_default, 'History')
        ]
        
        success_count = 0
        for p in paths_to_clear:
            if self._delete_path(p):
                success_count += 1
        return success_count > 0

    def clear_edge(self):
        local_app_data = os.environ.get('LOCALAPPDATA', '')
        if not local_app_data:
            return False
        
        edge_default = os.path.join(local_app_data, 'Microsoft', 'Edge', 'User Data', 'Default')
        paths_to_clear = [
            os.path.join(edge_default, 'Cache'),
            os.path.join(edge_default, 'Code Cache'),
            os.path.join(edge_default, 'Network', 'Cookies'),
            os.path.join(edge_default, 'History')
        ]
        
        success_count = 0
        for p in paths_to_clear:
            if self._delete_path(p):
                success_count += 1
        return success_count > 0

    def clear_firefox(self):
        app_data = os.environ.get('APPDATA', '')
        local_app_data = os.environ.get('LOCALAPPDATA', '')
        if not app_data or not local_app_data:
            return False
            
        firefox_profiles = os.path.join(app_data, 'Mozilla', 'Firefox', 'Profiles')
        firefox_local_profiles = os.path.join(local_app_data, 'Mozilla', 'Firefox', 'Profiles')
        
        success_count = 0
        
        # Clear places (history) and cookies in roaming appdata
        if os.path.exists(firefox_profiles):
            for profile_dir in glob.glob(os.path.join(firefox_profiles, '*')):
                if os.path.isdir(profile_dir):
                    if self._delete_path(os.path.join(profile_dir, 'places.sqlite')):
                        success_count += 1
                    if self._delete_path(os.path.join(profile_dir, 'cookies.sqlite')):
                        success_count += 1
                        
        # Clear cache in local appdata
        if os.path.exists(firefox_local_profiles):
            for profile_dir in glob.glob(os.path.join(firefox_local_profiles, '*')):
                cache_dir = os.path.join(profile_dir, 'cache2')
                if os.path.exists(cache_dir):
                    if self._delete_path(cache_dir):
                        success_count += 1
                        
        return success_count > 0
