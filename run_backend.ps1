Write-Host "Starting backend server with virtual environment..." -ForegroundColor Green
& .\venv\Scripts\python -m uvicorn backend.api:app --host 0.0.0.0 --port 8001 --reload
