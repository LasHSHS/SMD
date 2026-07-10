# Build SMD (Snapchat Memories Downloader) Windows executable
# Usage: powershell -ExecutionPolicy Bypass -File .\build_smd.ps1

$ErrorActionPreference = 'Stop'

Write-Host "[SMD Build] Activating venv (or creating if missing)" -ForegroundColor Cyan
if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    py -3 -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

Write-Host "[SMD Build] Ensuring PyInstaller and hooks are available" -ForegroundColor Cyan
python -m pip install --upgrade pip
pip install pyinstaller -r requirements.txt
Write-Host "[SMD Build] Dependencies installed" -ForegroundColor Green

Write-Host "[SMD Build] Ensuring bundled ffmpeg (all-in-one package)" -ForegroundColor Cyan
powershell -ExecutionPolicy Bypass -File .\scripts\fetch_ffmpeg.ps1
if (-not (Test-Path .\tools\ffmpeg\ffmpeg.exe)) {
    Write-Error "ffmpeg not found in tools/ffmpeg after fetch. Build aborted."
    exit 1
}

# Clean previous artifacts
Write-Host "[SMD Build] Cleaning previous artifacts" -ForegroundColor Cyan
if (Test-Path .\dist) { Remove-Item .\dist -Recurse -Force -ErrorAction SilentlyContinue }
if (Test-Path .\build) { Remove-Item .\build -Recurse -Force -ErrorAction SilentlyContinue }

# Collect Qt resources broadly to avoid missing-webengine issues
# Bundle HTML resources used by the GUI

$cmd = @(
    'pyinstaller',
    'smd.spec',
    '--noconfirm',
    '--clean'
)

Write-Host "[SMD Build] Running: $cmd" -ForegroundColor Cyan
& $cmd[0] $cmd[1..($cmd.Length - 1)]

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

# Ensure ffmpeg is reachable next to smd.exe (all-in-one layout)
$distFfmpeg = Join-Path 'dist\smd' 'tools\ffmpeg'
New-Item -ItemType Directory -Force -Path $distFfmpeg | Out-Null
Copy-Item -Path 'tools\ffmpeg\*' -Destination $distFfmpeg -Force -ErrorAction SilentlyContinue
$internalFfmpeg = Join-Path 'dist\smd\_internal' 'tools\ffmpeg'
if (Test-Path 'dist\smd\_internal') {
    New-Item -ItemType Directory -Force -Path $internalFfmpeg | Out-Null
    Copy-Item -Path 'tools\ffmpeg\*' -Destination $internalFfmpeg -Force -ErrorAction SilentlyContinue
}

Write-Host "[SMD Build] Done. All-in-one package: .\dist\smd\SMD.exe" -ForegroundColor Green
Write-Host "[SMD Build] Optional installer: compile smd_installer.iss with Inno Setup" -ForegroundColor Cyan
