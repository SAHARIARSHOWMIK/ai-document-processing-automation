@echo off
setlocal
cd /d "%~dp0"

echo [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install Python 3.12 and tick "Add Python to PATH".
  pause
  exit /b 1
)
python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) else 1)"
if errorlevel 1 (
  echo This project is tested with Python 3.12. Please install Python 3.12.
  python --version
  pause
  exit /b 1
)

echo [2/5] Creating virtual environment...
python -m venv .venv

echo [3/5] Installing dependencies...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo [4/5] Creating .env if missing...
if not exist .env copy .env.example .env >nul

echo [5/5] Running tests...
set DEMO_MODE=true
set DATABASE_URL=sqlite:///:memory:
set PYTHONPATH=%CD%
pytest -v
if errorlevel 1 (
  echo Tests failed. Copy the error and ask ChatGPT.
  pause
  exit /b 1
)

echo Setup complete. Run start_backend.bat, then start_dashboard.bat.
pause
