# FordPass Charge Parser

Simple CLI that converts FordPass charge-detail screenshots into CSV entries by
running the images through Tesseract OCR and parsing the resulting text.

## Requirements

- Python 3.9+
- [`tesseract`](https://tesseract-ocr.github.io/) binary available on `PATH`
  (macOS: `brew install tesseract`).

## Usage

```bash
python charge_parser.py /path/to/folder /path/to/another/screenshot.png -o charges.csv
```

- You can mix individual image paths and directories; every supported image found is processed.
- Use `--text-only` to see the OCR text that will be parsed.
- Pass `--append` if you want to merge with an existing CSV; entries are deduplicated by
  `(date, location, start_time)` and the file is re-sorted chronologically.
- Override the Tesseract page-segmentation mode with `--psm` if needed.

The generated CSV contains the following snake_case columns:

```
date,charger_name,charger_location,duration,kwh_added,
charger_kw_rating,charge_percentage,charge_miles,start_time,end_time,start_percentage,
end_percentage,cost,charger_brand
```

Rows that are missing a given value leave the corresponding cell blank.

## Development

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # empty placeholder, stdlib only
python -m unittest discover -s tests
```
