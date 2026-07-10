"""Detect PC capabilities and recommend processing settings."""

from __future__ import annotations



import os

from dataclasses import dataclass



import psutil



PERF_MODES = ("maximum", "balanced", "conservative")

PERF_FRACTIONS = {"maximum": 0.8, "balanced": 0.6, "conservative": 0.4}

MODE_LABELS = {

    "maximum": "Maximum (use all power)",

    "balanced": "Balanced (smooth PC use)",

    "conservative": "Eco (background friendly)",

}





@dataclass(frozen=True)

class SystemProfile:

    physical_cores: int

    logical_cpus: int

    ram_gb: float

    on_battery: bool | None  # None = no battery / desktop

    battery_percent: int | None



    @property

    def cpu_count(self) -> int:

        """Logical CPUs - used for thread-pool sizing."""

        return self.logical_cpus



    @property

    def power_label(self) -> str:

        if self.on_battery is None:

            return "Plugged in (desktop)"

        if self.on_battery:

            pct = f" {self.battery_percent}%" if self.battery_percent is not None else ""

            return f"On battery{pct}"

        return "Plugged in"



    def summary(self) -> str:

        if self.physical_cores == self.logical_cpus:

            cpu_txt = f"{self.physical_cores} cores"

        else:

            cpu_txt = f"{self.physical_cores} cores / {self.logical_cpus} threads"

        return f"{cpu_txt} • {self.ram_gb:.0f} GB RAM • {self.power_label}"





@dataclass(frozen=True)

class ProcessingSettings:

    performance_mode: str

    max_workers: int

    max_ffmpeg: int

    ffmpeg_threads: int

    reason: str





def get_system_profile() -> SystemProfile:

    logical = psutil.cpu_count(logical=True) or os.cpu_count() or 2

    physical = psutil.cpu_count(logical=False) or logical

    ram_gb = psutil.virtual_memory().total / (1024**3)

    on_battery: bool | None = None

    battery_percent: int | None = None

    try:

        bat = psutil.sensors_battery()

        if bat is not None:

            on_battery = not bat.power_plugged

            battery_percent = int(bat.percent) if bat.percent is not None else None

    except Exception:

        pass

    return SystemProfile(

        physical_cores=physical,

        logical_cpus=logical,

        ram_gb=ram_gb,

        on_battery=on_battery,

        battery_percent=battery_percent,

    )





def recommend_settings(profile: SystemProfile | None = None) -> ProcessingSettings:

    """Pick performance mode + worker counts from hardware and power state."""

    profile = profile or get_system_profile()

    mode = "balanced"

    reasons: list[str] = []



    if profile.on_battery is None:

        if profile.cpu_count >= 4 and profile.ram_gb >= 8:

            mode = "maximum"

            reasons.append("desktop PC with good CPU")

        elif profile.cpu_count >= 2:

            mode = "balanced"

            reasons.append("desktop PC")

        else:

            mode = "conservative"

            reasons.append("limited CPU cores")

    elif profile.on_battery:

        if profile.battery_percent is not None and profile.battery_percent < 20:

            mode = "conservative"

            reasons.append("low battery")

        elif profile.battery_percent is not None and profile.battery_percent < 40:

            mode = "conservative"

            reasons.append("battery below 40%")

        else:

            mode = "balanced"

            reasons.append("on battery - saving power")

    else:

        if profile.cpu_count >= 4 and profile.ram_gb >= 8:

            mode = "maximum"

            reasons.append("plugged in")

        else:

            mode = "balanced"

            reasons.append("plugged in")



    if profile.ram_gb < 8 and mode == "maximum":

        mode = "balanced"

        reasons.append("under 8 GB RAM")



    settings = compute_workers(mode, profile)

    reason = "; ".join(reasons) if reasons else "default"

    return ProcessingSettings(

        performance_mode=mode,

        max_workers=settings.max_workers,

        max_ffmpeg=settings.max_ffmpeg,

        ffmpeg_threads=settings.ffmpeg_threads,

        reason=reason,

    )





def _compute_ffmpeg_limits(
    ram_gb: float,
    workers: int,
    logical_cpus: int,
) -> tuple[int, int]:
    """
    Return (max_ffmpeg, threads_per_job).

    More RAM allows more concurrent lossless encodes; thread cap per job
    keeps total ffmpeg CPU use below logical_cpus with OS/Python headroom.
    """
    if ram_gb < 8:
        max_ffmpeg = 1
    elif ram_gb < 16:
        max_ffmpeg = min(3, max(1, workers // 3))
    elif ram_gb < 32:
        max_ffmpeg = min(5, max(2, workers // 2))
    else:
        max_ffmpeg = min(6, max(3, workers // 2))

    reserve = 2 if logical_cpus >= 8 else 1
    available = max(1, logical_cpus - reserve)
    threads_per_job = max(1, available // max_ffmpeg)
    return max_ffmpeg, threads_per_job


def compute_workers(

    performance_mode: str,

    profile: SystemProfile | None = None,

    *,

    task: str = "export",

) -> ProcessingSettings:

    """Translate performance mode into thread/ffmpeg limits."""

    profile = profile or get_system_profile()

    mode = performance_mode if performance_mode in PERF_FRACTIONS else "balanced"



    if profile.on_battery and profile.battery_percent is not None and profile.battery_percent < 25:

        mode = "conservative"

    elif profile.on_battery and mode == "maximum":

        mode = "balanced"



    if task == "gps":

        workers = _gps_workers(mode, profile.logical_cpus)

    else:

        frac = PERF_FRACTIONS[mode]

        workers = max(1, int(profile.logical_cpus * frac))



    if profile.ram_gb < 8:

        workers = min(workers, 4)

    max_ffmpeg, ffmpeg_threads = _compute_ffmpeg_limits(
        profile.ram_gb, workers, profile.logical_cpus
    )

    return ProcessingSettings(

        performance_mode=mode,

        max_workers=workers,

        max_ffmpeg=max_ffmpeg,

        ffmpeg_threads=ffmpeg_threads,

        reason=MODE_LABELS.get(mode, mode),

    )





def _gps_workers(mode: str, cpu_count: int) -> int:

    """GPS scan uses slightly higher parallelism than bundled export."""

    if mode == "conservative":

        if cpu_count <= 2:

            return 2

        if cpu_count <= 4:

            return 3

        if cpu_count <= 8:

            return 4

        if cpu_count <= 16:

            return 8

        return 12

    if mode == "balanced":

        if cpu_count <= 2:

            return 2

        if cpu_count <= 4:

            return 4

        if cpu_count <= 8:

            return 6

        if cpu_count <= 16:

            return 12

        if cpu_count <= 32:

            return 20

        return 28

    # maximum

    if cpu_count <= 2:

        return 2

    if cpu_count <= 4:

        return 4

    if cpu_count <= 16:

        return cpu_count

    if cpu_count <= 32:

        return int(cpu_count * 0.9)

    return int(cpu_count * 0.85)





def mode_to_combo_index(mode: str) -> int:

    return {"maximum": 0, "balanced": 1, "conservative": 2}.get(mode, 1)

