@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
if not exist "logs" mkdir "logs"
set "PHOTO_INTELLIGENCE_ROOT=%ROOT%"
if exist "src\app\desktop\main.py" (
  set "PYTHONPATH=%ROOT%src"
) else (
  set "PYTHONPATH=%ROOT%"
)
if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
)
echo --- Photo Intelligence developer startup --- >> "logs\dev_startup.log"
python -m app.desktop.main >> "logs\dev_startup.log" 2>&1
if errorlevel 1 (
  echo Startup failed. See logs\dev_startup.log
  pause
)
