# Environment checker for Local AI Video-to-SRT Studio.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\check_environment.ps1

$ErrorActionPreference = 'SilentlyContinue'

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

$results = @()

function Add-Result($label, $ok, $detail) {
    $script:results += [pscustomobject]@{
        Component = $label
        Status    = if ($ok) { 'OK' } else { 'MISSING' }
        Detail    = $detail
    }
}

# Python
if (Test-Command python) {
    $pyVer = (python --version) 2>$null
    Add-Result 'Python' $true "$pyVer"
} else {
    Add-Result 'Python' $false 'python not on PATH'
}

# uv
if (Test-Command uv) {
    Add-Result 'uv' $true (uv --version)
} else {
    Add-Result 'uv' $false 'optional - used to create the venv'
}

# Virtual environment
if (Test-Path "$PSScriptRoot\..\.venv\Scripts\python.exe") {
    Add-Result 'Virtualenv' $true '.venv exists'
} else {
    Add-Result 'Virtualenv' $false 'run: uv venv --python 3.11 .venv'
}

# FFmpeg
if (Test-Command ffmpeg) {
    $ff = (ffmpeg -version 2>$null | Select-Object -First 1)
    Add-Result 'FFmpeg' $true $ff
} else {
    Add-Result 'FFmpeg' $false 'run: scripts\install_ffmpeg.ps1'
}

if (Test-Command ffprobe) {
    Add-Result 'FFprobe' $true 'available'
} else {
    Add-Result 'FFprobe' $false 'ships with FFmpeg builds'
}

# Node.js (Phase 3: frontend)
if (Test-Command node) {
    Add-Result 'Node.js' $true (node --version)
} else {
    Add-Result 'Node.js' $false 'needed in Phase 3 (frontend)'
}

# NVIDIA GPU
if (Test-Command nvidia-smi) {
    $gpu = (nvidia-smi --query-gpu=name,memory.total --format=csv,noheader) 2>$null
    Add-Result 'NVIDIA GPU' $true "$gpu (CUDA under WSL2/Docker only)"
} else {
    Add-Result 'NVIDIA GPU' $false 'none detected - inference runs on CPU (int8)'
}

$results | Format-Table -AutoSize

$missing = ($results | Where-Object { $_.Status -eq 'MISSING' -and $_.Component -notin @('Node.js', 'NVIDIA GPU') }).Count
if ($missing -gt 0) {
    Write-Host "$missing required component(s) missing." -ForegroundColor Yellow
    exit 1
}
Write-Host 'Environment looks good.' -ForegroundColor Green
exit 0
