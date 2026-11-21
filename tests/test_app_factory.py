import pytest
from werkzeug.middleware.proxy_fix import ProxyFix

from app.app_factory import create_app
from app.base_path import BasePathMiddleware, RequestScopedCookieSessionInterface
from app.config import ConfigManager
from app.runtime import get_runtime


CORE_ENDPOINTS = {
    "desktop_runtime": ("/desktop-runtime", {"GET", "HEAD", "OPTIONS"}),
    "glossary_page": ("/glossary", {"GET", "HEAD", "OPTIONS"}),
    "health": ("/health", {"GET", "HEAD", "OPTIONS"}),
    "index": ("/", {"GET", "HEAD", "OPTIONS"}),
    "login": ("/login", {"GET", "POST", "HEAD", "OPTIONS"}),
    "logout": ("/logout", {"POST", "OPTIONS"}),
    "service_worker": ("/sw.js", {"GET", "HEAD", "OPTIONS"}),
    "settings": ("/settings", {"GET", "HEAD", "OPTIONS"}),
    "setup": ("/setup", {"GET", "HEAD", "OPTIONS"}),
    "web_app_manifest": ("/static/manifest.json", {"GET", "HEAD", "OPTIONS"}),
}


def test_create_app_requires_config_manager():
    with pytest.raises(TypeError, match="config_manager"):
        create_app(config_manager=None)


def test_factory_preserves_core_endpoints_filters_and_manifest(tmp_path):
    app = create_app(
        config_manager=ConfigManager(str(tmp_path / "data")),
        environ={},
        testing=True,
    )
    rules = {rule.endpoint: (rule.rule, rule.methods) for rule in app.url_map.iter_rules()}
    for endpoint, expected in CORE_ENDPOINTS.items():
        assert rules[endpoint] == expected
    assert {
        "safe_html", "fmt_k", "fmt_speed_value", "fmt_speed_unit", "fmt_uptime",
        "localtime", "localiso",
    }.issubset(app.jinja_env.filters)
    response = app.test_client().get("/static/manifest.json")
    assert response.status_code == 200
    assert response.mimetype == "application/manifest+json"
    assert get_runtime(app).config_manager.data_dir == str(tmp_path / "data")


def test_factory_installs_base_path_then_outer_proxy(tmp_path):
    app = create_app(
        config_manager=ConfigManager(str(tmp_path / "data")),
        environ={"BASE_PATH": "/docsight", "REVERSE_PROXY": "1"},
    )
    assert isinstance(app.wsgi_app, ProxyFix)
    assert isinstance(app.wsgi_app.app, BasePathMiddleware)
    assert isinstance(app.session_interface, RequestScopedCookieSessionInterface)
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_factory_drops_module_registries_of_an_earlier_app(tmp_path):
    from app import config as config_module, i18n

    def registries():
        return (
            config_module.DEFAULTS, config_module.SECRET_KEYS, config_module.PRIVATE_KEYS,
            config_module.INT_KEYS, config_module.BOOL_KEYS, config_module.MODULE_SECRET_KEYS,
            config_module.MODULE_SECRET_OWNERS, i18n._TRANSLATIONS, i18n._TRANSLATIONS["en"],
        )

    before = registries()
    config_module.set_module_secret_registry({"stale_secret"}, {"stale_secret": "community.stale"})
    config_module.SECRET_KEYS.add("stale_builtin_secret")
    config_module.PRIVATE_KEYS.add("stale_private")

    create_app(config_manager=ConfigManager(str(tmp_path / "core-only")), environ={}, testing=True)

    assert not config_module.MODULE_SECRET_KEYS
    assert not config_module.MODULE_SECRET_OWNERS
    assert "stale_builtin_secret" not in config_module.SECRET_KEYS
    assert "stale_private" not in config_module.PRIVATE_KEYS
    assert all(now is then for now, then in zip(registries(), before))
