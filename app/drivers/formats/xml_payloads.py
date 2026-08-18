"""Pure parsers for the XML channel payloads served by CBN-built modems."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from types import MappingProxyType

from ...types import DocsisDataFritz, RawChannel
from .contract import ParseDiagnostic, ParseResult, diagnostic, docsis_split
from .primitives import hz_to_mhz, normalize_modulation

_XML_FAMILY = "xml_payloads"
_SB8200_PROFILE = "sb8200_cbn_xml"

# The SB8200 is an Annex B (6 MHz) device and its downstream table omits the
# symbol rate. Without these the analyzer falls back to the EuroDOCSIS 8 MHz
# default and every downstream capacity estimate reads ~30% high.
_SB8200_ANNEX_B_DS_SYMBOL_RATES = MappingProxyType({"64QAM": 5057, "256QAM": 5361})


def _text(node: ET.Element | None, default: str = "") -> str:
    return node.text if node is not None and node.text is not None else default


def parse_ch7465_xml(
    downstream_xml: str | None,
    upstream_xml: str | None,
) -> ParseResult[dict | None]:
    if downstream_xml is None or upstream_xml is None:
        return ParseResult(None, (diagnostic(
            "ch7465_xml", "invalid_xml", family="xml_payloads",
        ),))
    try:
        downstream_root = ET.fromstring(downstream_xml)
        upstream_root = ET.fromstring(upstream_xml)
    except ET.ParseError:
        return ParseResult(None, (diagnostic(
            "ch7465_xml", "invalid_xml", family="xml_payloads",
        ),))

    downstream: list[RawChannel] = []
    upstream: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, channel in enumerate(downstream_root.findall("downstream")):
        try:
            item: RawChannel = {
                "channelID": int(channel.find("chid").text),
                "frequency": _text(channel.find("freq")),
                "powerLevel": float(_text(channel.find("pow"), "0")),
            }
            mer = _text(channel.find("RxMER"))
            modulation = normalize_modulation(_text(channel.find("mod")))
            corrected = _text(channel.find("PreRs"))
            uncorrected = _text(channel.find("PostRs"))
            if mer:
                item["mer"] = float(mer)
                item["mse"] = -float(mer)
            if modulation:
                item["modulation"] = modulation
            if corrected:
                item["corrErrors"] = int(corrected)
            if uncorrected:
                item["nonCorrErrors"] = int(uncorrected)
            downstream.append(item)
        except (AttributeError, TypeError, ValueError):
            diagnostics.append(diagnostic(
                "ch7465_xml", "invalid_channel", family="xml_payloads",
                direction="downstream", index=index,
            ))

    for index, channel in enumerate(upstream_root.findall("upstream")):
        try:
            item = {
                "channelID": int(channel.find("usid").text),
                "frequency": _text(channel.find("freq")),
                "powerLevel": float(_text(channel.find("power"), "0")),
            }
            modulation = normalize_modulation(_text(channel.find("mod")))
            message_type = _text(channel.find("messageType"))
            multiplex = {"2": "tdma", "29": "atdma", "35": "atdma"}.get(
                message_type, message_type
            )
            if modulation:
                item["modulation"] = modulation
            if multiplex:
                item["multiplex"] = multiplex
            upstream.append(item)
        except (AttributeError, TypeError, ValueError):
            diagnostics.append(diagnostic(
                "ch7465_xml", "invalid_channel", family="xml_payloads",
                direction="upstream", index=index,
            ))

    return ParseResult(
        {"docsis": "3.0", "downstream": downstream, "upstream": upstream},
        tuple(diagnostics),
    )


def _optional_int(value: str) -> int | None:
    """Parse an optional counter, keeping a missing value distinct from zero."""
    try:
        return int(value.strip())
    except (AttributeError, ValueError):
        return None


def _optional_float(value: str) -> float | None:
    """Parse an optional measurement, keeping a missing value distinct from zero."""
    try:
        return float(value.strip())
    except (AttributeError, ValueError):
        return None


def _sb8200_root(payload: str | None) -> ET.Element | None:
    """Return the parsed table root, or None for an absent or malformed table."""
    if not payload:
        return None
    try:
        return ET.fromstring(payload)
    except ET.ParseError:
        return None


def _sb8200_issue(
    code: str,
    *,
    direction: str | None = None,
    index: int | None = None,
    field: str | None = None,
) -> ParseDiagnostic:
    return diagnostic(
        _SB8200_PROFILE, code, family=_XML_FAMILY,
        direction=direction, index=index, field=field,
    )


def _sb8200_error_counters(
    root: ET.Element,
) -> tuple[dict[int, tuple[int | None, int | None]], list[ParseDiagnostic]]:
    """Index the separate codeword table that both downstream lanes join on.

    The SB8200 reports codeword counts in their own table keyed by ``dsid``,
    which matches the SC-QAM ``chid`` and the OFDM ``dsid``.
    """
    counters: dict[int, tuple[int | None, int | None]] = {}
    diagnostics: list[ParseDiagnostic] = []
    for index, entry in enumerate(root.findall("signal")):
        dsid = _optional_int(_text(entry.find("dsid")))
        if dsid is None:
            diagnostics.append(_sb8200_issue(
                "invalid_row", direction="downstream", index=index, field="dsid",
            ))
            continue
        counters[dsid] = (
            _optional_int(_text(entry.find("correctable"))),
            _optional_int(_text(entry.find("uncorrectable"))),
        )
    return counters, diagnostics


def _sb8200_locked(channel: ET.Element, field: str) -> bool:
    """Treat only an explicit unlocked marker as unlocked."""
    return _text(channel.find(field)).strip() in ("", "1")


def _sb8200_ofdm_locked(channel: ET.Element) -> bool:
    """Report OFDM lock from the explicit flags, falling back to the PLC state."""
    active = _text(channel.find("ofdmIsActive")).strip()
    if active and active != "1":
        return False
    locked = _text(channel.find("ofdmIsLocked")).strip()
    if locked:
        return locked == "1"
    return _text(channel.find("PLCLocked")).strip().upper() == "YES"


def _sb8200_downstream_scqam(
    root: ET.Element,
    counters: dict[int, tuple[int | None, int | None]],
) -> tuple[list[RawChannel], list[ParseDiagnostic]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, entry in enumerate(root.findall("downstream")):
        if not _sb8200_locked(entry, "IsLocked"):
            continue
        channel_id = _optional_int(_text(entry.find("chid")))
        power = _optional_float(_text(entry.find("pow")))
        if channel_id is None or power is None:
            diagnostics.append(_sb8200_issue(
                "invalid_channel", direction="downstream", index=index,
            ))
            continue
        channel: RawChannel = {
            "channelID": channel_id,
            "frequency": hz_to_mhz(_text(entry.find("freq"))),
            "powerLevel": power,
        }
        snr = _optional_float(_text(entry.find("snr")))
        if snr is not None:
            channel["mer"] = snr
            channel["mse"] = -snr
        modulation = normalize_modulation(_text(entry.find("mod")))
        if modulation:
            channel["modulation"] = modulation
            symbol_rate = _SB8200_ANNEX_B_DS_SYMBOL_RATES.get(modulation)
            if symbol_rate is not None:
                channel["symbolRate"] = symbol_rate
        corrected, uncorrected = counters.get(channel_id, (None, None))
        if corrected is not None:
            channel["corrErrors"] = corrected
        if uncorrected is not None:
            channel["nonCorrErrors"] = uncorrected
        channels.append(channel)
    return channels, diagnostics


def _sb8200_downstream_ofdm(
    root: ET.Element,
) -> tuple[list[RawChannel], list[ParseDiagnostic]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, entry in enumerate(root.findall("downstream")):
        if not _sb8200_ofdm_locked(entry):
            continue
        channel_id = _optional_int(_text(entry.find("dsid")))
        power = _optional_float(_text(entry.find("PLCPower")))
        if channel_id is None or power is None:
            diagnostics.append(_sb8200_issue(
                "invalid_channel", direction="downstream", index=index,
            ))
            continue
        channel: RawChannel = {
            "channelID": channel_id,
            "type": "OFDM",
            "frequency": hz_to_mhz(_text(entry.find("Subcarr0Frequency"))),
            "powerLevel": power,
            "mse": None,
        }
        mer = _optional_float(_text(entry.find("DataScAvgMer")))
        if mer is not None:
            channel["mer"] = mer
        modulation = normalize_modulation(_text(entry.find("ofdmModulation")))
        if modulation:
            channel["modulation"] = modulation
        # The OFDM codeword counters this firmware reports are not comparable
        # to the SC-QAM ones. Measured on a locked 4096QAM channel at 33 dB
        # MER they climb by roughly 1.3 million uncorrectables per minute
        # while the entire SC-QAM cohort adds 0-1, uncorrectables exceed
        # correctables, and the modem's own codeword table reports zero for
        # the same dsid. Reporting them as measured codewords pins downstream
        # health at critical, so the lane is left counter-unsupported instead.
        if _text(entry.find("ofdmCorrected")) or _text(entry.find("ofdmUncorrectable")):
            diagnostics.append(_sb8200_issue(
                "unsupported_counters", direction="downstream", index=index,
                field="ofdm_codewords",
            ))
        channels.append(channel)
    return channels, diagnostics


def _sb8200_upstream_scqam(
    root: ET.Element,
) -> tuple[list[RawChannel], list[ParseDiagnostic]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, entry in enumerate(root.findall("upstream")):
        if not _sb8200_locked(entry, "usLocked"):
            continue
        channel_id = _optional_int(_text(entry.find("usid")))
        power = _optional_float(_text(entry.find("power")))
        if channel_id is None or power is None:
            diagnostics.append(_sb8200_issue(
                "invalid_channel", direction="upstream", index=index,
            ))
            continue
        channel: RawChannel = {
            "channelID": channel_id,
            "frequency": hz_to_mhz(_text(entry.find("freq"))),
            "powerLevel": power,
        }
        modulation = normalize_modulation(_text(entry.find("mod")))
        if modulation:
            channel["modulation"] = modulation
        multiplex = _text(entry.find("channeltype")).strip().upper()
        if multiplex:
            channel["type"] = multiplex
            channel["multiplex"] = multiplex
        symbol_rate = _optional_float(_text(entry.find("srate")))
        if symbol_rate is not None:
            channel["symbolRate"] = int(round(symbol_rate * 1000))
        channels.append(channel)
    return channels, diagnostics


def _sb8200_ofdma_present(root: ET.Element) -> bool:
    """Report whether the modem claims an active OFDMA upstream lane."""
    if root.findall("upstream"):
        return True
    return bool(_optional_int(_text(root.find("us_num"))))


def parse_sb8200_cbn_xml(
    downstream_xml: str | None,
    upstream_xml: str | None,
    downstream_ofdm_xml: str | None,
    upstream_ofdma_xml: str | None,
    signal_xml: str | None,
) -> ParseResult[DocsisDataFritz | None]:
    """Normalize the five CBN XML tables an SB8200 serves for DOCSIS status.

    The downstream and upstream SC-QAM tables are required. The OFDM, OFDMA,
    and codeword tables enrich the result and degrade to a diagnostic so a
    partially reachable modem still reports the channels it did return.
    """
    downstream_root = _sb8200_root(downstream_xml)
    upstream_root = _sb8200_root(upstream_xml)
    if downstream_root is None or upstream_root is None:
        return ParseResult(None, (_sb8200_issue("invalid_xml"),))

    diagnostics: list[ParseDiagnostic] = []

    counters: dict[int, tuple[int | None, int | None]] = {}
    signal_root = _sb8200_root(signal_xml)
    if signal_root is None:
        if signal_xml:
            diagnostics.append(_sb8200_issue(
                "invalid_xml", direction="downstream", field="signal_table",
            ))
    else:
        counters, counter_issues = _sb8200_error_counters(signal_root)
        diagnostics.extend(counter_issues)

    ds30, ds30_issues = _sb8200_downstream_scqam(downstream_root, counters)
    diagnostics.extend(ds30_issues)

    ds31: list[RawChannel] = []
    ofdm_root = _sb8200_root(downstream_ofdm_xml)
    if ofdm_root is None:
        if downstream_ofdm_xml:
            diagnostics.append(_sb8200_issue(
                "invalid_xml", direction="downstream", field="ofdm_table",
            ))
    else:
        ds31, ds31_issues = _sb8200_downstream_ofdm(ofdm_root)
        diagnostics.extend(ds31_issues)

    us30, us30_issues = _sb8200_upstream_scqam(upstream_root)
    diagnostics.extend(us30_issues)

    # The observed firmware reports us_num=0 and no OFDMA rows. The lane is
    # reported as unsupported rather than guessed from field names that no
    # captured payload has ever shown.
    ofdma_root = _sb8200_root(upstream_ofdma_xml)
    if ofdma_root is None:
        if upstream_ofdma_xml:
            diagnostics.append(_sb8200_issue(
                "invalid_xml", direction="upstream", field="ofdma_table",
            ))
    elif _sb8200_ofdma_present(ofdma_root):
        diagnostics.append(_sb8200_issue(
            "unsupported_lane", direction="upstream", field="ofdma_table",
        ))

    return ParseResult(docsis_split(ds30, ds31, us30, []), tuple(diagnostics))
