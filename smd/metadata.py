import re
import subprocess
import sys
import json
import shutil
import os
from pathlib import Path
from datetime import datetime
import pytz
from timezonefinder import TimezoneFinder
import exif
from smd.models import Memory
from smd.ffmpeg_bundle import resolve_ffprobe, ffprobe_available
from mutagen.mp4 import MP4
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

# Initialize global timezone finder
_timezone_finder = TimezoneFinder()

_FFPROBE_AVAILABLE = ffprobe_available()

def get_local_datetime(memory: Memory) -> datetime:
    """Convert memory date to local time based on GPS or system timezone."""
    local_dt = memory.date
    if memory.latitude is not None and memory.longitude is not None:
        try:
            tz_name = _timezone_finder.timezone_at(lat=memory.latitude, lng=memory.longitude)
            if tz_name:
                tz = pytz.timezone(tz_name)
                local_dt = memory.date.astimezone(tz)
        except Exception:
            local_dt = memory.date.astimezone()
    else:
        local_dt = memory.date.astimezone()
    return local_dt

def add_exif_data_img(image_path: Path, memory: Memory):
    """Embed EXIF data into JPEG images using python-exif, with Pillow fallback."""
    try:
        original = image_path.read_bytes()
        if not original.startswith(b"\xff\xd8"):
            raise ValueError("not a JPEG")

        with open(image_path, "rb") as f:
            img = exif.Image(f)

        local_dt = get_local_datetime(memory)
        dt_str = local_dt.strftime("%Y:%m:%d %H:%M:%S")

        img.datetime_original = dt_str
        img.datetime_digitized = dt_str
        img.datetime = dt_str

        if memory.latitude is not None and memory.longitude is not None:
            def decimal_to_dms(decimal):
                degrees = int(abs(decimal))
                minutes_decimal = (abs(decimal) - degrees) * 60
                minutes = int(minutes_decimal)
                seconds = (minutes_decimal - minutes) * 60
                return (degrees, minutes, seconds)

            lat_dms = decimal_to_dms(memory.latitude)
            lon_dms = decimal_to_dms(memory.longitude)

            img.gps_latitude = lat_dms
            img.gps_latitude_ref = "N" if memory.latitude >= 0 else "S"
            img.gps_longitude = lon_dms
            img.gps_longitude_ref = "E" if memory.longitude >= 0 else "W"

        updated = img.get_file()
        if not updated.startswith(b"\xff\xd8"):
            raise ValueError("EXIF write produced invalid JPEG header")

        with open(image_path, "wb") as f:
            f.write(updated)
    except Exception:
        # Never leave a broken image — restore original bytes if we have them
        try:
            if "original" in locals() and original:
                image_path.write_bytes(original)
        except OSError:
            pass
        try:
            ts = get_local_datetime(memory).timestamp()
            os.utime(image_path, (ts, ts))
        except OSError:
            pass

def add_mp4_metadata(video_path: Path, memory: Memory):
    """Embed creation date and ISO6709 location into MP4 using Mutagen."""
    try:
        mp4 = MP4(str(video_path))
        local_dt = get_local_datetime(memory)
        date_iso = local_dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        
        # Standard QuickTime tags
        mp4['\xa9day'] = [date_iso]
        try:
            mp4['\xa9nam'] = [memory.filename]
        except Exception:
            pass
            
        # Location logic is handled in apply_video_metadata for consistency
        mp4.save()
    except Exception:
        pass

# embed_gps_fallback_exiftool removed (Deprecated)

def apply_video_metadata(file_path: Path, memory: Memory):
    """Apply MP4/MOV metadata: always write capture date; GPS when available."""
    try:
        video = MP4(str(file_path))
        date_iso = get_local_datetime(memory).strftime("%Y-%m-%dT%H:%M:%S%z")
        video["\xa9day"] = [date_iso]
        try:
            video["\xa9nam"] = ["Snapchat Memory"]
            video["\xa9swr"] = ["SMD"]
        except Exception:
            pass

        if memory.latitude is not None and memory.longitude is not None:
            lat = memory.latitude
            lon = memory.longitude
            lat_p = "+" if lat >= 0 else "-"
            lon_p = "+" if lon >= 0 else "-"
            gps_iso = f"{lat_p}{abs(lat):.4f}{lon_p}{abs(lon):.4f}/"
            video["\xa9xyz"] = [gps_iso]

        video.save()
    except Exception:
        pass

def apply_metadata(file_path: Path, memory: Memory, file_ext: str):
    """Facade function to apply best-effort metadata using Pure Python libraries."""
    try:
        # 1. Native Python libraries (Fast, basic)
        if file_ext.lower() in [".jpg", ".jpeg"]:
            add_exif_data_img(file_path, memory)
            
        elif file_ext.lower() in [".mp4", ".mov"]:
            apply_video_metadata(file_path, memory)
        
        else:
            # Other formats (PNG, WEBP, GIF, MKV) - Metadata writing skipped (Safe)
            pass
        
    except Exception:
        pass

# -----------------------------------------------------------------------------
# GPS Extraction (Read) Logic
# -----------------------------------------------------------------------------

_GPS_LATITUDE = 2
_GPS_LATITUDE_REF = 1
_GPS_LONGITUDE = 4
_GPS_LONGITUDE_REF = 3


def _ratio_to_float(value) -> float:
    """Convert EXIF rationals, IFDRational, or plain numbers to float."""
    if value is None:
        raise TypeError("missing coordinate value")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, tuple) and len(value) == 2:
        num, den = value
        num_f = _ratio_to_float(num)
        den_f = _ratio_to_float(den)
        return num_f / den_f if den_f else num_f
    # Pillow IFDRational and similar types expose float()
    return float(value)


def _convert_dms_to_degrees(value) -> float:
    """Convert GPS coordinates (DMS tuple) to decimal degrees."""
    d, m, s = value
    return (
        _ratio_to_float(d)
        + _ratio_to_float(m) / 60.0
        + _ratio_to_float(s) / 3600.0
    )


def _apply_gps_ref(degrees: float, ref) -> float:
    if ref in ("S", "W", b"S", b"W"):
        return -abs(degrees)
    return degrees


def _coords_from_gps_info(gps_info: dict) -> tuple[float, float] | None:
    lat_values = gps_info.get("GPSLatitude")
    lon_values = gps_info.get("GPSLongitude")
    if lat_values is None or lon_values is None:
        return None
    lat = _apply_gps_ref(_convert_dms_to_degrees(lat_values), gps_info.get("GPSLatitudeRef"))
    lon = _apply_gps_ref(_convert_dms_to_degrees(lon_values), gps_info.get("GPSLongitudeRef"))
    return (lat, lon)


def _gps_info_from_ifd(gps_ifd: dict) -> dict:
    gps_info = {}
    for gps_tag, gps_value in gps_ifd.items():
        gps_tag_name = GPSTAGS.get(gps_tag, gps_tag)
        gps_info[gps_tag_name] = gps_value
    return gps_info


def _extract_gps_exif_library(image_path: Path) -> tuple[float, float] | None:
    """Read GPS using python-exif (same format SMD writes)."""
    try:
        with open(image_path, "rb") as f:
            img = exif.Image(f)
        if not hasattr(img, "gps_latitude") or not hasattr(img, "gps_longitude"):
            return None
        lat = _apply_gps_ref(
            _convert_dms_to_degrees(img.gps_latitude),
            getattr(img, "gps_latitude_ref", "N"),
        )
        lon = _apply_gps_ref(
            _convert_dms_to_degrees(img.gps_longitude),
            getattr(img, "gps_longitude_ref", "E"),
        )
        return (lat, lon)
    except Exception:
        return None


def _extract_gps_pillow(image_path: Path) -> tuple[float, float] | None:
    """Read GPS from Pillow EXIF, including rational DMS tuples."""
    try:
        image = Image.open(image_path)
        exif = image.getexif()
        if exif:
            try:
                gps_ifd = exif.get_ifd(0x8825)
            except Exception:
                gps_ifd = {}
            if gps_ifd:
                coords = _coords_from_gps_info(
                    {
                        "GPSLatitude": gps_ifd.get(_GPS_LATITUDE),
                        "GPSLongitude": gps_ifd.get(_GPS_LONGITUDE),
                        "GPSLatitudeRef": gps_ifd.get(_GPS_LATITUDE_REF, "N"),
                        "GPSLongitudeRef": gps_ifd.get(_GPS_LONGITUDE_REF, "E"),
                    }
                )
                if coords:
                    return coords

        exif_data = image._getexif()
        if not exif_data:
            return None

        for tag, value in exif_data.items():
            if TAGS.get(tag, tag) != "GPSInfo":
                continue
            coords = _coords_from_gps_info(_gps_info_from_ifd(value))
            if coords:
                return coords
    except Exception:
        return None
    return None


def extract_gps_image(image_path: Path) -> tuple[float, float] | None:
    """Extract GPS coordinates from image EXIF data."""
    for reader in (_extract_gps_exif_library, _extract_gps_pillow):
        coords = reader(image_path)
        if coords:
            return coords
    return None

def _parse_coordinate(value):
    """Parse a single coordinate value with optional direction (N/S/E/W)."""
    try:
        s = str(value).strip()
        # Extract direction if present
        direction = None
        for d in ['N', 'S', 'E', 'W']:
            if d in s.upper():
                direction = d
                s = s.upper().replace(d, '').strip()
                break
        
        # Try to extract numeric value
        # Handle formats: "55.6761", "55 deg 40' 34.0\""
        s = s.replace('deg', ' ').replace("'", ' ').replace('"', ' ').replace('°', ' ')
        
        # Try simple decimal first
        parts = s.split()
        if len(parts) == 1:
            coord = float(parts[0])
        elif len(parts) >= 2:
            # DMS format: degrees minutes seconds
            d = float(parts[0])
            m = float(parts[1]) if len(parts) > 1 else 0
            sec = float(parts[2]) if len(parts) > 2 else 0
            coord = d + m/60.0 + sec/3600.0
        else:
            return None
        
        # Apply direction
        if direction in ['S', 'W']:
            coord = -coord
        
        return coord
    except (ValueError, IndexError):
        pass
    return None

def _parse_gps_position(value):
    """Parse GPSPosition string like '55.6761 N, 12.5683 E' or '55.6761, 12.5683'"""
    try:
        s = str(value).strip()
        # Remove degree symbols and clean up
        s = s.replace('°', ' ').replace("'", ' ').replace('"', ' ')
        
        # Pattern: "lat [N/S], lon [E/W]"
        parts = [p.strip() for p in s.split(',')]
        if len(parts) == 2:
            lat = _parse_coordinate(parts[0])
            lon = _parse_coordinate(parts[1])
            if lat is not None and lon is not None:
                return (lat, lon)
    except Exception:
        pass
    return None

def _parse_iso6709(value):
    """Parse ISO6709 or simple lat/lon strings found in video tags."""
    try:
        s = str(value).strip()
        s = s.replace(' ', '')
        if s.endswith('/'):
            s = s[:-1]
        m = re.match(r'([+-]?\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)', s)
        if m:
            return float(m.group(1)), float(m.group(2))
    except Exception:
        return None
    return None

def _extract_gps_ffprobe(video_path: Path):
    """Try extracting GPS using ffprobe."""
    if not _FFPROBE_AVAILABLE:
        return None
        
    ffprobe = resolve_ffprobe()
    if not ffprobe:
        return None

    ffprobe_cmd = [
        ffprobe, '-v', 'quiet', '-print_format', 'json',
        '-show_entries', 'format_tags=location:format_tags=com.apple.quicktime.location.ISO6709:stream_tags=location:stream_tags=com.apple.quicktime.location.ISO6709',
        str(video_path)
    ]

    startupinfo = None
    creationflags = 0
    if sys.platform.startswith('win'):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            ffprobe_cmd,
            capture_output=True,
            text=True,
            check=True,
            startupinfo=startupinfo,
            creationflags=creationflags,
            timeout=5
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return None

    try:
        data = json.loads(result.stdout or '{}')
    except json.JSONDecodeError:
        return None

    tags = {}
    tags.update(data.get('format', {}).get('tags', {}) or {})
    for stream in data.get('streams', []) or []:
        tags.update(stream.get('tags', {}) or {})

    for key in ['com.apple.quicktime.location.ISO6709', 'location', 'LOCATION']:
        if key in tags:
            coords = _parse_iso6709(tags[key])
            if coords:
                return coords
    
    return None

# extract_gps_video Cleanup: Removed exiftool fallback

def extract_gps_video(video_path: Path) -> tuple[float, float] | None:
    """Extract GPS from video metadata using ffprobe."""
    # Try ffprobe (standard format extraction)
    return _extract_gps_ffprobe(video_path)

