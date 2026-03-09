"""FritzBox authentication and DOCSIS data retrieval."""

import hashlib
import json
import logging
import xml.etree.ElementTree as ET

import requests

log = logging.getLogger("docsis.fritzbox")


def _get_data_page(url: str, sid: str, page: str) -> dict:
    """Fetch a FritzBox data.lua page and return its data payload."""
    r = requests.post(
        f"{url}/data.lua",
        data={
            "xhr": 1,
            "sid": sid,
            "lang": "de",
            "page": page,
            "xhrId": "all",
            "no_sidrenew": "",
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("data", {})


def _find_detail_value(details: list[dict], label: str) -> str:
    """Return the value for a labeled FritzBox detail row."""
    for item in details or []:
        if item.get("text") == label:
            return item.get("value", "")
    return ""


def _safe_int_list(values) -> list[int]:
    """Convert an arbitrary list of values to integers, dropping invalid items."""
    result = []
    for value in values or []:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _merge_series(*series_lists: list[int]) -> list[int]:
    """Sum equally-sized series element-wise, tolerating missing values."""
    width = max((len(series) for series in series_lists), default=0)
    merged = []
    for idx in range(width):
        total = 0
        for series in series_lists:
            if idx < len(series):
                total += series[idx]
        merged.append(total)
    return merged


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
    return _get_data_page(url, sid, "docInfo")


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
        data = _get_data_page(url, sid, "netMoni")
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


def get_cable_utilization(url: str, sid: str) -> dict:
    """Return FRITZ!Box cable utilization data for the cable overview UI."""
    doc_ov = _get_data_page(url, sid, "docOv")
    net_moni = _get_data_page(url, sid, "netMoni")

    connection = doc_ov.get("connectionData", {})
    info_middle = connection.get("infoMiddle", {})
    info_left = connection.get("infoLeft", {})
    line = (connection.get("line") or [{}])[0]
    details = info_middle.get("details", [])
    chart = info_middle.get("chartData", {})
    sync_group = (net_moni.get("sync_groups") or [{}])[0]

    upstream_series = _merge_series(
        _safe_int_list(sync_group.get("us_realtime_bps_curr")),
        _safe_int_list(sync_group.get("us_background_bps_curr")),
        _safe_int_list(sync_group.get("us_important_bps_curr")),
        _safe_int_list(sync_group.get("us_default_bps_curr")),
    )
    downstream_series = _safe_int_list(sync_group.get("ds_bps_curr"))

    return {
        "supported": True,
        "model": connection.get("modell", "FRITZ!Box"),
        "connection_type": connection.get("connectionType", "cable"),
        "status": line.get("trainState") or _find_detail_value(details, "Kabel-Internet:"),
        "state": line.get("state", ""),
        "mode": line.get("mode") or _find_detail_value(details, "Verbindungstyp:"),
        "duration": line.get("time") or _find_detail_value(details, "Verbindungsdauer:"),
        "downstream_rate": connection.get("dsRate", ""),
        "upstream_rate": connection.get("usRate", ""),
        "docsis_software_version": _find_detail_value(info_left.get("details", []), "DOCSIS-Software-Version:"),
        "cm_mac": _find_detail_value(info_left.get("details", []), "CM MAC-Adresse:"),
        "channel_counts": {
            "downstream": ((info_middle.get("upDownInfos", {}).get("details") or [{}])[0]).get("dsValue"),
            "upstream": ((info_middle.get("upDownInfos", {}).get("details") or [{}])[0]).get("usValue"),
        },
        "sampling_interval_seconds": int((net_moni.get("sampling_interval") or 5000) / 1000),
        "downstream": {
            "title": chart.get("title", "Nutzung der Kabel-Verbindung"),
            "subtitle": chart.get("subtitle", ""),
            "samples_bps": downstream_series,
            "current_bps": downstream_series[-1] if downstream_series else 0,
            "peak_bps": sync_group.get("ds_bps_curr_max", 0),
            "window_max_bps": sync_group.get("ds_bps_max", chart.get("max", 0)),
        },
        "upstream": {
            "title": "Nutzung der Kabel-Verbindung",
            "subtitle": "im Upstream",
            "samples_bps": upstream_series,
            "current_bps": upstream_series[-1] if upstream_series else 0,
            "peak_bps": sync_group.get("us_bps_curr_max", 0),
            "window_max_bps": sync_group.get("us_bps_max", 0),
        },
    }
