# Starts the local development stack.
# Phase 1: activates the venv and shows CLI usage.
# Phase 2+: will also start the FastAPI server and the AI worker.

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    Write-Host 'Virtual environment not found. Creating it with uv (Python 3.11)...' -ForegroundColor Yellow
    uv venv --python 3.11 (Join-Path $repoRoot '.venv')
    uv pip install --python $venvPython -r (Join-Path $repoRoot 'backend\requirements.txt')
}

Write-Host '=== Local AI Video-to-SRT Studio (Phase 1: CLI pipeline) ===' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Examples:'
Write-Host "  $venvPython -m app.cli probe      <video.mp4>   # inspect media"
Write-Host "  $venvPython -m app.cli transcribe <video.mp4> -o output  # video -> SRT"
Write-Host ''
& $venvPython -m app.cli --help
