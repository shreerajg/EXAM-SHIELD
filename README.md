# 🛡️ ExamShield v1.0

<p align="center">
  <em>A Secure Exam Browser and Proctoring System built with Python & Tkinter.</em>
</p>

## 📌 Overview

**ExamShield** is a robust, dark-themed desktop application designed to ensure complete integrity during computer-based examinations. By enforcing a highly restricted environment, ExamShield prevents cheating by blocking unauthorized actions such as accessing the internet, using external drives, or opening non-exam applications.

## 🚀 Features

- **Strict Process Management**: Continuously monitors and terminates unauthorized background and foreground processes.
- **Network Control**: Disables unauthorized internet adapters to enforce a closed-network exam environment, managing firewall rules directly.
- **USB & Peripheral Blocking**: Detects and prevents the use of unauthorized USB drives.
- **Input Restrictions**: System-level keyboard and mouse hooks prevent unauthorized shortcuts (e.g., `Alt+Tab`, `Ctrl+C/V`, `Windows Key`).
- **Secure Window Constraints**: Locks the application in a restricted state to prevent minimizing, closing, or losing focus.
- **Admin Panel**: A centralized dashboard for configuring exam rules, managing users, and viewing real-time security logs.
- **Animated UI**: Features a sleek, dark-mode animated login screen and an intuitive user interface.

## 🛠️ Technology Stack

- **Language**: Python 3.x
- **GUI Framework**: Tkinter
- **Dependencies**: 
  - `keyboard`, `mouse`, `pynput` (System-level input hooks)
  - `psutil` (Advanced process management)
  - `pystray`, `Pillow` (System tray integration)
  - `pywin32` (Windows API integration for admin elevation and system controls)

## ⚙️ Installation & Setup

1. **Clone the repository** (if applicable) or download the source code:
   ```bash
   git clone https://github.com/yourusername/ExamShield.git
   cd ExamShield
   ```

2. **Activate the Virtual Environment** (Optional but recommended):
   ```bash
   # If the environment 'myenv' exists:
   myenv\Scripts\activate
   
   # To create a new one:
   python -m venv myenv
   myenv\Scripts\activate
   ```

3. **Install required dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## 🚀 Usage

*Note: ExamShield requires **Administrator privileges** to control system hooks, network adapters, and processes.*

To launch the application:
```bash
python main.py
```
Upon launching, the app will automatically request Admin elevation if not already running as an administrator. After elevation, you'll be greeted by an animated login screen that transitions into the main Admin Panel.

## 📁 Project Structure

- `main.py` — Application entry point, handles admin elevation and login UI animation.
- `admin_panel.py` — Core dashboard for configuring the system.
- `security_manager.py` — Handles process monitoring and background security tasks.
- `network_manager.py` — Controls firewall rules and network adapters.
- `window_manager.py` — Secures the application window state.
- `mouse_manager.py` — Enforces mouse activity restrictions.
- `usb_manager.py` — Monitors and blocks external drives.
- `database_manager.py` — Interfaces with the local `exam_shield.db` SQLite database.
- `system_tray.py` — Manages the background system tray icon state.
- `logger.py` — Centralized security and event logging system.
- `config.py` — Global configuration parameters, styling, and rules.

## 🔒 Security Note

This software employs aggressive system-level hooks and administrative commands. Use it exclusively in authorized, dedicated exam environments. The creators assume no liability for potential system lockouts or network disruptions caused by improper configuration.

## 📄 License

This project is licensed under the [MIT License](LICENSE) - see the LICENSE file for details.
