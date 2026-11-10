# Starts the local development stack (Phase 2: FastAPI + AI worker).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start_local.ps1
# Stops with Ctrl+C (or close both windows).

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$backendDir = Join-Path $repoRoot 'backend'

if (-not (Test-Path $venvPython)) {
    Write-Host 'Virtual environment not found. Creating it with uv (Python 3.11)...' -ForegroundColor Yellow
    uv venv --python 3.11 (Join-Path $repoRoot '.venv')
    uv pip install --python $venvPython -r (Join-Path $repoRoot 'backend\requirements.txt')
}

Write-Host '=== Local AI Video-to-SRT Studio ===' -ForegroundColor Cyan
Write-Host 'Starting AI worker (background window)...'
$worker = Start-Process -FilePath $venvPython -ArgumentList '-m', 'app.workers.worker' `
    -WorkingDirectory $backendDir -PassThru
Write-Host "  worker pid: $($worker.Id)"

Write-Host 'Starting API server at http://127.0.0.1:8000 (docs: /docs)...'
Write-Host 'Press Ctrl+C to stop the API; the worker window closes separately.'
& $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir $backendDir
