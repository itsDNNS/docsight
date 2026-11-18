"""Shared factory fixtures for DOCSight tests."""

import functools
import json
import os
import socket
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import version as _version
from app.app_factory import create_app, default_module_loader_factory
from app.config import ConfigManager
from app.runtime import DerivedStorageCache, LoginRateLimiter, RuntimeState, get_runtime


_real_connect = socket.socket.connect


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Tests must never reach a real modem, GitHub or anything else off this host.

    Attempts fail like an unreachable host and fail the test at teardown, also
    when they come from a background thread.
    """
    attempts = []

    def loopback_only(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not (
            str(host).startswith("127.") or host in ("::1", "localhost")
        ):
            attempts.append(address)
            raise OSError(f"network blocked in tests: {address}")
        return _real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    yield
    if attempts:
        pytest.fail(f"Test tried to reach the network: {attempts}", pytrace=False)


# Every create_app() asks git for the display version, and an untagged or shallow
# checkout answers "no tag" each time. The suite builds hundreds of apps, so that
# was hundreds of git processes per worker, which cost seconds on Windows runners.
# The tags cannot change during a test run, so each question is asked once.
# tests/test_version.py replaces _git_tag with fakes and still sees the real logic.
_version._git_tag = functools.lru_cache(maxsize=None)(_version._git_tag)


# Route tests run without an admin password; DOCSight is only open then when the operator opts out.
OPEN_INSTANCE_ENVIRON = {"AUTH_DISABLED": "true"}


FACTORY_CONTEXT_MODULES = {
    "tests.test_auth", "tests.test_bqm", "tests.test_channel_timeline",
    "tests.test_comparison_module", "tests.test_correlation", "tests.test_demo_mode",
    "tests.test_device_info_display", "tests.test_events", "tests.test_evidence_api",
    "tests.test_first_run_demo", "tests.test_first_run_ux", "tests.test_line_status", "tests.test_metrics_endpoint", "tests.test_onboarding_checklist",
    "tests.test_module_install_api", "tests.test_pwa_web_push",
    "tests.test_module_integration",
    "tests.test_report_customer_defaults", "tests.test_security_audit_fixes",
    "tests.test_security_hardening", "tests.test_smart_capture_api", "tests.test_speedtest",
    "tests.test_trends_api", "tests.test_update_checks", "tests.test_weather",
    "tests.test_web_theme", "tests.modules.connection_monitor.test_routes",
    "tests.modules.connection_monitor.test_traceroute_routes",
    "tests.modules.test_fritzbox_cable_routes",
}


def _uses_factory_context(module):
    relative = Path(module.__file__).resolve().relative_to(Path(__file__).resolve().parent)
    canonical = "tests." + ".".join(relative.with_suffix("").parts)
    return canonical in FACTORY_CONTEXT_MODULES


@pytest.fixture(autouse=True, scope="module")
def _factory_context_for_direct_route_tests(request, tmp_path_factory):
    """Give direct route-unit modules an isolated factory app and context."""
    if not _uses_factory_context(request.module):
        yield
        return
    manager = ConfigManager(str(tmp_path_factory.mktemp("factory-context")))
    application = create_app(
        config_manager=manager,
        module_loader_factory=default_module_loader_factory(manager, search_paths=[]),
        environ=dict(OPEN_INSTANCE_ENVIRON),
        testing=True,
    )
    request.module.app = application
    with application.app_context():
        yield


def reset_runtime(runtime):
    """Drop the services and state a previous test wired into a shared app."""
    runtime.storage = None
    runtime.on_config_changed = None
    runtime.module_loader = None
    runtime.modem_collector = None
    runtime.collectors = []
    runtime.state = RuntimeState()
    runtime.login_rate_limiter = LoginRateLimiter()
    runtime.derived_storage = DerivedStorageCache()


@pytest.fixture(autouse=True)
def _reset_direct_route_runtime(request):
    if not _uses_factory_context(request.module):
        yield
        return
    reset_runtime(get_runtime(request.module.app))
    yield


@pytest.fixture
def make_config(tmp_path):
    """Return a factory for isolated configuration managers."""
    counter = 0

    def factory(values=None, *, data_dir=None):
        nonlocal counter
        counter += 1
        path = data_dir or str(tmp_path / f"config-{counter}")
        manager = ConfigManager(path)
        if values:
            manager.save(values)
        return manager

    return factory


@pytest.fixture
def builtin_module_loader_factory():
    """Return a loader-factory builder for all shipped modules."""
    builtin_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "modules"))

    def factory(config_manager):
        return default_module_loader_factory(
            config_manager,
            builtin_base_path=builtin_path,
            search_paths=[],
        )

    return factory


@pytest.fixture
def make_app(make_config):
    """Return a factory that creates an independent Flask application."""
    def factory(
        *,
        config_manager=None,
        storage=None,
        on_config_changed=None,
        module_loader_factory=None,
        environ=None,
        testing=True,
    ):
        manager = config_manager or make_config()
        return create_app(
            config_manager=manager,
            storage=storage,
            on_config_changed=on_config_changed,
            module_loader_factory=module_loader_factory,
            environ=dict(OPEN_INSTANCE_ENVIRON) if environ is None else environ,
            testing=testing,
        )

    return factory


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def make_client(make_app):
    """Return a factory producing a client for a new application."""
    def factory(**kwargs):
        return make_app(**kwargs).test_client()

    return factory


@pytest.fixture
def auth_config(tmp_path):
    """Config with admin_password set."""
    mgr = ConfigManager(str(tmp_path / "data"))
    mgr.save({"modem_password": "test", "modem_type": "fritzbox", "admin_password": "secret123"})
    return mgr


@pytest.fixture
def noauth_config(tmp_path):
    """Config without admin_password."""
    mgr = ConfigManager(str(tmp_path / "data"))
    mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
    return mgr


@pytest.fixture
def sample_analysis():
    return {
        "summary": {
            "ds_total": 33,
            "us_total": 4,
            "ds_power_min": -1.0,
            "ds_power_max": 5.0,
            "ds_power_avg": 2.5,
            "us_power_min": 40.0,
            "us_power_max": 45.0,
            "us_power_avg": 42.5,
            "ds_snr_min": 35.0,
            "ds_snr_avg": 37.0,
            "ds_correctable_errors": 1234,
            "ds_uncorrectable_errors": 56,
            "health": "good",
            "health_issues": [],
            "us_capacity_mbps": 50.0,
        },
        "ds_channels": [{
            "channel_id": 1,
            "frequency": "602 MHz",
            "power": 3.0,
            "snr": 35.0,
            "modulation": "256QAM",
            "correctable_errors": 100,
            "uncorrectable_errors": 5,
            "docsis_version": "3.0",
            "health": "good",
            "health_detail": "",
        }],
        "us_channels": [{
            "channel_id": 1,
            "frequency": "37 MHz",
            "power": 42.0,
            "modulation": "64QAM",
            "multiplex": "ATDMA",
            "docsis_version": "3.0",
            "health": "good",
            "health_detail": "",
        }],
    }


@pytest.fixture
def sample_bnetz_parsed():
    return {
        "date": "2025-02-04",
        "provider": "Vodafone",
        "tariff": "GigaZuhause 1000 Kabel",
        "download_max": 1000.0,
        "download_normal": 850.0,
        "download_min": 600.0,
        "upload_max": 50.0,
        "upload_normal": 35.0,
        "upload_min": 15.0,
        "measurement_count": 30,
        "measurements_download": [{"nr": 1, "mbps": 883.29}],
        "measurements_upload": [{"nr": 1, "mbps": 5.04}],
        "download_measured_avg": 748.04,
        "upload_measured_avg": 7.85,
        "verdict_download": "deviation",
        "verdict_upload": "deviation",
    }


def error_counter_coverage(*, total, correctable, uncorrectable, comparable, partial):
    return {
        "total_channels": total,
        "correctable_channels": correctable,
        "uncorrectable_channels": uncorrectable,
        "comparable_channels": comparable,
        "partial_channels": partial,
        "unsupported_channels": 0,
        "families": {},
    }


def mixed_error_counter_summary():
    """Summary fields of two channels where only one reports both counters."""
    return {
        "errors_supported": True,
        "ds_correctable_errors": 9900,
        "ds_uncorrectable_errors": 1100,
        "ds_comparable_correctable_errors": 9900,
        "ds_comparable_uncorrectable_errors": 100,
        "ds_uncorr_pct": 1.0,
        "error_counter_coverage": error_counter_coverage(
            total=2, correctable=1, uncorrectable=2, comparable=1, partial=1,
        ),
    }


def utc_ts(delta):
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def insert_snapshot(storage, analysis, timestamp):
    """Store an analysis under an explicit timestamp, bypassing save_snapshot's clock."""
    with sqlite3.connect(storage.db_path) as conn:
        conn.execute(
            "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?, ?, ?, ?)",
            (
                timestamp,
                json.dumps(analysis["summary"]),
                json.dumps(analysis["ds_channels"]),
                json.dumps(analysis["us_channels"]),
            ),
        )
