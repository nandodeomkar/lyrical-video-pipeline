@echo off
rem Double-click launcher for the Lyrics Pipeline (PRD §11 rollout).
cd /d "%~dp0"
".venv\Scripts\python.exe" -m streamlit run app.py
rem Keep the window open if Streamlit exits with an error.
pause
