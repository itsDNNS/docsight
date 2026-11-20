"""Static dependency, entrypoint, and thin-adapter guards for driver formats."""

from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
from pathlib import Path

import pytest

from app.drivers import create_driver_registry
from app.drivers.formats import FORMAT_PROFILE_MODULES
from tests.drivers.driver_format_cases import CASES


ROOT = Path(__file__).resolve().parents[2]
FORMATS = ROOT / "app" / "drivers" / "formats"

FORBIDDEN_IMPORTS = {
    "cryptography", "flask", "random", "requests", "secrets", "socket", "ssl", "time",
}

# Driver channel parsers and value helpers must return one call into the format
# functions. Other _fetch_, _get_ and _is_ methods carry transport and login logic.
DELEGATION_PREFIXES = (
    "_build_", "_cell", "_compensate_", "_extract_", "_find_", "_format_", "_hz_",
    "_map_", "_normalize_", "_ofdma_", "_parse", "_profile_", "_split_",
    "_get_row_values", "_is_ofdm_downstream",
)

# Device metadata, login and request helpers that are not DOCSIS channel parsers.
OWN_LOGIC = {
    "CM3000Driver": {"_parse_uptime", "_extract_login_form"},
    "CM3500Driver": {"_parse_service_flows"},
    "HitronCoda4680Driver": {"_parse_device_info", "_parse_rate_kbps"},
    "SurfboardDriver": {"_normalize_url"},
    "TC4400Driver": {"_parse_info_table"},
    "VodafoneStationDriver": {"_extract_js_var"},
    "SagemcomDriver": {"_build_request"},
}


@pytest.fixture(scope="module")
def driver_classes():
    registry = create_driver_registry()
    return {
        key: type(registry.load_driver(key, "http://modem.invalid", "", ""))
        for key in registry.get_all_type_keys()
    }


def test_formats_modules_have_no_transport_auth_or_runtime_dependencies():
    issues = []
    for path in sorted(FORMATS.rglob("*.py")):
        package = ".".join(path.relative_to(ROOT).parent.parts)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = importlib.util.resolve_name("." * node.level + (node.module or ""), package)
                imported = [base, *(f"{base}.{alias.name}" for alias in node.names)]
            for name in imported:
                if name.split(".", 1)[0] in FORBIDDEN_IMPORTS or (
                    name.startswith("app.drivers.") and not f"{name}.".startswith("app.drivers.formats.")
                ):
                    issues.append(f"{path.relative_to(FORMATS)}:{node.lineno} imports {name}")
    assert issues == []


def test_profiles_have_format_entrypoints_and_drivers_declare_exactly_their_case_families(driver_classes):
    for profile, module in FORMAT_PROFILE_MODULES.items():
        assert module.startswith("app.drivers.formats."), profile
        assert callable(getattr(importlib.import_module(module), f"parse_{profile}", None)), profile
    declared = {key: cls.FORMAT_FAMILIES for key, cls in driver_classes.items()}
    assert all(isinstance(families, tuple) for families in declared.values())
    assert {profile for families in declared.values() for profile in families} == set(FORMAT_PROFILE_MODULES)
    case_families = {key: set() for key in driver_classes}
    for case in CASES:
        for key in case.driver.split(","):
            case_families[key].add(case.family)
    assert {key: sorted(families) for key, families in declared.items()} == {
        key: sorted(families) for key, families in case_families.items()
    }


def _plain(node) -> bool:
    return isinstance(node, (ast.Name, ast.Constant)) or isinstance(node, ast.Attribute) and _plain(node.value)


def _delegates(node, namespace) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "value":
        node = node.value
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return False
    module = getattr(namespace.get(node.func.id), "__module__", "")
    return (
        (module.startswith("app.drivers.formats.") or module == "app.drivers.format_compat")
        and all(
            _plain(arg) or _delegates(arg, namespace)
            for arg in [*node.args, *(keyword.value for keyword in node.keywords)]
        )
    )


def test_driver_parsers_and_value_helpers_only_delegate_to_format_functions(driver_classes):
    issues = []
    classes = {
        klass for cls in driver_classes.values() for klass in cls.__mro__
        if klass.__module__.startswith("app.drivers.")
    }
    for klass in classes:
        namespace = vars(sys.modules[klass.__module__])
        for node in ast.parse(inspect.getsource(klass)).body[0].body:
            if (
                not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                or not node.name.startswith(DELEGATION_PREFIXES)
                or node.name in OWN_LOGIC.get(klass.__name__, ())
            ):
                continue
            body = node.body[1:] if ast.get_docstring(node) is not None else node.body
            if len(body) != 1 or not isinstance(body[0], ast.Return) or not _delegates(body[0].value, namespace):
                issues.append(f"{klass.__name__}.{node.name}")
    assert issues == []
