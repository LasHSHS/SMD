@echo off
REM Launch SMD from source (latest code — bundled ZIP export support)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv
    .venv\Scripts\python.exe -m pip install -q -r requirements.txt 2>nul
)

echo Starting SMD... log: smd_gui.log
start "" ".venv\Scripts\pythonw.exe" "%~dp0desktop_gui_pyqt.py"

REM If the process dies within a few seconds, show the log tail and pause
timeout /t 4 /nobreak >nul
powershell -NoProfile -Command ^
  "$running = Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*SMD\.venv*' };" ^
  "if (-not $running) {" ^
  "  Write-Host ''; Write-Host 'SMD failed to start. Last log lines:' -ForegroundColor Yellow;" ^
  "  if (Test-Path '%~dp0smd_gui.log') { Get-Content '%~dp0smd_gui.log' -Tail 30 } else { Write-Host '(no log file yet)' };" ^
  "  Write-Host ''; Read-Host 'Press Enter to close'" ^
  "}"
