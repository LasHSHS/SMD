from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from smd.metadata import (
    _convert_dms_to_degrees,
    add_exif_data_img,
    extract_gps_image,
)
from smd.models import Memory


def test_convert_dms_handles_exif_rationals():
    dms = ((55, 1), (40, 1), (3396, 100))
    assert abs(_convert_dms_to_degrees(dms) - 55.6761) < 0.0001


def test_extract_gps_image_roundtrip(tmp_path: Path):
    image_path = tmp_path / "sample.jpg"
    Image.new("RGB", (8, 8), color="red").save(image_path, quality=95)

    memory = Memory(
        filename="sample",
        date=datetime.now(timezone.utc),
        latitude=55.6761,
        longitude=12.5683,
        media_type="Image",
        download_url="",
    )
    add_exif_data_img(image_path, memory)

    coords = extract_gps_image(image_path)
    assert coords is not None
    assert abs(coords[0] - 55.6761) < 0.001
    assert abs(coords[1] - 12.5683) < 0.001
