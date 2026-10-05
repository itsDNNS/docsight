"""The built-in theme catalog loads completely or not at all."""

import json

import pytest

from app.module_registry import discover_builtin_theme_modules
from app.theme_catalog import CATALOG_PATH, ThemeCatalogError, load_builtin_themes
from app.theme_registry import BUILTIN_THEMES


def _catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _load(tmp_path, catalog):
    path = tmp_path / "builtin_themes.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return load_builtin_themes(path)


def test_registry_exposes_the_catalog_in_order():
    catalog = _catalog()
    assert catalog["schema_version"] == 1
    assert [theme["id"] for theme in BUILTIN_THEMES] == [theme["id"] for theme in catalog["themes"]]
    assert list(BUILTIN_THEMES) == catalog["themes"]


def test_loaded_theme_modules_do_not_share_the_catalog_data():
    module = discover_builtin_theme_modules()[0]
    module.theme_data["dark"]["--bg"] = "#000000"
    assert BUILTIN_THEMES[0]["theme_data"]["dark"]["--bg"] != "#000000"
    assert discover_builtin_theme_modules()[0].theme_data["dark"]["--bg"] != "#000000"


def _break(catalog, change):
    change(catalog)
    return catalog


@pytest.mark.parametrize("change, message", [
    (lambda c: c["themes"].append(dict(c["themes"][0])), "duplicate theme id"),
    (lambda c: c["themes"][0]["theme_data"].pop("light"), "missing the light mode"),
    (lambda c: c["themes"][0]["theme_data"]["dark"].update({"bg": "#000"}), "not a custom property name"),
    (lambda c: c["themes"][0]["theme_data"]["dark"].update({"--text-muted": "#777"}), "compatibility alias"),
    (lambda c: c["themes"][0]["theme_data"]["dark"].update({"--bg": 12}), "must be a string"),
    (lambda c: c["themes"][0]["theme_data"]["dark"].update({"--bg": "red; } body { x: y"}), "unsafe value"),
    (lambda c: c["themes"][0]["theme_data"]["dark"].update({"--bg": "var(--void)"}), "not a reference"),
    (lambda c: c["themes"][0].update({"tags": ["dark"]}), "unknown field tags"),
    (lambda c: c["themes"][0]["theme_data"]["meta"].update({"mood": "calm"}), "unknown meta field mood"),
    (lambda c: c["themes"][0].pop("author"), "missing author"),
    (lambda c: c["themes"][0].update({"id": "community.theme_x"}), "start with 'docsight.theme_'"),
    (lambda c: c.update({"schema_version": 2}), "unsupported schema_version"),
    (lambda c: c.update({"themes": []}), "non-empty list"),
])
def test_an_invalid_catalog_is_rejected_as_a_whole(tmp_path, change, message):
    with pytest.raises(ThemeCatalogError, match=message):
        _load(tmp_path, _break(_catalog(), change))


def test_an_unreadable_catalog_fails_clearly(tmp_path):
    path = tmp_path / "builtin_themes.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ThemeCatalogError, match="cannot be read"):
        load_builtin_themes(path)
