"""Focused contracts for saved Reports customer defaults."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from bs4 import BeautifulSoup
from flask import Flask
from jinja2 import ChoiceLoader, FileSystemLoader

from app import config as config_module
from app import module_loader as module_loader_module
from app import web
from app.config import ConfigManager
from app.module_loader import (
    ManifestError,
    ModuleLoader,
    discover_modules,
    register_module_config,
    setup_module_templates,
    validate_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "app" / "modules" / "reports"
REPORT_KEYS = {
    "report_customer_name",
    "report_customer_number",
    "report_customer_address",
}
SETTINGS_I18N_KEYS = {
    "report_settings_title",
    "report_settings_hint",
    "report_settings_privacy",
}


@pytest.fixture
def config_mgr(tmp_path):
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({
        "modem_password": "test",
        "modem_type": "fritzbox",
        "isp_name": "Vodafone",
    })
    return manager


@pytest.fixture
def client(config_mgr):
    web.init_config(config_mgr)
    web.init_storage(None)
    web.app.config["TESTING"] = True
    with web.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def sample_analysis():
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
            "us_capacity_mbps": 0,
        },
        "ds_channels": [],
        "us_channels": [],
    }


def _manifest(**updates):
    manifest = {
        "id": "docsight.reports_test",
        "name": "Reports",
        "description": "Report settings test module",
        "version": "1.0.0",
        "author": "DOCSight",
        "minAppVersion": "2026.2",
        "type": "analysis",
        "contributes": {},
        "config": {key: "" for key in REPORT_KEYS},
        "configPrivate": sorted(REPORT_KEYS),
    }
    manifest.update(updates)
    return manifest


@pytest.fixture
def reports_settings_module(monkeypatch):
    """Expose the checked-in Reports settings contribution to web templates."""
    raw = json.loads((REPORTS_DIR / "manifest.json").read_text(encoding="utf-8"))
    info = validate_manifest(raw, str(REPORTS_DIR), builtin=True)
    info.template_paths = setup_module_templates(info.id, info.path, info.contributes)
    register_module_config(
        info.config,
        module_id=info.id,
        builtin=True,
        config_private=info.config_private,
    )
    loader = SimpleNamespace(
        get_enabled_modules=lambda: [info],
        get_modules=lambda: [info],
        get_theme_modules=lambda: [],
    )

    old_module_loader = web._module_loader
    old_jinja_loader = web.app.jinja_loader
    web.init_modules(loader)
    web.app.jinja_loader = ChoiceLoader(
        [old_jinja_loader, FileSystemLoader(str(REPORTS_DIR / "templates"))]
    )
    web.app.jinja_env.cache.clear()
    try:
        yield info
    finally:
        web.init_modules(old_module_loader)
        web.app.jinja_loader = old_jinja_loader
        web.app.jinja_env.cache.clear()


def test_private_keys_encrypt_display_and_clear(tmp_path, monkeypatch):
    assert hasattr(config_module, "PRIVATE_KEYS")
    monkeypatch.setattr(config_module, "PRIVATE_KEYS", set(REPORT_KEYS))
    for key in REPORT_KEYS:
        monkeypatch.setitem(config_module.DEFAULTS, key, "")
    manager = ConfigManager(str(tmp_path / "data"))
    values = {
        "report_customer_name": "Max Mustermann",
        "report_customer_number": "KD-123456",
        "report_customer_address": "Musterstraße 1\n12345 Musterstadt",
    }

    manager.save(values.copy())

    raw = json.loads((tmp_path / "data" / "config.json").read_text(encoding="utf-8"))
    for key, value in values.items():
        assert raw[key] not in (value, "")
        assert manager.get(key) == value
        assert manager.get_all(mask_secrets=True)[key] == value

    manager.save({key: "" for key in REPORT_KEYS})
    cleared = json.loads((tmp_path / "data" / "config.json").read_text(encoding="utf-8"))
    for key in REPORT_KEYS:
        assert cleared[key] == ""
        assert manager.get(key) == ""


def test_private_values_are_hidden_from_demo_config_views(tmp_path, monkeypatch):
    assert hasattr(config_module, "PRIVATE_KEYS")
    monkeypatch.setattr(config_module, "PRIVATE_KEYS", set(REPORT_KEYS))
    for key in REPORT_KEYS:
        monkeypatch.setitem(config_module.DEFAULTS, key, "")
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({
        "report_customer_name": "Private Person",
        "report_customer_number": "PRIVATE-42",
        "report_customer_address": "Private Street",
        "demo_mode": True,
    })

    assert manager.get("report_customer_name") == "Private Person"
    visible = manager.get_all(mask_secrets=True)
    assert {key: visible[key] for key in REPORT_KEYS} == {key: "" for key in REPORT_KEYS}


def test_demo_settings_save_preserves_empty_hidden_private_values(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "PRIVATE_KEYS", set(REPORT_KEYS))
    for key in REPORT_KEYS:
        monkeypatch.setitem(config_module.DEFAULTS, key, "")
    manager = ConfigManager(str(tmp_path / "data"))
    values = {
        "report_customer_name": "Private Person",
        "report_customer_number": "PRIVATE-42",
        "report_customer_address": "Private Street",
    }
    manager.save({**values, "demo_mode": True, "isp_name": "Before save"})
    encrypted = json.loads(Path(manager.config_path).read_text(encoding="utf-8"))

    manager.save({
        **{key: "" for key in REPORT_KEYS},
        "isp_name": "Changed in demo mode",
    })

    raw = json.loads(Path(manager.config_path).read_text(encoding="utf-8"))
    assert manager.get("isp_name") == "Changed in demo mode"
    for key, value in values.items():
        assert manager.get(key) == value
        assert raw[key] == encrypted[key]
        assert raw[key] not in ("", value)


@pytest.mark.parametrize("value", ["report_customer_name", {"report_customer_name": True}, [1]])
def test_config_private_must_be_a_list_of_strings(value):
    with pytest.raises(ManifestError, match="configPrivate"):
        validate_manifest(_manifest(configPrivate=value), "/app/modules/reports", builtin=True)


def test_config_private_must_reference_declared_config_keys():
    with pytest.raises(ManifestError, match="report_customer_missing"):
        validate_manifest(
            _manifest(configPrivate=["report_customer_missing"]),
            "/app/modules/reports",
            builtin=True,
        )


def test_config_private_is_builtin_only():
    with pytest.raises(ManifestError, match="built-in"):
        validate_manifest(_manifest(), "/community/reports", builtin=False)


def test_community_discovery_cannot_infer_builtin_trust_from_its_path(tmp_path):
    community_root = tmp_path / "app" / "modules"
    module_dir = community_root / "reports"
    module_dir.mkdir(parents=True)
    (module_dir / "manifest.json").write_text(
        json.dumps(_manifest()),
        encoding="utf-8",
    )

    assert discover_modules(search_paths=[str(community_root)]) == []


def test_builtin_private_config_is_registered(monkeypatch):
    monkeypatch.setattr(config_module, "PRIVATE_KEYS", set())
    for key in REPORT_KEYS:
        monkeypatch.delitem(config_module.DEFAULTS, key, raising=False)

    info = validate_manifest(_manifest(), "/app/modules/reports", builtin=True)
    registered = register_module_config(
        info.config,
        module_id=info.id,
        builtin=True,
        config_private=info.config_private,
    )

    assert registered == REPORT_KEYS
    assert config_module.PRIVATE_KEYS == REPORT_KEYS


def test_disabled_builtin_still_registers_private_metadata(tmp_path, monkeypatch):
    builtin_root = tmp_path / "builtin"
    module_dir = builtin_root / "reports"
    module_dir.mkdir(parents=True)
    (module_dir / "manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setattr(module_loader_module, "BUILTIN_MODULE_DIRS", ("reports",))
    monkeypatch.setattr(config_module, "PRIVATE_KEYS", set())
    loader = ModuleLoader(
        Flask("disabled-private-module"),
        builtin_base_path=str(builtin_root),
        disabled_ids={"docsight.reports_test"},
    )

    modules = loader.load_all()

    reports_module = next(mod for mod in modules if mod.id == "docsight.reports_test")
    assert reports_module.enabled is False
    assert config_module.PRIVATE_KEYS == REPORT_KEYS


def test_reports_settings_panel_renders_saved_values(
    client, config_mgr, reports_settings_module
):
    values = {
        "report_customer_name": "Max Mustermann",
        "report_customer_number": "KD-123456",
        "report_customer_address": "Musterstraße 1\n12345 Musterstadt",
    }
    config_mgr.save(values.copy())
    web.init_config(config_mgr)

    response = client.get("/settings?lang=en")

    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    panel = soup.select_one("#panel-mod-docsight_reports")
    assert panel is not None
    assert "Customer details for reports" in panel.get_text(" ", strip=True)
    for key, value in values.items():
        field = panel.select_one(f"#{key}")
        assert field is not None
        if field.name == "textarea":
            assert field.get_text() == value
        else:
            assert field.get("value") == value


def test_existing_config_api_persists_encrypted_report_defaults(
    client, config_mgr, reports_settings_module
):
    values = {
        "report_customer_name": "API Person",
        "report_customer_number": "API-731",
        "report_customer_address": "API Street\nAPI City",
    }

    response = client.post("/api/config", json=values)

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    raw = json.loads(Path(config_mgr.config_path).read_text(encoding="utf-8"))
    for key, value in values.items():
        assert config_mgr.get(key) == value
        assert raw[key] not in (value, "")


def test_demo_settings_and_index_hide_saved_private_values(
    client, config_mgr, sample_analysis, reports_settings_module
):
    config_mgr.save({
        "report_customer_name": "Private Person",
        "report_customer_number": "PRIVATE-42",
        "report_customer_address": "Private Street",
        "demo_mode": True,
    })
    web.init_config(config_mgr)
    web.update_state(analysis=sample_analysis)

    settings_html = client.get("/settings?lang=en").get_data(as_text=True)
    index_html = client.get("/?lang=en").get_data(as_text=True)

    for secret in ("Private Person", "PRIVATE-42", "Private Street"):
        assert secret not in settings_html
        assert secret not in index_html
    soup = BeautifulSoup(index_html, "html.parser")
    assert soup.select_one("#report-name").get("value") == ""
    assert soup.select_one("#report-number").get("value") == ""
    assert soup.select_one("#report-address").get_text() == ""


def test_index_prefills_saved_customer_defaults_with_autoescaping(
    client, config_mgr, sample_analysis
):
    values = {
        "report_customer_name": '\"><script id="customer-xss">alert(1)</script>',
        "report_customer_number": "A&B<42>",
        "report_customer_address": '</textarea><img id="address-xss" src=x onerror=alert(1)>\nSecond line',
    }
    config_mgr.save(values.copy())
    web.init_config(config_mgr)
    web.update_state(analysis=sample_analysis)

    response = client.get("/?lang=en")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one("#customer-xss") is None
    assert soup.select_one("#address-xss") is None
    assert soup.select_one("#report-name").get("value") == values["report_customer_name"]
    assert soup.select_one("#report-number").get("value") == values["report_customer_number"]
    address = soup.select_one("textarea#report-address")
    assert address is not None
    assert address.get("rows") == "3"
    assert address.get_text() == values["report_customer_address"]
    template = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    for variable in REPORT_KEYS:
        assert f"{{{{ {variable} }}}}" in template
        assert f"{{{{ {variable}|safe }}}}" not in template


def test_index_report_fields_have_empty_server_defaults(client, config_mgr, sample_analysis):
    web.init_config(config_mgr)
    web.update_state(analysis=sample_analysis)

    soup = BeautifulSoup(client.get("/?lang=en").get_data(as_text=True), "html.parser")

    assert soup.select_one("#report-name").get("value") == ""
    assert soup.select_one("#report-number").get("value") == ""
    address = soup.select_one("textarea#report-address")
    assert address is not None
    assert address.get_text() == ""


def test_report_modal_reset_uses_default_values_without_persistence_side_channels():
    source = (ROOT / "app" / "static" / "js" / "utils.js").read_text(encoding="utf-8")
    start = source.index("function resetReportModalState()")
    end = source.index("\nfunction ", start + 1)
    reset_source = source[start:end]

    for field_id in ("report-name", "report-number", "report-address"):
        assert field_id in reset_source
    assert "defaultValue" in reset_source
    assert "localStorage" not in reset_source
    assert "/api/config" not in reset_source


def test_settings_form_serializer_includes_textareas():
    source = (ROOT / "app" / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    start = source.index("function getFormData()")
    end = source.index("\nfunction ", start + 1)

    assert "textarea" in source[start:end]


def test_reports_i18n_catalogs_are_valid_and_include_settings_copy():
    locale_dir = REPORTS_DIR / "i18n"
    english = json.loads((locale_dir / "en.json").read_text(encoding="utf-8"))
    assert SETTINGS_I18N_KEYS <= english.keys()

    for locale_path in sorted(locale_dir.glob("*.json")):
        catalog = json.loads(locale_path.read_text(encoding="utf-8"))
        assert catalog.keys() == english.keys(), locale_path.name
        for key in SETTINGS_I18N_KEYS:
            assert isinstance(catalog[key], str) and catalog[key].strip(), (
                locale_path.name,
                key,
            )


def test_direct_report_routes_do_not_fall_back_to_saved_customer_values():
    from app.modules.journal import routes as journal_routes
    from app.modules.reports import routes as report_routes

    saved = {
        "report_customer_name": "Stored Person",
        "report_customer_number": "STORED-42",
        "report_customer_address": "Stored Street",
    }
    config_manager = Mock()
    config_manager.get.side_effect = lambda key, default="": saved.get(key, default)
    analysis = {"summary": {"health": "critical"}, "ds_channels": [], "us_channels": []}
    report_storage = Mock()
    report_storage.get_range_data.return_value = []

    with web.app.test_request_context("/api/report"):
        with patch.object(report_routes, "get_storage", return_value=report_storage), patch.object(
            report_routes, "get_config_manager", return_value=config_manager
        ), patch.object(
            report_routes, "get_state", return_value={"analysis": analysis, "connection_info": {}}
        ), patch.object(report_routes, "generate_report", return_value=b"%PDF") as generate_report:
            getattr(report_routes.api_report, "__wrapped__")()
    assert generate_report.call_args.kwargs["customer_name"] == ""
    assert generate_report.call_args.kwargs["customer_number"] == ""
    assert generate_report.call_args.kwargs["customer_address"] == ""

    with web.app.test_request_context("/api/complaint"):
        with patch.object(report_routes, "get_storage", return_value=report_storage), patch.object(
            report_routes, "get_config_manager", return_value=config_manager
        ), patch.object(report_routes, "get_state", return_value={"analysis": analysis}), patch.object(
            report_routes, "generate_complaint_text", return_value="letter"
        ) as generate_complaint:
            getattr(report_routes.api_complaint, "__wrapped__")()
    assert generate_complaint.call_args.args[4:7] == ("", "", "")

    incident_storage = Mock()
    incident_storage.get_incident.return_value = {
        "id": 7,
        "name": "Outage",
        "status": "open",
        "start_date": None,
        "end_date": None,
    }
    incident_storage.get_entries.return_value = []
    with web.app.test_request_context("/api/incidents/7/report"):
        with patch.object(journal_routes, "_get_journal_storage", return_value=incident_storage), patch.object(
            journal_routes, "get_config_manager", return_value=config_manager
        ), patch.object(journal_routes, "get_state", return_value={"connection_info": {}}), patch(
            "app.modules.reports.report.generate_incident_report", return_value=b"%PDF"
        ) as generate_incident:
            getattr(journal_routes.api_incident_report, "__wrapped__")(7)
    assert generate_incident.call_args.kwargs["customer_name"] == ""
    assert generate_incident.call_args.kwargs["customer_number"] == ""
    assert generate_incident.call_args.kwargs["customer_address"] == ""
