"""The standalone manifest contract stays authoritative and pure stdlib."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.manifest_contract import validate_manifest_contract


ROOT = Path(__file__).resolve().parents[1]


def _valid_manifest() -> dict:
    return {
        "id": "community.sample",
        "name": "Sample",
        "description": "Sample module",
        "version": "1.0.0",
        "author": "Test",
        "minAppVersion": "2026.2",
        "type": "integration",
        "contributes": {},
        "config": {"sample_token": ""},
        "config_secrets": ["sample_token"],
    }


def test_contract_cli_validates_manifests_without_loading_application(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_valid_manifest()), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "app" / "manifest_contract.py"), str(manifest_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Manifest validation passed" in result.stdout


def test_contract_function_rejects_unknown_capability():
    manifest = _valid_manifest()
    manifest["configVault"] = {"provider": "example"}

    errors = validate_manifest_contract(manifest, builtin=False)

    assert errors == ["Unsupported manifest fields: configVault"]


def test_contract_rejects_non_string_secret_defaults():
    for default in (False, 0, 1, [], {}):
        manifest = _valid_manifest()
        manifest["config"]["sample_token"] = default

        errors = validate_manifest_contract(manifest, builtin=False)

        assert "'config_secrets' defaults must be strings" in errors


def test_contract_cli_does_not_print_undeclared_secret_names(tmp_path):
    secret_marker = "private_token_name_marker"
    manifest = _valid_manifest()
    manifest["config_secrets"] = [secret_marker]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "app" / "manifest_contract.py"), str(manifest_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "'config_secrets' references undeclared config keys" in result.stderr
    assert secret_marker not in result.stdout
    assert secret_marker not in result.stderr
