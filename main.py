#!/usr/bin/env python3
"""
Snapchat Memories Downloader (SMD) - CLI backend

Processes a bundled Snapchat data export (media inside the ZIP) fully offline:
extracts media, merges overlays, embeds timestamps and GPS metadata.

Created by: Las HS (https://github.com/LasHSHS)
License: Open Source
"""
import argparse
import functools
import sys
from pathlib import Path

# Force unbuffered output
print = functools.partial(print, flush=True)

# Force UTF-8 encoding for stdout
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Snapchat Memories Downloader - offline bundled export processor"
    )
    parser.add_argument(
        "export",
        type=Path,
        help="Bundled export ZIP (any part) or folder containing all ZIP parts",
    )

    home = Path.home()
    if sys.platform == "win32":
        default_output = home / "Desktop" / "SnapMemories"
    else:
        default_output = home / "SnapMemories"

    parser.add_argument("-o", "--output", type=Path, default=default_output, help="Output directory")
    parser.add_argument("--no-exif", action="store_true", help="Disable EXIF/GPS embedding")
    parser.add_argument("--no-overlay-merge", action="store_true", help="Skip overlay merge")
    parser.add_argument("--no-raw", action="store_true", help="Skip raw/ copy folder")
    parser.add_argument("--no-repair", action="store_true", help="Skip video repair attempts")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of files to process")

    args = parser.parse_args()

    if args.limit < 0:
        print(f"Invalid --limit: {args.limit}")
        return 2

    if not args.export.exists():
        print(f"Export path not found: {args.export}")
        return 2

    from smd.export_detect import analyze_zip_export
    from smd.local_pipeline import process_bundled_export

    analysis = analyze_zip_export(args.export)
    print(f"[export] {analysis.message}")
    if not analysis.is_bundled:
        print(
            "This export does not include media files inside the ZIP.\n"
            "Request a new Snapchat data export with memories included."
        )
        return 1

    try:
        args.output.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Cannot create output directory {args.output}: {e}")
        return 2

    print(f"[run] Processing bundled export -> {args.output}")
    stats = process_bundled_export(
        args.export,
        args.output,
        merge_overlays=not args.no_overlay_merge,
        keep_raw=not args.no_raw,
        repair_videos=not args.no_repair,
        apply_meta=not args.no_exif,
        limit=args.limit,
        status_callback=lambda msg: print(msg),
    )

    print("\n" + "=" * 40)
    for line in stats.summary_lines():
        print(line)
    print("=" * 40)

    return 1 if stats.failed else 0


if __name__ == "__main__":
    sys.exit(main())
