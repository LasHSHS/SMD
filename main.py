#!/usr/bin/env python3
"""
Snapchat Memories Downloader (SMD) - Backend
Download Snapchat memories with timestamps, GPS coordinates, and smart retry logic

Created by: Las HS (https://github.com/LasHSHS)
License: Open Source
"""
import argparse
import asyncio
import json
import os
import sys
import time
import functools
from pathlib import Path
from datetime import datetime, timedelta

# Force unbuffered output
print = functools.partial(print, flush=True)

# Force UTF-8 encoding for stdout
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from tqdm.asyncio import tqdm
from smd.models import Memory, Stats
from smd.utils import load_memories, parse_speed
from smd.core import BandwidthLimiter, download_memory, download_all

# Check tools
# (ExifTool removed)

# Local download_all removed in favor of smd.core.download_all

def run_bundled_export(args) -> int:
    """Process bundled Snapchat export (media inside ZIP, no CDN)."""
    from smd.export_detect import analyze_zip_export
    from smd.local_pipeline import process_bundled_export

    export_path = args.export
    if not export_path.exists():
        print(f"❌ Export path not found: {export_path}")
        return 1

    analysis = analyze_zip_export(export_path)
    print(f"📦 {analysis.message}")

    args.output.mkdir(parents=True, exist_ok=True)
    print(f"🚀 Processing bundled export → {args.output}")

    stats = process_bundled_export(
        export_path,
        args.output,
        merge_overlays=not args.no_overlay_merge,
        keep_raw=not args.no_raw,
        repair_videos=not args.no_repair,
        apply_meta=not args.no_exif,
        limit=args.limit or 0,
        status_callback=lambda msg: print(msg),
    )

    print("\n" + "=" * 40)
    for line in stats.summary_lines():
        print(line)
    print("=" * 40)
    return 0


async def main():
    parser = argparse.ArgumentParser(description="Snapchat Memories Downloader")
    parser.add_argument("input_json", nargs="?", type=Path, help="memories_history.json (CDN download mode)")
    parser.add_argument(
        "--export",
        type=Path,
        help="Bundled export ZIP or folder (2026+ format with media inside ZIP)",
    )
    # Portable default: Desktop is easy to find; fallback to Documents, then cwd
    home = Path.home()
    if sys.platform == "win32":
        default_output = home / "Desktop" / "SnapMemories"
    else:
        default_output = home / "SnapMemories"
    try:
        default_output.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        default_output = Path.cwd() / "downloads"
        
    parser.add_argument("-o", "--output", type=Path, default=default_output, help="Output directory")
    parser.add_argument("-c", "--concurrent", type=int, default=5, help="Concurrent downloads")
    parser.add_argument("--no-exif", action="store_true", help="Disable EXIF/GPS embedding")
    parser.add_argument("--no-skip-existing", action="store_true", help="Re-download existing files")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--limit-speed", type=str, help="Speed limit (e.g. 5MB/s)")
    parser.add_argument("--limit", type=int, help="Limit number of files to process")
    parser.add_argument("--template", type=str, default="{YYYY}-{MM}-{DD}_{Location}_{Type}_{ID}", help="Filename template")

    # Bundled export options
    parser.add_argument("--no-overlay-merge", action="store_true", help="Skip overlay merge (bundled mode)")
    parser.add_argument("--no-raw", action="store_true", help="Skip raw/ copy folder (bundled mode)")
    parser.add_argument("--no-repair", action="store_true", help="Skip video repair attempts (bundled mode)")
    
    # Date filters
    parser.add_argument("--last-30-days", action="store_true", help="Download last 30 days only")
    parser.add_argument("--last-year", action="store_true", help="Download last year only")
    parser.add_argument("--this-year", action="store_true", help="Download this year only")
    parser.add_argument("--from-date", type=str, help="YYYY-MM-DD")
    parser.add_argument("--to-date", type=str, help="YYYY-MM-DD")
    
    # Type filters
    parser.add_argument("--photos-only", action="store_true", help="Photos only")
    parser.add_argument("--videos-only", action="store_true", help="Videos only")

    args = parser.parse_args()

    if args.export:
        return run_bundled_export(args)

    if not args.input_json:
        parser.error("Provide memories_history.json or use --export for bundled ZIP/folder")

    if not args.input_json.exists():
        print(f"❌ Input file not found: {args.input_json}")
        return

    memories = load_memories(args.input_json)
    if not memories:
        print("❌ No memories found in JSON.")
        return

    # Apply Filters (preset ranges are mutually exclusive in spirit; last match wins if multiple set)
    if args.last_30_days:
        from_dt = datetime.now() - timedelta(days=30)
        memories = [m for m in memories if m.date.replace(tzinfo=None) >= from_dt]
    elif args.last_year:
        from_dt = datetime.now() - timedelta(days=365)
        memories = [m for m in memories if m.date.replace(tzinfo=None) >= from_dt]
    elif args.this_year:
        y = datetime.now().year
        memories = [m for m in memories if m.date.year == y]

    if args.from_date:
        try:
            fd = datetime.strptime(args.from_date, "%Y-%m-%d").date()
            memories = [m for m in memories if m.date.date() >= fd]
        except ValueError:
            print(f"❌ Invalid --from-date (use YYYY-MM-DD): {args.from_date}")
            return
    if args.to_date:
        try:
            td = datetime.strptime(args.to_date, "%Y-%m-%d").date()
            memories = [m for m in memories if m.date.date() <= td]
        except ValueError:
            print(f"❌ Invalid --to-date (use YYYY-MM-DD): {args.to_date}")
            return

    if args.photos_only:
        memories = [
            m for m in memories
            if (m.media_type or "").lower() != "video"
            and ".mp4" not in (m.download_link or "").lower()
        ]
    elif args.videos_only:
        memories = [
            m for m in memories
            if (m.media_type or "").lower() == "video"
            or ".mp4" in (m.download_link or "").lower()
        ]

    if args.limit:
        memories = memories[:args.limit]
        print(f"🎯 Limited download to first {args.limit} items.")

    limiter = None
    if args.limit_speed:
        try:
            bps = parse_speed(args.limit_speed)
            limiter = BandwidthLimiter(bps)
            print(f"🐢 Speed limit set to: {args.limit_speed}")
        except ValueError as e:
            print(f"❌ {e}")
            return

    args.output.mkdir(parents=True, exist_ok=True)
    
    print(f"🚀 Starting download of {len(memories)} memories...")
    total = len(memories)
    pbar = tqdm(total=total, unit="mem", desc="Downloading")
    
    def progress_adapter(current, total_files, success, size_bytes):
        pbar.update(1)
            
    stats = await download_all(
        memories,
        args.output,
        args.concurrent,
        not args.no_exif,
        not args.no_skip_existing,
        bandwidth_limiter=limiter,
        progress_callback=progress_adapter,
        status_callback=lambda msg: print(f"DEBUG: {msg}")
    )
    
    pbar.close()
    
    print("\n" + "=" * 40)
    print(f"🎉 Done! Downloaded: {stats.downloaded} ({stats.mb:.2f} MB)")
    if stats.skipped:
        print(f"⏭ Skipped (already on disk): {stats.skipped}")
    print(f"❌ Failed: {stats.failed}")
    print("=" * 40)
    
    if stats.failed > 0:
        # Could save failed list here
        pass

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
