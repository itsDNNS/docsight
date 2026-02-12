"""FritzBox authentication and DOCSIS data retrieval + event log parsing."""

import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET

import requests

log = logging.getLogger("docsis.fritzbox")


def login(url: str, user: str, password: str) -> str:
    """Authenticate to FritzBox and return session ID."""
    r = requests.get(
        f"{url}/login_sid.lua?version=2&username={user}", timeout=10
    )
    r.raise_for_status()
    root = ET.fromstring(r.text)
    challenge = root.find("Challenge").text

    if challenge.startswith("2$"):
        # PBKDF2 (modern FritzOS)
        parts = challenge.split("$")
        iter1, salt1 = int(parts[1]), bytes.fromhex(parts[2])
        iter2, salt2 = int(parts[3]), bytes.fromhex(parts[4])
        hash1 = hashlib.pbkdf2_hmac("sha256", password.encode(), salt1, iter1)
        hash2 = hashlib.pbkdf2_hmac("sha256", hash1, salt2, iter2)
        response = f"{parts[4]}${hash2.hex()}"
    else:
        # MD5 (legacy fallback)
        md5_input = f"{challenge}-{password}".encode("utf-16-le")
        md5_hash = hashlib.md5(md5_input).hexdigest()
        response = f"{challenge}-{md5_hash}"

    r2 = requests.get(
        f"{url}/login_sid.lua?version=2&username={user}&response={response}",
        timeout=10,
    )
    r2.raise_for_status()
    root2 = ET.fromstring(r2.text)
    sid = root2.find("SID").text

    if sid == "0000000000000000":
        raise RuntimeError("FritzBox authentication failed")

    log.info("Auth OK (SID: %s...)", sid[:8])
    return sid


def get_docsis_data(url: str, sid: str) -> dict:
    """Query DOCSIS channel data from FritzBox."""
    r = requests.post(
        f"{url}/data.lua",
        data={
            "xhr": 1,
            "sid": sid,
            "lang": "de",
            "page": "docInfo",
            "xhrId": "all",
            "no_sidrenew": "",
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("data", {})


def get_device_info(url: str, sid: str) -> dict:
    """Try to get FritzBox model info."""
    try:
        r = requests.post(
            f"{url}/data.lua",
            data={
                "xhr": 1,
                "sid": sid,
                "lang": "de",
                "page": "overview",
                "xhrId": "all",
                "no_sidrenew": "",
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data", {})
        fritzos = data.get("fritzos", {})
        result = {
            "model": fritzos.get("Productname", "FRITZ!Box"),
            "sw_version": fritzos.get("nspver", ""),
        }
        uptime = fritzos.get("Uptime")
        if uptime is not None:
            try:
                result["uptime_seconds"] = int(uptime)
            except (ValueError, TypeError):
                pass
        return result
    except Exception:
        return {"model": "FRITZ!Box", "sw_version": ""}


def get_connection_info(url: str, sid: str) -> dict:
    """Get internet connection info (speeds, type) from netMoni page."""
    try:
        r = requests.post(
            f"{url}/data.lua",
            data={
                "xhr": 1,
                "sid": sid,
                "lang": "de",
                "page": "netMoni",
                "xhrId": "all",
                "no_sidrenew": "",
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data", {})
        conns = data.get("connections", [])
        if not conns:
            return {}
        conn = conns[0]
        return {
            "max_downstream_kbps": conn.get("downstream", 0),
            "max_upstream_kbps": conn.get("upstream", 0),
            "connection_type": conn.get("medium", ""),
        }
    except Exception as e:
        log.warning("Failed to get connection info: %s", e)
        return {}


# ── DOCSIS Event Log Constants ──

# Known DOCSIS event codes and their meaning
DOCSIS_EVENT_CODES = {
    "T1": "Ranging Request not acknowledged",
    "T2": "No Ranging Response from CMTS",
    "T3": "No Ranging Response (timeout)",
    "T4": "Registration failed (timeout)",
    "T5": "No Upstream Channel Descriptor",
    "T6": "Registration aborted",
}

# Regex patterns for FritzBox event log entries related to DOCSIS
_DOCSIS_EVENT_PATTERNS = [
    re.compile(r"(T[1-6])\s*(?:Timeout|timeout|Timer)", re.IGNORECASE),
    re.compile(r"(Ranging\s+(?:Request|Abort|Timeout))", re.IGNORECASE),
    re.compile(r"(SYNC\s+(?:Timeout|Loss))", re.IGNORECASE),
    re.compile(r"(No\s+(?:Ranging\s+Response|UCD|MDD))", re.IGNORECASE),
    re.compile(r"(Registration\s+(?:Rejected|Failed|Abort))", re.IGNORECASE),
    re.compile(r"(Cable\s+Modem\s+(?:Reset|Reboot|Restart))", re.IGNORECASE),
    re.compile(r"(DHCP\s+(?:RENEW|NAK|failed))", re.IGNORECASE),
    re.compile(r"(DS\s+Channel\s+(?:Lock|Lost))", re.IGNORECASE),
    re.compile(r"(US\s+Channel\s+(?:Lock|Lost))", re.IGNORECASE),
    # FritzBox-specific German patterns
    re.compile(r"(Zeitüberschreitung)", re.IGNORECASE),
    re.compile(r"(DSL-Synchronisierung)", re.IGNORECASE),
    re.compile(r"(Kabelmodem)", re.IGNORECASE),
    re.compile(r"(Verbindung\s+(?:getrennt|unterbrochen|fehlgeschlagen))", re.IGNORECASE),
]


def get_event_log(url: str, sid: str, max_entries: int = 200) -> list[dict]:
    """Fetch and parse the FritzBox event log, filtering for DOCSIS events.

    Returns list of dicts with:
        timestamp: str (ISO format or raw)
        message: str (event text)
        category: str (docsis_error, connection, info)
        docsis_code: str | None (T1-T6 if detected)
    """
    try:
        # Try system log page
        r = requests.post(
            f"{url}/data.lua",
            data={
                "xhr": 1,
                "sid": sid,
                "lang": "de",
                "page": "log",
                "xhrId": "all",
                "no_sidrenew": "",
                "filter": "all",
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json().get("data", {})
        log_entries = data.get("log", [])

        if not log_entries:
            # Fallback: try query.lua
            r2 = requests.post(
                f"{url}/query.lua",
                data={
                    "sid": sid,
                    "command": "BoxInfoLog",
                    "count": str(max_entries),
                },
                timeout=15,
            )
            r2.raise_for_status()
            log_entries = r2.json() if r2.text.strip().startswith("[") else []

        return _parse_event_log(log_entries, max_entries)

    except Exception as e:
        log.warning("Failed to fetch event log: %s", e)
        return []


def _parse_event_log(entries: list, max_entries: int) -> list[dict]:
    """Parse raw event log entries and filter for DOCSIS-relevant events."""
    results = []

    for entry in entries[:max_entries]:
        # FritzBox log format varies: could be list of [date, time, message, category]
        # or dict with "date", "time", "msg" keys
        if isinstance(entry, list) and len(entry) >= 3:
            date_str = entry[0]
            time_str = entry[1]
            message = entry[2]
            raw_category = entry[3] if len(entry) > 3 else ""
        elif isinstance(entry, dict):
            date_str = entry.get("date", "")
            time_str = entry.get("time", "")
            message = entry.get("msg", entry.get("message", ""))
            raw_category = entry.get("category", entry.get("group", ""))
        else:
            continue

        if not message:
            continue

        # Check if this is a DOCSIS-relevant event
        category = _classify_event(message)
        if not category:
            continue

        # Extract DOCSIS error code if present
        docsis_code = None
        for code in DOCSIS_EVENT_CODES:
            if code in message:
                docsis_code = code
                break

        # Build timestamp
        timestamp = f"{date_str} {time_str}".strip()
        # Try to normalize to ISO format
        timestamp = _normalize_timestamp(timestamp)

        results.append({
            "timestamp": timestamp,
            "message": message.strip(),
            "category": category,
            "docsis_code": docsis_code,
        })

    return results


def _classify_event(message: str) -> str | None:
    """Classify an event log message. Returns category or None if not DOCSIS-related."""
    message_lower = message.lower()

    # DOCSIS error patterns
    for pattern in _DOCSIS_EVENT_PATTERNS:
        if pattern.search(message):
            return "docsis_error"

    # Connection events
    connection_keywords = [
        "internet", "verbindung", "connection", "online", "offline",
        "kabel", "cable", "docsis", "dsl",
    ]
    if any(kw in message_lower for kw in connection_keywords):
        return "connection"

    return None


def _normalize_timestamp(ts: str) -> str:
    """Try to normalize a Fritz timestamp to ISO format."""
    # Common FritzBox format: "01.02.2026 14:30:00"
    match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}:\d{2}(?::\d{2})?)", ts)
    if match:
        day, month, year, time_part = match.groups()
        if ":" in time_part and time_part.count(":") == 1:
            time_part += ":00"
        return f"{year}-{month}-{day}T{time_part}"
    return ts
