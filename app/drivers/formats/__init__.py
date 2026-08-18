"""Pure, explicit modem payload format profiles."""

from __future__ import annotations

from types import MappingProxyType

from .contract import ParseDiagnostic, ParseResult


FORMAT_PROFILE_MODULES = MappingProxyType({
    "arris_html": "app.drivers.formats.html_rows",
    "cgm4981_columnar_html": "app.drivers.formats.html_columnar",
    "ch7465_xml": "app.drivers.formats.xml_payloads",
    "cm1000_html_table": "app.drivers.formats.html_rows",
    "cm1000_javascript": "app.drivers.formats.javascript",
    "cm3000_javascript": "app.drivers.formats.javascript",
    "cm3500_html": "app.drivers.formats.html_rows",
    "f3896lg_rest_json": "app.drivers.formats.sagemcom",
    "fritzbox_data_lua": "app.drivers.formats.fritzbox",
    "generic_no_docsis": "app.drivers.formats.boundaries",
    "hitron_coda4680_json": "app.drivers.formats.hitron",
    "hitron_coda56_json": "app.drivers.formats.hitron",
    "sagemcom_xmo_json": "app.drivers.formats.sagemcom",
    "sb6141_transposed_html": "app.drivers.formats.html_transposed",
    "sb6183_html": "app.drivers.formats.html_rows",
    "sb6190_html": "app.drivers.formats.html_rows",
    "sb8200_cbn_xml": "app.drivers.formats.xml_payloads",
    "sercom_dm1000_json": "app.drivers.formats.sercom",
    "surfboard_hnap": "app.drivers.formats.surfboard",
    "tc4400_html": "app.drivers.formats.html_rows",
    "ultrahub7_json": "app.drivers.formats.vodafone",
    "vodafone_station_cga_json": "app.drivers.formats.vodafone",
    "vodafone_station_tg_embedded_json": "app.drivers.formats.vodafone",
})

__all__ = ["FORMAT_PROFILE_MODULES", "ParseDiagnostic", "ParseResult"]
