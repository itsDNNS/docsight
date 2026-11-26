"""ThinkBroadband BQM CSV and graph download via public share URLs."""

from app.version import get_app_version
import logging
import re
from urllib.parse import urlparse

import requests


log = logging.getLogger("docsis.bqm.auth")

BASE_URL = "https://www.thinkbroadband.com"
SHARE_PATH = "/broadband/monitoring/quality/share/"
_SHARE_HOSTS = {"thinkbroadband.com", "www.thinkbroadband.com"}
_HEADERS = {"User-Agent": f"DOCSight/{get_app_version()} (+https://github.com/itsDNNS/docsight)"}

# Match share hash from various URL formats
_SHARE_HASH_RE = re.compile(
    rf"(?:https?://www\.thinkbroadband\.com)?(?:{re.escape(SHARE_PATH)})?"
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


def is_share_url(url, csv_only=False):
    """Return True for direct https ThinkBroadband share URLs (only CSV ones with ``csv_only``)."""
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return False
    path = parsed.path or ""
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() in _SHARE_HOSTS
        and path.startswith(SHARE_PATH)
        and (not csv_only or path.endswith(".csv"))
    )


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
            headers={**_HEADERS, "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.8"},
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
        log.warning("ThinkBroadband response is not CSV")
        return ""
    except requests.RequestException as exc:  # the message can carry the URL and its share ID
        log.warning("ThinkBroadband CSV request failed: %s", type(exc).__name__)
        return ""


def validate_share_id(share_id: str) -> bool:
    """Check whether the share ID returns valid CSV data."""
    try:
        csv = fetch_share_csv(share_id, variant="y")
        return bool(csv)
    except ThinkBroadbandBatchAbort:
        return False


def fetch_graph(url, timeout=30):
    """Download a BQM graph PNG. Returns bytes or None on error."""
    if not url:
        return None
    try:
        response = requests.get(url, headers=_HEADERS, timeout=timeout)
    except Exception as e:  # the message can carry the URL and its share ID
        log.error("Failed to fetch BQM graph: %s", type(e).__name__)
        return None
    if response.status_code // 100 != 2:
        log.error("Failed to fetch BQM graph: HTTP %s", response.status_code)
        return None
    data = response.content
    if len(data) < 100:
        log.warning("BQM graph too small (%d bytes), skipping", len(data))
        return None
    log.info("BQM graph fetched (%d bytes)", len(data))
    return data
