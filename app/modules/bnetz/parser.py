"""Parser for BNetzA Breitbandmessung PDF protocols.

Extracts measurement data from official Bundesnetzagentur broadband
measurement PDFs (Messprotokolle der Breitbandmessung).

These PDFs are legally binding under TKG § 57 Abs. 4 and can be used
to file complaints with German ISPs.
"""

import logging
import re

log = logging.getLogger("docsis.bnetz_parser")

# ── Regex patterns (verified against real BNetzA PDFs) ──

_RE_DATE = re.compile(
    r"Messprotokoll der Breitbandmessung vom (\d{2}\.\d{2}\.\d{4})"
)
_RE_PROVIDER = re.compile(r"Anbieter:\s*(.+)")
_RE_TARIFF = re.compile(r"Tarifname:\s*(.+)")
_RE_MEASUREMENT_COUNT = re.compile(r"Anzahl Messungen:\s*(\d+)")

# Tariff rates: "Maximal: 1000,00 Mbit/s" etc.
# The PDF has DL and UL rates on the same lines, so we collect all
# matches and assign them in order: DL max, UL max, DL normal, UL normal, ...
_RE_RATE_MAXIMAL = re.compile(r"Maximal:\s*([\d.,]+)\s*Mbit/s")
_RE_RATE_NORMAL = re.compile(r"Normalerweise:\s*([\d.,]+)\s*Mbit/s")
_RE_RATE_MINIMAL = re.compile(r"Minimal:\s*([\d.,]+)\s*Mbit/s")

# Individual measurements: "1 29.01.2025 15:22 883,29 Mbit/s"
_RE_MEASUREMENT = re.compile(
    r"(\d+)\s+(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})\s+([\d.,]+)\s*Mbit/s"
)

# Verdict headings: "Ergebnis der Messkampagne im Download/Upload" (page 3) anywhere on a line, or the overall
# "Ergebnis" (page 2) at the start of a line. A section runs to the next heading.
_RE_RESULT_HEADING = re.compile(
    r"Ergebnis\s+der\s+Messkampagne\s+im\s+(Download|Upload)"
    r"|^[^\S\n]*Ergebnis\b(?!\s+der\s+Messkampagne)",
    re.MULTILINE,
)
# Sentence end; abbreviations such as "i.S.v. § 57" or "Nr. 1" are not followed by a capital letter
_RE_SENTENCE_END = re.compile(r"[.:]\s+(?=[A-ZÄÖÜ])")
# Clause boundaries in a sentence naming both directions; a comma only after a complete finding
_RE_CLAUSE_BREAK = re.compile(r"\b(?:und|aber|jedoch|sondern)\b|;|(?<=festgestellt),")
# "No deviation" only where the negation belongs to the finding: "keine (erhebliche, ...) Abweichung (... festgestellt)"
# or "Abweichung ... nicht festgestellt". Bridging words never cross a comma, a parenthesis, a conjunction,
# "Ergebnis" or another finding word, except the comma in the published "erhebliche, kontinuierliche oder regelmäßig
# wiederkehrende Abweichung".
_WORD = r"(?:(?!(?:und|aber|jedoch|sondern)\b|Abweichung|festgestellt|Ergebnis)[^\s,;()]+\s+)"
_PUBLISHED_ADJECTIVES = r"[\"„“]?erhebliche,\s+(?=kontinuierliche\s+oder\s+regelmäßig\s+wiederkehrende\s+Abweichung)"
_RE_NO_DEVIATION = re.compile(
    rf"\bkeine\s+(?:{_PUBLISHED_ADJECTIVES}|{_WORD}){{0,8}}Abweichung\b(?:\s+{_WORD}{{0,25}}festgestellt)?"
    rf"|Abweichung\s+{_WORD}{{0,8}}nicht\s+festgestellt",
    re.IGNORECASE,
)


# Campaign dates
_RE_CAMPAIGN_START = re.compile(
    r"Start Messkampagne:\s*(\d{2}\.\d{2}\.\d{4})"
)
_RE_CAMPAIGN_END = re.compile(
    r"Ende Messkampagne:\s*(\d{2}\.\d{2}\.\d{4})"
)


def _parse_de_float(s):
    """Parse a German-formatted float: '1.000,50' -> 1000.5, '883,29' -> 883.29."""
    s = s.strip().replace(".", "").replace(",", ".")
    return float(s)


def _convert_date(date_str):
    """Convert DD.MM.YYYY to YYYY-MM-DD."""
    parts = date_str.strip().split(".")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_str


def _finding(clause):
    """Return "ok" if only explicit no-deviation findings mention a finding, "deviation" for any other one."""
    rest = _RE_NO_DEVIATION.sub(" ", clause)
    if "Abweichung" in rest or "festgestellt" in rest:
        return "deviation"
    return "ok" if rest != clause else None


def _parse_verdicts(page_texts):
    """Return (download, upload) verdicts.

    A verdict statement is a sentence in a result section mentioning "Abweichung" and "festgestellt".
    A direction is a deviation if any statement says so, ok if one says ok.
    The overall summary only fills a direction without statements of its own.
    """
    found = {"Download": set(), "Upload": set(), None: set()}
    for page_text in page_texts:
        parts = _RE_RESULT_HEADING.split(re.sub(r"-\s*\n\s*", "", page_text))  # undo hyphenation first
        for heading_direction, section in zip(parts[1::2], parts[2::2]):
            for sentence in _RE_SENTENCE_END.split(section):
                if "Abweichung" not in sentence or "festgestellt" not in sentence:
                    continue
                # A sentence naming both directions is read clause by clause; a clause without its own
                # finding only inherits a deviation, never "ok", and a deviation naming no direction applies to both
                both = len(set(re.findall("Download|Upload", sentence))) > 1
                clauses = _RE_CLAUSE_BREAK.split(sentence) if both else [sentence]
                marks = [_finding(clause) for clause in clauses]
                for clause, mark in zip(clauses, marks):
                    if mark := mark or ("deviation" if "deviation" in marks else None):
                        named = set(re.findall("Download|Upload", clause))
                        for direction in named or ({"Download", "Upload"} if both and mark == "deviation"
                                                   else {heading_direction}):
                            found[direction].add(mark)
    return tuple("deviation" if "deviation" in v else "ok" if v else "unknown"
                 for v in (found["Download"] or found[None], found["Upload"] or found[None]))


def parse_bnetz_pdf(pdf_bytes):
    """Parse a BNetzA Breitbandmessung PDF and return structured data.

    Args:
        pdf_bytes: Raw PDF file content (bytes).

    Returns:
        dict with measurement data, or None if parsing fails.

    Raises:
        ValueError: If the PDF is not a valid BNetzA Messprotokoll.
    """
    try:
        from pypdf import PdfReader
        from io import BytesIO
        reader = PdfReader(BytesIO(pdf_bytes))
    except Exception as e:
        raise ValueError(f"Cannot read PDF: {e}") from e

    # Extract text from all pages
    full_text = ""
    page_texts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        page_texts.append(text)
        full_text += text + "\n"

    # ── Validate: is this a BNetzA Messprotokoll? ──
    if "Messprotokoll der Breitbandmessung" not in full_text:
        raise ValueError("Not a BNetzA Messprotokoll")

    result = {}

    # ── Date ──
    m = _RE_DATE.search(full_text)
    if m:
        result["date"] = _convert_date(m.group(1))
    else:
        raise ValueError("Cannot find measurement date")

    # ── Provider & Tariff ──
    m = _RE_PROVIDER.search(full_text)
    result["provider"] = m.group(1).strip() if m else None

    m = _RE_TARIFF.search(full_text)
    result["tariff"] = m.group(1).strip() if m else None

    # ── Measurement count ──
    m = _RE_MEASUREMENT_COUNT.search(full_text)
    result["measurement_count"] = int(m.group(1)) if m else None

    # ── Tariff rates ──
    # Page 1 contains DL and UL rates. The pattern appears twice per rate type
    # (once for DL, once for UL), in the order they appear on the page.
    maximal = _RE_RATE_MAXIMAL.findall(full_text)
    normal = _RE_RATE_NORMAL.findall(full_text)
    minimal = _RE_RATE_MINIMAL.findall(full_text)

    # First occurrence = download, second = upload
    result["download_max"] = _parse_de_float(maximal[0]) if len(maximal) >= 1 else None
    result["upload_max"] = _parse_de_float(maximal[1]) if len(maximal) >= 2 else None
    result["download_normal"] = _parse_de_float(normal[0]) if len(normal) >= 1 else None
    result["upload_normal"] = _parse_de_float(normal[1]) if len(normal) >= 2 else None
    result["download_min"] = _parse_de_float(minimal[0]) if len(minimal) >= 1 else None
    result["upload_min"] = _parse_de_float(minimal[1]) if len(minimal) >= 2 else None

    # ── Individual measurements ──
    # Page 4 = Download measurements, Page 5 = Upload measurements
    dl_measurements = []
    ul_measurements = []

    for i, page_text in enumerate(page_texts):
        if "Messungen im Download" in page_text:
            for m in _RE_MEASUREMENT.finditer(page_text):
                dl_measurements.append({
                    "nr": int(m.group(1)),
                    "date": _convert_date(m.group(2)),
                    "time": m.group(3),
                    "mbps": _parse_de_float(m.group(4)),
                })
        elif "Messungen im Upload" in page_text:
            for m in _RE_MEASUREMENT.finditer(page_text):
                ul_measurements.append({
                    "nr": int(m.group(1)),
                    "date": _convert_date(m.group(2)),
                    "time": m.group(3),
                    "mbps": _parse_de_float(m.group(4)),
                })

    result["measurements_download"] = dl_measurements
    result["measurements_upload"] = ul_measurements

    # ── Computed averages ──
    if dl_measurements:
        result["download_measured_avg"] = round(
            sum(m["mbps"] for m in dl_measurements) / len(dl_measurements), 2
        )
    else:
        result["download_measured_avg"] = None

    if ul_measurements:
        result["upload_measured_avg"] = round(
            sum(m["mbps"] for m in ul_measurements) / len(ul_measurements), 2
        )
    else:
        result["upload_measured_avg"] = None

    # ── Verdict ──
    result["verdict_download"], result["verdict_upload"] = _parse_verdicts(page_texts)

    # ── Campaign dates ──
    m = _RE_CAMPAIGN_START.search(full_text)
    result["campaign_start"] = _convert_date(m.group(1)) if m else None

    m = _RE_CAMPAIGN_END.search(full_text)
    result["campaign_end"] = _convert_date(m.group(1)) if m else None

    log.info(
        "Parsed BNetzA PDF: %s, %s, DL avg=%s, UL avg=%s, verdict=%s/%s",
        result.get("provider", "?"),
        result.get("date", "?"),
        *("n/a" if result[key] is None else result[key] for key in ("download_measured_avg", "upload_measured_avg")),
        result["verdict_download"],
        result["verdict_upload"],
    )

    return result
