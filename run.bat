@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .env copy .env.example .env >nul
echo.
echo Open http://localhost:8000 in your browser. Press Ctrl+C to stop.
echo.
python -m uvicorn app.main:app --port 8000
