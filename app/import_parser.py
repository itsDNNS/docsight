"""Import parser for Excel (.xlsx) and CSV files into Incident Journal."""

import csv
import io
import re
from datetime import datetime

MONTH_NAMES_DE = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9,
    "oktober": 10, "november": 11, "dezember": 12,
}

MONTH_HEADER_RE = re.compile(
    r"^(Januar|Februar|März|Maerz|April|Mai|Juni|Juli|August|September|"
    r"Oktober|November|Dezember)\s*\(?(\d{4})?\)?\s*$",
    re.IGNORECASE,
)

DATE_DD_MM_YYYY = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
DATE_DD_MM = re.compile(r"^(\d{1,2})\.(\d{1,2})\.\s*$")
DATE_DD_MM_RANGE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.\s*[-–—]\s*\d{1,2}\.\d{1,2}\.")
DATE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def parse_file(file_bytes, filename):
    """Parse uploaded file and return structured preview data.

    Returns dict with: columns, sample_headers, mapping, rows, total, skipped
    """
    if len(file_bytes) > MAX_FILE_SIZE:
        raise ValueError("File too large (max 5 MB)")

    lower = filename.lower()
    if lower.endswith(".xlsx"):
        raw_rows, headers_idx = _parse_xlsx(file_bytes)
    elif lower.endswith(".csv"):
        raw_rows, headers_idx = _parse_csv(file_bytes)
    else:
        raise ValueError("Unsupported file format. Use .xlsx or .csv")

    if not raw_rows:
        raise ValueError("File is empty")

    num_cols = max(len(r) for r in raw_rows)
    columns = [_col_letter(i) for i in range(num_cols)]

    sample_headers = []
    if headers_idx is not None and headers_idx < len(raw_rows):
        sample_headers = [str(c) if c else "" for c in raw_rows[headers_idx]]

    year_context = _extract_year_context(raw_rows)
    mapping = _detect_mapping(sample_headers, raw_rows, headers_idx)

    date_col = mapping.get("date")
    title_col = mapping.get("title")
    desc_col = mapping.get("description")

    result_rows = []
    skipped = 0
    start = (headers_idx + 1) if headers_idx is not None else 0

    for i in range(start, len(raw_rows)):
        row = raw_rows[i]
        raw = [str(c) if c else "" for c in row]

        # Skip empty rows
        if all(not c or not str(c).strip() for c in row):
            continue

        # Skip month-header rows
        first_cell = str(row[0]).strip() if row and row[0] else ""
        if MONTH_HEADER_RE.match(first_cell):
            continue

        # Extract fields
        raw_date = str(row[date_col]).strip() if date_col is not None and date_col < len(row) and row[date_col] else ""
        title = str(row[title_col]).strip() if title_col is not None and title_col < len(row) and row[title_col] else ""
        description = str(row[desc_col]).strip() if desc_col is not None and desc_col < len(row) and row[desc_col] else ""

        # Skip rows with no meaningful content
        if not title and not description and not raw_date:
            continue

        # Normalize date
        norm_date = _normalize_date(raw_date, year_context.get(i))

        # Clean up "None" strings
        if title == "None":
            title = ""
        if description == "None":
            description = ""

        entry = {
            "idx": i,
            "date": norm_date or "",
            "title": title,
            "description": description,
            "raw": raw,
        }

        if not norm_date:
            skipped += 1
            entry["skipped"] = True
            entry["raw_date"] = raw_date

        result_rows.append(entry)

    return {
        "columns": columns,
        "sample_headers": sample_headers,
        "mapping": mapping,
        "rows": result_rows,
        "total": len(result_rows),
        "skipped": skipped,
    }


def _parse_xlsx(file_bytes):
    """Parse .xlsx file. Returns (rows, header_index)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active

    rows = []
    for row in ws.iter_rows():
        cells = []
        for cell in row:
            val = cell.value
            if isinstance(val, datetime):
                cells.append(val.strftime("%Y-%m-%d"))
            elif val is not None:
                cells.append(str(val).strip())
            else:
                cells.append("")
        rows.append(cells)

    wb.close()
    header_idx = _find_header_row(rows)
    return rows, header_idx


def _parse_csv(file_bytes):
    """Parse CSV file. Returns (rows, header_index)."""
    # Try to detect encoding
    text = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            text = file_bytes.decode(encoding)
            break
        except (UnicodeDecodeError, ValueError):
            continue

    if text is None:
        raise ValueError("Could not decode CSV file")

    # Detect delimiter
    sample = text[:2000]
    semicolons = sample.count(";")
    commas = sample.count(",")
    tabs = sample.count("\t")
    delimiter = ";"
    if commas > semicolons and commas > tabs:
        delimiter = ","
    elif tabs > semicolons and tabs > commas:
        delimiter = "\t"

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = []
    for row in reader:
        rows.append([c.strip() for c in row])

    header_idx = _find_header_row(rows)
    return rows, header_idx


def _find_header_row(rows):
    """Find the header row index (first row with text in multiple columns)."""
    for i, row in enumerate(rows):
        non_empty = sum(1 for c in row if c and str(c).strip())
        if non_empty >= 2:
            # Check it's not a month header
            first = str(row[0]).strip() if row and row[0] else ""
            if not MONTH_HEADER_RE.match(first):
                return i
    return None


def _detect_mapping(headers, rows, headers_idx):
    """Detect which column is date, title, description."""
    mapping = {}

    if not headers:
        # No headers found, try to detect from data
        return _detect_mapping_from_data(rows)

    # Check header names for common patterns
    date_keywords = {"datum", "date", "tag", "day", "zeit", "time", "when"}
    title_keywords = {"titel", "title", "ereignis", "event", "betreff", "subject", "was", "what"}
    desc_keywords = {"beschreibung", "description", "details", "notiz", "note", "notes", "text", "inhalt", "content"}

    for i, h in enumerate(headers):
        hl = h.lower().strip()
        if hl in date_keywords:
            mapping["date"] = i
        elif hl in title_keywords:
            mapping["title"] = i
        elif hl in desc_keywords:
            mapping["description"] = i

    # If not all found by keyword, try data analysis
    if "date" not in mapping or "title" not in mapping:
        data_mapping = _detect_mapping_from_data(rows, headers_idx)
        if "date" not in mapping and "date" in data_mapping:
            mapping["date"] = data_mapping["date"]
        if "title" not in mapping and "title" in data_mapping:
            mapping["title"] = data_mapping["title"]
        if "description" not in mapping and "description" in data_mapping:
            mapping["description"] = data_mapping["description"]

    return mapping


def _detect_mapping_from_data(rows, skip=None):
    """Detect column mapping by analyzing data content."""
    mapping = {}
    if not rows:
        return mapping

    num_cols = max(len(r) for r in rows)
    start = (skip + 1) if skip is not None else 0
    sample = rows[start:start + 20]

    if not sample:
        return mapping

    # Score each column
    date_scores = [0] * num_cols
    text_lengths = [[] for _ in range(num_cols)]

    for row in sample:
        for col_idx in range(min(len(row), num_cols)):
            val = str(row[col_idx]).strip() if row[col_idx] else ""
            if not val:
                continue

            # Check if it looks like a date
            if _is_date_like(val):
                date_scores[col_idx] += 1

            text_lengths[col_idx].append(len(val))

    # Find date column (highest date score)
    max_date_score = max(date_scores) if date_scores else 0
    if max_date_score >= 2:
        mapping["date"] = date_scores.index(max_date_score)

    # Among remaining text columns, shorter avg = title, longer avg = description
    text_cols = []
    for col_idx in range(num_cols):
        if col_idx == mapping.get("date"):
            continue
        lengths = text_lengths[col_idx]
        if lengths:
            avg = sum(lengths) / len(lengths)
            if avg > 0:
                text_cols.append((col_idx, avg))

    text_cols.sort(key=lambda x: x[1])
    if len(text_cols) >= 2:
        mapping["title"] = text_cols[0][0]
        mapping["description"] = text_cols[1][0]
    elif len(text_cols) == 1:
        mapping["title"] = text_cols[0][0]

    return mapping


def _is_date_like(val):
    """Check if a string looks like a date."""
    val = val.strip()
    if DATE_ISO.match(val):
        return True
    if DATE_DD_MM_YYYY.match(val):
        return True
    if DATE_DD_MM.match(val):
        return True
    if DATE_DD_MM_RANGE.match(val):
        return True
    return False


def _extract_year_context(rows):
    """Extract year context from month-header rows (Dennis format).

    Returns dict mapping row_index -> year for rows that follow a month header.
    """
    year_map = {}
    current_year = None
    current_month = None

    for i, row in enumerate(rows):
        first_cell = str(row[0]).strip() if row and row[0] else ""
        m = MONTH_HEADER_RE.match(first_cell)
        if m:
            month_name = m.group(1).lower()
            year_str = m.group(2)

            if year_str:
                current_year = int(year_str)
            elif current_year is None:
                # Try to infer from nearby dates
                current_year = _infer_year_from_nearby(rows, i)

            month_num = MONTH_NAMES_DE.get(month_name)
            if month_num:
                current_month = month_num
        elif current_year is not None:
            year_map[i] = current_year

    return year_map


def _infer_year_from_nearby(rows, start_idx):
    """Try to find a year from dates in nearby rows."""
    for i in range(start_idx + 1, min(start_idx + 10, len(rows))):
        for cell in rows[i]:
            val = str(cell).strip() if cell else ""
            m = DATE_DD_MM_YYYY.match(val)
            if m:
                return int(m.group(3))
            m = DATE_ISO.match(val)
            if m:
                return int(m.group(1))
    return datetime.now().year


def _normalize_date(raw, year_from_context):
    """Normalize various date formats to YYYY-MM-DD.

    Priority:
    1. YYYY-MM-DD (ISO) -> direct
    2. DD.MM.YYYY -> parse
    3. DD.MM. -> year from context
    4. DD.MM. - DD.MM. -> take start date
    5. Not parseable -> None
    """
    if not raw:
        return None

    raw = raw.strip()

    # 1. ISO format
    m = DATE_ISO.match(raw)
    if m:
        try:
            datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return raw
        except ValueError:
            return None

    # 4. Date range DD.MM. - DD.MM. -> take start date
    m = DATE_DD_MM_RANGE.match(raw)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = year_from_context or datetime.now().year
        try:
            datetime(year, month, day)
            return f"{year:04d}-{month:02d}-{day:02d}"
        except ValueError:
            return None

    # 2. DD.MM.YYYY
    m = DATE_DD_MM_YYYY.match(raw)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            datetime(year, month, day)
            return f"{year:04d}-{month:02d}-{day:02d}"
        except ValueError:
            return None

    # 3. DD.MM. (with or without trailing dot/space)
    m = DATE_DD_MM.match(raw)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = year_from_context or datetime.now().year
        try:
            datetime(year, month, day)
            return f"{year:04d}-{month:02d}-{day:02d}"
        except ValueError:
            return None

    return None


def _col_letter(idx):
    """Convert column index (0-based) to Excel-style letter (A, B, ...)."""
    result = ""
    while True:
        result = chr(65 + (idx % 26)) + result
        idx = idx // 26 - 1
        if idx < 0:
            break
    return result
