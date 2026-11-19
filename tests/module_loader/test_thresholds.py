"""Tests for threshold module contributions and wiring."""

import copy
import json
import re

import pytest
from flask import Flask
from app.module_contributions import validate_thresholds
from app.module_loader import ModuleLoader
from app.module_registry import ManifestError, validate_manifest

_VALID_THRESHOLDS = {
    "downstream_power": {"_default": "256QAM", "256QAM": {"good": [-4, 13], "warning": [-6, 18], "critical": [-8, 20]}},
    "upstream_power": {"_default": "sc_qam", "sc_qam": {"good": [41, 47], "warning": [37, 51], "critical": [35, 53]}},
    # Sparse on purpose: the analyzer uses built-in limits for the missing 256QAM entry.
    "snr": {"_default": "256QAM", "ofdm": {"good_min": 27, "warning_min": 25.5, "critical_min": 24.5}},
}


@pytest.mark.parametrize("path, value", [
    ((), ["not", "an", "object"]),
    (("downstream_power", "_default"), 256),
    (("downstream_power", "_default"), "_default"),
    (("snr", "_default"), "_custom"),
    (("downstream_power", "256QAM", "good"), None),
    (("downstream_power", "256QAM", "good"), ["-4", "13"]),
    (("downstream_power", "256QAM", "good"), [5, -5]),
    (("upstream_power", "sc_qam", "warning"), [True, 51]),
    (("upstream_power", "sc_qam", "critical"), [35]),
    (("snr", "256QAM", "critical_min"), "29"),
    (("snr", "256QAM", "good_min"), float("nan")),
    (("snr", "256QAM"), 33),
    (("errors", "spike_expiry_hours"), None),
    pytest.param(("errors", "spike_expiry_hours"), 10**400, id="huge-int"),
    (("errors", "uncorrectable_pct"), 3),
    (("errors", "uncorrectable_pct", "warning"), "1"),
    (("upstream_modulation", "warning_max_qam"), True),
])
def test_threshold_validation_rejects_invalid_shapes(path, value):
    root = {"profile": copy.deepcopy(_VALID_THRESHOLDS)}
    *parents, leaf = ("profile", *path)
    target = root
    for name in parents:
        target = target.setdefault(name, {})
    target[leaf] = value
    with pytest.raises(ManifestError, match=re.escape(".".join(path) or "Threshold contribution")):
        validate_thresholds(root["profile"])


class TestThresholdContributes:
    """Test threshold module loading and validation."""

    def test_thresholds_is_valid_contributes(self):
        from app.manifest_contract import VALID_CONTRIBUTES
        assert "thresholds" in VALID_CONTRIBUTES

    def test_manifest_with_thresholds_valid(self):
        raw = {
            "id": "test.thresholds",
            "name": "Test Thresholds",
            "description": "Test threshold profile",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "analysis",
            "contributes": {"thresholds": "thresholds.json"},
        }
        info = validate_manifest(raw, "/some/path")
        assert info.contributes == {"thresholds": "thresholds.json"}
        assert info.menu["order"] == 999  # default for modules without menu

    def test_threshold_module_loads_data(self, tmp_path):
        from app import analyzer
        orig = analyzer._thresholds.copy()
        try:
            mod_dir = tmp_path / "mythresholds"
            mod_dir.mkdir()
            manifest = {
                "id": "test.mythresholds",
                "name": "My Thresholds",
                "description": "desc",
                "version": "1.0.0",
                "author": "Test",
                "minAppVersion": "2026.2",
                "type": "analysis",
                "contributes": {"thresholds": "thresholds.json"},
            }
            (mod_dir / "manifest.json").write_text(json.dumps(manifest))
            (mod_dir / "thresholds.json").write_text(json.dumps(_VALID_THRESHOLDS))

            app = Flask(__name__)
            app.config["TESTING"] = True
            loader = ModuleLoader(app, search_paths=[str(tmp_path)])
            loader.load_all()

            mod = next(m for m in loader.get_modules() if m.id == "test.mythresholds")
            assert mod.thresholds_data is not None
            assert mod.error is None
            assert "downstream_power" in mod.thresholds_data
        finally:
            analyzer._thresholds = orig

    def test_threshold_validation_missing_section(self, tmp_path):
        from app import analyzer
        orig = analyzer._thresholds.copy()
        try:
            mod_dir = tmp_path / "badthresholds"
            mod_dir.mkdir()
            manifest = {
                "id": "test.badthresholds",
                "name": "Bad",
                "description": "desc",
                "version": "1.0.0",
                "author": "Test",
                "minAppVersion": "2026.2",
                "type": "analysis",
                "contributes": {"thresholds": "thresholds.json"},
            }
            (mod_dir / "manifest.json").write_text(json.dumps(manifest))
            (mod_dir / "thresholds.json").write_text(json.dumps({"downstream_power": {}}))

            app = Flask(__name__)
            app.config["TESTING"] = True
            loader = ModuleLoader(app, search_paths=[str(tmp_path)])
            loader.load_all()

            mod = next(m for m in loader.get_modules() if m.id == "test.badthresholds")
            assert mod.error is not None
        finally:
            analyzer._thresholds = orig

    def test_threshold_validation_missing_file(self, tmp_path):
        from app import analyzer
        orig = analyzer._thresholds.copy()
        try:
            mod_dir = tmp_path / "nothresholds"
            mod_dir.mkdir()
            manifest = {
                "id": "test.nothresholds",
                "name": "No File",
                "description": "desc",
                "version": "1.0.0",
                "author": "Test",
                "minAppVersion": "2026.2",
                "type": "analysis",
                "contributes": {"thresholds": "thresholds.json"},
            }
            (mod_dir / "manifest.json").write_text(json.dumps(manifest))

            app = Flask(__name__)
            app.config["TESTING"] = True
            loader = ModuleLoader(app, search_paths=[str(tmp_path)])
            loader.load_all()

            mod = next(m for m in loader.get_modules() if m.id == "test.nothresholds")
            assert mod.error is not None
        finally:
            analyzer._thresholds = orig


class TestThresholdWiring:
    """Test that threshold modules wire into the analyzer."""

    def test_loading_threshold_module_sets_analyzer_thresholds(self, tmp_path):
        from app import analyzer
        orig = analyzer._thresholds.copy()
        try:
            mod_dir = tmp_path / "mythresholds"
            mod_dir.mkdir()
            manifest = {
                "id": "test.wiring",
                "name": "Wiring Test",
                "description": "desc",
                "version": "1.0.0",
                "author": "Test",
                "minAppVersion": "2026.2",
                "type": "analysis",
                "contributes": {"thresholds": "thresholds.json"},
            }
            (mod_dir / "manifest.json").write_text(json.dumps(manifest))
            thresholds = {
                "downstream_power": {"_default": "256QAM", "256QAM": {"good": [-99, 99], "warning": [-99, 99], "critical": [-99, 99]}},
                "upstream_power": {"_default": "sc_qam", "sc_qam": {"good": [-99, 99], "warning": [-99, 99], "critical": [-99, 99]}},
                "snr": {"_default": "256QAM", "256QAM": {"good_min": 99, "warning_min": 99, "critical_min": 99}},
            }
            (mod_dir / "thresholds.json").write_text(json.dumps(thresholds))

            app = Flask(__name__)
            app.config["TESTING"] = True
            loader = ModuleLoader(app, search_paths=[str(tmp_path)])
            loader.load_all()

            assert analyzer._thresholds["downstream_power"]["256QAM"]["good"] == [-99, 99]
        finally:
            analyzer._thresholds = orig


class TestGetThresholdModules:
    """Test the get_threshold_modules helper."""

    def test_returns_threshold_modules(self, tmp_path, load_with_regular_module):
        from app import analyzer
        orig = analyzer._thresholds.copy()
        try:
            mod_t = tmp_path / "thresh"
            mod_t.mkdir()
            (mod_t / "manifest.json").write_text(json.dumps({
                "id": "test.thresh", "name": "T", "description": "d",
                "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
                "type": "analysis", "contributes": {"thresholds": "thresholds.json"},
            }))
            (mod_t / "thresholds.json").write_text(json.dumps(_VALID_THRESHOLDS))

            loader = load_with_regular_module()

            threshold_mods = loader.get_threshold_modules()
            assert len(threshold_mods) == 1
            assert threshold_mods[0].id == "test.thresh"
        finally:
            analyzer._thresholds = orig

