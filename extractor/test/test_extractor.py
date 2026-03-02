# pyright: reportUnknownLambdaType=false
"""Tests for the iOS data usage screenshot extractor."""

from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from extractor.database import create_database, insert_entries
from extractor.metadata import extract_reporting_month
from extractor.ocr import convert_to_kb, extract_entries

TEST_DIR = Path(__file__).parent
INPUT_DIR = TEST_DIR / "input"
DATA_CSV = TEST_DIR / "data.csv"


class TestConvertToKb(unittest.TestCase):
    def test_gb(self):
        self.assertEqual(convert_to_kb("1", "GB"), 1024 * 1024)

    def test_mb(self):
        self.assertEqual(convert_to_kb("1", "MB"), 1024)

    def test_kb(self):
        self.assertEqual(convert_to_kb("1", "KB"), 1)

    def test_decimal_comma(self):
        self.assertAlmostEqual(convert_to_kb("76,6", "MB"), 76.6 * 1024)

    def test_decimal_period(self):
        self.assertAlmostEqual(convert_to_kb("76.6", "MB"), 76.6 * 1024)

    def test_slash_separator(self):
        self.assertAlmostEqual(convert_to_kb("76/6", "MB"), 76.6 * 1024)

    def test_unknown_unit(self):
        with self.assertRaises(ValueError):
            convert_to_kb("1", "TB")


class TestDateExtraction(unittest.TestCase):
    def test_reporting_month(self):
        """Screenshots taken in Feb 2026 should report Jan 2026."""
        images = sorted(INPUT_DIR.glob("*.PNG"))
        if not images:
            self.skipTest("No test images available")
        year, month = extract_reporting_month(images[0])
        self.assertEqual(year, 2026)
        self.assertEqual(month, 1)

    def test_january_wraps_to_december(self):
        """Verify month subtraction wraps correctly."""
        from unittest.mock import MagicMock, patch

        from extractor.metadata import extract_reporting_month

        # Mock a January capture date with proper exif structure
        mock_img = MagicMock()
        mock_img.__enter__ = lambda s: s
        mock_img.__exit__ = lambda s, *a: None
        mock_exif = MagicMock()
        mock_exif.get_ifd.return_value = {}  # No ExifIFD tag 36867
        mock_exif.__contains__ = lambda s, k: k == 306
        mock_exif.__getitem__ = lambda s, k: "2026:01:15 10:00:00" if k == 306 else None
        mock_img.getexif.return_value = mock_exif

        with patch("extractor.metadata.Image.open", return_value=mock_img):
            year, month = extract_reporting_month(Path("dummy.png"))
        self.assertEqual(year, 2025)
        self.assertEqual(month, 12)


class TestIntegration(unittest.TestCase):
    """Run the full pipeline on test images and compare against data.csv."""

    def test_full_pipeline(self):
        if not INPUT_DIR.is_dir() or not any(INPUT_DIR.glob("*.PNG")):
            self.skipTest("No test images available")

        image_files = sorted(INPUT_DIR.glob("*.PNG"))

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            create_database(db_path)

            all_entries: list[tuple[int, int, str, float]] = []
            for image_path in image_files:
                year, month = extract_reporting_month(image_path)
                entries = extract_entries(image_path)
                all_entries.extend(
                    (year, month, entry.app_name, entry.data_volume_kb) for entry in entries
                )

            insert_entries(db_path, all_entries)

            # Read DB results
            conn = sqlite3.connect(db_path)
            db_rows = set(
                conn.execute(
                    "SELECT year, month, app_name, data_volume_kb FROM data_usage"
                ).fetchall()
            )
            conn.close()

            # Read expected CSV
            csv_rows: set[tuple[int, int, str, float]] = set()
            with DATA_CSV.open() as f:
                reader = csv.reader(f)
                for row in reader:
                    if not row:
                        continue
                    csv_rows.add(
                        (int(row[0]), int(row[1]), row[2], float(row[3]))
                    )

            self.assertEqual(
                len(db_rows),
                len(csv_rows),
                f"Entry count mismatch: DB={len(db_rows)}, CSV={len(csv_rows)}",
            )

            missing = csv_rows - db_rows
            extra = db_rows - csv_rows

            self.assertEqual(
                missing,
                set(),
                "Missing from DB:\n"
                + "\n".join(f"  {r}" for r in sorted(missing, key=lambda x: x[2])),
            )
            self.assertEqual(
                extra,
                set(),
                "Extra in DB:\n"
                + "\n".join(f"  {r}" for r in sorted(extra, key=lambda x: x[2])),
            )

        finally:
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
