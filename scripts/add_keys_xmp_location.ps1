# Add QuickTime Keys + XMP LocationShown GPS tags for media analysis tools
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
    
    # Write: Keys:GPSCoordinates (QuickTime), XMP:LocationShownGPS* (XMP)
    & $exo -overwrite_original "-Keys:GPSCoordinates=$lat, $lon" "-XMP:LocationShownGPSLatitude=$lat" "-XMP:LocationShownGPSLongitude=$lon" "-XMP:LocationShownGPSAltitude=0" $_.FullName
    Write-Host "Added Keys+XMP LocationShown -> $($_.Name)"
}
