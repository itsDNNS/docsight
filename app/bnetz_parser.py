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

# Verdict: "wurde ... festgestellt" or "wurde keine ... festgestellt"
_RE_VERDICT = re.compile(
    r"Abweichung.*?im\s+(Down|Up)load\s+wurde\s+(festgestellt|nicht festgestellt)",
    re.DOTALL,
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
    # Look for verdict on page 2 (overall) and page 3 (per-direction details)
    result["verdict_download"] = "unknown"
    result["verdict_upload"] = "unknown"

    # Check page 3 for per-direction verdicts
    for page_text in page_texts:
        if "Ergebnis der Messkampagne im Download" in page_text:
            if "im Download wurde festgestellt" in page_text:
                result["verdict_download"] = "deviation"
            elif "im Download wurde nicht festgestellt" in page_text or \
                 "im Download nicht festgestellt" in page_text:
                result["verdict_download"] = "ok"
            # Also try: "Abweichung ... im Download wurde ..."
            if "Abweichung" in page_text:
                dl_section = page_text.split("im Download")[0] if "im Upload" in page_text else page_text
                if "wurde festgestellt" in page_text.split("im Download")[-1].split("im Upload")[0] if "im Upload" in page_text else "wurde festgestellt" in page_text:
                    pass  # already handled above

        if "Ergebnis der Messkampagne im Upload" in page_text:
            # Find the upload section
            upload_section = page_text.split("Ergebnis der Messkampagne im Upload")[-1] if "Ergebnis der Messkampagne im Upload" in page_text else ""
            if "im Upload wurde festgestellt" in upload_section or \
               "im Upload wurde festgestellt" in page_text:
                result["verdict_upload"] = "deviation"
            elif "im Upload wurde nicht festgestellt" in upload_section or \
                 "im Upload nicht festgestellt" in page_text:
                result["verdict_upload"] = "ok"

    # Fallback: check overall verdict on page 2
    if result["verdict_download"] == "unknown" or result["verdict_upload"] == "unknown":
        for page_text in page_texts:
            if "Ergebnis" in page_text and "Abweichung" in page_text:
                # Overall verdict (page 2 has a single statement)
                if "wurde eine" in page_text.lower() and "abweichung" in page_text.lower() and "festgestellt" in page_text.lower():
                    if "keine" not in page_text.lower().split("abweichung")[0].split("wurde")[-1]:
                        if result["verdict_download"] == "unknown":
                            result["verdict_download"] = "deviation"
                        if result["verdict_upload"] == "unknown":
                            result["verdict_upload"] = "deviation"
                    else:
                        if result["verdict_download"] == "unknown":
                            result["verdict_download"] = "ok"
                        if result["verdict_upload"] == "unknown":
                            result["verdict_upload"] = "ok"

    # ── Campaign dates ──
    m = _RE_CAMPAIGN_START.search(full_text)
    result["campaign_start"] = _convert_date(m.group(1)) if m else None

    m = _RE_CAMPAIGN_END.search(full_text)
    result["campaign_end"] = _convert_date(m.group(1)) if m else None

    log.info(
        "Parsed BNetzA PDF: %s, %s, DL avg=%.1f, UL avg=%.1f, verdict=%s/%s",
        result.get("provider", "?"),
        result.get("date", "?"),
        result.get("download_measured_avg") or 0,
        result.get("upload_measured_avg") or 0,
        result["verdict_download"],
        result["verdict_upload"],
    )

    return result
