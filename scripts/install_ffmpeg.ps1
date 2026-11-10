# Installs FFmpeg via winget (full build includes ffmpeg + ffprobe).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install_ffmpeg.ps1

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host 'winget is not available on this system.' -ForegroundColor Red
    Write-Host 'Install FFmpeg manually from https://www.gyan.dev/ffmpeg/builds/ and add it to PATH.'
    exit 1
}

Write-Host 'Installing FFmpeg (Gyan.FFmpeg) via winget...'
winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements

if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Write-Host 'FFmpeg installed. Open a NEW terminal so PATH updates apply, then verify:'
    Write-Host '  ffmpeg -version'
    Write-Host '  ffprobe -version'
} else {
    Write-Host "winget failed with exit code $LASTEXITCODE." -ForegroundColor Red
    exit $LASTEXITCODE
}
