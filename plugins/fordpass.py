from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List

from .base import ChargingAppPlugin

DATE_PATTERN = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+((?:\d{1,2})(?:st|nd|rd|th)?|[iI]st)(?:,\s*|\s+)(\d{4})",
    re.IGNORECASE,
)
TIME_PATTERN = re.compile(r"\b\d{1,2}[:.]\d{2}\b")
PERCENT_PATTERN = re.compile(r"(\d{1,3})\s*%")
KWH_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*kWh\b", re.IGNORECASE)
COST_PATTERN = re.compile(r"\$[\d,.]+")

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
            time_str = match.group(0)
            # Normalize periods to colons for consistent output
            return time_str.replace(".", ":")
    return ""


def extract_section(lines: List[str], label: str) -> List[str]:
    """Return lines that belong to a section header until the next section break."""
    target = label.lower()
    for idx, line in enumerate(lines):
        clean = line.strip()
        if not clean:
            continue
        lowered = clean.lower()
        if lowered == target or lowered.startswith(f"{target} "):
            section: List[str] = []
            if lowered.startswith(f"{target} "):
                inline = clean[len(label) :].strip().lstrip(":").strip()
                if inline:
                    section.append(inline)
            for follower in lines[idx + 1 :]:
                follower_clean = follower.strip()
                if not follower_clean:
                    continue
                follower_lower = follower_clean.lower()
                if lower_is_section_break(follower_lower):
                    break
                section.append(follower_clean)
            return section
    return []


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
            if time_match:
                # Normalize periods to colons for consistent output
                pending_time = time_match.group(0).replace(".", ":")
            else:
                pending_time = ""
            continue

        # Check if line is a standalone time (EasyOCR often splits date and time)
        time_match = TIME_PATTERN.search(line)
        if time_match and time_match.group(0).strip() == line.strip():
            # This line contains only a time, save it as pending
            pending_time = time_match.group(0).replace(".", ":")
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


def parse_duration_minutes(duration_text: str) -> str:
    """Convert duration text like '2 hrs 50 min' into total minutes."""
    if not duration_text:
        return ""
    hours = 0
    minutes = 0
    hour_match = re.search(r"(\d+)\s*hr", duration_text, flags=re.IGNORECASE)
    if hour_match:
        hours = int(hour_match.group(1))
    minute_match = re.search(r"(\d+)\s*min", duration_text, flags=re.IGNORECASE)
    if minute_match:
        minutes = int(minute_match.group(1))
    total = hours * 60 + minutes
    return str(total) if total > 0 else ""


def extract_record_from_text(text: str) -> Dict[str, str]:
    """Parse OCR text into the CSV-ready dictionary."""
    lines = [line.strip() for line in text.splitlines()]
    additional_idx = next((idx for idx, line in enumerate(lines) if "additional details" in line.lower()), None)

    def extract_summary_info(start_idx: int) -> tuple[str, str]:
        summary_lines: List[str] = []
        for candidate in lines[start_idx:]:
            clean = candidate.strip()
            if not clean:
                continue
            lowered = clean.lower()
            if lower_is_section_break(lowered):
                if lowered in {"summary", "charge details"}:
                    continue
                break
            summary_lines.append(clean)

        if not summary_lines:
            return "", ""

        # Use the last line as the address, everything before as the name
        if len(summary_lines) >= 2:
            location = summary_lines[-1].strip()
            name = " ".join(summary_lines[:-1]).strip()
        elif len(summary_lines) == 1:
            # Only one line - treat it as the name
            name = summary_lines[0].strip()
            location = ""
        else:
            name = ""
            location = ""

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
    duration_minutes = parse_duration_minutes(duration)
    kwh_text = extract_label_value(lines, "energy added")
    kwh_match = KWH_PATTERN.search(kwh_text)
    kwh_added = kwh_match.group(1) if kwh_match else ""

    charge_text = extract_label_value(lines, "charge")
    if not charge_text:
        charge_section = extract_section(lines, "charge")
        if charge_section:
            charge_text = charge_section[0]
    charge_pct = ""
    charge_miles = ""
    if charge_text:
        pct_match = PERCENT_PATTERN.search(charge_text)
        if pct_match:
            charge_pct = pct_match.group(1)
        miles_match = re.search(r"\((?:\+)?(\d+)\s*mi\)", charge_text)
        if miles_match:
            charge_miles = miles_match.group(1)
    if not charge_pct or not charge_miles:
        scan_limit = additional_idx if additional_idx is not None else len(lines)
        for line in lines[:scan_limit]:
            if not charge_pct:
                pct_match = PERCENT_PATTERN.search(line)
                if pct_match:
                    charge_pct = pct_match.group(1)
            if not charge_miles:
                miles_match = re.search(r"\((?:\+)?(\d+)\s*mi\)", line)
                if miles_match:
                    charge_miles = miles_match.group(1)
            if charge_pct and charge_miles:
                break

    cost_match = COST_PATTERN.search(text)
    cost_value = cost_match.group(0) if cost_match else ""

    additional = extract_additional_details(lines)
    date_value = additional["start_date"] or additional["end_date"] or ""
    start_time = additional["start_time"]
    end_time = additional["end_time"]

    # Fix OCR errors in percentages where leading digits may be misread
    start_pct = additional["start_pct"]
    end_pct = additional["end_pct"]

    if start_pct and end_pct and charge_pct:
        try:
            start_val = int(start_pct)
            end_val = int(end_pct)
            charge_val = int(charge_pct)
            expected_end = start_val + charge_val

            # Check if OCR misread a leading digit (e.g., "79" as "19", "78" as "18")
            if abs(expected_end - end_val) >= 10:
                # Try common OCR errors: 1→7, 7→1, 1→4, etc.
                for correction in [60, 70, 80, -60, -70, -80, 30, 40, 50, -30, -40, -50]:
                    corrected_end = end_val + correction
                    if corrected_end == expected_end and 0 <= corrected_end <= 100:
                        end_pct = str(corrected_end)
                        break
        except (ValueError, TypeError):
            pass

    record = {
        "date": date_value,
        "charger_name": charger_name,
        "charger_location": charger_location,
        "duration_minutes": duration_minutes,
        "kwh_added": kwh_added,
        "charge_percentage": charge_pct,
        "charge_miles": charge_miles,
        "start_time": start_time,
        "end_time": end_time,
        "start_percentage": start_pct,
        "end_percentage": end_pct,
        "cost": cost_value,
        "charger_brand": extract_brand(charger_name),
    }
    return record


class FordPassPlugin(ChargingAppPlugin):
    name = "fordpass"
    display_name = "FordPass"

    def detect(self, text: str) -> float:
        lowered = text.lower()
        score = 0.0
        if "fordpass" in lowered or "ford pass" in lowered:
            score += 2.0
        for token in ("charge details", "additional details", "energy added", "time charging"):
            if token in lowered:
                score += 0.5
        if "summary" in lowered:
            score += 0.25
        return score

    def parse(self, text: str) -> Dict[str, str]:
        return extract_record_from_text(text)
