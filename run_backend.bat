@echo off
echo Starting backend server with virtual environment...
.\venv\Scripts\python -m uvicorn backend.api:app --host 0.0.0.0 --port 8001 --reload
pause
