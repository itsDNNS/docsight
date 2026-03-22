"""ThinkBroadband BQM CSV download via public share URLs."""

import logging
import re

import requests

from app.web import APP_VERSION

log = logging.getLogger("docsis.bqm.auth")

BASE_URL = "https://www.thinkbroadband.com"
SHARE_PATH = "/broadband/monitoring/quality/share/"

# Match share hash from various URL formats
_SHARE_HASH_RE = re.compile(
    r"(?:https?://www\.thinkbroadband\.com)?(?:/broadband/monitoring/quality/share/)?"
    r"([a-f0-9]{40,}(?:-\d+)?)"
)


class ThinkBroadbandBatchAbort(Exception):
    """Abort the current collection batch and let collector backoff handle retries."""


def extract_share_id(url: str) -> str | None:
    """Extract the share hash from a ThinkBroadband URL or bare hash.

    Accepts:
        - Full share URL (PNG, CSV, XML)
        - Bare share hash with channel suffix (e.g. abc123-2)
    Returns the base hash (without file suffix like .png, -y.csv, -l.csv).
    """
    if not url:
        return None
    # Strip known suffixes
    url = url.strip()
    for suffix in (".png", "-y.csv", "-l.csv", ".csv", ".xml"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    m = _SHARE_HASH_RE.search(url)
    return m.group(1) if m else None


def is_csv_url(url: str) -> bool:
    """Check if the user entered a CSV share URL (vs legacy PNG)."""
    url = (url or "").strip().lower()
    return url.endswith((".csv", ".xml")) or "-y.csv" in url or "-l.csv" in url


def fetch_share_csv(share_id: str, variant: str = "y") -> str:
    """Download CSV from a ThinkBroadband public share URL.

    Args:
        share_id: The share hash (e.g. bd77751689f2f7b8d47d99...-2)
        variant: 'y' for yesterday, 'l' for live 24h
    Returns:
        CSV content as string, or empty string on failure.
    """
    url = f"{BASE_URL}{SHARE_PATH}{share_id}-{variant}.csv"
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": f"DOCSight/{APP_VERSION} (+https://github.com/itsDNNS/docsight)",
                "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.8",
            },
            timeout=30,
        )
        if response.status_code in (403, 429):
            log.warning("ThinkBroadband CSV aborted with HTTP %s", response.status_code)
            raise ThinkBroadbandBatchAbort(f"HTTP {response.status_code}")
        if response.status_code != 200:
            log.warning("ThinkBroadband CSV download failed: HTTP %s", response.status_code)
            return ""
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "csv" in content_type or response.text.startswith('"Timestamp"'):
            return response.text
        log.warning("ThinkBroadband response is not CSV (content-type: %s)", content_type)
        return ""
    except ThinkBroadbandBatchAbort:
        raise
    except requests.RequestException as exc:
        log.warning("ThinkBroadband CSV request failed: %s", exc)
        return ""


def validate_share_id(share_id: str) -> bool:
    """Check whether the share ID returns valid CSV data."""
    try:
        csv = fetch_share_csv(share_id, variant="y")
        return bool(csv)
    except ThinkBroadbandBatchAbort:
        return False
