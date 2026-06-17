@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set PYTHONPATH=%CD%
uvicorn app.main:app --reload
pause
