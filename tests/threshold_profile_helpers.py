"""Register threshold profiles through the real module loader."""

import contextlib
import json
import os

from flask import Flask

from app import analyzer
from app.module_loader import ModuleLoader

_BUILTIN_MODULES = os.path.join(os.path.dirname(__file__), "..", "app", "modules")

COMMUNITY_PROFILE_ID = "community.strict_cable_thresholds"
COMMUNITY_PROFILE_NAME = "Strict Cable"
COMMUNITY_PROFILE_VERSION = "2.3.0"

# 256QAM has no warning band and no warning SNR, so the analyzer falls back to
# the good values for both.
COMMUNITY_THRESHOLDS = {
    "downstream_power": {
        "_default": "256QAM",
        "256QAM": {"good": [-3.0, 10.0], "critical": [-7.0, 14.0]},
    },
    "upstream_power": {
        "_default": "sc_qam",
        "sc_qam": {"good": [40.0, 48.0], "warning": [38.0, 50.0], "critical": [36.0, 52.0]},
    },
    "snr": {
        "_default": "256QAM",
        "256QAM": {"good_min": 34.0, "critical_min": 30.0},
    },
}


@contextlib.contextmanager
def registered_community_profile(tmp_path, name=COMMUNITY_PROFILE_NAME, meta=None):
    """Load a community threshold module and restore the analyzer afterwards."""
    module = tmp_path / "strict_cable"
    module.mkdir()
    (module / "manifest.json").write_text(json.dumps({
        "id": COMMUNITY_PROFILE_ID,
        "name": name,
        "description": "Stricter community signal thresholds",
        "version": COMMUNITY_PROFILE_VERSION,
        "author": "community",
        "minAppVersion": "2026.2",
        "type": "analysis",
        "contributes": {"thresholds": "thresholds.json"},
    }), encoding="utf-8")
    thresholds = dict(COMMUNITY_THRESHOLDS, **({"_meta": meta} if meta is not None else {}))
    (module / "thresholds.json").write_text(json.dumps(thresholds), encoding="utf-8")

    with _restored_analyzer():
        ModuleLoader(Flask(__name__), search_paths=[str(tmp_path)]).load_all()
        assert analyzer.threshold_snapshot()["profile"]["id"] == COMMUNITY_PROFILE_ID
        yield


@contextlib.contextmanager
def registered_builtin_profiles():
    """Load the shipped modules, which activates the built-in VFKD profile."""
    with _restored_analyzer():
        ModuleLoader(
            Flask(__name__), builtin_base_path=os.path.abspath(_BUILTIN_MODULES), search_paths=[],
        ).load_all()
        assert analyzer.threshold_snapshot()["profile"]["id"] == "docsight.thresholds_vfkd"
        yield


@contextlib.contextmanager
def no_registered_profile():
    """Run without a loaded profile, so the analyzer uses its VFKD fallback."""
    with _restored_analyzer():
        analyzer._thresholds = {}
        analyzer._threshold_profile = {"id": None, "version": None}
        yield


@contextlib.contextmanager
def _restored_analyzer():
    saved_thresholds = analyzer._thresholds
    saved_profile = dict(analyzer._threshold_profile)
    try:
        yield
    finally:
        analyzer._thresholds = saved_thresholds
        analyzer._threshold_profile = saved_profile
