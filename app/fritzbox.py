"""FritzBox authentication and DOCSIS data retrieval."""

import hashlib
import json
import logging
import xml.etree.ElementTree as ET

import requests

log = logging.getLogger("docsis.fritzbox")
_TR064_NS = {"tr64": "urn:dslforum-org:device-1-0"}


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


def _parse_fritzos_device_info(data: dict) -> dict:
    """Extract model/version/uptime from a FritzBox fritzos object."""
    fritzos = data.get("fritzos", {})
    if not fritzos:
        return {}

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
    for page in ("home", "boxinfo", "overview"):
        try:
            result = _parse_fritzos_device_info(_get_data_page(url, sid, page))
            if result:
                return result
        except Exception as e:
            log.debug("FritzBox %s device info unavailable: %s", page, e)

    try:
        r = requests.get(f"{url}/tr064/tr64desc.xml", timeout=10)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        model = (
            root.findtext(".//tr64:modelName", namespaces=_TR064_NS)
            or root.findtext(".//tr64:modelDescription", namespaces=_TR064_NS)
            or root.findtext(".//tr64:friendlyName", namespaces=_TR064_NS)
            or "FRITZ!Box"
        )
        sw_version = root.findtext(".//tr64:systemVersion/tr64:Display", namespaces=_TR064_NS) or ""
        return {"model": model, "sw_version": sw_version}
    except Exception as e:
        log.debug("FritzBox TR-064 device info fallback unavailable: %s", e)
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
