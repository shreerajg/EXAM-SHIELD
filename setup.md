# ExamShield v1.0 - Setup Guide

This guide will walk you through setting up **ExamShield v1.0** on your local Windows machine. 

## 📋 Prerequisites
- **Operating System:** Windows 10 or Windows 11 (ExamShield relies on Windows APIs for system hooks).
- **Python:** Python 3.8 or higher installed on your system. 
  - *Make sure to check the box "Add Python to PATH" during installation.*
- **Git** (optional, but recommended if you are pulling from a repository).

## 🛠️ Step 1: Prepare the Project Directory
1. Open your terminal or Command Prompt.
2. Navigate to the folder where you have the project files (or clone the repository).
   ```bash
   cd "C:\path\to\ExamShield v1.0"
   ```

## 📦 Step 2: Create a Virtual Environment
Using a virtual environment is highly recommended to prevent conflicts with other Python projects on your machine.

1. **Create the environment:**
   ```bash
   python -m venv myenv
   ```
2. **Activate the environment:**
   - **Command Prompt:**
     ```cmd
     myenv\Scripts\activate.bat
     ```
   - **PowerShell:**
     ```powershell
     myenv\Scripts\Activate.ps1
     ```
   *(Note: You should see `(myenv)` appear at the beginning of your command line prompt, indicating it is active.)*

## 📥 Step 3: Install Dependencies
ExamShield requires several specific libraries (like `pywin32`, `psutil`, `pynput`, `pystray`, etc.) to control system hardware and processes.

1. With your virtual environment activated, run:
   ```bash
   pip install -r requirements.txt
   ```
2. *(Optional)* Verify the installation of the core packages by running:
   ```bash
   pip list
   ```

## 🚀 Step 4: Run the Application
ExamShield requires administrative permissions to manage network adapters, firewall rules, and aggressive keyboard/mouse hooks.

1. Execute the main file:
   ```bash
   python main.py
   ```
2. The application will immediately check if it has **Administrator privileges**. 
3. If it doesn't, it will trigger a Windows UAC (User Account Control) prompt asking for permission to restart with elevated rights. Click **Yes**.
4. You will then see the animated dark-mode login screen, followed by the Admin Panel.

## 🛑 Troubleshooting

- **Elevation Fails:** If the app fails to elevate itself, try opening your Command Prompt or PowerShell as an Administrator (Right-click -> "Run as administrator") before running `python main.py`.
- **"ModuleNotFoundError"**: Make sure you have activated your virtual environment (`myenv\Scripts\activate`) before running the script.
- **Hook Errors (Keyboard/Mouse):** Some antivirus software might flag python scripts using `keyboard` or `pynput` as suspicious. You may need to add an exception for your Python environment.
- ** the main thing changes here that we have to do complete admin premissions and needs admin UAC prompt **
- ** webcamm / microphome access will be granted only once when the app is started **
- ** black list only allows same name apps to be run but it should run all apps with same name for that we have to add .exe in the black list **