# Implementation Plan: iOS Data Usage Screenshot Extractor

## Context

Build a Python CLI tool that extracts per-app monthly mobile data usage from iOS screenshots (German locale) and stores it in a SQLite database. The screenshots show two layouts: an app list (data below name) and a system services list (data right of name). A test set of 15 screenshots with expected output (129 entries in `data.csv`) is provided.

## Step 1: Project Setup

- Initialize `pyproject.toml` with `uv init` in the repo root
- `uv add pillow pytesseract` (Python Tesseract wrapper + image library)
- Create `AGENTS.md` documenting the dependency on system-level Tesseract (`brew install tesseract`)

**Files:** `pyproject.toml`, `AGENTS.md`

## Step 2: Update Specification

Add the clarifications from our discussion to `specifications/extractor.md`:
- Target unit is KB (not bytes)
- Accept both "," and "." as decimal separators
- Database file path is a CLI argument
- Navigable aggregate rows (e.g., "Systemdienste") are skipped; only individual sub-items are stored
- Entries in plain "Byte" (< 1 KB) are ignored

**Files:** `specifications/extractor.md`

## Step 3: Image Metadata Module

Extract the reporting month from image EXIF data using Pillow.

- Use `Image.open(path).getexif()` to read EXIF from PNG
- Read `DateTimeOriginal` (tag 36867) or fall back to `DateTime` (tag 306)
- EXIF timestamps are in local time (no timezone), format: `"YYYY:MM:DD HH:MM:SS"`
- Subtract 1 month from the capture date to get the reporting period
- Return `(year, month)` tuple

**File:** `extractor/metadata.py`

## Step 4: OCR + Parsing Module

Run Tesseract via `pytesseract` and parse the output into structured entries.

### Screen type detection
Scan the first few lines of OCR text for the title:
- "Datennutzung" → app list layout
- "Systemdienste" → service list layout
- "Apple Watch" → app list layout (same format as main app list)
- Other titles (e.g., "Hotspot") → process normally, entries in "Byte" will be filtered

### Parsing strategy
Use regex to find all data volume patterns: `(\d+[.,]?\d*)\s*(GB|MB|KB)`

**App list layout** (data below name): Scan line by line. When a line matches a data volume pattern (and is essentially just the volume), associate it with the preceding non-empty text line as the app name.

**Service list layout** (data right of name): When a line contains both text AND a data volume pattern, split into name (text before the number) and value.

### Filtering
- Skip lines matching known headers: "Aktueller Zeitraum", "Roaming", "APPS SORTIEREN", "NACH NAMEN", "Suchen"
- Skip entries with unit "Byte"
- In the main app list, "Systemdienste" appears with data on the same line (not below), so it naturally won't match the app-list parsing pattern — it gets skipped

### Unit conversion to KB
- GB value: `value * 1024 * 1024`
- MB value: `value * 1024`
- KB value: `value` (no conversion)

Replace comma with period in numeric values before conversion.

**File:** `extractor/ocr.py`

## Step 5: Database Module

SQLite operations for storing extracted data.

- `create_database(db_path)`: Create table if not exists with schema: `year INTEGER, month INTEGER, app_name TEXT, data_volume_kb REAL`
- `insert_entries(db_path, entries)`: Insert list of `(year, month, name, value_kb)` tuples
- Deduplication: Use a set of `(year, month, name, value_kb)` tuples to skip exact duplicates (handles overlapping screenshots). Note: "Wo ist?" legitimately appears twice with different values (app list vs system services) — both are kept.

**File:** `extractor/database.py`

## Step 6: CLI Entry Point + Main Orchestration

- `argparse` with two arguments: `input_folder` (Path) and `database` (Path)
- Iterate over image files in input folder (sorted for deterministic order)
- For each image: extract date, run OCR, parse entries
- Collect all entries, deduplicate
- Store in database
- Log progress to stdout using `logging`

**Files:** `extractor/__main__.py`, `extractor/__init__.py`

## Step 7: Tests

Use `unittest` to validate against the test data.

**Integration test**: Run the full pipeline on `extractor/test/input/`, compare the resulting database contents against `extractor/test/data.csv`. Sort both by `(app_name, data_volume_kb)` before comparing to avoid order-sensitivity.

**Unit tests** (as appropriate):
- `test_convert_to_kb`: Verify GB/MB/KB conversion with 1024 factor
- `test_parse_decimal_separators`: Verify "76,6" and "76.6" both parse to 76.6
- `test_date_extraction`: Verify month subtraction (Feb → Jan, Jan → Dec of prev year)

**File:** `extractor/test/test_extractor.py`

## Module Structure

```
extractor/
├── __init__.py
├── __main__.py      # CLI entry point + orchestration
├── metadata.py      # EXIF date extraction
├── ocr.py           # Tesseract OCR + text parsing + unit conversion
├── database.py      # SQLite operations
└── test/
    ├── __init__.py
    ├── data.csv           (existing)
    ├── input/             (existing, 15 PNGs)
    └── test_extractor.py
```

## Implementation Order

1. Project setup (Step 1)
2. Spec update (Step 2)
3. Metadata module (Step 3) — can test independently with sample image
4. OCR + parsing module (Step 4) — core complexity, iterate until output matches expectations
5. Database module (Step 5)
6. CLI entry point (Step 6) — wires everything together
7. Tests (Step 7) — validate against data.csv

## Verification

1. Run `uv run python -m extractor extractor/test/input/ /tmp/test.db` and inspect the database
2. Compare database contents against `extractor/test/data.csv`
3. Run `uv run python -m unittest discover extractor/test/` to execute tests
