#!/usr/bin/env python3
"""
Command line utility that converts EV charge-detail screenshots into CSV rows.

The tool shells out to the `tesseract` binary (must be installed separately) to OCR the
image, then hands the text to a plugin responsible for parsing the chosen charging app.
If the app cannot be determined automatically, the user is prompted to pick the plugin.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False

from plugins import (
    ChargingAppPlugin,
    discover_plugins,
    get_plugin_by_name,
    pick_plugin_from_scores,
    score_plugins,
)
from plugins.fordpass import FordPassPlugin, extract_record_from_text as fordpass_extract

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heic", ".tif", ".tiff", ".bmp"}

CSV_COLUMNS = [
    "date",
    "charger_name",
    "charger_location",
    "duration_minutes",
    "kwh_added",
    "charge_percentage",
    "charge_miles",
    "start_time",
    "end_time",
    "start_percentage",
    "end_percentage",
    "charger_brand",
    "cost",
]

# Global EasyOCR reader instance (initialized on first use)
_easyocr_reader = None


def get_easyocr_reader():
    """Lazy initialization of EasyOCR reader."""
    global _easyocr_reader
    if _easyocr_reader is None and EASYOCR_AVAILABLE:
        # Try to use GPU on macOS (MPS) if available, suppress pin_memory warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*pin_memory.*")
            # EasyOCR will automatically detect and use MPS on Apple Silicon
            _easyocr_reader = easyocr.Reader(['en'], gpu=True, verbose=False)
    return _easyocr_reader


def run_easyocr(image_path: Path) -> str:
    """Run EasyOCR on the image and return the extracted text."""
    reader = get_easyocr_reader()
    if reader is None:
        raise RuntimeError("EasyOCR not available")

    # Suppress pin_memory warnings on MPS (macOS)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*pin_memory.*")
        result = reader.readtext(str(image_path), detail=0)
    return "\n".join(result)


def run_tesseract(image_path: Path, psm: str) -> str:
    """Run tesseract on the image and return the extracted text."""
    try:
        result = subprocess.run(
            [
                "tesseract",
                str(image_path),
                "stdout",
                "--psm", psm,
                "--oem", "1",  # Use LSTM engine only (better for modern screenshots)
            ],
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


def run_ocr(image_path: Path, psm: str, use_easyocr: bool = True) -> str:
    """
    Run OCR on the image using EasyOCR if available, otherwise fall back to Tesseract.

    Args:
        image_path: Path to the image file
        psm: Tesseract page segmentation mode (ignored if using EasyOCR)
        use_easyocr: If True and EasyOCR is available, use it instead of Tesseract

    Returns:
        Extracted text from the image
    """
    if use_easyocr and EASYOCR_AVAILABLE:
        return run_easyocr(image_path)
    return run_tesseract(image_path, psm)


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


def extract_record_from_text(text: str) -> Dict[str, str]:
    """
    Backwards-compatible helper that parses OCR text using the FordPass plugin.

    Other charging apps can be supported by registering additional plugins and
    routing through the plugin selection helpers in `main`.
    """
    return fordpass_extract(text)


def available_plugins() -> List[ChargingAppPlugin]:
    """Return all known charging app plugins."""
    return discover_plugins()


def prompt_user_for_plugin(plugins: Sequence[ChargingAppPlugin], image_path: Path) -> ChargingAppPlugin:
    print(f"Could not determine the charging app for {image_path}.")
    for idx, plugin in enumerate(plugins, start=1):
        print(f"{idx}. {plugin.display_name}")
    while True:
        response = input("Select the correct app by number: ").strip()
        try:
            choice = int(response)
        except ValueError:
            print("Please enter a numeric choice from the list.")
            continue
        if 1 <= choice <= len(plugins):
            return plugins[choice - 1]
        print("Choice out of range; try again.")


def resolve_plugin_for_text(
    text: str, plugins: Sequence[ChargingAppPlugin], image_path: Path
) -> ChargingAppPlugin:
    scores = score_plugins(text, plugins)
    plugin = pick_plugin_from_scores(scores)
    if plugin:
        return plugin
    return prompt_user_for_plugin(plugins, image_path)


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
        description="Extract EV charge details from charging app screenshots and output CSV rows."
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
    parser.add_argument(
        "--plugin",
        dest="plugin_name",
        help="Force a specific plugin by name (e.g. 'fordpass') instead of auto-detecting.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = []
    image_paths = gather_image_paths(args.inputs)
    if not image_paths and not args.text_only:
        raise SystemExit("No images found in the provided paths.")
    plugins = available_plugins()
    forced_plugin: Optional[ChargingAppPlugin] = None
    if args.plugin_name:
        forced_plugin = get_plugin_by_name(args.plugin_name, plugins)
        if forced_plugin is None:
            available = ", ".join(plugin.name for plugin in plugins)
            raise SystemExit(f"Unknown plugin '{args.plugin_name}'. Available plugins: {available}")
    for image in image_paths:
        text = run_ocr(image, args.psm)
        if args.text_only:
            ocr_engine = "EasyOCR" if EASYOCR_AVAILABLE else "Tesseract"
            print(f"--- OCR output for {image} (using {ocr_engine}) ---\n{text}")
            continue
        plugin = forced_plugin or resolve_plugin_for_text(text, plugins, image)
        rows.append(plugin.parse(text))

    if args.text_only:
        return
    if not rows:
        raise SystemExit("No data rows produced.")
    inserted = write_csv(args.output, rows, append=args.append)
    print(f"Wrote {inserted} new row(s) to {args.output}")


if __name__ == "__main__":  # pragma: no cover
    main()
