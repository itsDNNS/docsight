"""Parser for BNetzA Breitbandmessung CSV exports.

Parses CSV files exported from the official Breitbandmessung Desktop App
(semicolon-separated, German locale numbers).
"""

import csv
import io
import logging
import re

log = logging.getLogger("docsis.bnetz_csv_parser")


def _parse_de_float(s):
    """Parse a float that may be German or English formatted.

    German: '1.000,50' -> 1000.5, '883,29' -> 883.29
    English: '235.5' -> 235.5, '1000.50' -> 1000.50
    """
    if not s or not s.strip():
        return None
    s = s.strip()
    has_comma = "," in s
    has_dot = "." in s
    if has_comma:
        # German format: dots are thousands separators, comma is decimal
        s = s.replace(".", "").replace(",", ".")
    # else: English format, dots are decimal separators, keep as-is
    try:
        return float(s)
    except ValueError:
        return None


def _convert_date(date_str):
    """Convert DD.MM.YYYY to YYYY-MM-DD, pass through YYYY-MM-DD as-is."""
    if not date_str:
        return None
    date_str = date_str.strip()
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", date_str)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    # Already ISO format
    if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
        return date_str
    return date_str


def parse_bnetz_csv(csv_content):
    """Parse a BNetzA Breitbandmessung CSV and return structured data.

    Expects semicolon-separated CSV with columns for date, time, download, upload speeds.
    German locale numbers (comma as decimal separator).

    Args:
        csv_content: CSV file content as string.

    Returns:
        dict with measurement data matching save_bnetz_measurement() schema.

    Raises:
        ValueError: If the CSV cannot be parsed or contains no valid rows.
    """
    if not csv_content or not csv_content.strip():
        raise ValueError("Empty CSV content")

    # Try semicolon first, then comma
    dialect_delimiter = ";"
    reader = csv.reader(io.StringIO(csv_content.strip()), delimiter=dialect_delimiter)

    rows = list(reader)
    if not rows:
        raise ValueError("Empty CSV file")

    # Detect header row - look for common BNetzA CSV column names
    header = rows[0]
    if len(header) <= 1 and ";" not in csv_content:
        # Try comma delimiter
        dialect_delimiter = ","
        reader = csv.reader(io.StringIO(csv_content.strip()), delimiter=dialect_delimiter)
        rows = list(reader)
        header = rows[0]

    # Normalize header names (lowercase, strip whitespace)
    header_lower = [h.strip().lower() for h in header]

    # Find relevant column indices
    date_col = _find_col(header_lower, ["datum", "date", "messdatum"])
    time_col = _find_col(header_lower, ["uhrzeit", "time", "zeit"])
    dl_col = _find_col(header_lower, ["download", "download (mbit/s)", "dl", "download_mbps"])
    ul_col = _find_col(header_lower, ["upload", "upload (mbit/s)", "ul", "upload_mbps"])

    if dl_col is None and ul_col is None:
        raise ValueError("CSV must contain at least download or upload speed columns")

    dl_measurements = []
    ul_measurements = []
    dates = []

    for i, row in enumerate(rows[1:], start=1):
        if not row or all(not c.strip() for c in row):
            continue

        date_val = row[date_col].strip() if date_col is not None and date_col < len(row) else None
        time_val = row[time_col].strip() if time_col is not None and time_col < len(row) else None
        dl_val = _parse_de_float(row[dl_col]) if dl_col is not None and dl_col < len(row) else None
        ul_val = _parse_de_float(row[ul_col]) if ul_col is not None and ul_col < len(row) else None

        iso_date = _convert_date(date_val) if date_val else None
        if iso_date:
            dates.append(iso_date)

        if dl_val is not None:
            dl_measurements.append({
                "nr": len(dl_measurements) + 1,
                "date": iso_date or "",
                "time": time_val or "",
                "mbps": dl_val,
            })

        if ul_val is not None:
            ul_measurements.append({
                "nr": len(ul_measurements) + 1,
                "date": iso_date or "",
                "time": time_val or "",
                "mbps": ul_val,
            })

    if not dl_measurements and not ul_measurements:
        raise ValueError("No valid measurement rows found in CSV")

    # Compute averages
    dl_avg = round(sum(m["mbps"] for m in dl_measurements) / len(dl_measurements), 2) if dl_measurements else None
    ul_avg = round(sum(m["mbps"] for m in ul_measurements) / len(ul_measurements), 2) if ul_measurements else None

    # Use latest date as measurement date
    measurement_date = max(dates) if dates else None

    result = {
        "date": measurement_date,
        "provider": "CSV Import",
        "tariff": None,
        "download_max": None,
        "download_normal": None,
        "download_min": None,
        "upload_max": None,
        "upload_normal": None,
        "upload_min": None,
        "download_measured_avg": dl_avg,
        "upload_measured_avg": ul_avg,
        "measurement_count": max(len(dl_measurements), len(ul_measurements)),
        "verdict_download": "unknown",
        "verdict_upload": "unknown",
        "measurements_download": dl_measurements,
        "measurements_upload": ul_measurements,
    }

    log.info(
        "Parsed BNetzA CSV: %d DL + %d UL measurements, DL avg=%.1f, UL avg=%.1f",
        len(dl_measurements), len(ul_measurements),
        dl_avg or 0, ul_avg or 0,
    )

    return result


def _find_col(header, candidates):
    """Find the first matching column index from a list of candidate names."""
    for candidate in candidates:
        for i, h in enumerate(header):
            if candidate in h:
                return i
    return None
