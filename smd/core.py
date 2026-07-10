import asyncio
import os
import shutil
import time
import httpx
from pathlib import Path
from smd.models import Memory, Stats
from smd.utils import extract_url_from_text, get_extension_from_content_type, detect_ext_from_bytes, extract_main_media_from_zip
from smd.metadata import apply_metadata

# Snapchat "Download My Data" HTML (memories_history.html) uses this header on GET for /dmd/mm URLs.
_SNAP_DMD_ROUTE_TAG = "mem-dmd"
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _snapchat_download_headers(url: str) -> dict:
    """Headers required for signed memory URLs in official Snapchat exports."""
    h = {
        "User-Agent": _DEFAULT_UA,
        "Accept": "*/*",
        "Referer": "https://accounts.snapchat.com/",
        "Origin": "https://accounts.snapchat.com",
    }
    if "snapchat.com" in url and "dmd/mm" in url:
        h["X-Snap-Route-Tag"] = _SNAP_DMD_ROUTE_TAG
    return h


async def resolve_snapchat_memory_url(memory: Memory) -> str:
    """
    Turn export fields into a URL we can GET.

    Newer exports include a direct aws /dmd/mm URL, but it often 403s until you run the
    same handshake older tools used: POST to app.snapchat.com/dmd/memories (Download Link)
    and read the signed CDN URL from the response body (plain text).
    """
    media = (memory.media_download_url or "").strip()
    dl = (memory.download_link or "").strip()

    if dl and "app.snapchat.com" in dl and "dmd/memories" in dl:
        try:
            async with httpx.AsyncClient(timeout=45.0, http2=True, follow_redirects=True) as client:
                # Match simple community scripts (e.g. POST body only); extra headers can break the handshake.
                post_headers = {
                    "User-Agent": _DEFAULT_UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                }
                r = await client.post(dl, headers=post_headers, data={})
                if 300 <= r.status_code < 400:
                    loc = r.headers.get("location")
                    if loc and loc.startswith("http"):
                        return loc.strip()
                if r.status_code == 200:
                    text = (r.text or "").strip()
                    if text.startswith("http"):
                        extracted = extract_url_from_text(text)
                        if extracted:
                            return extracted
                        return text.split()[0].strip()
        except Exception:
            pass

    if media:
        return media
    return dl


def find_unique_path(target_path: Path) -> Path:
    """If target_path exists, append (1), (2), etc. until unique."""
    if not target_path.exists():
        return target_path
    
    stem = target_path.stem
    ext = target_path.suffix
    directory = target_path.parent
    counter = 1
    
    while True:
        new_path = directory / f"{stem} ({counter}){ext}"
        if not new_path.exists():
            return new_path
        counter += 1

# Bandwidth Limiter (simple token bucket)
class BandwidthLimiter:
    def __init__(self, max_bytes_per_second):
        self.max_rate = max_bytes_per_second
        self.tokens = max_bytes_per_second
        self.last_check = time.monotonic()
        self.lock = asyncio.Lock()

    async def wait_for_bandwidth(self, amount):
        if self.max_rate is None:
            return
        async with self.lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_check
                self.last_check = now
                self.tokens = min(self.max_rate, self.tokens + elapsed * self.max_rate)
                
                if self.tokens >= amount:
                    self.tokens -= amount
                    return
                
                wait_time = (amount - self.tokens) / self.max_rate
                if wait_time > 0:
                    await asyncio.sleep(min(wait_time, 1.0))

async def get_cdn_url(download_link: str) -> str:
    """Extract real CDN URL from Snapchat's redirect/pre-auth link."""
    # Signed /dmd/mm URLs from JSON are final CDN URLs; official HTML downloads them with GET + X-Snap-Route-Tag.
    # POSTing to them returns 400 and breaks downloads.
    if "dmd/mm" in download_link:
        return download_link

    if "app.snapchat.com" not in download_link and "aws.snapchat.com" not in download_link:
        return download_link

    try:
        async with httpx.AsyncClient(timeout=30.0, http2=True, follow_redirects=True) as client:
            headers = {
                "User-Agent": _DEFAULT_UA,
                "Content-Type": "application/x-www-form-urlencoded",
            }
            # Often it's a POST to get the real link
            response = await client.post(download_link, headers=headers, data={})
            response.raise_for_status()
            
            # Check content type if it's already the file
            content_type = response.headers.get("content-type", "")
            if "text/" not in content_type and "json" not in content_type:
                 return str(response.url)

            text = (response.text or "").strip()
            if text.startswith("http"):
                extracted = extract_url_from_text(text)
                if extracted:
                    return extracted
                return text.split()[0].strip()
            return str(response.url)
    except Exception:
        # Fallback to original link if extraction fails
        return download_link

async def download_memory(
    memory: Memory, 
    output_dir: Path, 
    add_exif: bool, 
    semaphore: asyncio.Semaphore,
    max_retries: int = 2,
    retry_delay: float = 2.0,
    bandwidth_limiter: BandwidthLimiter = None,
    status_callback = None,
    should_stop = None, # Callable[[], bool]
    skip_existing: bool = True,
) -> tuple[str, int]:
    """Download a single memory. Returns (outcome, size_bytes) where outcome is ok|skipped|failed."""
    async with semaphore:
        # Initial check
        if should_stop and should_stop():
            return "failed", 0
            
        # Determine target filename (pre-download check)
        # We need the extension. If we don't have it, we might download to temp first.
        # But commonly we check if we can guess it or check if file exists with ANY ext.
        # For simplicity of this function, we assume we download first then move/rename.
        
        # We rely on memory.filename (which is date-based)
        # Check if file exists with common extensions
        base_name = memory.filename
        if skip_existing:
            for ext in ['.jpg', '.mp4', '.png', '.mov', '.heic', '.webp', '.gif']:
                if (output_dir / f"{base_name}{ext}").exists():
                    if status_callback: status_callback(f"Skipping {base_name} (exists)")
                    return "skipped", 0
        
        if status_callback: status_callback(f"Downloading {base_name}...")
        
        # Resolve signed CDN URL (POST handshake when needed), then legacy app.snapchat.com handling
        url = await resolve_snapchat_memory_url(memory)
        cdn_url = await get_cdn_url(url)

        if not cdn_url or not str(cdn_url).strip().lower().startswith(("http://", "https://")):
            if status_callback:
                status_callback(
                    f"No usable URL for {base_name}: 'Download Link' / 'Media Download Url' are empty in JSON. "
                    "Snapchat shipped metadata-only rows-re-request Download My Data with media URLs included, "
                    "or use embedded files from the ZIP memories/ folder."
                )
            return "failed", 0
        
        retries = 0
        while retries <= max_retries:
            # Check before retry attempt
            if should_stop and should_stop():
                return "failed", 0
                
            try:
                req_headers = _snapchat_download_headers(cdn_url)
                async with httpx.AsyncClient(timeout=60.0, http2=True, follow_redirects=True) as client:
                    async with client.stream("GET", cdn_url, headers=req_headers) as response:
                        response.raise_for_status()
                        
                        # Determine extension
                        content_type = response.headers.get("content-type", "")
                        ext = get_extension_from_content_type(content_type)
                        if not ext:
                            ext = ".tmp" # Temporarily
                        
                        temp_file = output_dir / f"{base_name}_temp{ext}"
                        
                        # Download loop
                        downloaded_bytes = 0
                        first_chunk = None
                        with open(temp_file, "wb") as f:
                            async for chunk in response.aiter_bytes(chunk_size=8192):
                                if not first_chunk:
                                    first_chunk = chunk
                                
                                # Check cancellation inside stream
                                if should_stop and should_stop():
                                    if status_callback: status_callback(f"Cancelled {base_name}")
                                    break
                                
                                if bandwidth_limiter:
                                    await bandwidth_limiter.wait_for_bandwidth(len(chunk))
                                f.write(chunk)
                                downloaded_bytes += len(chunk)
                        
                        # If cancelled mid-stream, cleanup and return
                        if should_stop and should_stop():
                            try:
                                temp_file.unlink()
                            except OSError:
                                pass
                            return "failed", 0
                                
                        # Identify file type if unknown
                        # Check for ZIP or wrong extension based on magic bytes
                        detected_ext = detect_ext_from_bytes(first_chunk)
                        
                        # Special handling for ZIP files (Snapchat Memories Packages)
                        if detected_ext == ".zip":
                            if status_callback: status_callback(f"Detected ZIP package for {base_name}, attempting to extract main media...")
                            extracted_temp_path = output_dir / f"{base_name}_extracted_temp.mp4" # Temp name for extracted
                            
                            # Remove if exists from previous failed run
                            if extracted_temp_path.exists():
                                try: extracted_temp_path.unlink()
                                except: pass

                            if extract_main_media_from_zip(temp_file, extracted_temp_path):
                                # Replace temp_file with the extracted file
                                try:
                                    temp_file.unlink() # Delete the original zip file
                                except Exception as e:
                                    print(f"Warning: Could not delete zip {temp_file}: {e}")
                                
                                temp_file = extracted_temp_path # Now point to the extracted file
                                
                                # Re-detect extension of the extracted file
                                try:
                                    with open(temp_file, "rb") as f:
                                        header = f.read(32)
                                        real_ext = detect_ext_from_bytes(header) or ".mp4" # Default to .mp4 if detection fails
                                        ext = real_ext
                                    if status_callback: status_callback(f"Extracted media for {base_name} as {ext}")
                                except Exception as e:
                                    print(f"Error re-detecting extension: {e}")
                                    ext = ".mp4"
                            else:
                                if status_callback: status_callback(f"Failed to extract media from ZIP {base_name}, keeping as .zip")
                                ext = ".zip" # Keep as zip if extraction failed
                        
                        elif ext == ".tmp" or (detected_ext and ext != detected_ext):
                            if detected_ext:
                                ext = detected_ext
                        
                        # Find unique final path to avoid collisions
                        final_path = find_unique_path(output_dir / f"{base_name}{ext}")

                        shutil.move(temp_file, final_path)
                        temp_file = final_path # Update temp_file to final_path for subsequent operations
                        
                        # Metadata
                        if add_exif:
                             if status_callback: status_callback(f"Applying metadata {base_name}...")
                             apply_metadata(temp_file, memory, ext)
                        
                        # Quarantine check (empty files or small files that are likely errors)
                        file_size = temp_file.stat().st_size
                        if file_size < 1000:
                            # Possible error file (html error etc)
                            quarantine_dir = output_dir / "quarantine"
                            quarantine_dir.mkdir(exist_ok=True)
                            shutil.move(temp_file, quarantine_dir / temp_file.name)
                            if status_callback: status_callback(f"Quarantined {base_name} (too small)")
                            return "failed", 0
                            
                        return "ok", file_size

            except Exception as e:
                # Check cancellation before retry handling
                if should_stop and should_stop():
                    return "failed", 0
                    
                retries += 1
                if retries <= max_retries:
                    if status_callback: status_callback(f"Retry {retries}/{max_retries} for {base_name}")
                    await asyncio.sleep(retry_delay * retries)
                else:
                    if status_callback: status_callback(f"Failed {base_name}: {str(e)}")
                    return "failed", 0
                    
        return "failed", 0

async def download_all(
    memories: list[Memory],
    output_dir: Path,
    concurrent: int,
    add_exif: bool,
    skip_existing: bool,
    batch_size: int = 50,
    batch_delay: int = 15,
    max_retries: int = 2,
    bandwidth_limiter: BandwidthLimiter = None,
    progress_callback = None, # Callable[[current, total, success, size_bytes], None]
    status_callback = None, # Callable[[str], None] -- for log messages
    should_stop = None, # Callable[[], bool] -- returns True if download should be cancelled
    limit: int = 0 # Limit number of downloads (0 = no limit)
) -> Stats:
    """
    Orchestrate the download of all memories.
    """
    semaphore = asyncio.Semaphore(concurrent)
    stats = Stats()
    
    if limit > 0:
        if status_callback: status_callback(f"⚠️ TEST MODE: Limiting download to recent {limit} memories")
        memories = memories[:limit]
    
    total_memories = len(memories)
    if status_callback: status_callback(f"🚀 Starting download of {total_memories} memories...")
    
    # Process in batches
    for i in range(0, total_memories, batch_size):
        # Check cancellation before starting batch
        if should_stop and should_stop():
            if status_callback: status_callback("⏹ Download cancelled by user.")
            break
            
        batch = memories[i : i + batch_size]
        tasks = []
        for mem in batch:
            # Check cancellation before queueing task (optional granularity)
            if should_stop and should_stop():
                break

            tasks.append(
                download_memory(
                    mem, output_dir, add_exif, semaphore,
                    max_retries=max_retries,
                    bandwidth_limiter=bandwidth_limiter,
                    status_callback=status_callback,
                    should_stop=should_stop,
                    skip_existing=skip_existing,
                )
            )
        
        if tasks:
            results = await asyncio.gather(*tasks)
            
            for outcome, size_bytes in results:
                if outcome == "ok":
                    stats.downloaded += 1
                    stats.mb += size_bytes / (1024 * 1024)
                elif outcome == "skipped":
                    stats.skipped += 1
                else:
                    stats.failed += 1
                
                if progress_callback:
                    done = stats.downloaded + stats.skipped + stats.failed
                    progress_callback(done, total_memories, outcome == "ok", size_bytes)
            
        if batch_delay > 0 and i + batch_size < total_memories:
            # Check cancellation before sleep
            if should_stop and should_stop():
                if status_callback: status_callback("⏹ Download cancelled by user.")
                break
                
            if status_callback: status_callback(f"Sleeping {batch_delay}s between batches...")
            # Sleep in small chunks to remain responsive to cancel
            for _ in range(batch_delay * 10):
                if should_stop and should_stop():
                    break
                await asyncio.sleep(0.1)

    return stats
