# EV Charge Tracker

Simple CLI that converts FordPass charge-detail screenshots into CSV entries by
running the images through Tesseract OCR and parsing the resulting text.

Generated with vscode + OpenAI codex

## Requirements

- Python 3.9+
- [`tesseract`](https://tesseract-ocr.github.io/) binary available on `PATH`
  - macOS: `brew install tesseract`
  - Linux: `apt install tesseract-ocr` or your distro equivalent (untested)

## Usage

```bash
python charge_parser.py /path/to/folder /path/to/another/screenshot.png -o charges.csv
```

- You can mix individual image paths and directories; every supported image found is processed.
- Use `--text-only` to see the OCR text that will be parsed.
- Pass `--append` if you want to merge with an existing CSV; entries are deduplicated by
  `(date, location, start_time)` and the file is re-sorted chronologically.
- Override the Tesseract page-segmentation mode with `--psm` if needed. Some screenshot
  layouts (tall, multi-column, or heavy with white space) OCR better with alternate modes;
  try `--psm 6` (default), `--psm 4`, `--psm 11`, `--psm 12`, or `--psm 13` if longer screenshots fail to parse.

The generated CSV contains the following snake_case columns:

```
date,charger_name,charger_location,duration,kwh_added,
charger_kw_rating,charge_percentage,charge_miles,start_time,end_time,start_percentage,
end_percentage,cost,charger_brand,duration_minutes
```

Rows that are missing a given value leave the corresponding cell blank.

## Development

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # empty placeholder, stdlib only
python -m unittest discover -s tests
```

## Creating new plugins

Plugins live under `plugins/` and are auto-discovered. To scaffold a plugin from a
representative screenshot, run:

```
python generate_plugin.py electrify_america /path/to/sample.png --display-name "Electrify America"
```

The script OCRs the screenshot (respecting `--psm` if provided), seeds a keyword-based
`detect()` implementation, and writes `plugins/<plugin_name>.py` with a `parse()` stub
to fill in. Use `--force` to overwrite an existing plugin file. After implementing
`parse()`, commit the new plugin so it is picked up automatically.

## Future work

Add support for screenshots from other charging apps
