"""Built-in theme catalog: application-owned theme data kept as validated JSON."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("catalogs") / "builtin_themes.json"
SCHEMA_VERSION = 1

# Shared with the template filter that renders theme tokens into a <style> block.
THEME_PROPERTY = re.compile(r"^--[A-Za-z0-9_-]+$")
THEME_UNSAFE_VALUE = re.compile(r"[<>{};\\\n\r]|/\*|\*/")

_REQUIRED_FIELDS = {"id", "name", "description", "version", "author", "minAppVersion", "theme_data"}
_OPTIONAL_FIELDS = {"homepage", "license"}
_MODES = ("dark", "light")
_META_FIELDS = {"family", "collection"}
# Compatibility aliases are defined once in tokens.css; theme data sets the canonical token.
ALIAS_TOKENS = {"--card-bg", "--text-primary", "--text-muted", "--success", "--warning", "--danger"}


class ThemeCatalogError(ValueError):
    """The built-in theme catalog is malformed; DOCSight refuses a partial catalog."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ThemeCatalogError(message)


def _check_strings(entry: dict[str, Any], fields: set[str], where: str) -> None:
    for field in fields & entry.keys():
        _require(isinstance(entry[field], str) and entry[field].strip() != "", f"{where}: '{field}' must be a non-empty string")


def _check_tokens(tokens: Any, where: str) -> None:
    _require(isinstance(tokens, dict) and bool(tokens), f"{where}: tokens must be a non-empty object")
    for name, value in tokens.items():
        _require(bool(THEME_PROPERTY.match(name)), f"{where}: '{name}' is not a custom property name")
        _require(name not in ALIAS_TOKENS, f"{where}: '{name}' is a compatibility alias, set its canonical token")
        _require(isinstance(value, str), f"{where}: '{name}' must be a string")
        _require(not THEME_UNSAFE_VALUE.search(value), f"{where}: '{name}' has an unsafe value")
        _require("var(" not in value, f"{where}: '{name}' must be a value, not a reference")


def _check_theme(entry: Any, index: int) -> str:
    where = f"theme {index}"
    _require(isinstance(entry, dict), f"{where}: must be an object")
    missing = _REQUIRED_FIELDS - entry.keys()
    _require(not missing, f"{where}: missing {', '.join(sorted(missing))}")
    unknown = entry.keys() - _REQUIRED_FIELDS - _OPTIONAL_FIELDS
    _require(not unknown, f"{where}: unknown field {', '.join(sorted(unknown))}")
    where = entry["id"] if isinstance(entry["id"], str) else where
    _check_strings(entry, _REQUIRED_FIELDS - {"theme_data"}, where)
    _require(entry["id"].startswith("docsight.theme_"), f"{where}: built-in theme ids start with 'docsight.theme_'")
    for field in _OPTIONAL_FIELDS & entry.keys():
        _require(isinstance(entry[field], str), f"{where}: '{field}' must be a string")

    data = entry["theme_data"]
    _require(isinstance(data, dict), f"{where}: theme_data must be an object")
    unknown = data.keys() - set(_MODES) - {"meta"}
    _require(not unknown, f"{where}: unknown theme_data field {', '.join(sorted(unknown))}")
    for mode in _MODES:
        _require(mode in data, f"{where}: missing the {mode} mode")
        _check_tokens(data[mode], f"{where} {mode}")
    meta = data.get("meta", {})
    _require(isinstance(meta, dict), f"{where}: meta must be an object")
    unknown = meta.keys() - _META_FIELDS
    _require(not unknown, f"{where}: unknown meta field {', '.join(sorted(unknown))}")
    _check_strings(meta, _META_FIELDS, f"{where} meta")
    return entry["id"]


def load_builtin_themes(path: Path = CATALOG_PATH) -> tuple[dict[str, Any], ...]:
    """Read and validate the catalog; return the themes in catalog order as fresh copies."""
    try:
        catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThemeCatalogError(f"built-in theme catalog cannot be read: {exc}") from exc
    _require(isinstance(catalog, dict), "catalog must be an object")
    _require(set(catalog) == {"schema_version", "themes"}, "catalog needs exactly schema_version and themes")
    _require(catalog["schema_version"] == SCHEMA_VERSION, f"unsupported schema_version {catalog['schema_version']!r}")
    themes = catalog["themes"]
    _require(isinstance(themes, list) and bool(themes), "themes must be a non-empty list")
    seen: set[str] = set()
    for index, entry in enumerate(themes):
        theme_id = _check_theme(entry, index)
        _require(theme_id not in seen, f"duplicate theme id {theme_id}")
        seen.add(theme_id)
    return tuple(deepcopy(themes))
