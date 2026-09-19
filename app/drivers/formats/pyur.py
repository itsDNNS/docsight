"""Pure PYUR /api/v1 profile, distinct from Sagemcom XMO and LG REST."""

from collections import Counter
import re

from ...types import DeviceInfo, DocsisDataFritz, RawChannel
from .contract import ParseResult, diagnostic, docsis_split
from .primitives import parse_optional_finite_float


_NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"


def _integer(value: object) -> int | None:
    # No float conversion: counters above 2**53 must remain exact.
    if type(value) is int:
        return value if 0 <= value < 10**20 else None
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value.strip()):
        return int(value)
    return None


def _measurement(value: object, unit: str) -> float | None:
    if isinstance(value, str):
        if len(value) > 64:
            return None
        match = re.fullmatch(rf"\s*({_NUMBER})\s*(?:{unit})?\s*", value)
        return parse_optional_finite_float(match[1]) if match else None
    return parse_optional_finite_float(value) if type(value) in (int, float) else None


def _frequency(value: object) -> str:
    # Unitless values are undocumented; never infer Hz/MHz from magnitude.
    if not isinstance(value, str) or len(value) > 64:
        return ""
    match = re.fullmatch(rf"\s*({_NUMBER})\s*(MHz|kHz|Hz)\s*", value, re.IGNORECASE)
    if not match:
        return ""
    number = parse_optional_finite_float(match[1])
    if number is None or number < 0:
        return ""
    mhz = number / {"mhz": 1, "khz": 1000, "hz": 1000000}[match[2].lower()]
    return f"{mhz:.12f}".rstrip("0").rstrip(".") + " MHz"


def _modulation(value: object) -> str:
    if not isinstance(value, str) or len(value) > 32:
        return ""
    token = value.strip().upper().replace(" ", "")
    if token in {"OFDM", "OFDMA", "QAM", "QPSK", "ATDMA", "TDMA"}:
        return token
    match = re.fullmatch(r"(?:QAM([0-9]+)|([0-9]+)QAM)", token)
    if match:
        order = match[1] or match[2]
        if order in {"4", "8", "16", "32", "64", "128", "256", "512", "1024", "2048", "4096"}:
            return order + "QAM"
    return ""


def _one_object(payload: object) -> dict:
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ValueError("PYUR expected one object in an array")
    return payload[0]


def parse_pyur_api_v1(payload: object) -> ParseResult[DocsisDataFritz]:
    """Normalize connection channels; ambiguous counter joins stay unknown."""
    data = _one_object(payload)
    downstream, upstream = data.get("Downstreams"), data.get("Upstreams")
    errors = data.get("CMErrorCodewords")
    if errors is None:
        errors = []
    if any(not isinstance(rows, list) or len(rows) > 256 for rows in (downstream, upstream, errors)):
        raise ValueError("PYUR invalid connection channel arrays")

    ds_ids = Counter(_integer(row.get("id")) for row in downstream if isinstance(row, dict))
    error_ids = Counter(_integer(row.get("id")) for row in errors if isinstance(row, dict))
    error_by_id = {
        _integer(row.get("id")): row for row in errors
        if isinstance(row, dict) and _integer(row.get("id")) is not None
        and error_ids[_integer(row.get("id"))] == 1
    }
    ds30, ds31, us30, us31 = [], [], [], []
    diagnostics = []
    for direction, rows, legacy, ofdm in (
        ("downstream", downstream, ds30, ds31), ("upstream", upstream, us30, us31),
    ):
        for index, row in enumerate(rows):
            channel_id = _integer(row.get("ChannelID")) if isinstance(row, dict) else None
            if channel_id is None:
                diagnostics.append(diagnostic("pyur_api_v1", "invalid_channel", family="pyur", direction=direction, index=index, field="ChannelID"))
                continue
            modulation = _modulation(row.get("Modulation"))
            is_ofdm = modulation == ("OFDM" if direction == "downstream" else "OFDMA")
            channel: RawChannel = {
                "channelID": channel_id,
                "frequency": _frequency(row.get("Frequency")),
                "powerLevel": _measurement(row.get("PowerLevel"), "dBmV"),
                "modulation": modulation,
            }
            if is_ofdm:
                channel["type"] = modulation
            if direction == "downstream":
                snr = _measurement(row.get("SNR"), "dB")
                row_id = _integer(row.get("id"))
                counters = error_by_id.get(row_id, {}) if row_id is not None and ds_ids[row_id] == 1 else {}
                channel.update(
                    mer=snr, mse=-snr if snr is not None and not is_ofdm else None,
                    corrErrors=_integer(counters.get("CorrectableCodewords")),
                    nonCorrErrors=_integer(counters.get("UncorrectableCodewords")),
                )
                if not counters:
                    diagnostics.append(diagnostic("pyur_api_v1", "unavailable_counters", family="pyur", direction=direction, index=index))
            elif "SymbolRate" in row:
                channel["symbolRate"] = _integer(row["SymbolRate"])
            (ofdm if is_ofdm else legacy).append(channel)

    if (downstream or upstream) and not (ds30 or ds31 or us30 or us31):
        raise ValueError("PYUR connection contains no valid channels")
    return ParseResult(docsis_split(ds30, ds31, us30, us31), tuple(diagnostics))


def parse_pyur_device_info(payload: object) -> ParseResult[DeviceInfo]:
    """Allowlist model/version/uptime only; never retain subscriber fields."""
    device = _one_object(payload).get("device")
    if not isinstance(device, dict):
        raise ValueError("PYUR invalid device payload")
    info: DeviceInfo = {"manufacturer": "Sagemcom"}
    model = device.get("modelname")
    if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9 ._@()-]{1,128}", model):
        info["model"] = model
    for key in ("running", "main"):
        section = device.get(key)
        version = section.get("version") if isinstance(section, dict) else None
        if isinstance(version, str) and re.fullmatch(r"[A-Za-z0-9 ._()-]{1,128}", version):
            info["sw_version"] = version
            break
    uptime = _integer(device.get("uptime"))
    if uptime is not None:
        info["uptime_seconds"] = uptime
    return ParseResult(info)
