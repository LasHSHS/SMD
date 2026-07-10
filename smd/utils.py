import re
import sys
import json
import shutil
import zipfile
import os
from pathlib import Path
from urllib.parse import urlparse
from smd.models import Memory


def get_debug_dir(output_dir: Path) -> Path:
    """Return the debug folder for this account. Prefer sibling of downloads."""
    parent = output_dir.parent
    if parent.exists():
        dbg = parent / "debug"
    else:
        dbg = output_dir / "debug"
    try:
        dbg.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return dbg

def parse_speed(speed_str: str) -> float:
    """Parse speed string like '5MB/s' or '500KB/s' to bytes per second."""
    speed_str = speed_str.upper().replace(" ", "")
    
    # Remove /s suffix if present
    speed_str = speed_str.replace("/S", "")
    
    # Extract number and unit
    match = re.match(r"([\d.]+)(KB|MB|GB)?", speed_str)
    if not match:
        raise ValueError(f"Invalid speed format: {speed_str}")
    
    value = float(match.group(1))
    unit = match.group(2) or "MB"  # Default to MB
    
    # Convert to bytes per second
    if unit == "KB":
        return value * 1024
    elif unit == "MB":
        return value * 1024 * 1024
    elif unit == "GB":
        return value * 1024 * 1024 * 1024
    else:
        return value

def extract_url_from_text(text: str) -> str | None:
    # Find all http(s) URLs in the response text
    try:
        urls = re.findall(r"https?://[^\s\"'<>]+", text)
    except Exception:
        urls = []
    if not urls:
        return None
    # Prefer URLs that look like downloadable assets (file extensions or signed query)
    # Skip Snapchat account pages which often return 405 for GET
    def is_asset_like(u: str) -> bool:
        ul = u.lower()
        return any(ext in ul for ext in (".jpg", ".jpeg", ".png", ".mp4")) or ("?" in ul)

    def is_snapchat_domain(u: str) -> bool:
        try:
            netloc = urlparse(u).netloc.lower()
        except Exception:
            return False
        return "snapchat.com" in netloc

    # First pass: asset-like and not snapchat.com
    for u in urls:
        if not is_snapchat_domain(u) and is_asset_like(u):
            return u
    # Second pass: any non-snapchat.com URL
    for u in urls:
        if not is_snapchat_domain(u):
            return u
    # Fallback: first URL (may be snapchat.com and not ideal)
    return urls[0]

def get_extension_from_content_type(content_type: str) -> str:
    """Map Content-Type header to file extension."""
    ctype = content_type.lower().split(";")[0].strip() if content_type else ""
    
    # Image types
    if ctype in ["image/jpeg", "image/jpg"]:
        return ".jpg"
    elif ctype == "image/png":
        return ".png"
    elif ctype in ["image/heic", "image/heif"]:
        return ".heic"
    elif ctype == "image/webp":
        return ".webp"
    elif ctype == "image/gif":
        return ".gif"
    elif ctype == "image/bmp":
        return ".bmp"
    # Video types
    elif ctype in ["video/mp4", "video/quicktime"]:
        return ".mp4"
    elif ctype == "video/x-msvideo":
        return ".avi"
    elif ctype == "video/x-matroska":
        return ".mkv"
    # Apple motion photo (video+jpeg combined)
    elif "ftyp" in ctype or ctype == "image/heic-sequence":
        return ".heic"  # Motion photos are HEIC-based
    else:
        # Fallback for unknown image types
        return ".jpg" if ctype.startswith("image/") else ".mp4"

def detect_ext_from_bytes(data: bytes) -> str | None:
    """Detect file type from magic bytes. Returns actual extension, not forced conversion."""
    if not data or len(data) < 4:
        return None
    # JPEG
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    # PNG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    # WebP
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    # GIF
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    # MP4/HEIC/MOV (all use ftyp - need to check brand)
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12].decode('latin1', errors='ignore').strip()
        # HEIC variants
        if brand in ["heix", "heic", "mif1"]:
            return ".heic"
        # QuickTime/MOV variants
        elif brand in ["qt  ", "mdat"]:
            return ".mov"
        # MP4 variants (most common)
        else:
            return ".mp4"
    # AVI
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"AVI ":
        return ".avi"
    # Matroska (MKV)
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return ".mkv"
    # BMP
    if data.startswith(b"BM"):
        return ".bmp"
    # ZIP
    if data.startswith(b"PK\x03\x04"):
        return ".zip"
    return None

def load_memories(json_path: Path) -> list[Memory]:
    if not json_path.exists():
        raise FileNotFoundError(f"Memories JSON not found: {json_path}")
    try:
        # Handle empty files gracefully
        if json_path.stat().st_size == 0:
            return []
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("Saved Media")
        if not isinstance(items, list):
            return []
        memories: list[Memory] = []
        for item in items:
            try:
                memories.append(Memory(**item))
            except Exception:
                # Skip malformed entries but continue
                pass
        return memories
    except json.JSONDecodeError:
        return []

def extract_main_media_from_zip(zip_path: Path, output_path: Path) -> bool:
    """
    Extract the main video/image from a Snapchat ZIP.
    Returns True if successful, False otherwise.
    """
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            file_list = zf.namelist()
            # Strategy: Look for "main" media file or largest video file
            main_files = [f for f in file_list if ("main" in f.lower() or "media" in f.lower()) and f.endswith(('.mp4', '.mov', '.jpg', '.png', '.heic'))]
            
            target_file = None
            if main_files:
                # Prefer .mp4 or .mov if mixed
                videos = [f for f in main_files if f.endswith(('.mp4', '.mov'))]
                target_file = videos[0] if videos else main_files[0]
            else:
                # Fallback: Find largest video/image
                media_files = [f for f in file_list if f.endswith(('.mp4', '.mov', '.jpg', '.png', '.heic'))]
                if media_files:
                    # Sort by size (largest first)
                    media_files.sort(key=lambda x: zf.getinfo(x).file_size, reverse=True)
                    target_file = media_files[0]
            
            if target_file:
                # Extract to output_path
                with zf.open(target_file) as source, open(output_path, "wb") as target:
                    shutil.copyfileobj(source, target)
                return True
                
    except Exception as e:
        print(f"Error extracting ZIP {zip_path}: {e}")
        
    return False
