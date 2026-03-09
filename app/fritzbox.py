"""FritzBox authentication and DOCSIS data retrieval."""

import hashlib
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


def _get_rest_endpoint(url: str, sid: str, path: str) -> dict:
    """Fetch a FritzBox /api/v0 endpoint using AVM's SID header format."""
    r = requests.get(
        f"{url}/api/v0/{path.lstrip('/')}",
        headers={
            "Accept": "application/json",
            "Authorization": f"AVM-SID {sid}",
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _iter_candidate_dicts(data: dict) -> list[dict]:
    """Return nested dict candidates so parsers can tolerate schema drift."""
    candidates = [data]
    for key in ("data", "box", "connection", "connections"):
        value = data.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    return candidates


def _parse_generic_box_info(data: dict) -> dict:
    """Extract model/version/uptime from a generic /api/v0/box response."""
    model_keys = ("model", "productName", "Productname", "name", "deviceName")
    version_keys = ("sw_version", "firmwareVersion", "version", "nspver")
    uptime_keys = ("uptime_seconds", "uptime", "uptimeSeconds", "Uptime")

    for candidate in _iter_candidate_dicts(data):
        result = {}

        for key in model_keys:
            value = candidate.get(key)
            if value:
                result["model"] = value
                break

        for key in version_keys:
            value = candidate.get(key)
            if value:
                result["sw_version"] = value
                break

        for key in uptime_keys:
            value = candidate.get(key)
            if value is not None:
                try:
                    result["uptime_seconds"] = int(value)
                except (ValueError, TypeError):
                    pass
                break

        if result:
            return result

    return {}


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
            result.append(int(round(float(value))))
        except (TypeError, ValueError):
            continue
    return result


def _find_first_list(data: dict, keys: tuple[str, ...]) -> list:
    """Return the first list-like value found in the given key set."""
    for candidate in _iter_candidate_dicts(data):
        for key in keys:
            value = candidate.get(key)
            if isinstance(value, list):
                return value
    return []


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


def _parse_segment_subsets(data: dict) -> list[dict]:
    """Extract available segment time ranges from /monitor/segment/subsets."""
    raw_subsets = _find_first_list(data, ("subsets", "segmentSubsets", "ranges", "data"))
    subsets = []
    for idx, item in enumerate(raw_subsets):
        if not isinstance(item, dict):
            continue
        subset_id = item.get("id")
        if subset_id is None:
            subset_id = item.get("subset")
        if subset_id is None:
            subset_id = idx
        label = (
            item.get("label")
            or item.get("name")
            or item.get("title")
            or item.get("text")
            or str(subset_id)
        )
        subsets.append({"id": int(subset_id), "label": str(label)})
    return subsets


def _extract_series_from_series_list(series_list: list) -> dict[str, list[int]]:
    """Map named series entries to normalized numeric samples."""
    result = {}
    for item in series_list or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("id") or item.get("key") or "").lower()
        samples = item.get("samples")
        if samples is None:
            samples = item.get("values")
        if samples is None:
            samples = item.get("data")
        if name and isinstance(samples, list):
            result[name] = _safe_int_list(samples)
    return result


def _extract_segment_direction(payload: dict, prefix: str) -> dict:
    """Extract total/own-share series for one traffic direction."""
    direction = payload.get(prefix)
    if isinstance(direction, dict):
        total = _safe_int_list(
            direction.get("total")
            or direction.get("values")
            or direction.get("samples")
            or direction.get("data")
        )
        own = _safe_int_list(
            direction.get("own")
            or direction.get("ownShare")
            or direction.get("self")
            or direction.get("own_share")
        )
        series_map = _extract_series_from_series_list(direction.get("series", []))
        if not total:
            total = series_map.get("total") or series_map.get("segment") or series_map.get("load") or []
        if not own:
            own = (
                series_map.get("own")
                or series_map.get("ownshare")
                or series_map.get("self")
                or series_map.get("share")
                or []
            )
        title = direction.get("title") or ("Downstream" if prefix == "downstream" else "Upstream")
        subtitle = direction.get("subtitle") or ""
        return {"total": total, "own": own, "title": title, "subtitle": subtitle}

    total = _safe_int_list(
        payload.get(f"{prefix}_total")
        or payload.get(f"{prefix}Total")
        or payload.get(f"{prefix}_load")
    )
    own = _safe_int_list(
        payload.get(f"{prefix}_own")
        or payload.get(f"{prefix}Own")
        or payload.get(f"{prefix}_share")
        or payload.get(f"{prefix}OwnShare")
    )
    if not total or not own:
        series_map = _extract_series_from_series_list(payload.get("series", []))
        if prefix == "downstream":
            total = total or series_map.get("ds_total") or series_map.get("downstream_total") or []
            own = own or series_map.get("ds_own") or series_map.get("downstream_own") or []
        else:
            total = total or series_map.get("us_total") or series_map.get("upstream_total") or []
            own = own or series_map.get("us_own") or series_map.get("upstream_own") or []

    return {
        "total": total,
        "own": own,
        "title": "Downstream" if prefix == "downstream" else "Upstream",
        "subtitle": "",
    }


def _build_segment_direction_payload(direction: dict) -> dict:
    """Normalize a segment direction into the UI payload shape."""
    total = direction["total"]
    own = direction["own"]
    current_total = total[-1] if total else 0
    current_own = own[-1] if own else 0
    peak_total = max(total) if total else 0
    return {
        "title": direction["title"],
        "subtitle": direction["subtitle"],
        "samples_percent": total,
        "own_samples_percent": own,
        "current_percent": current_total,
        "peak_percent": peak_total,
        "current_own_percent": current_own,
    }


def _get_segment_snapshot(url: str, sid: str, subset_id: int) -> dict:
    """Fetch a single segment utilization dataset."""
    payload = _get_rest_endpoint(url, sid, f"monitor/segment/{subset_id}")
    if isinstance(payload.get("data"), dict):
        payload = payload["data"]

    downstream = _extract_segment_direction(payload, "downstream")
    upstream = _extract_segment_direction(payload, "upstream")
    if not downstream["total"] and not upstream["total"]:
        raise RuntimeError(f"Segment subset {subset_id} did not include utilization series")

    return {
        "subset_id": subset_id,
        "downstream": _build_segment_direction_payload(downstream),
        "upstream": _build_segment_direction_payload(upstream),
    }


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
    r = requests.get(f"{url}/login_sid.lua?version=2&username={user}", timeout=10)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    challenge = root.find("Challenge").text

    if challenge.startswith("2$"):
        parts = challenge.split("$")
        iter1, salt1 = int(parts[1]), bytes.fromhex(parts[2])
        iter2, salt2 = int(parts[3]), bytes.fromhex(parts[4])
        hash1 = hashlib.pbkdf2_hmac("sha256", password.encode(), salt1, iter1)
        hash2 = hashlib.pbkdf2_hmac("sha256", hash1, salt2, iter2)
        response = f"{parts[4]}${hash2.hex()}"
    else:
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
        result = _parse_generic_box_info(_get_rest_endpoint(url, sid, "generic/box"))
        if result:
            return result
    except Exception as e:
        log.debug("FritzBox REST device info unavailable: %s", e)

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
    """Get internet connection info from REST API or netMoni fallback."""
    try:
        data = _get_rest_endpoint(url, sid, "generic/connections")
        if isinstance(data.get("connections"), list) and data["connections"]:
            conn = data["connections"][0]
        elif (
            isinstance(data.get("data"), dict)
            and isinstance(data["data"].get("connections"), list)
            and data["data"]["connections"]
        ):
            conn = data["data"]["connections"][0]
        else:
            conn = data

        result = {}
        if conn.get("downstream") is not None:
            result["max_downstream_kbps"] = conn.get("downstream", 0)
        if conn.get("upstream") is not None:
            result["max_upstream_kbps"] = conn.get("upstream", 0)
        medium = conn.get("medium") or conn.get("type") or conn.get("connectionType")
        if medium:
            result["connection_type"] = medium
        if result:
            return result
    except Exception as e:
        log.debug("FritzBox REST connection info unavailable: %s", e)

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
    """Return cable utilization with REST-first segment data and legacy fallback."""
    device_info = get_device_info(url, sid)
    connection_info = get_connection_info(url, sid)

    try:
        subset_data = _get_rest_endpoint(url, sid, "monitor/segment/subsets")
        subsets = _parse_segment_subsets(subset_data)
        if not subsets:
            subsets = [{"id": idx, "label": f"Range {idx + 1}"} for idx in range(5)]

        selected_subset = subsets[0]
        snapshot = _get_segment_snapshot(url, sid, int(selected_subset["id"]))
        return {
            "supported": True,
            "source": "api_v0",
            "model": device_info.get("model", "FRITZ!Box"),
            "connection_type": connection_info.get("connection_type", "cable"),
            "status": "active",
            "state": "ready",
            "mode": "Segment utilization",
            "duration": selected_subset["label"],
            "downstream_rate": "",
            "upstream_rate": "",
            "docsis_software_version": device_info.get("sw_version", ""),
            "cm_mac": "",
            "channel_counts": {"downstream": None, "upstream": None},
            "sampling_interval_seconds": 0,
            "available_ranges": subsets,
            "selected_range": selected_subset,
            "downstream": snapshot["downstream"],
            "upstream": snapshot["upstream"],
        }
    except Exception as e:
        log.debug("FritzBox REST cable utilization unavailable: %s", e)

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
        "source": "legacy",
        "model": connection.get("modell", device_info.get("model", "FRITZ!Box")),
        "connection_type": connection.get("connectionType", connection_info.get("connection_type", "cable")),
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
        "available_ranges": [],
        "selected_range": None,
        "downstream": {
            "title": chart.get("title", "Cable connection usage"),
            "subtitle": chart.get("subtitle", ""),
            "samples_bps": downstream_series,
            "current_bps": downstream_series[-1] if downstream_series else 0,
            "peak_bps": sync_group.get("ds_bps_curr_max", 0),
            "window_max_bps": sync_group.get("ds_bps_max", chart.get("max", 0)),
        },
        "upstream": {
            "title": "Cable connection usage",
            "subtitle": "Upstream",
            "samples_bps": upstream_series,
            "current_bps": upstream_series[-1] if upstream_series else 0,
            "peak_bps": sync_group.get("us_bps_curr_max", 0),
            "window_max_bps": sync_group.get("us_bps_max", 0),
        },
    }
