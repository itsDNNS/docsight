"""Regression tests for the self-hosted doctor command."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


SENTINELS = (
    "TEST_PASSWORD_SENTINEL_593",
    "TEST_TOKEN_SENTINEL_593",
    "AA:BB:CC:DD:EE:FF",
    "203.0.113.42",
    "SERIAL-SENTINEL-1234",
    "CUSTOMER-SENTINEL-593",
)


def _write_config(data_dir: Path, payload: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_doctor_json_and_human_output_redact_sensitive_sentinels(tmp_path, monkeypatch):
    from app.doctor import build_report, format_human

    data_dir = tmp_path / "data"
    _write_config(
        data_dir,
        {
            "modem_type": "fritzbox",
            "modem_url": "http://user:TEST_PASSWORD_SENTINEL_593@203.0.113.42/router",
            "modem_user": "CUSTOMER-SENTINEL-593",
            "modem_password": "TEST_PASSWORD_SENTINEL_593",
            "notify_webhook_url": "https://hooks.example.test/TEST_TOKEN_SENTINEL_593",
            "notify_apprise_enabled": True,
            "notify_apprise_url": "http://apprise.internal:notaport/TEST_TOKEN_SENTINEL_593",
            "notify_webhook_token": "TEST_TOKEN_SENTINEL_593",
            "isp_name": "SERIAL-SENTINEL-1234",
            "bqm_url": "https://bqm.example.test/AA:BB:CC:DD:EE:FF",
        },
    )
    monkeypatch.setenv("MODEM_PASSWORD", "TEST_PASSWORD_SENTINEL_593")
    monkeypatch.setenv("MQTT_HOST", "router.internal.example")
    monkeypatch.setenv("SPEEDTEST_TRACKER_TOKEN", "TEST_TOKEN_SENTINEL_593")

    report = build_report(data_dir=str(data_dir))
    serialized = json.dumps(report, sort_keys=True)
    human = format_human(report, color=False)

    for sentinel in SENTINELS:
        assert sentinel not in serialized
        assert sentinel not in human
    assert "router.internal.example" not in serialized
    assert "router.internal.example" not in human
    assert "notaport" not in serialized
    assert "notaport" not in human
    assert "<redacted>" in serialized
    assert "<host:redacted>" in serialized
    assert "<redacted>" in human


def test_doctor_marks_optional_integrations_as_skipped_or_warn_not_core_fail(tmp_path):
    from app.doctor import build_report

    data_dir = tmp_path / "data"
    _write_config(
        data_dir,
        {
            "modem_type": "fritzbox",
            "notify_apprise_enabled": True,
            # Missing URL: configured flag without usable destination should warn,
            # but optional integrations must not make the core install fail.
            "notify_apprise_url": "",
        },
    )

    report = build_report(data_dir=str(data_dir))
    apprise = next(check for check in report["checks"] if check["id"] == "integration.apprise")

    assert apprise["status"] == "warn"
    assert apprise["core"] is False
    assert report["summary"]["core_fail"] is False


def test_doctor_reports_sqlite_integrity_failures_as_core_fail(tmp_path):
    from app.doctor import build_report

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "docsis_history.db").write_bytes(b"not a sqlite database")

    report = build_report(data_dir=str(data_dir))
    db_check = next(check for check in report["checks"] if check["id"] == "storage.database")

    assert db_check["status"] == "fail"
    assert db_check["core"] is True
    assert report["summary"]["core_fail"] is True


def test_doctor_cli_json_is_parseable_and_exits_successfully_for_fresh_install(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "app.doctor", "--json", "--data-dir", str(data_dir)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["doctor_version"] == 1
    assert payload["summary"]["core_fail"] is False
    assert any(check["status"] == "warn" for check in payload["checks"])


def test_doctor_uses_only_offline_checks_by_default(tmp_path, monkeypatch):
    from app.doctor import build_report

    data_dir = tmp_path / "data"
    _write_config(
        data_dir,
        {
            "modem_type": "fritzbox",
            "modem_url": "http://192.0.2.1",
            "mqtt_host": "192.0.2.2",
            "notify_webhook_url": "https://hooks.example.test/TEST_TOKEN_SENTINEL_593",
        },
    )

    def fail_if_called(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("doctor must not perform active network probes by default")

    monkeypatch.setattr("socket.create_connection", fail_if_called)
    monkeypatch.setattr("socket.getaddrinfo", fail_if_called)
    monkeypatch.setattr("urllib.request.urlopen", fail_if_called)
    monkeypatch.setattr("requests.sessions.Session.request", fail_if_called)
    monkeypatch.setattr("tempfile.NamedTemporaryFile", fail_if_called)
    build_report(data_dir=str(data_dir))
