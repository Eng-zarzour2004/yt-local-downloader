@echo off
REM Start the YT Downloader companion (Windows). Binds to 127.0.0.1:8765 only.
cd /d "%~dp0"
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo WARNING: ffmpeg not found on PATH.
  echo Install with: winget install Gyan.FFmpeg
  echo Then close and reopen this terminal.
  echo.
)
if not exist ".venv" (
  echo Creating virtual environment...
  py -3 -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt
python run.py
pause
