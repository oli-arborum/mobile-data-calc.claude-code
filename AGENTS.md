# Agents / Development Notes

## System Dependencies

- **Tesseract OCR**: Required for text extraction from screenshots.
  Install via Homebrew: `brew install tesseract`

## Python Dependencies

Managed via `uv`. Install with `uv sync`.

- **Pillow**: Image handling and EXIF metadata extraction
- **pytesseract**: Python wrapper for Tesseract OCR

## Running

```bash
uv run python -m extractor <input_folder> <database_path>
```

## Testing

```bash
uv run python -m unittest discover extractor/test/
```

## Type Checking

```bash
uv run pyright
```
