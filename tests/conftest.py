"""Shared factory fixtures for DOCSight tests."""

import functools
import json
import os
import socket
import sqlite3
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

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


@pytest.fixture(autouse=True, scope="module")
def _core_module_registries():
    """Start each test module, and its module-scoped apps, from the core config schema and catalogs."""
    from app import config, i18n

    config.reset_module_config_schema()
    i18n.reset_module_translations()


@pytest.fixture(autouse=True)
def _restore_module_registries():
    """Restore the config schema and translations after a test that builds its own app or registers modules directly."""
    from app import config
    from app.i18n import _TRANSLATIONS

    sets = [config.BOOL_KEYS, config.INT_KEYS, config.SECRET_KEYS, config.PRIVATE_KEYS]
    saved_sets = [set(keys) for keys in sets]
    defaults = dict(config.DEFAULTS)
    module_secrets = (set(config.MODULE_SECRET_KEYS), dict(config.MODULE_SECRET_OWNERS))
    translations = {lang: dict(values) for lang, values in _TRANSLATIONS.items()}
    yield
    for keys, saved in zip(sets, saved_sets):
        keys.clear()
        keys.update(saved)
    config.DEFAULTS.clear()
    config.DEFAULTS.update(defaults)
    config.set_module_secret_registry(*module_secrets)
    _TRANSLATIONS.clear()
    _TRANSLATIONS.update(translations)


# Every create_app() asks git for the display version, and an untagged or shallow
# checkout answers "no tag" each time. The suite builds hundreds of apps, so that
# was hundreds of git processes per worker, which cost seconds on Windows runners.
# The tags cannot change during a test run, so each question is asked once.
# tests/test_version.py replaces _git_tag with fakes and still sees the real logic.
_version._git_tag = functools.lru_cache(maxsize=None)(_version._git_tag)


@pytest.fixture
def clear_version_cache():
    _version.get_available_app_version.cache_clear()
    yield
    _version.get_available_app_version.cache_clear()


@pytest.fixture
def running_app_version(request, monkeypatch, clear_version_cache):
    """Resolve the app version like a source checkout without a VERSION file."""
    tag = getattr(request, "param", "v2026-07-01.1")
    monkeypatch.setattr(_version, "_read_version_file", lambda: None)
    monkeypatch.setattr(_version, "_git_tag", lambda *args: tag if args == ("--abbrev=0",) else None)
    return _version.get_app_version()


# Route tests run without an admin password; DOCSight is only open then when the operator opts out.
OPEN_INSTANCE_ENVIRON = {"AUTH_DISABLED": "true"}


@pytest.fixture(scope="module")
def _module_route_app(tmp_path_factory):
    manager = ConfigManager(str(tmp_path_factory.mktemp("route-app")))
    application = create_app(
        config_manager=manager,
        module_loader_factory=default_module_loader_factory(manager, search_paths=[]),
        environ=dict(OPEN_INSTANCE_ENVIRON),
        testing=True,
    )
    with application.app_context():
        yield application


@pytest.fixture
def route_app(_module_route_app):
    """Return the module's shared factory app, inside its app context, with a clean runtime."""
    reset_runtime(get_runtime(_module_route_app))
    return _module_route_app


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
def foreign_system_tz(monkeypatch):
    """Give the process a system zone (UTC+14) unlike the configured zones of a test, where TZ can change at runtime."""
    if not hasattr(time, "tzset"):
        yield
        return
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def mock_storage(tmp_path_factory):
    """Return a storage mock whose database lives in its own temporary directory."""
    storage = MagicMock()
    storage.db_path = str(tmp_path_factory.mktemp("storage") / "test.db")
    storage.get_device_state.return_value = {}
    return storage


@pytest.fixture
def class_mock_storage(request, mock_storage):
    """Expose mock_storage as self.storage to the helpers of a test class."""
    request.instance.storage = mock_storage


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
