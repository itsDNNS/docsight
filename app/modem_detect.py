"""Opt-in detection of a modem on the local network during setup.

Only runs when the user asks for it. It sends one short GET request to each
of a few fixed private addresses that cable modems and routers commonly use,
reads the start page and looks for model names of the built-in drivers. It
never logs in, sends no credentials and nothing leaves the local network.
"""

from __future__ import annotations

import html
import re
import warnings
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3

CANDIDATE_HOSTS = ("192.168.100.1", "192.168.0.1", "192.168.178.1", "10.0.0.1")
PROBE_TIMEOUT_SECONDS = 2.0
MAX_BODY_BYTES = 64 * 1024

# Model names as they appear on start pages. A match is a suggestion the user
# confirms; several matches (e.g. the SURFboard family) are all offered.
DRIVER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fritzbox": ("fritz!box",),
    "cm3500": ("cm3500",),
    "surfboard": ("sb8200", "surfboard s33", "surfboard s34"),
    "sb8200_cbn": ("sb8200",),
    "sb6141": ("sb6141",),
    "sb6183": ("sb6183",),
    "sb6190": ("sb6190",),
    "cm8200": ("cm8200",),
    "cm1000": ("cm1000",),
    "cm3000": ("cm3000",),
    "tc4400": ("tc4400",),
    "ch7465": ("ch7465", "connect box"),
    "ch7465_play": ("ch7465",),
    "hitron": ("coda-56", "coda56"),
    "hitron_coda_4680": ("coda-4680", "coda4680"),
    "f3896lg": ("f3896lg", "hub 5"),
    "sagemcom": ("f@st 3896", "f@st3896"),
    "pyur_fast3896": ("fast3896",),
    "sercom_dm1000": ("dm1000",),
    "cgm4981": ("cgm4981",),
    "vodafone_station": ("vodafone station",),
    "ultrahub7": ("ultra hub 7", "ultrahub"),
}

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def _searchable_text(body: str) -> str:
    """Visible text plus the title, lower-cased with collapsed whitespace."""
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", body))).strip().lower()


def match_drivers(body: str, known_drivers=None) -> list[str]:
    """Driver keys whose model names appear on a start page."""
    text = _searchable_text(body or "")
    return [
        key for key, keywords in DRIVER_KEYWORDS.items()
        if (known_drivers is None or key in known_drivers)
        and any(keyword in text for keyword in keywords)
    ]


def _read_start_page(url: str, get) -> str | None:
    try:
        with get(url, timeout=PROBE_TIMEOUT_SECONDS, verify=False, stream=True,
                 allow_redirects=True) as response:
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=8192):
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_BODY_BYTES:
                    break
            raw = b"".join(chunks)[:MAX_BODY_BYTES]
            return raw.decode(response.encoding or "utf-8", errors="replace")
    except requests.RequestException:
        return None


def probe_host(host: str, get=requests.get, known_drivers=None) -> dict | None:
    """Ask one address for its start page; HTTPS is tried when HTTP fails."""
    for scheme in ("http", "https"):
        url = f"{scheme}://{host}"
        body = _read_start_page(url, get)
        if body is not None:
            return {"host": host, "url": url, "drivers": match_drivers(body, known_drivers)}
    return None


def detect_modems(get=requests.get, known_drivers=None) -> list[dict]:
    """Probe all candidate addresses in parallel; answering devices in address order."""
    # Modems use self-signed certificates; nothing is sent that would need protecting.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
        with ThreadPoolExecutor(max_workers=len(CANDIDATE_HOSTS)) as pool:
            results = list(pool.map(lambda host: probe_host(host, get, known_drivers), CANDIDATE_HOSTS))
    return [result for result in results if result]
