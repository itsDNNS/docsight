"""Static dependency, entrypoint, and thin-adapter guards for driver formats."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from app.drivers.formats import FORMAT_PROFILE_MODULES
from tests.architecture.test_driver_formats_contract_red import EXPECTED_CLASS_FAMILIES


ROOT = Path(__file__).resolve().parents[2]
FORMATS = ROOT / "app" / "drivers" / "formats"

FORBIDDEN_IMPORTS = {
    "cryptography", "flask", "random", "requests", "secrets", "socket", "ssl", "time",
}

PROFILE_ENTRYPOINTS = {
    "arris_html": "parse_arris_html",
    "cgm4981_columnar_html": "parse_cgm4981_columnar_html",
    "ch7465_xml": "parse_ch7465_xml",
    "cm1000_html_table": "parse_cm1000_html_table",
    "cm1000_javascript": "parse_cm1000_javascript",
    "cm3000_javascript": "parse_cm3000_javascript",
    "cm3500_html": "parse_cm3500_html",
    "f3896lg_rest_json": "parse_f3896lg_rest_json",
    "fritzbox_data_lua": "parse_fritzbox_data_lua",
    "generic_no_docsis": "parse_generic_no_docsis",
    "hitron_coda4680_json": "parse_hitron_coda4680_json",
    "hitron_coda56_json": "parse_hitron_coda56_json",
    "sagemcom_xmo_json": "parse_sagemcom_xmo_json",
    "sb6141_transposed_html": "parse_sb6141_transposed_html",
    "sb6183_html": "parse_sb6183_html",
    "sb6190_html": "parse_sb6190_html",
    "sercom_dm1000_json": "parse_sercom_dm1000_json",
    "surfboard_hnap": "parse_surfboard_hnap",
    "tc4400_html": "parse_tc4400_html",
    "ultrahub7_json": "parse_ultrahub7_json",
    "vodafone_station_cga_json": "parse_vodafone_station_cga_json",
    "vodafone_station_tg_embedded_json": "parse_vodafone_station_tg_embedded_json",
}

# Only these private methods remain as compatibility seams. Device-info,
# connection-info, auth, and transport parsers are outside the DOCSIS grammar.
COMPATIBILITY_METHODS = {
    "CGM4981Driver": {"_build_ds_channels", "_build_us_channels"},
    "CH7465Driver": {"_normalize_modulation"},
    "CM3000Driver": {
        "_parse_ds_qam", "_parse_us_atdma", "_parse_ds_ofdm", "_parse_us_ofdma",
        "_extract_tag_value_list", "_split_channels", "_hz_to_mhz", "_parse_number",
        "_normalize_modulation",
    },
    "CM3500Driver": {
        "_find_table_sections", "_parse_ds_qam", "_parse_ds_ofdm", "_parse_us_qam",
        "_parse_us_ofdm", "_parse_number", "_format_freq",
    },
    "F3896LGDriver": {"_parse_downstream", "_parse_upstream"},
    "FritzBoxDriver": {"_compensate_us31_power"},
    "HitronDriver": {
        "_fetch_ds_scqam", "_fetch_us_scqam", "_fetch_ds_ofdm", "_fetch_us_ofdma",
        "_ofdma_power_1_6", "_hz_to_mhz",
    },
    "HitronCoda4680Driver": {
        "_parse_ds_scqam", "_parse_us_scqam", "_parse_ds_ofdm", "_parse_us_ofdma",
        "_ofdma_power_1_6",
    },
    "SagemcomDriver": {
        "_parse_downstream", "_parse_upstream", "_hz_to_mhz", "_is_ofdm_downstream",
        "_normalize_modulation", "_normalize_us_modulation",
    },
    "SB6141Driver": {
        "_parse_downstream", "_parse_upstream", "_extract_transposed_rows",
        "_get_row_values", "_extract_upstream_modulation", "_parse_freq_hz", "_parse_number",
    },
    "SB6183Driver": {"_parse_downstream", "_parse_upstream"},
    "SB6190Driver": {"_parse_downstream", "_parse_upstream", "_normalize_mhz", "_parse_number"},
    "SercomDM1000Driver": {
        "_parse_ds_scqam", "_parse_ds_ofdm", "_parse_us_scqam", "_parse_us_ofdma",
        "_profile_modulation_from_bits",
    },
    "SurfboardDriver": {"_parse_downstream", "_parse_upstream", "_hz_to_mhz", "_normalize_modulation"},
    "TC4400Driver": {
        "_parse_downstream", "_parse_upstream", "_find_header_row", "_map_columns", "_cell",
        "_parse_frequency", "_parse_number", "_normalize_modulation",
    },
    "UltraHub7Driver": {"_parse_downstream_channels", "_parse_upstream_channels"},
    "VodafoneStationDriver": {
        "_parse_number", "_parse_tg_power", "_parse_tg_frequency", "_normalize_modulation",
    },
}

# These parse device metadata rather than normalized DOCSIS channel payloads.
NON_DOCSIS_PARSERS = {
    "CM3000Driver": {"_parse_uptime"},
    "CM3500Driver": {"_parse_service_flows"},
    "HitronCoda4680Driver": {"_parse_device_info", "_parse_rate_kbps"},
    "TC4400Driver": {"_parse_info_table"},
}


def test_formats_modules_have_no_transport_auth_or_runtime_dependencies():
    issues = []
    for path in sorted(FORMATS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            for name in imported:
                if name.split(".", 1)[0] in FORBIDDEN_IMPORTS:
                    issues.append(f"{path.name}:{node.lineno} imports {name}")
    assert issues == []


def test_every_profile_has_one_named_entrypoint_in_its_cohesive_module():
    assert set(PROFILE_ENTRYPOINTS) == set(FORMAT_PROFILE_MODULES)
    for profile, function_name in PROFILE_ENTRYPOINTS.items():
        module = importlib.import_module(FORMAT_PROFILE_MODULES[profile])
        assert callable(getattr(module, function_name, None)), (profile, function_name)


def test_registry_matrix_is_complete_and_alias_safe_in_both_directions():
    matrix_profiles = {
        profile
        for profiles in EXPECTED_CLASS_FAMILIES.values()
        for profile in profiles
    }
    assert matrix_profiles == set(FORMAT_PROFILE_MODULES)
    assert len(EXPECTED_CLASS_FAMILIES) == 20
    assert len(PROFILE_ENTRYPOINTS) == 22


def test_migrated_private_methods_are_finite_one_statement_delegations():
    discovered: dict[str, set[str]] = {}
    issues = []
    for class_path in EXPECTED_CLASS_FAMILIES:
        module_name, class_name = class_path.rsplit(".", 1)
        path = ROOT / (module_name.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        class_node = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        expected = COMPATIBILITY_METHODS.get(class_name, set())
        actual = {
            node.name for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in expected
        }
        if actual:
            discovered[class_name] = actual
        for node in class_node.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in expected:
                continue
            statements = node.body[1:] if (
                node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ) else node.body
            if len(statements) != 1 or isinstance(statements[0], (ast.For, ast.While, ast.If, ast.Try)):
                issues.append(f"{class_name}.{node.name} is not a one-statement delegation")
    assert discovered == {name: methods for name, methods in COMPATIBILITY_METHODS.items() if methods}
    assert issues == []


def test_concrete_drivers_cannot_add_local_parser_implementations():
    unexpected = []
    for class_path in EXPECTED_CLASS_FAMILIES:
        module_name, class_name = class_path.rsplit(".", 1)
        path = ROOT / (module_name.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        class_node = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        allowed = COMPATIBILITY_METHODS.get(class_name, set()) | NON_DOCSIS_PARSERS.get(
            class_name, set()
        )
        parser_names = {
            node.name for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("_parse")
        }
        unexpected.extend(
            f"{class_name}.{name}" for name in sorted(parser_names - allowed)
        )
    assert unexpected == []
