@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  [1/2] Creating Python 3.13 venv (.venv)...
echo ============================================
py -3.13 -m venv .venv
if errorlevel 1 (
    echo.
    echo [ERROR] venv creation failed.
    echo Please confirm Python 3.13 is installed: run "py -0p"
    pause
    exit /b 1
)

echo.
echo ============================================
echo  [2/3] Installing CPU-only torch (~200MB, skip 2.5GB CUDA)...
echo ============================================
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 (
    echo.
    echo [ERROR] CPU torch install failed. Check network to download.pytorch.org
    pause
    exit /b 1
)

echo.
echo ============================================
echo  [3/3] Installing remaining dependencies...
echo ============================================
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] dependency install failed.
    echo If pip says "no matching distribution", Python 3.13 may lack wheels
    echo for the pinned deps; create a Python 3.11 env via conda instead.
    pause
    exit /b 1
)

echo.
echo Done. Next run run_server.bat to start the backend.
pause
