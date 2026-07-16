"""Timezone conversion shared by output naming and metadata.

Output filenames and embedded EXIF timestamps must agree, so both go through
this single implementation.

Deliberately uses the system's local timezone rather than a GPS-derived
timezone for the photo/video location. Snapchat's own app displays memory
timestamps in the phone's configured device timezone, not the timezone of
wherever the phone physically was at capture time. If a phone doesn't
auto-update timezone while traveling (common when roaming without a data
connection, or with automatic timezone updates disabled), GPS-derived local
time can be off by an hour or more from what the user actually saw in
Snapchat and remembers. Matching the system timezone keeps SMD's output
consistent with what users expect from their own Snapchat app. See
agent-docs/DECISIONS.md for the concrete case that motivated this.
"""
from __future__ import annotations

from datetime import datetime


def to_local_datetime(
    date: datetime,
    latitude: float | None = None,
    longitude: float | None = None,
) -> datetime:
    """Convert a UTC capture time to the local system timezone.

    latitude/longitude are accepted for backward compatibility but are no
    longer used to derive the timezone; see module docstring for why.
    """
    return date.astimezone()
