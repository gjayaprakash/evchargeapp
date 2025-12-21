import csv
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from charge_parser import (
    FordPassPlugin,
    available_plugins,
    extract_record_from_text,
    gather_image_paths,
    pick_plugin_from_scores,
    score_plugins,
    write_csv,
)


SAMPLE_TEXT = """
Charge details

Summary
Shell Recharge - Southland Mall - Macy's
One Southland Mall Drive Hayward

Charge
29% (+86 mi)

Time charging
2 hrs 50 min

Energy added
16.7 kWh

Additional details
December 16, 2025
Start 12:32 71%
December 16, 2025
End 15:23 100%
"""

NO_SUMMARY_TEXT = """
Charge details

ChargePoint - Hillsdale Shopping Center
2910 Edison St San Mateo

Charge
20% (+49 mi)

Time charging
2 hrs 47 min

Energy added
14.9 kWh

Additional details
December 7, 2025
Start 17:13 46%
December 7, 2025
End 20:01 66%
"""

IST_TEXT = """
Charge details

Summary
ChargePoint Downtown
123 Main St

Charge
25% (+70 mi)

Time charging
1 hr 15 min

Energy added
12.3 kWh

Additional details
December Ist, 2025
Start 08:05 30%
December Ist, 2025
End 09:20 55%
"""

DATE_TIME_SAME_LINE_TEXT = """
Charge details

Summary
ChargePoint DateTime
42 Some Pl

Charge
30% (+60 mi)

Time charging
1 hr

Energy added
10 kWh

Additional details
December 10, 2025 07:00
Start 40%
December 10, 2025 09:00
End 70%
"""


class ParserTestCase(unittest.TestCase):
    def test_extract_record_from_text(self) -> None:
        record = extract_record_from_text(SAMPLE_TEXT)
        self.assertEqual(record["charger_name"], "Shell Recharge - Southland Mall - Macy's")
        self.assertEqual(record["charger_location"], "One Southland Mall Drive Hayward")
        self.assertEqual(record["duration"], "2 hrs 50 min")
        self.assertEqual(record["duration_minutes"], "170")
        self.assertEqual(record["kwh_added"], "16.7")
        self.assertEqual(record["start_time"], "12:32")
        self.assertEqual(record["end_time"], "15:23")
        self.assertEqual(record["start_percentage"], "71")
        self.assertEqual(record["end_percentage"], "100")
        self.assertEqual(record["date"], "2025-12-16")
        self.assertEqual(record["charge_percentage"], "29")
        self.assertEqual(record["charge_miles"], "86")
        self.assertEqual(record["charger_brand"], "Shell")

    def test_extract_record_without_summary_label(self) -> None:
        record = extract_record_from_text(NO_SUMMARY_TEXT)
        self.assertEqual(record["charger_name"], "ChargePoint - Hillsdale Shopping Center")
        self.assertEqual(record["charger_location"], "2910 Edison St San Mateo")
        self.assertEqual(record["start_time"], "17:13")
        self.assertEqual(record["end_time"], "20:01")
        self.assertEqual(record["start_percentage"], "46")
        self.assertEqual(record["end_percentage"], "66")
        self.assertEqual(record["date"], "2025-12-07")
        self.assertEqual(record["duration_minutes"], "167")

    def test_extract_record_with_ordinal_date(self) -> None:
        record = extract_record_from_text(IST_TEXT)
        self.assertEqual(record["date"], "2025-12-01")
        self.assertEqual(record["start_time"], "08:05")
        self.assertEqual(record["end_time"], "09:20")
        self.assertEqual(record["start_percentage"], "30")
        self.assertEqual(record["end_percentage"], "55")
        self.assertEqual(record["charge_miles"], "70")

    def test_extract_record_with_time_on_date_line(self) -> None:
        record = extract_record_from_text(DATE_TIME_SAME_LINE_TEXT)
        self.assertEqual(record["date"], "2025-12-10")
        self.assertEqual(record["start_time"], "07:00")
        self.assertEqual(record["end_time"], "09:00")


class GatherImagesTestCase(unittest.TestCase):
    def test_collects_images_from_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img1 = base / "one.PNG"
            img1.write_bytes(b"a")
            non_img = base / "ignore.txt"
            non_img.write_text("noop")
            nested = base / "nested"
            nested.mkdir()
            img2 = nested / "two.jpg"
            img2.write_bytes(b"b")

            collected = gather_image_paths([base])

            self.assertEqual(collected, [img1.resolve(), img2.resolve()])


class CsvWriteTestCase(unittest.TestCase):
    def test_append_sorts_and_dedups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "charges.csv"

            initial_row = {
                "date": "2025-12-16",
                "charger_name": "Shell Recharge",
                "charger_location": "Location A",
                "duration": "2 hrs",
                "duration_minutes": "120",
                "kwh_added": "10",
                "charger_kw_rating": "",
                "start_time": "12:00",
                "end_time": "14:00",
                "start_percentage": "20",
                "end_percentage": "80",
                "cost": "",
                "charger_brand": "Shell",
            }

            write_csv(output_path, [initial_row], append=False)

            duplicate_row = dict(initial_row)
            later_row = dict(initial_row)
            later_row.update(
                {
                    "date": "2026-01-01",
                    "start_time": "09:00",
                    "charger_location": "Location B",
                    "duration_minutes": "180",
                }
            )

            added = write_csv(output_path, [duplicate_row, later_row], append=True)
            self.assertEqual(added, 1)

            blank_date = dict(initial_row)
            blank_date.update({"date": "", "start_time": "", "duration_minutes": ""})
            added = write_csv(output_path, [blank_date], append=True)
            self.assertEqual(added, 1)

            with output_path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

            self.assertEqual(len(rows), 3)
            self.assertEqual(
                [row["charger_location"] for row in rows],
                ["Location A", "Location B", "Location A"],
            )


class PluginDetectionTestCase(unittest.TestCase):
    def test_detects_fordpass_plugin(self) -> None:
        plugins = available_plugins()
        scores = score_plugins(SAMPLE_TEXT, plugins)
        plugin = pick_plugin_from_scores(scores)
        self.assertIsInstance(plugin, FordPassPlugin)

    def test_detection_returns_none_for_unknown_app(self) -> None:
        plugins = available_plugins()
        scores = score_plugins("unknown text without markers", plugins)
        plugin = pick_plugin_from_scores(scores)
        self.assertIsNone(plugin)


if __name__ == "__main__":
    unittest.main()
