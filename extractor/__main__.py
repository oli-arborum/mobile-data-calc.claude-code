"""CLI entry point for the iOS data usage screenshot extractor."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from extractor.database import create_database, insert_entries
from extractor.metadata import extract_reporting_month
from extractor.ocr import DataEntry, extract_entries

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract per-app mobile data usage from iOS screenshots.",
    )
    parser.add_argument(
        "-i", "--input-path", type=Path, default=Path("./images"),
        help="Folder containing screenshot images (default: ./images)",
    )
    parser.add_argument(
        "-d", "--db", type=Path, default=Path("data_usage.sqlite"),
        help="Path to SQLite database file (default: data_usage.sqlite)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    input_folder: Path = args.input_path
    db_path: Path = args.db

    if not input_folder.is_dir():
        logger.error("Input folder does not exist: %s", input_folder)
        raise SystemExit(1)

    # Collect image files (sorted for deterministic order)
    image_files = sorted(
        p for p in input_folder.iterdir()
        if p.suffix.upper() in (".PNG", ".JPG", ".JPEG", ".TIFF")
    )

    if not image_files:
        logger.warning("No image files found in %s", input_folder)
        raise SystemExit(1)

    logger.info("Found %d image files in %s", len(image_files), input_folder)

    # Create database
    create_database(db_path)

    # Process each image
    all_entries: list[tuple[int, int, str, float]] = []
    for image_path in image_files:
        logger.info("Processing %s...", image_path.name)

        # Extract reporting month
        year, month = extract_reporting_month(image_path)

        # Extract data entries via OCR
        entries: list[DataEntry] = extract_entries(image_path)

        # Convert to database tuples
        all_entries.extend(
            (year, month, entry.app_name, entry.data_volume_kb) for entry in entries
        )

    logger.info("Collected %d total entries from %d images", len(all_entries), len(image_files))

    # Store in database (with deduplication)
    inserted = insert_entries(db_path, all_entries)
    logger.info("Done. %d entries stored in %s", inserted, db_path)


if __name__ == "__main__":
    main()
