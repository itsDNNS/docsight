"""Tests for threshold module contributions and wiring."""

# tests/test_module_loader.py
import importlib
import json
import os
import tempfile
import textwrap

import pytest
from flask import Flask
from app.module_loader import ModuleInfo, validate_manifest, ManifestError, discover_modules, register_module_config, merge_module_i18n, load_module_routes, load_module_collector, load_module_publisher, setup_module_static, setup_module_templates, ModuleLoader

_VALID_THRESHOLDS = {
    "downstream_power": {"_default": "256QAM", "256QAM": {"good": [-4, 13], "warning": [-6, 18], "critical": [-8, 20]}},
    "upstream_power": {"_default": "sc_qam", "sc_qam": {"good": [41, 47], "warning": [37, 51], "critical": [35, 53]}},
    "snr": {"_default": "256QAM", "256QAM": {"good_min": 33, "warning_min": 31, "critical_min": 30}},
}

class TestThresholdContributes:
    """Test threshold module loading and validation."""

    def test_thresholds_is_valid_contributes(self):
        from app.module_loader import VALID_CONTRIBUTES
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

    def test_returns_threshold_modules(self, tmp_path):
        from app import analyzer
        orig = analyzer._thresholds.copy()
        try:
            # Threshold module
            mod_t = tmp_path / "thresh"
            mod_t.mkdir()
            (mod_t / "manifest.json").write_text(json.dumps({
                "id": "test.thresh", "name": "T", "description": "d",
                "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
                "type": "analysis", "contributes": {"thresholds": "thresholds.json"},
            }))
            (mod_t / "thresholds.json").write_text(json.dumps(_VALID_THRESHOLDS))

            # Regular module
            mod_r = tmp_path / "regular"
            mod_r.mkdir()
            (mod_r / "manifest.json").write_text(json.dumps({
                "id": "test.regular", "name": "R", "description": "d",
                "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
                "type": "integration", "contributes": {},
            }))

            app = Flask(__name__)
            loader = ModuleLoader(app, search_paths=[str(tmp_path)])
            loader.load_all()

            threshold_mods = loader.get_threshold_modules()
            assert len(threshold_mods) == 1
            assert threshold_mods[0].id == "test.thresh"
        finally:
            analyzer._thresholds = orig

