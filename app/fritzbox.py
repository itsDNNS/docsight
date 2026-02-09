"""FritzBox authentication and DOCSIS data retrieval."""

import hashlib
import json
import logging
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
        return {
            "model": fritzos.get("Productname", "FRITZ!Box"),
            "sw_version": fritzos.get("nspver", ""),
        }
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
