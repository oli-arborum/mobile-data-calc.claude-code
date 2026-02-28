from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pytesseract
from PIL import Image, ImageEnhance

logger = logging.getLogger(__name__)

# Matches values like "427 MB", "76,6 MB", "31,1MB" (no space), "97,0 KB"
# Also handles "/" as decimal separator (Tesseract sometimes reads commas as "/")
VOLUME_PATTERN = re.compile(r"(\d+[,./]?\d*)\s*(GB|MB|KB|Byte)", re.IGNORECASE)

SKIP_PATTERNS = [
    "aktueller zeitraum",
    "roaming",
    "apps sortieren",
    "nach namen",
    "suchen",
    "systemweite übersetzung",
    "persönlicher hotspot",
]

TITLE_NAMES = {"systemdienste", "mobile datennutzung", "datennutzung"}


@dataclass
class DataEntry:
    app_name: str
    data_volume_kb: float


def convert_to_kb(value_str: str, unit: str) -> float:
    """Convert a value string with unit to KB.

    Handles both "," and "." and "/" as decimal separators.
    """
    normalized = value_str.replace(",", ".").replace("/", ".")
    value = float(normalized)
    unit_upper = unit.upper()
    if unit_upper == "GB":
        return value * 1024 * 1024
    elif unit_upper == "MB":
        return value * 1024
    elif unit_upper == "KB":
        return value
    else:
        raise ValueError(f"Unknown unit: {unit}")


def _should_skip_line(line: str) -> bool:
    """Check if a line matches known headers/noise to skip."""
    lower = line.lower().strip()
    for skip in SKIP_PATTERNS:
        if skip in lower:
            return True
    return False


def _is_title_name(name: str) -> bool:
    """Check if a name is a screen title to be excluded."""
    return name.lower().strip() in TITLE_NAMES


def _is_volume_only_line(line: str) -> bool:
    """Check if a line contains essentially just a data volume value."""
    stripped = line.strip()
    if not stripped:
        return False
    m = VOLUME_PATTERN.search(stripped)
    if not m:
        return False
    rest = stripped[:m.start()] + stripped[m.end():]
    rest = re.sub(r"[^a-zA-ZäöüÄÖÜß]", "", rest)
    return len(rest) <= 2


def _clean_app_name(name: str) -> str:
    """Clean up an app name from OCR artifacts."""
    # Remove purely symbolic/numeric noise at the start
    name = re.sub(r"^[®©™%)\]}\d\W]+\s*", "", name)
    # Remove trailing symbols/noise
    name = re.sub(r"[\s@_)\]>»]+$", "", name)
    # Strip short artifact prefixes (1-4 chars) before a real app name
    # Catches: "oO Wetter", "ee Notizen", "tail Solar.web", "ee fraenk"
    # But keeps: "Home Assistant", "MG iSMART", "Post & DHL", "Wo ist?"
    m = re.match(r"^(.{1,4})\s+(.{3,})$", name)
    if m:
        prefix, rest = m.group(1), m.group(2)
        # Keep prefix if it starts with uppercase and has ≥ 2 chars (real word)
        if not (len(prefix) >= 2 and prefix[0].isupper()):
            name = rest
    return name.strip()


def _is_valid_name(name: str) -> bool:
    """Check if a cleaned name is a valid app name (not noise)."""
    if not name or len(name) < 3:
        return False
    if _is_title_name(name):
        return False
    # Must have at least 2 alphabetic characters
    alpha = re.sub(r"[^a-zA-ZäöüÄÖÜß]", "", name)
    if len(alpha) < 2:
        return False
    # Filter pure timestamps like "00:02"
    if re.match(r"^[\d:]+$", name):
        return False
    return True


def _detect_screen_type(text: str) -> str:
    """Detect the type of screen from OCR text."""
    for line in text.split("\n")[:8]:
        lower = line.lower()
        if "systemdienste" in lower and "mobile" not in lower:
            return "services"
        if "apple watch" in lower:
            return "apps"
        if "hotspot" in lower:
            return "hotspot"
    return "apps"


def _parse_app_list(text: str) -> list[DataEntry]:
    """Parse app list layout: data volume appears below app name."""
    entries: list[DataEntry] = []
    prev_name = ""

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if _should_skip_line(stripped):
            prev_name = ""
            continue

        if _is_volume_only_line(stripped):
            m = VOLUME_PATTERN.search(stripped)
            if m and prev_name:
                unit = m.group(2)
                if unit.lower() == "byte":
                    prev_name = ""
                    continue
                value_str = m.group(1)
                try:
                    kb = convert_to_kb(value_str, unit)
                    entries.append(DataEntry(app_name=prev_name, data_volume_kb=kb))
                except ValueError:
                    pass
                prev_name = ""
        else:
            m = VOLUME_PATTERN.search(stripped)
            if m:
                # Line with both name and value — skip navigable aggregates in app list
                prev_name = ""
            else:
                cleaned = _clean_app_name(stripped)
                if _is_valid_name(cleaned):
                    prev_name = cleaned
                # If not valid, keep prev_name (skip noise lines between name and value)

    return entries


def _parse_service_list_inline(text: str) -> list[DataEntry]:
    """Parse service list layout where name and value appear on the same line.

    Used with PSM 6 output for Systemdienste screenshots.
    """
    entries: list[DataEntry] = []

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if _should_skip_line(stripped):
            continue

        m = VOLUME_PATTERN.search(stripped)
        if not m:
            continue

        unit = m.group(2)
        if unit.lower() == "byte":
            continue

        before = stripped[:m.start()].strip()
        name = _clean_app_name(before) if before else ""

        if not _is_valid_name(name):
            continue

        value_str = m.group(1)
        try:
            kb = convert_to_kb(value_str, unit)
            entries.append(DataEntry(app_name=name, data_volume_kb=kb))
        except ValueError:
            continue

    return entries


def _parse_psm4_app_list(text: str) -> list[DataEntry]:
    """Parse PSM 4 output for app list screenshots.

    PSM 4 captures app names that PSM 3 misses (due to icon interference).
    Names and values may be on the same line or adjacent lines.
    """
    entries: list[DataEntry] = []
    prev_name = ""

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if _should_skip_line(stripped):
            prev_name = ""
            continue

        m = VOLUME_PATTERN.search(stripped)
        if m:
            unit = m.group(2)
            if unit.lower() == "byte":
                prev_name = ""
                continue

            # Check if there's a name before the value
            before = stripped[:m.start()].strip()
            name = _clean_app_name(before) if before else ""

            if _is_valid_name(name):
                try:
                    kb = convert_to_kb(m.group(1), unit)
                    entries.append(DataEntry(app_name=name, data_volume_kb=kb))
                except ValueError:
                    pass
                prev_name = ""
            elif prev_name:
                try:
                    kb = convert_to_kb(m.group(1), unit)
                    entries.append(DataEntry(app_name=prev_name, data_volume_kb=kb))
                except ValueError:
                    pass
                prev_name = ""
            else:
                prev_name = ""
        else:
            cleaned = _clean_app_name(stripped)
            if _is_valid_name(cleaned):
                prev_name = cleaned

    return entries


def _correct_name_disagreements(
    entries: list[DataEntry],
    secondary: list[DataEntry],
    img: Image.Image,
) -> list[DataEntry]:
    """Fix entry names where primary and secondary OCR disagree.

    When two passes produce near-identical names (edit distance 1-2) for the
    same value, re-OCR the name region at 2x scale to get the correct spelling.
    """
    # Index secondary entries by value for quick lookup
    sec_by_value: dict[float, list[DataEntry]] = {}
    for e in secondary:
        sec_by_value.setdefault(e.data_volume_kb, []).append(e)

    corrected = list(entries)
    data = pytesseract.image_to_data(
        img, lang="deu+eng", output_type=pytesseract.Output.DICT
    )

    for idx, entry in enumerate(corrected):
        candidates = sec_by_value.get(entry.data_volume_kb, [])
        for sec in candidates:
            norm_e = _normalize_name(entry.app_name)
            norm_s = _normalize_name(sec.app_name)
            if norm_e == norm_s:
                continue
            shorter, longer = sorted([norm_e, norm_s], key=len)
            if len(shorter) < 5 or len(shorter) / len(longer) <= 0.7:
                continue
            dist = _edit_distance(norm_e, norm_s)
            if dist > 2 or dist / len(longer) >= 0.2:
                continue

            # Name disagreement: re-OCR the name region at 2x scale
            for i in range(len(data["text"])):
                text = str(data["text"][i]).strip()
                if _normalize_name(text) == norm_e and int(data["conf"][i]) > 30:
                    x = data["left"][i]
                    y = data["top"][i]
                    w = data["width"][i]
                    h = data["height"][i]
                    pad = 10
                    crop = img.crop((
                        max(0, x - pad), max(0, y - pad),
                        min(img.width, x + w + pad), min(img.height, y + h + pad),
                    ))
                    scaled = crop.resize(
                        (crop.width * 2, crop.height * 2), Image.LANCZOS
                    )
                    result = pytesseract.image_to_string(
                        scaled, lang="deu+eng", config="--psm 7"
                    ).strip()
                    result = _clean_app_name(result)
                    if _is_valid_name(result) and result != entry.app_name:
                        logger.info(
                            "Corrected name: %s -> %s", entry.app_name, result
                        )
                        corrected[idx] = DataEntry(
                            app_name=result,
                            data_volume_kb=entry.data_volume_kb,
                        )
                    break
            break

    return corrected


def _run_dual_ocr(img: Image.Image, screen_type: str) -> list[DataEntry]:
    """Run dual-language OCR and merge results.

    Primary: deu+eng (best for numbers overall)
    Secondary: deu (catches different errors, better for umlauts)
    """
    if screen_type == "services":
        text_primary = pytesseract.image_to_string(img, lang="deu+eng", config="--psm 6")
        text_secondary = pytesseract.image_to_string(img, lang="deu", config="--psm 6")
        entries_primary = _parse_service_list_inline(text_primary)
        entries_secondary = _parse_service_list_inline(text_secondary)

        # PSM 3 deu+eng gives more accurate values (preserves commas better)
        # Use it to fix values that PSM 6 dropped commas from
        text_psm3 = pytesseract.image_to_string(img, lang="deu+eng")
        psm3_values = VOLUME_PATTERN.findall(text_psm3)
        psm3_kb_values = []
        for val_str, unit in psm3_values:
            if unit.lower() != "byte":
                try:
                    psm3_kb_values.append(convert_to_kb(val_str, unit))
                except ValueError:
                    pass
        # Replace values positionally when PSM 3 value has a decimal
        for i, entry in enumerate(entries_primary):
            if i < len(psm3_kb_values) and entry.data_volume_kb != psm3_kb_values[i]:
                ratio = entry.data_volume_kb / psm3_kb_values[i] if psm3_kb_values[i] > 0 else 0
                if ratio > 5:  # PSM 6 value much larger → dropped comma
                    logger.info(
                        "Fixed Systemdienste value: %s %.1f -> %.1f KB",
                        entry.app_name, entry.data_volume_kb, psm3_kb_values[i],
                    )
                    entries_primary[i] = DataEntry(
                        app_name=entry.app_name, data_volume_kb=psm3_kb_values[i],
                    )
    else:
        text_primary = pytesseract.image_to_string(img, lang="deu+eng")
        text_secondary = pytesseract.image_to_string(img, lang="deu")
        entries_primary = _parse_app_list(text_primary)
        entries_secondary = _parse_app_list(text_secondary)

        # Also run PSM 4 to capture names that PSM 3 misses
        text_psm4 = pytesseract.image_to_string(img, lang="deu+eng", config="--psm 4")
        psm4_entries = _parse_psm4_app_list(text_psm4)
        # Add PSM 4 entries as supplementary (after merge, below)
        entries_primary = _merge_entries_by_name(entries_primary, psm4_entries)

    merged = _merge_dual_entries(entries_primary, entries_secondary)
    return _correct_name_disagreements(merged, entries_secondary, img)


def _normalize_name(name: str) -> str:
    """Normalize a name for dedup comparison.

    Handles OCR variants like Ö→O, i→l, co→©→∞, Homekit→HomeKit.
    """
    n = name.lower()
    n = n.replace("ö", "o").replace("ä", "a").replace("ü", "u")
    # Normalize common OCR confusions
    n = re.sub(r"[©∞]", "x", n)
    n = n.replace(" co", " x")  # "Calculator co" → "Calculator x"
    return n


def _merge_entries_by_name(
    primary: list[DataEntry], secondary: list[DataEntry]
) -> list[DataEntry]:
    """Add secondary entries that don't already exist in primary (by normalized name)."""
    existing = {_normalize_name(e.app_name) for e in primary}
    merged = list(primary)
    for entry in secondary:
        norm = _normalize_name(entry.app_name)
        if norm not in existing and not _is_noisy_duplicate(entry, merged):
            merged.append(entry)
            existing.add(norm)
    return merged


def _merge_dual_entries(
    primary: list[DataEntry], secondary: list[DataEntry]
) -> list[DataEntry]:
    """Merge deu+eng (primary) and deu (secondary) OCR results.

    For entries with the same name: prefer the value with a decimal separator
    (fixes dropped-comma issues where one language setting preserves the comma).
    For entries only in one set: include them.
    """
    secondary_by_norm: dict[str, DataEntry] = {}
    for entry in secondary:
        norm = _normalize_name(entry.app_name)
        secondary_by_norm[norm] = entry

    merged: list[DataEntry] = []
    used_norms: set[str] = set()

    for entry in primary:
        norm = _normalize_name(entry.app_name)
        used_norms.add(norm)

        if norm in secondary_by_norm:
            sec = secondary_by_norm[norm]
            if entry.data_volume_kb == sec.data_volume_kb:
                merged.append(entry)
            else:
                merged.append(_pick_better_value(entry, sec))
        else:
            merged.append(entry)

    # Add secondary-only entries (with smart dedup)
    for entry in secondary:
        norm = _normalize_name(entry.app_name)
        if norm not in used_norms and not _is_noisy_duplicate(entry, merged):
            merged.append(entry)
            used_norms.add(norm)

    return merged


def _edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]


def _is_noisy_duplicate(candidate: DataEntry, existing: list[DataEntry]) -> bool:
    """Check if a candidate entry is a noisy duplicate of an existing entry.

    Detects cases like "Qo Signal" being a noisy version of "Signal",
    "Decathion" being a garbled "Decathlon", or "MyrFitnessPal" for "MyFitnessPal".
    """
    cand_norm = _normalize_name(candidate.app_name)
    for entry in existing:
        ent_norm = _normalize_name(entry.app_name)
        if ent_norm == cand_norm:
            return True
        # Check substring relationship with length ratio > 0.5
        shorter, longer = sorted([ent_norm, cand_norm], key=len)
        if len(shorter) > 0 and len(shorter) / len(longer) > 0.5:
            if shorter in longer:
                return True
        # Check edit distance for similar-length names (catches OCR typos)
        if len(shorter) >= 5 and len(shorter) / len(longer) > 0.7:
            dist = _edit_distance(ent_norm, cand_norm)
            if dist <= 2 and dist / len(longer) < 0.2:
                return True
    return False


def _pick_better_value(primary: DataEntry, secondary: DataEntry) -> DataEntry:
    """Pick the better value between deu+eng and deu OCR readings.

    When one value is much larger than the other (~10x-100x), the smaller one
    likely has the decimal separator preserved (dropped comma in the other).
    """
    if primary.data_volume_kb > 0 and secondary.data_volume_kb > 0:
        ratio = primary.data_volume_kb / secondary.data_volume_kb
        if ratio > 5:
            return secondary
        elif ratio < 0.2:
            return primary

    # Default to primary (deu+eng)
    return primary


def _fix_dropped_commas(entries: list[DataEntry], img: Image.Image) -> list[DataEntry]:
    """Fix dropped commas by re-OCR'ing suspicious value regions.

    For values that are 3-digit integers (potential dropped comma), crop the
    specific region, preprocess, scale 8x, and re-OCR with eng PSM 7.
    """
    if not entries:
        return entries

    # Get word-level data with bounding boxes using deu+eng
    data = pytesseract.image_to_data(img, lang="deu+eng", output_type=pytesseract.Output.DICT)

    # Collect all 3-digit numeric words with their bounding boxes
    three_digit_boxes: list[tuple[str, int, int, int, int]] = []
    for i, word in enumerate(data["text"]):
        word_str = str(word).strip()
        if re.match(r"^\d{3}$", word_str) and int(data["conf"][i]) > 0:
            three_digit_boxes.append((
                word_str,
                data["left"][i],
                data["top"][i],
                data["width"][i],
                data["height"][i],
            ))

    if not three_digit_boxes:
        return entries

    fixed_entries: list[DataEntry] = []
    for entry in entries:
        kb = entry.data_volume_kb
        fixed = False

        for raw_val, x, y, w, h in three_digit_boxes:
            if fixed:
                break
            for unit, multiplier in [("MB", 1024.0), ("KB", 1.0)]:
                expected_kb = int(raw_val) * multiplier
                if abs(expected_kb - kb) < 0.01:
                    new_val = _reocr_value_region(img, x, y, w, h)
                    if new_val and ("," in new_val or "." in new_val):
                        m = re.match(r"(\d+[,.]\d+)", new_val)
                        if m:
                            try:
                                new_kb = convert_to_kb(m.group(1), unit)
                                if new_kb != kb:
                                    logger.info(
                                        "Fixed dropped comma: %s %s %s -> %s %s",
                                        entry.app_name, raw_val, unit, m.group(1), unit,
                                    )
                                    fixed_entries.append(DataEntry(
                                        app_name=entry.app_name, data_volume_kb=new_kb,
                                    ))
                                    fixed = True
                            except ValueError:
                                pass
                    break

        if not fixed:
            fixed_entries.append(entry)

    return fixed_entries


def _reocr_value_region(
    img: Image.Image, x: int, y: int, w: int, h: int, pad: int = 15
) -> str | None:
    """Re-OCR a specific value region at 8x scale with preprocessing.

    Crops the region, converts to grayscale, thresholds to binary,
    scales 8x, and runs Tesseract in single-line mode with English.
    """
    region = img.crop((
        max(0, x - pad),
        max(0, y - pad),
        min(img.width, x + w + pad),
        min(img.height, y + h + pad),
    ))

    gray = region.convert("L")
    enhancer = ImageEnhance.Contrast(gray)
    enhanced = enhancer.enhance(2.0)
    binary = enhanced.point(lambda p: 255 if p > 128 else 0)
    rw, rh = binary.size
    scaled = binary.resize((rw * 8, rh * 8), Image.LANCZOS)

    result = pytesseract.image_to_string(scaled, lang="eng", config="--psm 7")
    return result.strip() if result else None


def _recover_missing_entries(
    entries: list[DataEntry], img: Image.Image
) -> list[DataEntry]:
    """Recover entries missed by text-based parsing.

    Uses two strategies:
    1. Position-based: image_to_data preserves correct spatial ordering,
       catching names that image_to_string misplaces (e.g., adidas).
    2. Gap-based: detects vertical gaps between detected values and re-OCRs
       those regions to find entries invisible to full-page OCR (e.g., tado°).
    """
    data = pytesseract.image_to_data(
        img, lang="deu+eng", output_type=pytesseract.Output.DICT
    )

    existing_norms = {_normalize_name(e.app_name) for e in entries}
    recovered = list(entries)

    # Build word list from image_to_data
    words: list[dict] = []
    for i in range(len(data["text"])):
        text = str(data["text"][i]).strip()
        if text and int(data["conf"][i]) > 0:
            words.append({
                "text": text, "y": data["top"][i], "x": data["left"][i],
                "conf": int(data["conf"][i]),
            })

    # --- Step 1: Position-based recovery ---
    # Find name words not in our entries that have a value word below them.
    # This catches names that image_to_string misplaces (e.g., adidas).
    unit_words = {
        w["y"]: w["text"]
        for w in words
        if w["text"].upper() in ("MB", "KB", "GB") and w["conf"] > 50
    }
    for w in words:
        if w["conf"] < 60:
            continue
        cleaned = _clean_app_name(w["text"])
        if not _is_valid_name(cleaned) or _should_skip_line(w["text"]):
            continue
        norm = _normalize_name(cleaned)
        if norm in existing_norms or _is_noisy_duplicate(
            DataEntry(cleaned, 0), recovered
        ):
            continue
        # Skip if this word is part of an existing multi-word entry name
        if any(cleaned.lower() in e.app_name.lower() for e in recovered):
            continue
        # Skip words that are part of screen titles
        if any(cleaned.lower() in title for title in TITLE_NAMES):
            continue
        # Look for a numeric value 50-150px below this name
        for vw in words:
            dy = vw["y"] - w["y"]
            if 50 < dy < 150 and re.match(r"^\d+[,.]?\d*$", vw["text"]):
                # Check for a unit word on the same line as the value
                for uy, ut in unit_words.items():
                    if abs(uy - vw["y"]) < 30 and ut.upper() != "BYTE":
                        try:
                            kb = convert_to_kb(vw["text"], ut)
                            recovered.append(DataEntry(app_name=cleaned, data_volume_kb=kb))
                            existing_norms.add(norm)
                            logger.info(
                                "Recovered from positions: %s %.1f KB", cleaned, kb
                            )
                        except ValueError:
                            pass
                        break
                break

    # --- Step 2: Gap-based recovery ---
    # Find y-positions of detected volume values
    unit_ys: set[int] = set()
    for i in range(len(data["text"])):
        text = str(data["text"][i]).strip().upper()
        if text in ("MB", "KB", "GB") and int(data["conf"][i]) > 50:
            unit_ys.add(data["top"][i])

    value_ys: list[int] = []
    for i in range(len(data["text"])):
        text = str(data["text"][i]).strip()
        y = data["top"][i]
        if re.match(r"^\d+[,.]?\d*$", text) and int(data["conf"][i]) > 50:
            if any(abs(y - uy) < 30 for uy in unit_ys):
                value_ys.append(y)
    value_ys.sort()

    if len(value_ys) >= 3:
        spacings = sorted(
            value_ys[i + 1] - value_ys[i] for i in range(len(value_ys) - 1)
        )
        median_spacing = spacings[len(spacings) // 2]

        # Collect gap regions (between consecutive values and after last value)
        gap_regions: list[tuple[int, int]] = []
        for i in range(len(value_ys) - 1):
            gap = value_ys[i + 1] - value_ys[i]
            if gap > median_spacing * 1.5:
                n_missing = round(gap / median_spacing) - 1
                for j in range(1, n_missing + 1):
                    center = value_ys[i] + j * median_spacing
                    gap_regions.append(
                        (int(center - median_spacing * 0.6), int(center + median_spacing * 0.6))
                    )

        # Check gap after last value (before "Suchen")
        suchen_y = None
        for i in range(len(data["text"])):
            if str(data["text"][i]).strip().lower() == "suchen":
                suchen_y = data["top"][i]
                break
        if suchen_y and value_ys:
            gap_after = suchen_y - value_ys[-1]
            if gap_after > median_spacing * 1.3:
                center = value_ys[-1] + median_spacing
                gap_regions.append(
                    (int(center - median_spacing * 0.6), int(center + median_spacing * 0.6))
                )

        # Re-OCR each gap region
        for y_start, y_end in gap_regions:
            y_start = max(0, y_start)
            y_end = min(img.height, y_end)
            crop = img.crop((0, y_start, int(img.width * 0.65), y_end))
            text = pytesseract.image_to_string(
                crop, lang="deu+eng", config="--psm 6"
            ).strip()

            # Parse: name may be on same line as value or the previous line
            prev_name = ""
            for line in text.split("\n"):
                m = VOLUME_PATTERN.search(line)
                if not m:
                    # Potential name line
                    cleaned = re.sub(r"^[^a-zA-ZäöüÄÖÜß°]+", "", line).strip()
                    cleaned = _clean_app_name(cleaned)
                    if _is_valid_name(cleaned):
                        prev_name = cleaned
                    continue
                unit = m.group(2)
                if unit.lower() == "byte":
                    prev_name = ""
                    continue
                # Try same-line name first, then previous line
                before = line[: m.start()].strip()
                before = re.sub(r"^[^a-zA-ZäöüÄÖÜß°]+", "", before).strip()
                before = _clean_app_name(before)
                name = before if _is_valid_name(before) else prev_name
                prev_name = ""
                if not _is_valid_name(name):
                    continue
                norm = _normalize_name(name)
                if norm not in existing_norms and not _is_noisy_duplicate(
                    DataEntry(name, 0), recovered
                ):
                    try:
                        kb = convert_to_kb(m.group(1), unit)
                        recovered.append(DataEntry(app_name=name, data_volume_kb=kb))
                        existing_norms.add(norm)
                        logger.info("Recovered from gap re-OCR: %s %.1f KB", name, kb)
                    except ValueError:
                        pass

    return recovered


def extract_entries(image_path: Path) -> list[DataEntry]:
    """Extract data usage entries from a screenshot."""
    img = Image.open(image_path)

    # Detect screen type using a quick deu OCR pass
    text_detect = pytesseract.image_to_string(img, lang="deu")
    screen_type = _detect_screen_type(text_detect)
    logger.debug("Detected screen type for %s: %s", image_path.name, screen_type)

    if screen_type == "hotspot":
        logger.info("Skipping hotspot screen: %s", image_path.name)
        return []

    # Run dual-language OCR and merge
    entries = _run_dual_ocr(img, screen_type)

    # Fix dropped commas using targeted re-OCR
    entries = _fix_dropped_commas(entries, img)

    # Recover entries missed by text-based parsing (app list only)
    if screen_type == "apps":
        entries = _recover_missing_entries(entries, img)

    logger.info("Extracted %d entries from %s (%s)", len(entries), image_path.name, screen_type)
    return entries
