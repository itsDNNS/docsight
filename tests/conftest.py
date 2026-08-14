"""Shared factory fixtures for DOCSight tests."""

import importlib
import json
import os
from pathlib import Path

import pytest

from app.app_factory import create_app, default_module_loader_factory
from app.config import ConfigManager
from app.builtin_modules import BUILTIN_MODULE_DIRS
from app.module_loader import module_static_endpoint, setup_module_static
from app.runtime import DerivedStorageCache, LoginRateLimiter, RuntimeState, get_runtime


FACTORY_CONTEXT_MODULES = {
    "tests.test_auth", "tests.test_bqm", "tests.test_channel_timeline",
    "tests.test_comparison_module", "tests.test_correlation", "tests.test_demo_mode",
    "tests.test_device_info_display", "tests.test_events", "tests.test_evidence_api",
    "tests.test_first_run_demo", "tests.test_first_run_ux", "tests.test_metrics_endpoint",
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


def register_builtin_test_routes(app):
    """Register shipped module route and static contributions on one test app."""
    module_base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "modules"))
    blueprints = set(app.blueprints)
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    for module_dir in BUILTIN_MODULE_DIRS:
        manifest_path = os.path.join(module_base, module_dir, "manifest.json")
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except OSError:
            continue
        contributes = manifest.get("contributes", {})
        if "routes" in contributes:
            try:
                routes = importlib.import_module(f"app.modules.{module_dir}.routes")
            except ImportError:
                routes = None
            blueprint = getattr(routes, "bp", None) or getattr(routes, "blueprint", None)
            if blueprint is not None and blueprint.name not in blueprints:
                app.register_blueprint(blueprint)
                blueprints.add(blueprint.name)
        static_subdir = contributes.get("static")
        endpoint = module_static_endpoint(manifest["id"])
        if static_subdir and endpoint not in endpoints:
            setup_module_static(app, manifest["id"], os.path.join(module_base, module_dir), static_subdir)
            endpoints.add(endpoint)
    return app


@pytest.fixture(autouse=True, scope="module")
def _factory_context_for_direct_route_tests(request, tmp_path_factory):
    """Give direct route-unit modules an isolated factory app and context."""
    if not _uses_factory_context(request.module):
        yield
        return
    manager = ConfigManager(str(tmp_path_factory.mktemp("factory-context")))
    application = register_builtin_test_routes(create_app(
        config_manager=manager,
        environ={},
        testing=True,
    ))
    request.module.app = application
    with application.app_context():
        yield


@pytest.fixture(autouse=True)
def _reset_direct_route_runtime(request):
    if not _uses_factory_context(request.module):
        yield
        return
    runtime = get_runtime(request.module.app)
    runtime.storage = None
    runtime.on_config_changed = None
    runtime.module_loader = None
    runtime.modem_collector = None
    runtime.collectors = []
    runtime.state = RuntimeState()
    runtime.login_rate_limiter = LoginRateLimiter()
    runtime.derived_storage = DerivedStorageCache()
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
            environ={} if environ is None else environ,
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
