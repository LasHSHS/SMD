import re
import subprocess
import sys
import json
import shutil
import os
from pathlib import Path
from datetime import datetime, timezone
import pytz
from timezonefinder import TimezoneFinder
import exif
from smd.models import Memory
from smd.ffmpeg_bundle import resolve_ffprobe, ffprobe_available
from mutagen.mp4 import MP4
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

_FFPROBE_AVAILABLE = ffprobe_available()

def get_local_datetime(memory: Memory) -> datetime:
    """Convert memory date to local time based on GPS or system timezone."""
    from smd.timeutil import to_local_datetime

    return to_local_datetime(memory.date, memory.latitude, memory.longitude)

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

def _gps_iso6709(memory: Memory) -> str | None:
    """ISO 6709 coordinate string for QuickTime location tags, or None."""
    if memory.latitude is None or memory.longitude is None:
        return None
    lat, lon = memory.latitude, memory.longitude
    lat_p = "+" if lat >= 0 else "-"
    lon_p = "+" if lon >= 0 else "-"
    # 6 decimal places keeps GPS precision to ~0.1 m (4 was ~11 m).
    return f"{lat_p}{abs(lat):.6f}{lon_p}{abs(lon):.6f}/"


def _set_video_container_date(file_path: Path, memory: Memory) -> bool:
    """Set the MP4/MOV container ``creation_time`` (and location) via a fast
    ffmpeg ``-c copy`` remux.

    Many tools (Windows Explorer "Media created", Google Photos, players) read
    the container ``creation_time`` in the ``mvhd``/``udta`` box rather than the
    iTunes-style ``\xa9day`` atom that mutagen writes. Snapchat leaves its own
    original timestamp there, so without this the capture date is invisible to
    those tools. QuickTime stores this in UTC; viewers convert to local time,
    which matches our local-time filename.
    """
    from smd.ffmpeg_bundle import resolve_ffmpeg
    from smd.fsutil import tmp_sibling
    from smd.procutil import subprocess_flags

    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return False

    utc_dt = memory.date.astimezone(timezone.utc)
    creation = utc_dt.strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    startupinfo, creationflags = subprocess_flags()
    tmp = tmp_sibling(file_path)

    cmd = [
        ffmpeg, "-nostdin", "-y",
        "-i", str(file_path),
        "-map", "0", "-c", "copy", "-map_metadata", "0",
        "-metadata", f"creation_time={creation}",
    ]
    gps_iso = _gps_iso6709(memory)
    if gps_iso:
        cmd += [
            "-metadata", f"location={gps_iso}",
            "-metadata", f"location-eng={gps_iso}",
        ]
    cmd.append(str(tmp))

    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            startupinfo=startupinfo,
            creationflags=creationflags,
            timeout=180,
        )
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, file_path)
            return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass
    return False


def apply_video_metadata(file_path: Path, memory: Memory):
    """Apply MP4/MOV metadata: always write capture date; GPS when available.

    Sets both the container ``creation_time`` (recognized by Explorer, Photos,
    players) and the iTunes-style ``\xa9day``/``\xa9xyz`` atoms (used by SMD's
    own GPS map and Apple software).
    """
    # Container-level date/location first (ffmpeg remux), so the mutagen atoms
    # added below survive on the final file.
    try:
        _set_video_container_date(file_path, memory)
    except Exception:
        pass

    try:
        video = MP4(str(file_path))
        date_iso = get_local_datetime(memory).strftime("%Y-%m-%dT%H:%M:%S%z")
        video["\xa9day"] = [date_iso]
        try:
            video["\xa9nam"] = ["Snapchat Memory"]
            video["\xa9swr"] = ["SMD"]
        except Exception:
            pass

        gps_iso = _gps_iso6709(memory)
        if gps_iso:
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

    from smd.procutil import subprocess_flags

    startupinfo, creationflags = subprocess_flags()

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

