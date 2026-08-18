"""Representative RED contract for the future parser extraction."""

from __future__ import annotations

import importlib
import importlib.util

from app.drivers import driver_registry


EXPECTED_REGISTRY_KEYS = {
    "cgm4981",
    "ch7465",
    "ch7465_play",
    "cm1000",
    "cm3000",
    "cm3500",
    "cm8200",
    "f3896lg",
    "fritzbox",
    "generic",
    "hitron",
    "hitron_coda_4680",
    "sagemcom",
    "sb6141",
    "sb6183",
    "sb6190",
    "sb8200_cbn",
    "sercom_dm1000",
    "surfboard",
    "tc4400",
    "ultrahub7",
    "vodafone_station",
}

EXPECTED_CLASS_FAMILIES = {
    "app.drivers.cgm4981.CGM4981Driver": ("cgm4981_columnar_html",),
    "app.drivers.ch7465.CH7465Driver": ("ch7465_xml",),
    "app.drivers.cm1000.CM1000Driver": ("cm1000_html_table", "cm1000_javascript"),
    "app.drivers.cm3000.CM3000Driver": ("cm3000_javascript",),
    "app.drivers.cm3500.CM3500Driver": ("cm3500_html",),
    "app.drivers.cm8200.CM8200Driver": ("arris_html",),
    "app.drivers.f3896lg.F3896LGDriver": ("f3896lg_rest_json",),
    "app.drivers.fritzbox.FritzBoxDriver": ("fritzbox_data_lua",),
    "app.drivers.generic.GenericDriver": ("generic_no_docsis",),
    "app.drivers.hitron.HitronDriver": ("hitron_coda56_json",),
    "app.drivers.hitron_coda_4680.HitronCoda4680Driver": ("hitron_coda4680_json",),
    "app.drivers.sagemcom.SagemcomDriver": ("sagemcom_xmo_json",),
    "app.drivers.sb6141.SB6141Driver": ("sb6141_transposed_html",),
    "app.drivers.sb6183.SB6183Driver": ("sb6183_html",),
    "app.drivers.sb6190.SB6190Driver": ("sb6190_html",),
    "app.drivers.sb8200_cbn.SB8200CBNDriver": ("sb8200_cbn_xml",),
    "app.drivers.sercom_dm1000.SercomDM1000Driver": ("sercom_dm1000_json",),
    "app.drivers.surfboard.SurfboardDriver": ("arris_html", "surfboard_hnap"),
    "app.drivers.tc4400.TC4400Driver": ("tc4400_html",),
    "app.drivers.ultrahub7.UltraHub7Driver": ("ultrahub7_json",),
    "app.drivers.vodafone_station.VodafoneStationDriver": (
        "vodafone_station_cga_json",
        "vodafone_station_tg_embedded_json",
    ),
}

# Profiles remain explicit while cohesive modules own related grammars. This
# prevents a one-file-per-device reshuffle from passing as consolidation.
EXPECTED_PROFILE_MODULES = {
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
}


def test_formats_package_and_immutable_per_driver_family_metadata_contract_red():
    """Intentionally RED until the production extraction creates this contract."""
    issues = []
    actual_keys = driver_registry.get_all_type_keys()
    if actual_keys != EXPECTED_REGISTRY_KEYS:
        issues.append(
            f"registry keys differ: missing={sorted(EXPECTED_REGISTRY_KEYS - actual_keys)!r} "
            f"extra={sorted(actual_keys - EXPECTED_REGISTRY_KEYS)!r}"
        )

    package_exists = importlib.util.find_spec("app.drivers.formats") is not None
    if not package_exists:
        issues.append("missing package app.drivers.formats")

    paths_by_key = driver_registry._builtin
    concrete_paths = set(paths_by_key.values())
    if concrete_paths != set(EXPECTED_CLASS_FAMILIES):
        issues.append("concrete registry classes differ from the finite contract")

    # CH7465 and CH7465 Play are registry aliases for one concrete behavior.
    if paths_by_key["ch7465"] != paths_by_key["ch7465_play"]:
        issues.append("CH7465 alias keys no longer resolve to one concrete class")

    for class_path, expected_families in sorted(EXPECTED_CLASS_FAMILIES.items()):
        module_name, class_name = class_path.rsplit(".", 1)
        cls = getattr(importlib.import_module(module_name), class_name)
        actual_families = getattr(cls, "FORMAT_FAMILIES", None)
        if actual_families != expected_families or not isinstance(actual_families, tuple):
            issues.append(
                f"{class_path}.FORMAT_FAMILIES must be immutable tuple {expected_families!r}; "
                f"got {actual_families!r}"
            )

    if package_exists:
        formats_package = importlib.import_module("app.drivers.formats")
        actual_profile_modules = getattr(formats_package, "FORMAT_PROFILE_MODULES", None)
        if actual_profile_modules != EXPECTED_PROFILE_MODULES:
            issues.append(
                "app.drivers.formats.FORMAT_PROFILE_MODULES must match the finite "
                "profile-to-cohesive-module contract"
            )
        for module_name in sorted(set(EXPECTED_PROFILE_MODULES.values())):
            if importlib.util.find_spec(module_name) is None:
                issues.append(f"missing cohesive parser module {module_name}")

    assert issues == [], "future driver formats contract is unmet:\n- " + "\n- ".join(issues)
