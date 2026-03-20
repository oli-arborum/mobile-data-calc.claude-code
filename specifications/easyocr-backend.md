# Plan: Add EasyOCR as switchable OCR backend

## Context
The current Tesseract pipeline in `extractor/ocr.py` requires extensive postprocessing to work reliably (dual-language passes, PSM variants, dropped-comma re-OCR, gap-based recovery). EasyOCR (deep learning-based, from Jaided AI) offers better initial accuracy and cleaner output, but is a heavy optional dependency (~1 GB with PyTorch). Both backends should be supported and selectable via `--ocr-backend {tesseract,easyocr}`. For naming consistency, `ocr.py` is renamed to `ocr_tesseract.py`.

---

## Files to rename

### `extractor/ocr.py` → `extractor/ocr_tesseract.py`
No code changes — rename only. All imports referencing `extractor.ocr` must be updated (see below).

---

## Files to create

### `extractor/ocr_easyocr.py`
EasyOCR backend. Public API mirrors `ocr_tesseract.py`:
- `create_reader() -> easyocr.Reader` — initializes the PyTorch model once per process (slow)
- `extract_entries_easyocr(image_path: Path, reader: easyocr.Reader) -> list[DataEntry]`

Internals:
- `_easyocr_results_to_lines(results)` — converts EasyOCR's `(bbox, text, conf)` list to a plain-text string by grouping results with y-centroids within **12 px** into one line, sorting by x within each line, joining with spaces, then joining lines with `\n`
- Reuses from `extractor.ocr_tesseract` (same package, private imports suppressed via ruff per-file-ignores): `DataEntry`, `convert_to_kb`, `VOLUME_PATTERN`, `_detect_screen_type`, `_parse_app_list`, `_parse_service_list_inline`
- Lazy import guard: wrap `import easyocr` in `try/except ImportError` with a friendly message pointing to `uv sync --extra easyocr`
- No advanced recovery strategies (dropped-comma re-OCR, gap detection) — EasyOCR's accuracy makes them unnecessary; can be added later if needed

### `typings/easyocr/__init__.pyi`
Minimal stub following `typings/pytesseract/__init__.pyi` pattern:
```python
from PIL import Image
BBox = list[list[float]]
ReadTextResult = tuple[BBox, str, float]

class Reader:
    def __init__(self, lang_list: list[str], gpu: bool = ..., verbose: bool = ..., ...) -> None: ...
    def readtext(self, image: str | bytes | Image.Image, ...) -> list[ReadTextResult]: ...
```
Pyright discovers this automatically via the default `./typings` stub path — no config change needed.

---

## Files to modify

### `extractor/__main__.py`
1. Update import: `from extractor.ocr_tesseract import DataEntry, extract_entries`
2. Add `--ocr-backend` argument:
   ```python
   parser.add_argument("--ocr-backend", choices=["tesseract", "easyocr"], default="tesseract")
   ```
3. Initialize EasyOCR reader once before the image loop, dispatch via two `def _process_image` branches (avoids partial/lambda, pyright-clean):
   ```python
   if args.ocr_backend == "easyocr":
       from extractor.ocr_easyocr import create_reader, extract_entries_easyocr
       _reader = create_reader()
       def _process_image(p: Path) -> list[DataEntry]:
           return extract_entries_easyocr(p, _reader)
   else:
       def _process_image(p: Path) -> list[DataEntry]:
           return extract_entries(p)
   ```
4. Replace `extract_entries(image_path)` call in the loop with `_process_image(image_path)`

### `extractor/test/test_extractor.py`
Update import: `from extractor.ocr_tesseract import convert_to_kb, extract_entries`

### `pyproject.toml`
1. Add optional dependency group:
   ```toml
   [project.optional-dependencies]
   easyocr = ["easyocr>=1.7"]
   ```
2. Add per-file-ignores to allow private imports from sibling module in `ocr_easyocr.py`:
   ```toml
   "extractor/ocr_easyocr.py" = ["PLC2701"]
   ```

### `AGENTS.md`
- Add EasyOCR under System Dependencies (optional, no brew install needed, ~1 GB on first use)
- Add `uv sync --extra easyocr` install command
- Add `--ocr-backend easyocr` to example usage

### `README.md`
- Add `--ocr-backend` row to the CLI options table
- Add short "OCR Backends" subsection explaining tesseract (default, requires brew) vs. easyocr (optional, heavier, better accuracy)

---

## Verification
```bash
# Existing tests must still pass
uv run python -m unittest discover extractor/test/ -v

# Type checking and linting must pass clean
uv run pyright
uv run ruff check

# Smoke test EasyOCR backend (requires uv sync --extra easyocr first)
uv sync --extra easyocr
uv run extractor.py -i extractor/test/input/ --ocr-backend easyocr
```
