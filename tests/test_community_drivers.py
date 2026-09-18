"""Community modem drivers use the complete application registration path."""

import json
from unittest.mock import patch

import pytest
from flask import Flask

from app.app_factory import create_app, default_module_loader_factory
from app.config import ConfigManager
from app.manifest_contract import validate_manifest_contract
from app.module_loader import ModuleLoader
from app.runtime import get_runtime

DRIVER_ID = "community.example"
DRIVER_SOURCE = '''from app.drivers.generic import GenericDriver
from .helper import MODEL

class ExampleDriver(GenericDriver):
    def login(self):
        assert self._user == "tester"
        assert self._password == "test-password"

    def get_device_info(self):
        return {"model": MODEL, "sw_version": "1.0"}
'''


def write_driver(root, **overrides):
    directory = root / "example"
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": DRIVER_ID, "name": "Example Driver", "description": "Example",
        "version": "1.0.0", "author": "someone", "minAppVersion": "2026.2",
        "type": "driver", "contributes": {"driver": "driver.py:ExampleDriver"},
        "hints": {"default_user": "tester", "default_url": "http://192.0.2.1"},
    }
    manifest.update(overrides)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "driver.py").write_text(DRIVER_SOURCE)
    (directory / "helper.py").write_text('MODEL = "Community Test Modem"\n')
    return directory, manifest


def make_app(tmp_path, *, disabled="", search=True, modem_type=DRIVER_ID):
    config = ConfigManager(str(tmp_path / "data"))
    config.save({"modem_type": modem_type, "modem_url": "http://192.0.2.1",
                 "modem_user": "tester", "modem_password": "test-password",
                 "disabled_modules": disabled, "update_check_enabled": False})
    application = create_app(
        config_manager=config, testing=True, environ={},
        module_loader_factory=default_module_loader_factory(
            config, search_paths=[str(tmp_path / "modules")] if search else []),
    )
    return application, get_runtime(application)


@pytest.mark.parametrize("driver_id", [DRIVER_ID, "ch7465_play"])
def test_community_driver_complete_workflow(tmp_path, driver_id):
    _, manifest = write_driver(tmp_path / "modules", id=driver_id)
    assert validate_manifest_contract(manifest) == []
    application, runtime = make_app(tmp_path, modem_type=driver_id)
    module = next(m for m in runtime.module_loader.get_modules() if m.id == driver_id)
    assert module.error is None
    assert module.driver_class is not None
    registry = runtime.driver_registry
    assert (driver_id, "Example Driver") in registry.get_available_drivers()
    driver = registry.load_driver(driver_id, "http://192.0.2.1", "tester", "test-password")
    driver.login()
    assert driver.get_device_info()["model"] == "Community Test Modem"
    client = application.test_client()
    for path in ("/setup", "/settings"):
        with patch.object(runtime.config_manager, "is_configured", return_value=path != "/setup"):
            response = client.get(path)
        assert response.status_code == 200
        assert f'<option value="{driver_id}"' in response.text
    response = client.post("/api/test-modem", json={
        "modem_type": driver_id, "modem_user": "tester", "modem_password": "test-password"})
    assert response.json == {"success": True, "model": "Community Test Modem"}
    assert client.post("/api/config", json={"modem_type": driver_id}).status_code == 200
    from app import analyzer
    from app.collectors import discover_collectors
    from app.event_detector import EventDetector
    from app.storage import SnapshotStorage
    storage = SnapshotStorage(str(tmp_path / "history.db"))
    collectors = discover_collectors(runtime.config_manager, storage, EventDetector(),
                                     None, runtime, analyzer)
    modem = next(c for c in collectors if c.name == "modem")
    assert isinstance(modem._driver, module.driver_class)
    modem.collect()
    assert runtime.get_state()["device_info"]["model"] == "Community Test Modem"


def test_preflight_does_not_register_driver(tmp_path):
    write_driver(tmp_path)
    app = Flask(__name__)
    app.extensions["docsight_registration_deferred"] = True
    loader = ModuleLoader(app, search_paths=[str(tmp_path)])
    module = loader.load_all()[0]
    assert module.error is None
    assert module.driver_class is None
    assert loader.registration_plan.modules[0].driver_class is not None
    from app.drivers import driver_registry
    assert not driver_registry.has_driver(DRIVER_ID)


@pytest.mark.parametrize("spec", ["driver.py", "../secret.py:Secret", "/secret.py:Secret",
                                  "missing.py:ExampleDriver", "driver.py:Missing", "driver.py:"])
def test_invalid_driver_rejected_without_details(tmp_path, spec, caplog):
    write_driver(tmp_path, contributes={"driver": spec})
    loader = ModuleLoader(Flask(__name__), search_paths=[str(tmp_path)])
    module = loader.load_all()[0]
    assert module.error
    assert module.driver_class is None
    assert not loader.registration_plan.modules
    assert str(tmp_path) not in module.error + caplog.text
    assert spec not in module.error + caplog.text


@pytest.mark.parametrize("source", [
    'ExampleDriver = 123',
    'class ExampleDriver: pass',
    'from app.drivers.base import ModemDriver as ExampleDriver',
    'from app.drivers.base import ModemDriver\nclass ExampleDriver(ModemDriver): pass',
    'from abc import abstractmethod\nfrom app.drivers.generic import GenericDriver\nclass ExampleDriver(GenericDriver):\n @abstractmethod\n def login(self): pass',
    'raise RuntimeError("private-password /private/path")',
    'from .missing import ExampleDriver',
    'def __getattr__(name): raise RuntimeError("private-password /private/path")',
])
def test_invalid_class_or_import_rejects_whole_module(tmp_path, source, caplog):
    directory, _ = write_driver(tmp_path, contributes={"driver": "driver.py:ExampleDriver", "static": "static/"})
    (directory / "static").mkdir()
    (directory / "driver.py").write_text(source)
    app = Flask(__name__)
    loader = ModuleLoader(app, search_paths=[str(tmp_path)])
    module = loader.load_all()[0]
    assert module.error and module.driver_class is None
    assert not loader.registration_plan.modules
    assert "module_static_community.example" not in app.view_functions
    assert "private-password" not in module.error + caplog.text
    assert "/private/path" not in module.error + caplog.text


def test_driver_symlink_outside_module_rejected(tmp_path):
    directory, _ = write_driver(tmp_path / "modules")
    (tmp_path / "secret.py").write_text('raise AssertionError("must not import")')
    (directory / "driver.py").unlink()
    (directory / "driver.py").symlink_to(tmp_path / "secret.py")
    _, runtime = make_app(tmp_path)
    module = next(m for m in runtime.module_loader.get_modules() if m.id == DRIVER_ID)
    assert module.error == "driver contribution reference is unsafe"
    assert not runtime.driver_registry.has_driver(DRIVER_ID)


@pytest.mark.parametrize("hints", [{"unknown": True}, {"credentials_required": "false"},
    {"default_user": []}, {"default_url": "https://%"}, {"default_url": "http://[fe80::1%25eth0]"}, {"default_url": "http://999.999.999.999"}, {"default_url": "http://example.org/\u0000"}, {"default_url": "javascript:alert(1)"},
    {"default_url": "https://user:password@example.org"}, {"default_url": "http://[broken"},
    {"default_url": "https://example.org:99999"}, {"default_user": "x" * 20001},
    {"__proto__": {}}, {"default_url": "https://example.org\\bad"}])
def test_driver_hints_reject_browser_bootstrap_failures(tmp_path, hints):
    _, manifest = write_driver(tmp_path, hints=hints)
    assert "Invalid driver hints or driver key" in validate_manifest_contract(manifest)


@pytest.mark.parametrize("module_id", ["constructor", "prototype", "c" * 129])
def test_driver_key_must_fit_browser_contract(tmp_path, module_id):
    _, manifest = write_driver(tmp_path, id=module_id)
    assert "Invalid driver hints or driver key" in validate_manifest_contract(manifest)


@pytest.mark.parametrize("mode", ["disabled", "missing", "broken"])
def test_unavailable_driver_preserves_config_and_fails_safely(tmp_path, mode):
    directory, _ = write_driver(tmp_path / "modules")
    if mode == "broken":
        (directory / "driver.py").write_text('raise RuntimeError("private-password")')
    application, runtime = make_app(tmp_path, disabled=DRIVER_ID if mode == "disabled" else "", search=mode != "missing")
    assert not runtime.driver_registry.has_driver(DRIVER_ID)
    assert runtime.config_manager.get("modem_type") == DRIVER_ID
    client = application.test_client()
    html = client.get("/settings").text
    assert f'value="{DRIVER_ID}" selected' in html
    assert client.post("/api/config", json={"modem_type": DRIVER_ID, "modem_user": "tester"}).status_code == 200
    assert client.post("/api/config", json={"modem_type": "community.missing"}).status_code == 400
    assert client.post("/api/test-modem", json={"modem_type": DRIVER_ID}).json["success"] is False
    from app import analyzer
    from app.collectors import discover_collectors
    from app.event_detector import EventDetector
    from app.storage import SnapshotStorage
    storage = SnapshotStorage(str(tmp_path / "history.db"))
    collectors = discover_collectors(runtime.config_manager, storage, EventDetector(), None, runtime, analyzer)
    modem = next(c for c in collectors if c.name == "modem")
    with pytest.raises(RuntimeError, match="Configured modem driver is unavailable"):
        modem.collect()
    assert runtime.config_manager.get("modem_type") == DRIVER_ID


def test_apps_and_reloads_do_not_share_driver_classes_or_hints(tmp_path):
    directory, _ = write_driver(tmp_path / "modules")
    first_app, first = make_app(tmp_path)
    (directory / "helper.py").write_text('MODEL = "Reloaded Community Modem"\n')
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["hints"]["default_user"] = "second-user"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    _, second = make_app(tmp_path)
    _, disabled = make_app(tmp_path, disabled=DRIVER_ID)
    _, empty = make_app(tmp_path, search=False)
    for runtime in (disabled, empty):
        assert not runtime.driver_registry.has_driver(DRIVER_ID)
        assert DRIVER_ID not in runtime.driver_registry.get_driver_hints()
    one = first.driver_registry.load_driver(DRIVER_ID, "", "", "")
    two = second.driver_registry.load_driver(DRIVER_ID, "", "", "")
    assert one.get_device_info()["model"] == "Community Test Modem"
    assert two.get_device_info()["model"] == "Reloaded Community Modem"
    assert type(one) is not type(two)
    assert first.driver_registry.get_driver_hints()[DRIVER_ID]["default_user"] == "tester"
    assert second.driver_registry.get_driver_hints()[DRIVER_ID]["default_user"] == "second-user"
    assert DRIVER_ID.encode() in first_app.test_client().get("/settings").data
    from app.drivers import driver_registry
    assert not driver_registry.has_driver(DRIVER_ID)
    assert first.driver_registry.get_all_type_keys() == driver_registry.get_all_type_keys() | {DRIVER_ID}
    for key, hints in driver_registry.get_driver_hints().items():
        assert first.driver_registry.get_driver_hints()[key] == hints
    assert first.driver_registry.load_driver("ch7465_play", "http://192.0.2.1", "", "")._is_play is True


@pytest.mark.parametrize("state", ["disabled", "removed", "broken", "invalid_contribution"])
def test_builtin_override_is_app_owned_and_restores_pristine_fallback(tmp_path, state):
    from app.drivers import driver_registry

    key = "ch7465_play"
    builtin_names = driver_registry.get_available_drivers()
    builtin_hints = driver_registry.get_driver_hints()
    builtin_class = type(driver_registry.load_driver(key, "", "", ""))
    directory, manifest = write_driver(tmp_path / "modules", id=key)
    application, runtime = make_app(tmp_path, modem_type=key)
    registry = runtime.driver_registry
    module = next(m for m in runtime.module_loader.get_modules() if m.id == key)
    assert module.error is None
    assert not registry.is_builtin(key)
    assert (key, "Example Driver") in registry.get_available_drivers()
    assert registry.get_driver_hints()[key] == manifest["hints"]
    driver = registry.load_driver(key, "http://192.0.2.1", "tester", "test-password")
    assert type(driver) is module.driver_class
    driver.login()
    assert driver._url == "http://192.0.2.1"
    assert not hasattr(driver, "_is_play")

    _, independent = make_app(tmp_path / "independent", modem_type=key, search=False)
    config = runtime.config_manager
    paths = [str(tmp_path / "modules")]
    if state == "disabled":
        config.save({"disabled_modules": key})
        (directory / "driver.py").write_text('raise AssertionError("disabled code executed")')
    elif state == "removed":
        paths = []
    elif state == "broken":
        (directory / "driver.py").write_text('raise RuntimeError("broken override")')
    else:
        manifest["contributes"]["thresholds"] = "missing.json"
        (directory / "manifest.json").write_text(json.dumps(manifest))
    restarted = create_app(config_manager=config, testing=True, environ={},
                           module_loader_factory=default_module_loader_factory(
                               config, search_paths=paths))
    restored = get_runtime(restarted)
    for fallback in (driver_registry, independent.driver_registry, restored.driver_registry):
        assert fallback.is_builtin(key)
        assert fallback.get_available_drivers() == builtin_names
        assert fallback.get_driver_hints() == builtin_hints
        instance = fallback.load_driver(key, "http://192.0.2.1", "tester", "test-password")
        assert type(instance) is builtin_class
        assert instance._is_play is True
    assert restored.config_manager.get("modem_type") == key
    assert type(registry.load_driver(key, "", "", "")) is module.driver_class
    assert registry.get_driver_hints()[key] == manifest["hints"]
    if state != "removed":
        rejected = next(m for m in restored.module_loader.get_modules() if m.id == key)
        assert rejected.driver_class is None
        if state == "disabled":
            assert rejected.error is None
        else:
            assert rejected.error


@pytest.mark.parametrize("exception", ["ValueError", "RuntimeError"])
def test_builtin_override_connection_errors_are_redacted(tmp_path, caplog, exception):
    directory, _ = write_driver(tmp_path / "modules", id="fritzbox")
    (directory / "driver.py").write_text(DRIVER_SOURCE + f'''
    def login(self):
        raise {exception}("private-password /private/path")
''')
    application, runtime = make_app(tmp_path, modem_type="fritzbox")
    assert not runtime.driver_registry.is_builtin("fritzbox")
    response = application.test_client().post("/api/test-modem", json={"modem_type": "fritzbox"})
    assert response.json == {"success": False, "error": "Community modem connection failed"}
    assert "private-password" not in response.text + caplog.text
    assert "/private/path" not in response.text + caplog.text


def test_builtin_override_preflight_does_not_mutate_active_registry(tmp_path):
    from app.drivers import driver_registry

    application, runtime = make_app(tmp_path, search=False)
    registry = runtime.driver_registry
    names, hints = registry.get_available_drivers(), registry.get_driver_hints()
    write_driver(tmp_path / "modules", id="fritzbox")
    application.extensions["docsight_registration_deferred"] = True
    loader = ModuleLoader(application, search_paths=[str(tmp_path / "modules")])
    module = loader.load_all()[0]
    assert module.error is None
    assert module.driver_class is None
    assert loader.registration_plan.modules[0].driver_class is not None
    assert runtime.driver_registry is registry
    assert application.extensions["docsight_driver_registry"] is registry
    for untouched in (registry, driver_registry):
        assert untouched.is_builtin("fritzbox")
        assert untouched.get_available_drivers() == names
        assert untouched.get_driver_hints() == hints


def test_other_contribution_failure_does_not_register_driver(tmp_path):
    write_driver(tmp_path / "modules", contributes={"driver": "driver.py:ExampleDriver", "thresholds": "missing.json"})
    _, runtime = make_app(tmp_path)
    assert not runtime.driver_registry.has_driver(DRIVER_ID)
    assert DRIVER_ID not in runtime.driver_registry.get_driver_hints()


def test_install_enable_restart_registers_driver(tmp_path, monkeypatch):
    import shutil

    source, _ = write_driver(tmp_path / "download")
    application, runtime = make_app(tmp_path)
    monkeypatch.setenv("MODULES_DIR", str(tmp_path / "modules"))

    def download(_url, target):
        shutil.copytree(source, target, dirs_exist_ok=True)
        return True

    with patch("app.blueprints.modules_bp.download_github_directory", side_effect=download):
        response = application.test_client().post("/api/modules/install", json={
            "id": DRIVER_ID, "download_url": "https://api.github.com/repos/example/driver/contents/module"})
    assert response.status_code == 200 and response.json["success"]
    assert (tmp_path / "modules" / DRIVER_ID / "driver.py").is_file()
    assert DRIVER_ID in runtime.config_manager.get("disabled_modules")

    def restart():
        app = create_app(config_manager=runtime.config_manager, testing=True, environ={},
                         module_loader_factory=default_module_loader_factory(
                             runtime.config_manager, search_paths=[str(tmp_path / "modules")]))
        return app, get_runtime(app)

    disabled_app, disabled = restart()
    assert not disabled.driver_registry.has_driver(DRIVER_ID)
    response = disabled_app.test_client().post(f"/api/modules/{DRIVER_ID}/enable")
    assert response.json == {"success": True, "restart_required": True}
    enabled_app, enabled = restart()
    assert enabled.driver_registry.has_driver(DRIVER_ID)
    assert enabled_app.test_client().post("/api/test-modem", json={
        "modem_type": DRIVER_ID, "modem_user": "tester", "modem_password": "test-password"
    }).json["model"] == "Community Test Modem"


def test_community_constructor_errors_are_redacted(tmp_path, caplog):
    directory, _ = write_driver(tmp_path / "modules")
    (directory / "driver.py").write_text(DRIVER_SOURCE + '''
    def __init__(self, url, user, password):
        raise RuntimeError("private-password /private/path")
''')
    application, runtime = make_app(tmp_path)
    response = application.test_client().post("/api/test-modem", json={"modem_type": DRIVER_ID})
    assert response.json == {"success": False, "error": "Community modem connection failed"}
    driver = runtime.driver_registry.load_for_polling(DRIVER_ID, "", "", "")
    with pytest.raises(RuntimeError, match="Configured modem driver is unavailable"):
        driver.login()
    assert "private-password" not in caplog.text
    assert "/private/path" not in caplog.text


def test_valid_hints_match_actual_browser_parser(tmp_path):
    import subprocess
    from pathlib import Path

    _, manifest = write_driver(tmp_path, hints={
        "default_url": "https://[::1]:8443/", "default_user": "tester",
        "needs_user": True, "needs_password": True, "username_required": True,
        "credentials_required": True, "url_hint": None, "user_hint": "user",
        "password_hint": "password",
    })
    assert validate_manifest_contract(manifest) == []
    payload = {"translations": {}, "driverHints": {DRIVER_ID: manifest["hints"]},
               "indexUrl": "/", "loginUrl": "/login"}
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["node", "-e", '''
const fs = require('node:fs');
const contracts = require('./app/static/js/browser-contracts.js');
contracts.parseSetupBootstrapText(fs.readFileSync(0, 'utf8'));
'''], input=json.dumps(payload), cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_demo_mode_does_not_show_its_synthetic_key_as_an_unavailable_driver(tmp_path):
    application, runtime = make_app(tmp_path)
    runtime.config_manager.save({"demo_mode": True, "modem_type": "demo"})
    html = application.test_client().get("/settings").text
    assert '<option value="demo"' not in html
    assert '<option value="fritzbox"' in html
