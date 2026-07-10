"""Detect and use GPU video encoders when ffmpeg supports them."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache

from smd.ffmpeg_bundle import resolve_ffmpeg


@dataclass(frozen=True)
class VideoEncodeProfile:
    """ffmpeg video codec arguments (after inputs / filters, before output path)."""

    id: str
    label: str
    args: tuple[str, ...]


def _subprocess_flags():
    startupinfo = None
    creationflags = 0
    if sys.platform.startswith("win"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW
    return startupinfo, creationflags


@lru_cache(maxsize=4)
def _ffmpeg_encoder_list(ffmpeg: str) -> frozenset[str]:
    startupinfo, creationflags = _subprocess_flags()
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=12,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return frozenset()
    encoders: set[str] = set()
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            encoders.add(parts[1])
    return frozenset(encoders)


def cpu_lossless_profile() -> VideoEncodeProfile:
    return VideoEncodeProfile(
        id="cpu_lossless",
        label="CPU lossless (x264)",
        args=(
            "-c:v",
            "libx264",
            "-crf",
            "0",
            "-preset",
            "slow",
            "-pix_fmt",
            "yuv420p",
        ),
    )


def detect_video_encode_profiles(ffmpeg: str | None = None) -> list[VideoEncodeProfile]:
    """
    Ordered encode profiles to try for overlay video merges.
    GPU paths use maximum quality available; CPU CRF 0 is always the final fallback.
    """
    ffmpeg = ffmpeg or resolve_ffmpeg()
    profiles: list[VideoEncodeProfile] = []
    if not ffmpeg:
        return [cpu_lossless_profile()]

    encoders = _ffmpeg_encoder_list(ffmpeg)

    if "h264_nvenc" in encoders:
        profiles.append(
            VideoEncodeProfile(
                id="h264_nvenc_lossless",
                label="NVIDIA GPU lossless (NVENC)",
                args=(
                    "-c:v",
                    "h264_nvenc",
                    "-preset",
                    "lossless",
                    "-pix_fmt",
                    "yuv420p",
                ),
            )
        )

    if "h264_amf" in encoders:
        profiles.append(
            VideoEncodeProfile(
                id="h264_amf_hq",
                label="AMD GPU maximum quality (AMF)",
                args=(
                    "-c:v",
                    "h264_amf",
                    "-usage",
                    "high_quality",
                    "-quality",
                    "quality",
                    "-rc",
                    "cqp",
                    "-qp_i",
                    "0",
                    "-qp_p",
                    "0",
                    "-qp_b",
                    "0",
                    "-pix_fmt",
                    "yuv420p",
                ),
            )
        )

    if "h264_qsv" in encoders:
        profiles.append(
            VideoEncodeProfile(
                id="h264_qsv_hq",
                label="Intel GPU maximum quality (Quick Sync)",
                args=(
                    "-c:v",
                    "h264_qsv",
                    "-preset",
                    "veryslow",
                    "-global_quality",
                    "1",
                    "-pix_fmt",
                    "yuv420p",
                ),
            )
        )

    profiles.append(cpu_lossless_profile())
    return profiles


def preferred_video_encoder_label(ffmpeg: str | None = None) -> str:
    profiles = detect_video_encode_profiles(ffmpeg)
    return profiles[0].label if profiles else cpu_lossless_profile().label
