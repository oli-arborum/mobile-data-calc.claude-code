# Mobile Data Usage Calculation Toolkit

## Preface

This little project is an experiment of me using Claude Code to write the complete (!) code based on my specification(s) (see "specifications" folder).

## Extractor

A Python CLI tool that extracts per-app monthly mobile data usage from iOS screenshots (German locale) using OCR, and stores the results in a SQLite database.

### How it works

1. Reads iOS "Mobile Datennutzung" screenshots from a folder
2. Extracts the reporting month from EXIF metadata (one month before capture date)
3. Uses Tesseract OCR with dual-language passes (deu+eng) to extract app names and data volumes
4. Handles two screenshot layouts: app list (value below name) and Systemdienste (value right of name)
5. Deduplicates entries and stores them in a SQLite database with values normalized to KB

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager
- Tesseract OCR with German language data

```bash
brew install tesseract
```

### Installation

```bash
uv sync
```

### Usage

```bash
uv run python -m extractor <input_folder> <database_path>
```

**Example:**

```bash
uv run python -m extractor ~/screenshots/ usage.db
```

This processes all PNG/JPG screenshots in the input folder and writes the extracted data to `usage.db`.

### Database schema

```sql
CREATE TABLE data_usage (
    year            INTEGER,
    month           INTEGER,
    app_name        TEXT,
    data_volume_kb  REAL
);
```

### Testing

A test set with 15 screenshots and 131 expected entries for January 2026 is included in `extractor/test/`.

```bash
uv run python -m unittest discover extractor/test/ -v
```

### Linting

```bash
uv run ruff check
```

### Type checking

```bash
uv run pyright
```

### OCR approach

Tesseract alone struggles with iOS screenshots due to app icons, stylized fonts, and the German locale. The extractor uses several strategies to maximize accuracy:

- **Dual-language OCR**: Primary pass with `deu+eng` (best for numbers), secondary with `deu` (better for umlauts). Results are merged, preferring the reading that preserves decimal separators.
- **PSM modes**: PSM 3 (default) for app lists, PSM 6 for Systemdienste, PSM 4 as supplementary to capture names that icons obscure.
- **Dropped comma fix**: Values like "893" that should be "8,93" are detected and re-OCR'd at 8x scale on the cropped region.
- **Position-based recovery**: Uses `image_to_data` bounding boxes to find names that `image_to_string` misplaces (e.g., "adidas").
- **Gap-based recovery**: Detects vertical gaps between entries and re-OCRs those regions to find rows invisible to full-page OCR (e.g., "tado\u00b0").
- **Name correction**: When primary and secondary passes disagree on a name by 1-2 characters, re-OCRs the name region at 2x scale to resolve the conflict.

## Project structure

```
extractor/
  __init__.py
  __main__.py        CLI entry point (argparse)
  metadata.py        EXIF date extraction
  ocr.py             OCR + parsing (dual-language, gap recovery, name correction)
  database.py        SQLite operations
  test/
    __init__.py
    test_extractor.py
    data.csv           Expected output (131 entries)
    input/             15 iOS screenshots
specifications/
  extractor.md         Detailed specification
```