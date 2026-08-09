"""Integration regressions for server-generated URLs below SCRIPT_NAME."""

from __future__ import annotations

from copy import deepcopy
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import pytest

import app.web as web
from app.config import ConfigManager
from app.module_loader import ModuleInfo
from app.web import (
    _login_attempts,
    app,
    init_config,
    init_modules,
    init_storage,
    update_state,
)


PREFIX_ENV = {"SCRIPT_NAME": "/docsight"}


@pytest.fixture(autouse=True)
def _restore_app_globals():
    """Keep this module's singleton app mutations isolated from other tests."""
    previous_config_manager = web.get_config_manager()
    previous_config_callback = web.get_on_config_changed()
    previous_storage = web.get_storage()
    previous_state = web.get_state()
    previous_module_loader = web._module_loader
    previous_login_attempts = deepcopy(_login_attempts)
    previous_app_config = {
        key: app.config[key]
        for key in ("PERMANENT_SESSION_LIFETIME", "SECRET_KEY", "TESTING")
    }

    yield

    web._config_manager = previous_config_manager
    web._on_config_changed = previous_config_callback
    init_modules(previous_module_loader)
    init_storage(previous_storage)
    with web._state_lock:
        web._state.clear()
        web._state.update(previous_state)
    _login_attempts.clear()
    _login_attempts.update(previous_login_attempts)
    app.config.update(previous_app_config)


@pytest.fixture
def sample_analysis():
    """Minimal dashboard data needed to exercise rendered URL generation."""
    return {
        "summary": {
            "ds_total": 0,
            "us_total": 0,
            "ds_power_min": 0,
            "ds_power_max": 0,
            "ds_power_avg": 0,
            "us_power_min": 0,
            "us_power_max": 0,
            "us_power_avg": 0,
            "ds_snr_min": 0,
            "ds_snr_avg": 0,
            "ds_correctable_errors": 0,
            "ds_uncorrectable_errors": 0,
            "health": "good",
            "health_issues": [],
        },
        "ds_channels": [],
        "us_channels": [],
    }


@pytest.fixture
def client(tmp_path):
    """Create a configured client without relying on tests/web/conftest.py."""
    init_config(_configured_manager(tmp_path))
    init_modules(_enabled_bqm_loader())
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def _application_root_attributes(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [
        value
        for tag in soup.find_all(True)
        for attribute in ("href", "src", "action")
        if isinstance((value := tag.get(attribute)), str) and value.startswith("/")
    ]


def _browser_bootstrap(html: str) -> tuple[dict[str, str], BeautifulSoup]:
    soup = BeautifulSoup(html, "html.parser")
    element = soup.find("script", id="docsight-url-bootstrap")
    assert element is not None
    assert element.get("type") == "application/json"
    return json.loads(element.get_text()), soup


def _assert_url_helper_precedes_application_scripts(html: str, prefix: str) -> None:
    _, soup = _browser_bootstrap(html)
    scripts = soup.find_all("script")
    helper_index = next(
        index
        for index, script in enumerate(scripts)
        if (script.get("src") or "").startswith(f"{prefix}/static/js/url-contract.js")
    )
    bootstrap_index = next(
        index
        for index, script in enumerate(scripts)
        if script.get("id") == "docsight-url-bootstrap"
    )

    assert bootstrap_index < helper_index
    for index, script in enumerate(scripts):
        if index == bootstrap_index or index == helper_index:
            continue
        src = script.get("src")
        is_application_script = src is None or src.startswith(
            f"{prefix}/static/js/"
        ) or src.startswith(f"{prefix}/modules/")
        if is_application_script:
            assert index > helper_index


def _configured_manager(tmp_path, *, password: str = "") -> ConfigManager:
    manager = ConfigManager(str(tmp_path / "data"))
    values = {"modem_type": "fritzbox", "modem_password": "test"}
    if password:
        values["admin_password"] = password
    manager.save(values)
    return manager


def _enabled_bqm_loader():
    module = ModuleInfo(
        id="docsight.bqm",
        name="BQM",
        description="Test module context",
        version="1.0.0",
        author="DOCSight",
        min_app_version="2026.2",
        type="integration",
        contributes={},
        path="",
        menu={"order": 1},
    )

    class Loader:
        @staticmethod
        def get_enabled_modules():
            return [module]

        @staticmethod
        def get_modules():
            return [module]

        @staticmethod
        def get_theme_modules():
            return []

    return Loader()


def test_dashboard_and_settings_render_prefix_aware_navigation_and_assets(
    client, sample_analysis
):
    update_state(analysis=sample_analysis)

    dashboard = client.get("/?lang=en", environ_overrides=PREFIX_ENV)
    settings = client.get("/settings?lang=en", environ_overrides=PREFIX_ENV)

    assert dashboard.status_code == 200
    assert settings.status_code == 200
    dashboard_html = dashboard.get_data(as_text=True)
    settings_html = settings.get_data(as_text=True)
    for html in (dashboard_html, settings_html):
        root_attributes = _application_root_attributes(html)
        assert root_attributes
        assert all(value.startswith("/docsight/") for value in root_attributes)

    assert 'href="/docsight/settings"' in dashboard_html
    assert 'href="/docsight/settings#support"' in dashboard_html
    assert (
        'href="/docsight/api/events/export.csv?exclude_operational=true"'
        in dashboard_html
    )
    assert (
        'src="/docsight/modules/docsight.bqm/static/js/bqm-chart.js?v='
        in dashboard_html
    )
    assert 'href="/docsight/" class="sidebar-header"' in settings_html
    assert 'src="/docsight/static/js/settings.js?v=' in settings_html


def test_login_and_setup_render_prefix_aware_assets_forms_and_navigation(tmp_path):
    credential = "prefix-" + "credential"
    auth_manager = _configured_manager(tmp_path, password=credential)
    init_config(auth_manager)
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        login = client.get("/login", environ_overrides=PREFIX_ENV)

    assert login.status_code == 200
    login_html = login.get_data(as_text=True)
    assert _application_root_attributes(login_html)
    assert all(
        value.startswith("/docsight/")
        for value in _application_root_attributes(login_html)
    )
    assert 'href="/docsight/static/css/fonts.css?v=' in login_html

    setup_manager = ConfigManager(str(tmp_path / "setup-data"))
    init_config(setup_manager)
    with app.test_client() as client:
        setup = client.get("/setup", environ_overrides=PREFIX_ENV)

    assert setup.status_code == 200
    setup_html = setup.get_data(as_text=True)
    assert all(
        value.startswith("/docsight/")
        for value in _application_root_attributes(setup_html)
    )
    assert 'action="/docsight/api/config"' in setup_html
    assert 'var SETUP_INDEX_URL = "/docsight/";' in setup_html
    assert 'var SETUP_LOGIN_URL = "/docsight/login";' in setup_html


def test_auth_setup_glossary_and_backup_redirects_preserve_script_name(tmp_path):
    _login_attempts.clear()
    credential = "prefix-" + "credential"
    auth_manager = _configured_manager(tmp_path, password=credential)
    init_config(auth_manager)
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        auth_redirect = client.get("/settings", environ_overrides=PREFIX_ENV)
        restore_redirect = client.post(
            "/api/restore/validate", environ_overrides=PREFIX_ENV
        )
        login_page = client.get("/login", environ_overrides=PREFIX_ENV)
        csrf = re.search(
            r'name="csrf_token" value="([^"]+)"', login_page.get_data(as_text=True)
        )
        assert csrf is not None
        login_redirect = client.post(
            "/login",
            data={"password": credential, "csrf_token": csrf.group(1)},
            environ_overrides=PREFIX_ENV,
        )
        authenticated_dashboard = client.get("/", environ_overrides=PREFIX_ENV)
        logout_redirect = client.post("/logout", environ_overrides=PREFIX_ENV)

    assert auth_redirect.headers["Location"] == "/docsight/login"
    assert restore_redirect.headers["Location"] == "/docsight/login"
    assert login_redirect.headers["Location"] == "/docsight/"
    assert 'action="/docsight/logout"' in authenticated_dashboard.get_data(as_text=True)
    assert logout_redirect.headers["Location"] == "/docsight/login"

    configured_manager = _configured_manager(tmp_path / "configured")
    init_config(configured_manager)
    with app.test_client() as client:
        setup_redirect = client.get("/setup", environ_overrides=PREFIX_ENV)
        glossary_redirect = client.get(
            "/glossary?lang=en&term=sc_qam", environ_overrides=PREFIX_ENV
        )
    assert setup_redirect.headers["Location"] == "/docsight/"
    assert (
        glossary_redirect.headers["Location"]
        == "/docsight/?lang=en#glossary?term=sc_qam"
    )

    unconfigured_manager = ConfigManager(str(tmp_path / "unconfigured"))
    init_config(unconfigured_manager)
    with app.test_client() as client:
        index_redirect = client.get("/", environ_overrides=PREFIX_ENV)
    assert index_redirect.headers["Location"] == "/docsight/setup"


def test_root_mount_keeps_existing_effective_server_generated_paths(
    client, sample_analysis
):
    update_state(analysis=sample_analysis)

    response = client.get("/?lang=en")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'href="/settings"' in html
    assert 'src="/static/js/modals.js?v=' in html
    assert 'src="/modules/docsight.bqm/static/js/bqm-chart.js?v=' in html


@pytest.mark.parametrize(
    ("environ", "mount_path"),
    [({}, ""), (PREFIX_ENV, "/docsight")],
    ids=["root", "docsight-prefix"],
)
def test_pwa_routes_and_manifest_identity_follow_effective_mount(
    client, sample_analysis, environ, mount_path
):
    update_state(analysis=sample_analysis)

    dashboard = client.get("/", environ_overrides=environ)
    service_worker = client.get("/sw.js", environ_overrides=environ)
    manifest_response = client.get(
        "/static/manifest.json", environ_overrides=environ
    )

    assert dashboard.status_code == 200
    assert f'rel="manifest" href="{mount_path}/static/manifest.json"' in dashboard.get_data(
        as_text=True
    )
    assert service_worker.status_code == 200
    assert service_worker.mimetype == "application/javascript"
    assert "self.registration.scope" in service_worker.get_data(as_text=True)
    assert manifest_response.status_code == 200
    assert manifest_response.mimetype == "application/manifest+json"
    manifest = manifest_response.get_json()
    expected_id = f"{mount_path}/"
    assert manifest["id"] == expected_id
    assert manifest["start_url"] == "../?source=pwa"
    assert manifest["scope"] == "../"

    manifest_url = f"https://example.test{mount_path}/static/manifest.json"
    start_url = urljoin(manifest_url, manifest["start_url"])
    parsed_start_url = urlsplit(start_url)
    start_url_origin = f"{parsed_start_url.scheme}://{parsed_start_url.netloc}/"
    assert urljoin(start_url_origin, manifest["id"]) == (
        f"https://example.test{expected_id}"
    )


def test_browser_url_bootstrap_is_minimal_canonical_and_early(
    client, sample_analysis, tmp_path
):
    update_state(analysis=sample_analysis)
    dashboard_html = client.get(
        "/?lang=en", environ_overrides=PREFIX_ENV
    ).get_data(as_text=True)
    settings_html = client.get(
        "/settings?lang=en", environ_overrides=PREFIX_ENV
    ).get_data(as_text=True)

    credential = "bootstrap-credential"
    init_config(_configured_manager(tmp_path / "auth", password=credential))
    login_html = client.get(
        "/login", environ_overrides=PREFIX_ENV
    ).get_data(as_text=True)

    init_config(ConfigManager(str(tmp_path / "setup")))
    setup_html = client.get(
        "/setup", environ_overrides=PREFIX_ENV
    ).get_data(as_text=True)

    for html in (dashboard_html, settings_html, login_html, setup_html):
        bootstrap, _ = _browser_bootstrap(html)
        assert bootstrap == {"basePath": "/docsight"}
        assert set(bootstrap) == {"basePath"}
        _assert_url_helper_precedes_application_scripts(html, "/docsight")


def test_root_browser_url_bootstrap_preserves_root_deployment(client, sample_analysis):
    update_state(analysis=sample_analysis)

    html = client.get("/?lang=en").get_data(as_text=True)
    bootstrap, _ = _browser_bootstrap(html)

    assert bootstrap == {"basePath": ""}
    _assert_url_helper_precedes_application_scripts(html, "")
