# Starts the local development stack.
# Phase 3: FastAPI + AI worker + React frontend (Vite dev server).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start_local.ps1
#        add -NoFrontend to skip the frontend (API-only).

param(
    [switch]$NoFrontend
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$backendDir = Join-Path $repoRoot 'backend'
$frontendDir = Join-Path $repoRoot 'frontend'

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

if ($NoFrontend) {
    Write-Host 'Starting API server at http://127.0.0.1:8000 (docs: /docs)...'
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir $backendDir
} else {
    Write-Host 'Starting API server (background)...'
    $api = Start-Process -FilePath $venvPython `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' `
        -WorkingDirectory $backendDir -PassThru -WindowStyle Hidden
    Write-Host "  api pid: $($api.Id)  ->  http://127.0.0.1:8000/docs"

    Write-Host 'Starting frontend dev server (Ctrl+C stops it)...'
    Write-Host '  app: http://localhost:5173'
    Set-Location $frontendDir
    try { & npm run dev } finally { Set-Location $repoRoot }
}
