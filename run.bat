@echo off
cd /d "%~dp0"

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [!] ffmpeg not found.
    echo     Open a terminal and run:  winget install Gyan.FFmpeg
    echo     Then close and reopen this window.
)

where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python not found. Install Python 3.11+ from https://python.org
    echo     IMPORTANT: tick "Add Python to PATH" during installation.
    pause
    exit /b 1
)

if not exist .venv (
    echo First run: creating a private Python environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

python -c "import gradio" >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies - this only happens once...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
)

echo Starting ClipStitch - your browser will open automatically...
python -m clipstitch.app
pause
