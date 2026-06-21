"""Tests for static built-in module registration."""

from __future__ import annotations

import json
from pathlib import Path

from app.builtin_modules import BUILTIN_MODULE_DIRS, BUILTIN_PYTHON_CONTRIBUTIONS
from app.module_loader import (
    attach_builtin_python_contributions,
    discover_builtin_modules,
    discover_modules,
)

ROOT = Path(__file__).resolve().parents[1]
BUILTIN_MODULES_DIR = ROOT / "app" / "modules"


def test_builtin_registry_matches_tracked_manifest_dirs():
    """Every tracked built-in manifest is in the static registry, and only those."""
    manifest_dirs = tuple(sorted(path.parent.name for path in BUILTIN_MODULES_DIR.glob("*/manifest.json")))
    assert tuple(sorted(BUILTIN_MODULE_DIRS)) == manifest_dirs


def test_discover_builtin_modules_uses_static_registry(monkeypatch):
    """Built-in registration must not discover core modules by directory scan."""
    import app.module_loader as module_loader

    def fail_listdir(_path):
        raise AssertionError("built-in module discovery must use the static registry")

    monkeypatch.setattr(module_loader.os, "listdir", fail_listdir)

    modules = discover_builtin_modules(str(BUILTIN_MODULES_DIR))

    assert len(modules) == len(BUILTIN_MODULE_DIRS)
    assert all(mod.builtin for mod in modules)
    assert {mod.id for mod in modules} >= {"docsight.speedtest", "docsight.mqtt"}


def test_builtin_python_contribution_registry_covers_manifest_entry_points():
    for dirname in BUILTIN_MODULE_DIRS:
        manifest = json.loads((BUILTIN_MODULES_DIR / dirname / "manifest.json").read_text(encoding="utf-8"))
        contributes = manifest.get("contributes", {})
        specs = BUILTIN_PYTHON_CONTRIBUTIONS.get(manifest["id"])
        for key in ("collector", "publisher", "driver"):
            if key in contributes:
                assert specs is not None, f"missing static Python contribution spec for {manifest['id']}"
                assert getattr(specs, key), f"missing {key} spec for {manifest['id']}"


def test_builtin_python_contributions_are_static_imports():
    modules = {mod.id: mod for mod in discover_builtin_modules(str(BUILTIN_MODULES_DIR))}

    speedtest = modules["docsight.speedtest"]
    mqtt = modules["docsight.mqtt"]
    attach_builtin_python_contributions(speedtest)
    attach_builtin_python_contributions(mqtt)

    assert speedtest.collector_class is not None
    assert mqtt.publisher_class is not None
    assert speedtest.collector_class.__name__ == "SpeedtestCollector"
    assert mqtt.publisher_class.__name__ == "MQTTPublisher"
    assert "docsight.speedtest" in BUILTIN_PYTHON_CONTRIBUTIONS
    assert "docsight.mqtt" in BUILTIN_PYTHON_CONTRIBUTIONS


def test_builtin_python_contribution_missing_spec_sets_module_error(monkeypatch):
    import app.module_loader as module_loader

    modules = {mod.id: mod for mod in discover_builtin_modules(str(BUILTIN_MODULES_DIR))}
    speedtest = modules["docsight.speedtest"]
    monkeypatch.delitem(module_loader.BUILTIN_PYTHON_CONTRIBUTIONS, "docsight.speedtest")

    try:
        attach_builtin_python_contributions(speedtest)
    except module_loader.ManifestError as exc:
        assert "missing static collector registration" in str(exc)
    else:
        raise AssertionError("missing built-in static contribution spec must fail closed")


def test_community_scan_skips_ids_already_registered_by_builtins(tmp_path):
    module_dir = tmp_path / "duplicate"
    module_dir.mkdir()
    (module_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "docsight.speedtest",
                "name": "Duplicate Speedtest",
                "description": "Should not override the built-in module",
                "version": "1.0.0",
                "author": "Test",
                "minAppVersion": "2026.2",
                "type": "integration",
                "contributes": {},
            }
        ),
        encoding="utf-8",
    )

    modules = discover_modules([str(tmp_path)], known_ids={"docsight.speedtest"})

    assert modules == []
