# Re-embed GPS + XMP GPS tags for all completed MP4s in accounts/Las/downloads
$ErrorActionPreference = 'Stop'

$exo = Join-Path (Join-Path (Join-Path $PSScriptRoot '..') 'tools') 'exiftool.exe'
$downloads = Join-Path (Join-Path (Join-Path (Join-Path $PSScriptRoot '..') 'accounts') 'Las') 'downloads'

Get-ChildItem $downloads -Filter '*.mp4' | Where-Object { -not $_.Name.EndsWith('.part') } | ForEach-Object {
    $latRaw = & $exo -n -GPSLatitude $_.FullName
    $lonRaw = & $exo -n -GPSLongitude $_.FullName
    $lat = ($latRaw -split ':')[-1].Trim()
    $lon = ($lonRaw -split ':')[-1].Trim()
    if ([string]::IsNullOrWhiteSpace($lat) -or [string]::IsNullOrWhiteSpace($lon)) {
        Write-Host "Skip (no GPS found) -> $($_.Name)"
        return
    }
    $latRef = if ([double]$lat -ge 0) { 'N' } else { 'S' }
    $lonRef = if ([double]$lon -ge 0) { 'E' } else { 'W' }
    & $exo -overwrite_original "-GPSLatitude=$lat" "-GPSLongitude=$lon" "-XMP:GPSLatitude=$lat" "-XMP:GPSLongitude=$lon" "-XMP:GPSLatitudeRef=$latRef" "-XMP:GPSLongitudeRef=$lonRef" $_.FullName
    Write-Host "Updated XMP GPS -> $($_.Name)"
}
