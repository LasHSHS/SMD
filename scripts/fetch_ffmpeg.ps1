# Fetch Windows ffmpeg essentials into tools/ffmpeg/ for SMD all-in-one builds.
# Usage: powershell -ExecutionPolicy Bypass -File .\scripts\fetch_ffmpeg.ps1

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root 'tools\ffmpeg'
New-Item -ItemType Directory -Force -Path $dest | Out-Null

if (Test-Path (Join-Path $dest 'ffmpeg.exe')) {
    Write-Host '[ffmpeg] Already present in tools/ffmpeg - skipping download.' -ForegroundColor Green
    exit 0
}

$url = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
$zip = Join-Path $env:TEMP 'ffmpeg-release-essentials.zip'
$extract = Join-Path $env:TEMP 'ffmpeg-essentials-extract'

Write-Host '[ffmpeg] Downloading essentials build...' -ForegroundColor Cyan
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing

if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
New-Item -ItemType Directory -Force -Path $extract | Out-Null
Expand-Archive -Path $zip -DestinationPath $extract -Force

$binDir = Get-ChildItem -Path $extract -Recurse -Directory -Filter 'bin' |
    Where-Object { Test-Path (Join-Path $_.FullName 'ffmpeg.exe') } |
    Select-Object -First 1

if (-not $binDir) {
    Write-Error 'Could not find ffmpeg.exe in downloaded archive.'
    exit 1
}

Write-Host "[ffmpeg] Copying from $($binDir.FullName) to $dest" -ForegroundColor Cyan
Get-ChildItem -Path $binDir.FullName -File | Copy-Item -Destination $dest -Force

Remove-Item $zip -Force -ErrorAction SilentlyContinue
Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue

$bundled = Join-Path $dest 'ffmpeg.exe'
Write-Host "[ffmpeg] Done. Bundled: $bundled" -ForegroundColor Green
