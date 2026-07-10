"""GPS-aware timezone conversion shared by output naming and metadata.

Output filenames and embedded EXIF timestamps must agree, so both go through
this single implementation.
"""
from __future__ import annotations

from datetime import datetime

import pytz
from timezonefinder import TimezoneFinder

# One shared instance: TimezoneFinder initialization is expensive.
_timezone_finder = TimezoneFinder()


def to_local_datetime(
    date: datetime,
    latitude: float | None = None,
    longitude: float | None = None,
) -> datetime:
    """Convert a UTC capture time to local time at the GPS location.

    Falls back to the system timezone when GPS is absent or lookup fails.
    """
    if latitude is not None and longitude is not None:
        try:
            tz_name = _timezone_finder.timezone_at(lat=latitude, lng=longitude)
            if tz_name:
                return date.astimezone(pytz.timezone(tz_name))
        except Exception:
            pass
    return date.astimezone()
