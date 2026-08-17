"""Canonical registration manifest and fingerprint contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from app.app_factory import create_app, default_module_loader_factory
from app.config import ConfigManager
from app.registration import canonical_manifest, manifest_fingerprint


def test_manifest_is_canonical_and_redacted(tmp_path):
    manager = ConfigManager(str(tmp_path / "private-data-location"))
    secret_name = "module_super_secret_name"
    secret_value = "module-super-secret-value"
    manager.save({secret_name: secret_value})
    app = create_app(config_manager=manager, environ={}, testing=True)

    manifest = canonical_manifest(app, app.extensions.get("docsight_module_loader"))
    encoded = json.dumps(manifest, sort_keys=True)

    assert manifest["version"] == 1
    assert manifest_fingerprint(manifest) == app.extensions["docsight_registration_fingerprint"]
    assert str(tmp_path) not in encoded
    assert "private-data-location" not in encoded
    assert secret_name not in encoded
    assert secret_value not in encoded
    assert "<function" not in encoded and " at 0x" not in encoded


def test_fingerprint_is_stable_across_hash_seeds_and_fresh_processes(tmp_path):
    script = """
from app.app_factory import create_app, default_module_loader_factory
from app.config import ConfigManager
manager = ConfigManager(DATA_DIR)
app = create_app(
    config_manager=manager,
    module_loader_factory=default_module_loader_factory(manager, search_paths=[]),
    environ={},
    testing=True,
)
print(app.extensions['docsight_registration_fingerprint'])
"""
    fingerprints = []
    for seed in ("1", "987654"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        command = [sys.executable, "-c", f"DATA_DIR={str(tmp_path / seed)!r}\n{script}"]
        result = subprocess.run(command, check=True, capture_output=True, text=True, env=env)
        fingerprints.append(result.stdout.strip().splitlines()[-1])

    assert fingerprints[0] == fingerprints[1]
