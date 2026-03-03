# Agents / Development Notes

## System Dependencies

- **Tesseract OCR**: Required for text extraction from screenshots.
  Install via Homebrew: `brew install tesseract`

## Python Dependencies

Managed via `uv`. Install with `uv sync`.

- **Pillow**: Image handling and EXIF metadata extraction
- **pytesseract**: Python wrapper for Tesseract OCR
- **ruff**: Linting and formatting
- **pyright**: Static type checking

## Running

```bash
uv run extractor.py [-i INPUT_PATH] [-d DB]
```

## Testing

```bash
uv run python -m unittest discover extractor/test/
```

## Linting

```bash
uv run ruff check
```

## Type Checking

```bash
uv run pyright
```
