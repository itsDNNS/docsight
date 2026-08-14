"""Pure parser for the Compal CH7465 downstream/upstream XML profile."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ...types import RawChannel
from .contract import ParseDiagnostic, ParseResult, diagnostic
from .primitives import normalize_modulation


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
