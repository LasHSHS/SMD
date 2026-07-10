from datetime import datetime, timezone
import re
from typing import Optional
from pydantic import BaseModel, Field, field_validator

from smd.timeutil import to_local_datetime

class Memory(BaseModel):
    model_config = {"populate_by_name": True}
    
    date: datetime = Field(alias="Date")
    download_link: str = Field(default="", alias="Download Link")
    media_download_url: Optional[str] = Field(None, alias="Media Download Url")
    media_type: Optional[str] = Field(None, alias="Media Type")
    location: str = Field(default="", alias="Location")
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v):
        if isinstance(v, str):
            # Stored as UTC in JSON; attach tzinfo so we can convert to local later
            try:
                dt_utc = datetime.strptime(v, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
                return dt_utc
            except ValueError:
                # Fallback for ISO format or other variations if they appear
                return v
        return v

    def model_post_init(self, __context):
        if self.location and not self.latitude:
            if match := re.search(r"([-\d.]+),\s*([-\d.]+)", self.location):
                lat = float(match.group(1))
                lon = float(match.group(2))
                # Skip if coordinates are exactly 0,0 (Snapchat's "no location" marker)
                if lat != 0.0 or lon != 0.0:
                    self.latitude = lat
                    self.longitude = lon

    @property
    def filename(self) -> str:
        """Local-time output name; must stay in sync with EXIF timestamps."""
        local_dt = to_local_datetime(self.date, self.latitude, self.longitude)
        return local_dt.strftime("%Y-%m-%d_%H-%M-%S")


class Stats(BaseModel):
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    mb: float = 0
