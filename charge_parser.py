#!/usr/bin/env python3
"""
Command line utility that converts FordPass charge-detail screenshots into CSV rows.

The tool shells out to the `tesseract` binary (must be installed separately) to OCR the
image, then uses a handful of heuristics to pull the pieces of data we care about.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

DATE_PATTERN = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+((?:\d{1,2})(?:st|nd|rd|th)?|[iI]st)(?:,\s*|\s+)(\d{4})",
    re.IGNORECASE,
)
TIME_PATTERN = re.compile(r"\b\d{1,2}:\d{2}\b")
PERCENT_PATTERN = re.compile(r"(\d{1,3})\s*%")
KW_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)\s*kW\b(?!h)", re.IGNORECASE)
KWH_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*kWh\b", re.IGNORECASE)
COST_PATTERN = re.compile(r"\$[\d,.]+")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heic", ".tif", ".tiff", ".bmp"}

CSV_COLUMNS = [
    "date",
    "charger_name",
    "charger_location",
    "duration",
    "kwh_added",
    "charger_kw_rating",
    "charge_percentage",
    "charge_miles",
    "start_time",
    "end_time",
    "start_percentage",
    "end_percentage",
    "cost",
    "charger_brand",
]

SECTION_BREAKS = [
    "summary",
    "charge details",
    "charge",
    "time charging",
    "energy added",
    "additional details",
]


def lower_is_section_break(lowered: str) -> bool:
    for label in SECTION_BREAKS:
        if lowered == label or lowered.startswith(f"{label} "):
            return True
    return False


def run_tesseract(image_path: Path, psm: str) -> str:
    """Run tesseract on the image and return the extracted text."""
    try:
        result = subprocess.run(
            ["tesseract", str(image_path), "stdout", "--psm", psm],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "tesseract binary not found. Install it (e.g. `brew install tesseract`)."
        ) from exc
    except subprocess.CalledProcessError as exc:  # pragma: no cover - depends on OCR input
        raise RuntimeError(f"OCR failed for {image_path}: {exc.stderr}") from exc
    return result.stdout


def extract_label_value(lines: List[str], label: str) -> str:
    """Return the text immediately associated with the provided label."""
    target = label.lower()
    for idx, line in enumerate(lines):
        clean = line.strip()
        if not clean:
            continue
        lowered = clean.lower()
        stripped = lowered.rstrip(":")
        is_direct_match = stripped == target
        inline_value = ""
        if not is_direct_match and lowered.startswith(f"{target} "):
            inline_value = clean[len(label) :].strip()
            inline_value = inline_value.lstrip(":").strip()
            if inline_value and not inline_value[0].isdigit() and inline_value[0] not in "+-($" and inline_value[0] != "(":
                inline_value = ""
        if is_direct_match or inline_value:
            if inline_value:
                return inline_value
            for follower in lines[idx + 1 :]:
                follower = follower.strip()
                if not follower:
                    continue
                follower_lower = follower.lower()
                if follower_lower == target or follower_lower.startswith(f"{target} "):
                    continue
                return follower
    return ""


def find_percentage(lines: List[str], start_idx: int) -> str:
    """Find the first percentage value at or after the provided index."""
    for follower in lines[start_idx:]:
        match = PERCENT_PATTERN.search(follower)
        if match:
            return match.group(1)
    return ""


def find_time(lines: List[str], start_idx: int) -> str:
    """Find the first time value at or after the provided index."""
    for follower in lines[start_idx:]:
        match = TIME_PATTERN.search(follower)
        if match:
            return match.group(0)
    return ""


def parse_date_to_iso(date_text: str) -> str:
    """Normalize and convert textual dates like 'December Ist, 2025' to ISO."""
    if not date_text:
        return ""

    def _normalize_day_token(text: str) -> str:
        text = re.sub(r"\b[iI]st\b", "1", text)
        text = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
        return text

    normalized = _normalize_day_token(date_text)
    normalized = normalized.replace(" ,", ",")
    normalized = re.sub(r"\s+", " ", normalized.strip())

    # Ensure there is a comma between day and year for consistent parsing.
    normalized = re.sub(r"(\d{1,2})\s+(\d{4})", r"\1, \2", normalized)

    for fmt in ("%B %d, %Y", "%B %d %Y"):
        try:
            dt = datetime.strptime(normalized, fmt)
            return dt.date().isoformat()
        except ValueError:
            continue
    return ""


def extract_additional_details(lines: List[str]) -> Dict[str, str]:
    """Pull start/end metadata from the Additional Details section."""
    additional_idx = next(
        (idx for idx, line in enumerate(lines) if "additional details" in line.lower()),
        None,
    )
    if additional_idx is None:
        return {
            "start_date": "",
            "end_date": "",
            "start_time": "",
            "end_time": "",
            "start_pct": "",
            "end_pct": "",
        }
    section = [line.strip() for line in lines[additional_idx + 1 :]]
    result = {
        "start_date": "",
        "end_date": "",
        "start_time": "",
        "end_time": "",
        "start_pct": "",
        "end_pct": "",
    }
    current_date = ""
    pending_time = ""
    for idx, line in enumerate(section):
        if not line:
            continue
        date_match = DATE_PATTERN.search(line)
        if date_match:
            current_date = parse_date_to_iso(date_match.group(0))
            time_match = TIME_PATTERN.search(line)
            pending_time = time_match.group(0) if time_match else ""
            continue
        lowered = line.lower()
        if lowered.startswith("start"):
            if not result["start_date"]:
                result["start_date"] = current_date
            if not result["start_time"]:
                time_value = pending_time or find_time(section, idx)
                result["start_time"] = time_value
            if not result["start_pct"]:
                result["start_pct"] = find_percentage(section, idx)
            pending_time = ""
        elif lowered.startswith("end"):
            if not result["end_date"]:
                result["end_date"] = current_date
            if not result["end_time"]:
                time_value = pending_time or find_time(section, idx)
                result["end_time"] = time_value
            if not result["end_pct"]:
                result["end_pct"] = find_percentage(section, idx)
            pending_time = ""
    return result


def extract_brand(charger_name: str) -> str:
    """Guess the charger brand from the leading token of the charger name."""
    if not charger_name:
        return ""
    for token in re.split(r"[\s\-]+", charger_name):
        token = token.strip()
        if token:
            return token
    return ""


def extract_record_from_text(text: str) -> Dict[str, str]:
    """Parse OCR text into the CSV-ready dictionary."""
    lines = [line.strip() for line in text.splitlines()]

    def extract_summary_info(start_idx: int) -> tuple[str, str]:
        name = ""
        location = ""
        for candidate in lines[start_idx:]:
            clean = candidate.strip()
            if not clean:
                continue
            lowered = clean.lower()
            if lower_is_section_break(lowered):
                if lowered in {"summary", "charge details"}:
                    continue
                break
            if not name:
                name = clean
            elif not location:
                location = clean
                break
        return name, location

    summary_idx = next((i for i, l in enumerate(lines) if "summary" in l.lower()), None)
    charger_name = ""
    charger_location = ""
    if summary_idx is not None:
        charger_name, charger_location = extract_summary_info(summary_idx + 1)
    if not charger_name:
        details_idx = next((i for i, l in enumerate(lines) if "charge details" in l.lower()), None)
        if details_idx is not None:
            charger_name, charger_location = extract_summary_info(details_idx + 1)

    duration = extract_label_value(lines, "time charging")
    kwh_text = extract_label_value(lines, "energy added")
    kwh_match = KWH_PATTERN.search(kwh_text)
    kwh_added = kwh_match.group(1) if kwh_match else ""

    charge_text = extract_label_value(lines, "charge")
    charge_pct = ""
    charge_miles = ""
    if charge_text:
        pct_match = PERCENT_PATTERN.search(charge_text)
        if pct_match:
            charge_pct = pct_match.group(1)
        miles_match = re.search(r"\((?:\+)?(\d+)\s*mi\)", charge_text)
        if miles_match:
            charge_miles = miles_match.group(1)

    kw_match = KW_PATTERN.search(text)
    charger_kw = kw_match.group(1) if kw_match else ""

    cost_match = COST_PATTERN.search(text)
    cost_value = cost_match.group(0) if cost_match else ""

    additional = extract_additional_details(lines)
    date_value = additional["start_date"] or additional["end_date"] or ""
    start_time = additional["start_time"]
    end_time = additional["end_time"]

    record = {
        "date": date_value,
        "charger_name": charger_name,
        "charger_location": charger_location,
        "duration": duration,
        "kwh_added": kwh_added,
        "charger_kw_rating": charger_kw,
        "charge_percentage": charge_pct,
        "charge_miles": charge_miles,
        "start_time": start_time,
        "end_time": end_time,
        "start_percentage": additional["start_pct"],
        "end_percentage": additional["end_pct"],
        "cost": cost_value,
        "charger_brand": extract_brand(charger_name),
    }
    return record


def gather_image_paths(paths: Iterable[Path]) -> List[Path]:
    """Expand file/directory arguments into a concrete list of image paths."""
    collected: List[Path] = []
    seen = set()

    def _collect_directory(directory: Path) -> None:
        for child in sorted(directory.iterdir(), key=lambda p: (p.is_dir(), p.name.lower())):
            if child.is_file():
                if child.suffix.lower() in IMAGE_EXTENSIONS:
                    norm = child.resolve()
                    if norm not in seen:
                        seen.add(norm)
                        collected.append(norm)
                continue
            if child.is_dir():
                _collect_directory(child)

    for path in paths:
        if not path.exists():
            raise SystemExit(f"Input path not found: {path}")
        if path.is_file():
            ext = path.suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                norm = path.resolve()
                if norm not in seen:
                    seen.add(norm)
                    collected.append(norm)
            else:
                raise SystemExit(f"Unsupported file type: {path}")
            continue
        if path.is_dir():
            _collect_directory(path)
            continue
        raise SystemExit(f"Unsupported path: {path}")
    return collected


def load_existing_rows(output_path: Path) -> List[Dict[str, str]]:
    if not output_path.exists():
        return []
    with output_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        existing = []
        for row in reader:
            normalized = {column: row.get(column, "") for column in CSV_COLUMNS}
            existing.append(normalized)
        return existing


def _parse_row_datetime(date_str: str, time_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    time_formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %I:%M%p"]
    if time_str:
        for fmt in time_formats:
            try:
                return datetime.strptime(f"{date_str} {time_str}", fmt)
            except ValueError:
                continue
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


def row_sort_key(row: Dict[str, str]) -> tuple:
    date_str = (row.get("date") or "").strip()
    time_str = (row.get("start_time") or "").strip()
    dt_value = _parse_row_datetime(date_str, time_str)
    if dt_value is None:
        dt_value = datetime.max  # push unknown dates to the end
    location = (row.get("charger_location") or "").strip().lower()
    name = (row.get("charger_name") or "").strip().lower()
    return (dt_value, location, name)


def write_csv(output_path: Path, rows: Iterable[Dict[str, str]], append: bool) -> int:
    """Write the rows to the CSV file and return the number of new rows added."""
    existing_rows = load_existing_rows(output_path) if append else []
    combined = []
    seen_keys = set()

    def dedup_key(row: Dict[str, str]) -> tuple:
        return (
            row.get("date") or "",
            row.get("charger_location") or "",
            row.get("start_time") or "",
        )

    for row in existing_rows:
        key = dedup_key(row)
        seen_keys.add(key)
        combined.append(row)

    added = 0
    for row in rows:
        key = dedup_key(row)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        combined.append(row)
        added += 1

    combined.sort(key=row_sort_key)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in combined:
            writer.writerow(row)

    return added


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract FordPass charge details from screenshots and output CSV rows."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Screenshot image(s) or directory/directories containing screenshots",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("charges.csv"),
        help="CSV file to create/append",
    )
    parser.add_argument(
        "--psm",
        default="6",
        help="Tesseract page segmentation mode (passed through to `tesseract --psm`).",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append rows to the existing CSV instead of overwriting it.",
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Print the OCR text for debugging instead of writing CSV.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = []
    image_paths = gather_image_paths(args.inputs)
    if not image_paths and not args.text_only:
        raise SystemExit("No images found in the provided paths.")
    for image in image_paths:
        text = run_tesseract(image, args.psm)
        if args.text_only:
            print(f"--- OCR output for {image} ---\n{text}")
            continue
        rows.append(extract_record_from_text(text))

    if args.text_only:
        return
    if not rows:
        raise SystemExit("No data rows produced.")
    inserted = write_csv(args.output, rows, append=args.append)
    print(f"Wrote {inserted} new row(s) to {args.output}")


if __name__ == "__main__":  # pragma: no cover
    main()
