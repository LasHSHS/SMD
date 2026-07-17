"""Detect and use GPU video encoders when ffmpeg supports them."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache

from smd.ffmpeg_bundle import resolve_ffmpeg
from smd.procutil import subprocess_flags as _subprocess_flags


@dataclass(frozen=True)
class VideoEncodeProfile:
    """ffmpeg video codec arguments (after inputs / filters, before output path)."""

    id: str
    label: str
    args: tuple[str, ...]


# Snapchat's source video is already lossy-compressed by its own phone-app
# encoder, so re-encoding it truly losslessly (x264 CRF 0 / QP 0) doesn't
# recover or preserve any extra quality that wasn't already lost - it just
# perfectly preserves the source's existing compression artifacts at 15-25x
# the file size.
#
# Every value below targets the same "visually lossless" bar: VMAF >= ~99.9
# (a perceptual quality score, 100 = pixel identical) against the old CRF 0
# / QP 0 output, on a real overlay-merged Snapchat video. Encoders are NOT
# interchangeable at the same nominal number - x264's CRF and each vendor's
# QP/CQ scale have different rate-distortion curves, so each value was
# picked separately rather than reusing one number everywhere:
#   - x264 CRF 16              -> measured 63 MB (was 484 MB), VMAF 99.96
#     [hardware-tested here with real Snapchat overlay video + VMAF]
#   - AMD AMF QP 22             -> measured 65 MB (was 484 MB), VMAF 99.91
#     [hardware-tested here with real Snapchat overlay video + VMAF]
#   - NVIDIA NVENC CQ 18, Intel QSV global_quality 18 -> not verified on real
#     hardware (none available while tuning this). Set from published
#     third-party CRF/CQ-equivalence benchmarks instead of a guess: NVENC CQ
#     18 and QSV global_quality ~18-25 are independently reported as the
#     "visually lossless" tier matching x264 CRF 16-18. If you have this
#     hardware and can confirm/adjust these with a real VMAF test (see
#     AMD_AMF_QP above for the method), that's a welcome follow-up.
CPU_X264_CRF = 16
AMD_AMF_QP = 22
NVIDIA_NVENC_CQ = 18
INTEL_QSV_QUALITY = 18


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


# Checked in this order - first one that actually produces output on this
# machine wins. Args here are deliberately minimal/fast (not the quality
# settings used for real merges) since this is just a capability probe.
_GPU_PROBE_CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("h264_nvenc", ("-preset", "p1", "-cq", "30")),
    ("h264_amf", ("-usage", "transcoding", "-quality", "speed")),
    ("h264_qsv", ("-preset", "veryfast", "-global_quality", "30")),
)


@lru_cache(maxsize=4)
def _working_gpu_encoder(ffmpeg: str) -> str | None:
    """Which GPU encoder (if any) can actually produce output on *this*
    hardware - not just which ones ffmpeg was compiled with.

    "Full" ffmpeg builds (including the one SMD bundles) compile in the
    NVENC/AMF/QSV wrapper code regardless of what GPU is installed, so
    `-encoders` lists all three even on, say, an AMD-only machine with no
    NVIDIA hardware at all. Checking that list alone (the old approach)
    meant NVENC was always tried first and always failed on non-NVIDIA
    machines - one wasted, failing ffmpeg subprocess call per overlay video,
    forever, before falling through to the encoder that actually works.

    This runs one tiny real test encode per candidate, exactly once per
    ffmpeg binary (cached), instead of re-discovering the same failure on
    every single file.
    """
    encoders = _ffmpeg_encoder_list(ffmpeg)
    startupinfo, creationflags = _subprocess_flags()
    for codec, extra_args in _GPU_PROBE_CANDIDATES:
        if codec not in encoders:
            continue
        try:
            r = subprocess.run(
                [
                    # 320x240, not something tiny like 64x64: AMD's AMF
                    # encoder init fails below its minimum resolution, which
                    # would otherwise look identical to "no GPU support" and
                    # wrongly fall through to CPU on real AMD hardware.
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.1",
                    "-frames:v", "1", "-c:v", codec, *extra_args,
                    "-pix_fmt", "yuv420p", "-f", "null", "-",
                ],
                capture_output=True,
                timeout=10,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
            if r.returncode == 0:
                return codec
        except (subprocess.TimeoutExpired, OSError):
            continue
    return None


def cpu_quality_profile() -> VideoEncodeProfile:
    return VideoEncodeProfile(
        id="cpu_high_quality",
        label="CPU high quality (x264)",
        args=(
            "-c:v",
            "libx264",
            "-crf",
            str(CPU_X264_CRF),
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
        ),
    )


def _nvenc_quality_profile() -> VideoEncodeProfile:
    return VideoEncodeProfile(
        id="h264_nvenc_hq",
        label="NVIDIA GPU high quality (NVENC)",
        args=(
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p7",
            "-tune",
            "hq",
            "-rc",
            "vbr",
            "-cq",
            str(NVIDIA_NVENC_CQ),
            # NVENC's -cq is silently ignored without an explicit,
            # unset bitrate cap - this is a well-documented gotcha,
            # not optional polish.
            "-b:v",
            "0",
            "-pix_fmt",
            "yuv420p",
        ),
    )


def _amf_quality_profile() -> VideoEncodeProfile:
    return VideoEncodeProfile(
        id="h264_amf_hq",
        label="AMD GPU high quality (AMF)",
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
            str(AMD_AMF_QP),
            "-qp_p",
            str(AMD_AMF_QP),
            "-qp_b",
            str(AMD_AMF_QP),
            "-pix_fmt",
            "yuv420p",
        ),
    )


def _qsv_quality_profile() -> VideoEncodeProfile:
    return VideoEncodeProfile(
        id="h264_qsv_hq",
        label="Intel GPU high quality (Quick Sync)",
        args=(
            "-c:v",
            "h264_qsv",
            "-preset",
            "veryslow",
            "-global_quality",
            str(INTEL_QSV_QUALITY),
            # Enables LA_ICQ (lookahead intelligent constant quality),
            # QSV's closest match to x264's CRF behavior.
            "-look_ahead",
            "1",
            "-pix_fmt",
            "yuv420p",
        ),
    )


_GPU_QUALITY_PROFILES = {
    "h264_nvenc": _nvenc_quality_profile,
    "h264_amf": _amf_quality_profile,
    "h264_qsv": _qsv_quality_profile,
}


def detect_video_encode_profiles(ffmpeg: str | None = None) -> list[VideoEncodeProfile]:
    """
    Ordered encode profiles to try for overlay video merges: the one GPU
    encoder that actually works on this hardware (if any), then CPU x264 as
    the final fallback. All paths target a "visually lossless" quality bar,
    not true losslessness - see the constants above for how each was
    calibrated.

    Only one GPU profile is ever returned (not "every compiled-in vendor
    wrapper in priority order") because `_working_gpu_encoder` already ran a
    real probe - see its docstring for why that matters.
    """
    ffmpeg = ffmpeg or resolve_ffmpeg()
    if not ffmpeg:
        return [cpu_quality_profile()]

    profiles: list[VideoEncodeProfile] = []
    working = _working_gpu_encoder(ffmpeg)
    builder = _GPU_QUALITY_PROFILES.get(working) if working else None
    if builder:
        profiles.append(builder())

    profiles.append(cpu_quality_profile())
    return profiles


def preferred_video_encoder_label(ffmpeg: str | None = None) -> str:
    profiles = detect_video_encode_profiles(ffmpeg)
    return profiles[0].label if profiles else cpu_quality_profile().label
