@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo [ERROR] venv not found. Run setup_env.bat first.
    pause
    exit /b 1
)

echo Starting Aligo Agent backend at http://127.0.0.1:8000 ...
echo Health check: http://127.0.0.1:8000/health
echo Press Ctrl+C to stop.
echo.
.venv\Scripts\python -m uvicorn server:app --host 127.0.0.1 --port 8000
