@echo off
rem Upgrade yt-dlp alone (NFR-007) — it breaks when YouTube changes.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install --upgrade yt-dlp
pause
