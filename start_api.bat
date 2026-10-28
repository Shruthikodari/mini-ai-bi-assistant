@echo off
REM Start the FastAPI backend on http://127.0.0.1:8000
cd /d "%~dp0"
if not exist data\sales.db python -m backend.database
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
