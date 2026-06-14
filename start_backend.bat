@echo off
cd /d "%~dp0backend"
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m pip install -r requirements.txt -q
echo If port 8000 is busy, run: start_backend.ps1 -Port 8001
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
