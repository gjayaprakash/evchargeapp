#!/usr/bin/env python3
"""
Utility script to scaffold a charging-app plugin from a sample screenshot.

The script OCRs the provided screenshot with tesseract and builds a plugin class
with a detect() method seeded by common keywords. The parse() method is left as
a TODO for manual implementation.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import List

from charge_parser import run_tesseract

KEYWORD_MIN_LENGTH = 4


def slug_to_class_name(slug: str) -> str:
    pattern = r"[_\-\s]+"
    return "".join(part.capitalize() for part in re.split(pattern, slug) if part)


def extract_keywords(text: str, limit: int) -> List[str]:
    tokens = re.findall(r"[A-Za-z]{%d,}" % KEYWORD_MIN_LENGTH, text.lower())
    counts = Counter(tokens)
    keywords = []
    for word, _ in counts.most_common():
        if word not in keywords:
            keywords.append(word)
        if len(keywords) >= limit:
            break
    return keywords


def render_plugin_source(class_name: str, plugin_name: str, display_name: str, keywords: List[str]) -> str:
    keyword_literal = ", ".join([f'"{kw}"' for kw in keywords]) if keywords else ""
    return f'''from plugins.base import ChargingAppPlugin

KEYWORDS = [{keyword_literal}]


class {class_name}(ChargingAppPlugin):
    name = "{plugin_name}"
    display_name = "{display_name}"

    def detect(self, text: str) -> float:
        lowered = text.lower()
        score = 0.0
        for token in KEYWORDS:
            if token in lowered:
                score += 1.0
        return score

    def parse(self, text: str) -> dict:
        \"\"\"Parse OCR text into a CSV row for this app.\"\"\"
        # TODO: implement parsing for {display_name}
        raise NotImplementedError("Implement parsing for {class_name}")'''


def generate_plugin_file(
    plugin_name: str, display_name: str, image_path: Path, output_path: Path, psm: str, keyword_limit: int
) -> Path:
    text = run_tesseract(image_path, psm)
    class_name = slug_to_class_name(plugin_name)
    keywords = extract_keywords(text, limit=keyword_limit)
    source = render_plugin_source(class_name, plugin_name, display_name, keywords)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(source, encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a charging-app plugin skeleton from a sample screenshot."
    )
    parser.add_argument("plugin_name", help="Short, slug-style plugin name (e.g. 'electrify_america').")
    parser.add_argument("screenshot", type=Path, help="Path to a representative screenshot for OCR.")
    parser.add_argument(
        "-d",
        "--display-name",
        help="Human-friendly name for the plugin; defaults to title-cased plugin_name.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output plugin file path; defaults to plugins/<plugin_name>.py",
    )
    parser.add_argument(
        "--psm",
        default="6",
        help="Tesseract page segmentation mode (passed through to `tesseract --psm`).",
    )
    parser.add_argument(
        "--keywords",
        type=int,
        default=6,
        help="Maximum number of keywords to seed into detect().",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing plugin file if present.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    screenshot = args.screenshot
    if not screenshot.exists():
        raise SystemExit(f"Screenshot not found: {screenshot}")
    output = args.output or Path("plugins") / f"{args.plugin_name}.py"
    if output.exists() and not args.force:
        raise SystemExit(f"Output file already exists: {output}. Use --force to overwrite.")

    display_name = args.display_name or slug_to_class_name(args.plugin_name)
    generated = generate_plugin_file(
        plugin_name=args.plugin_name,
        display_name=display_name,
        image_path=screenshot,
        output_path=output,
        psm=args.psm,
        keyword_limit=args.keywords,
    )
    print(f"Generated plugin scaffold at {generated}")


if __name__ == "__main__":  # pragma: no cover
    main()
