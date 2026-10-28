@echo off
REM Start backend and front end, each in its own window
cd /d "%~dp0"
start "Sales Intelligence API" cmd /k start_api.bat
start "Sales Intelligence UI" cmd /k start_ui.bat
