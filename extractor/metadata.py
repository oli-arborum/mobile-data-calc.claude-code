from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image


def extract_reporting_month(image_path: Path) -> tuple[int, int]:
    """Extract the reporting month from image EXIF data.

    The reporting month is one month before the capture date, since iOS
    screenshots of data usage are taken at the start of the next month.

    Returns (year, month) tuple.
    """
    with Image.open(image_path) as img:
        exif = img.getexif()

        # Try DateTimeOriginal from ExifIFD first, fall back to DateTime
        timestamp_str = None
        ifd = exif.get_ifd(0x8769)
        if 36867 in ifd:
            timestamp_str = ifd[36867]
        elif 306 in exif:
            timestamp_str = exif[306]

    if timestamp_str is None:
        raise ValueError(f"No date metadata found in {image_path}")

    capture_date = datetime.strptime(timestamp_str, "%Y:%m:%d %H:%M:%S")

    # Subtract one month
    if capture_date.month == 1:
        return (capture_date.year - 1, 12)
    else:
        return (capture_date.year, capture_date.month - 1)
