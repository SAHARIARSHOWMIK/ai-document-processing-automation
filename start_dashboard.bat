@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set API_BASE_URL=http://localhost:8000
streamlit run dashboard/app.py
pause
