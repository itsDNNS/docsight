"""Route-level authentication boundary coverage."""

from __future__ import annotations

import pytest
from flask import url_for

from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.web import app, init_config, init_storage


# Public routes are intentionally small and documented here so newly added
# routes must make an explicit choice: require authentication or extend this
# allowlist with a product reason.
PUBLIC_ENDPOINT_METHODS = {
    "health": {"GET"},  # container/runtime health probe
    "metrics_bp.metrics": {"GET"},  # Prometheus scrape endpoint
    "login": {"GET", "POST"},  # authentication entrypoint
    "service_worker": {"GET"},  # PWA service-worker asset
    "setup": {"GET"},  # first-run setup page
    "static": {"GET"},  # Flask static assets
}

PUBLIC_ENDPOINT_PREFIX_METHODS = {
    # Built-in module CSS/JS assets mounted by the module loader.
    "module_static_": {"GET"},
}

_IGNORED_METHODS = {"HEAD", "OPTIONS"}


_SAMPLE_VALUES = {
    "attachment_id": 1,
    "date": "2026-01-01",
    "entry_id": 1,
    "filename": "main.js",
    "incident_id": 1,
    "measurement_id": 1,
    "result_id": 1,
    "target": "example-target",
    "target_id": 1,
    "timespan": "24h",
    "timestamp": "2026-01-01T00:00:00Z",
    "trace_id": 1,
}


@pytest.fixture
def auth_client(tmp_path):
    """Unauthenticated client with admin auth enabled."""

    config = ConfigManager(str(tmp_path / "data"))
    config.save({
        "admin_password": "route-auth-secret",
        "modem_password": "test",
        "modem_type": "fritzbox",
    })
    init_config(config)
    init_storage(SnapshotStorage(str(tmp_path / "auth-routes.db"), max_days=7))
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _is_public_route_method(rule, method: str) -> bool:
    if method in PUBLIC_ENDPOINT_METHODS.get(rule.endpoint, set()):
        return True
    return any(
        rule.endpoint.startswith(prefix) and method in methods
        for prefix, methods in PUBLIC_ENDPOINT_PREFIX_METHODS.items()
    )


def _sample_value_for_rule(rule, argument: str):
    if argument in _SAMPLE_VALUES:
        return _SAMPLE_VALUES[argument]

    converter_name = rule._converters[argument].__class__.__name__
    if converter_name in {"IntegerConverter", "FloatConverter"}:
        return 1
    if converter_name == "PathConverter":
        return "sample/path"
    return "sample"


def _path_for_rule(rule) -> str:
    values = {argument: _sample_value_for_rule(rule, argument) for argument in rule.arguments}
    with app.test_request_context():
        return url_for(rule.endpoint, **values)


def _assert_auth_boundary(rule, response) -> None:
    if response.status_code in {301, 302, 303, 307, 308}:
        assert "/login" in response.headers.get("Location", "")
        return

    assert response.status_code == 401
    if rule.rule.startswith("/api/"):
        assert response.is_json
        assert response.get_json().get("error") == "Authentication required"


def test_routes_require_authentication_unless_explicitly_public(auth_client):
    """All protected route methods should enforce auth when admin_password is set."""

    checked = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda item: item.rule):
        path = _path_for_rule(rule)
        for method in sorted(rule.methods - _IGNORED_METHODS):
            if _is_public_route_method(rule, method):
                continue

            response = auth_client.open(path, method=method, follow_redirects=False)
            _assert_auth_boundary(rule, response)
            checked.append((method, rule.rule))

    assert checked, "auth coverage should exercise protected route methods"


def test_public_route_allowlist_matches_current_route_surface():
    """Keep the intentional public surface explicit and easy to review."""

    public_rules = sorted(
        (rule.endpoint, rule.rule, tuple(sorted(rule.methods & methods)))
        for rule in app.url_map.iter_rules()
        for endpoint, methods in [(rule.endpoint, PUBLIC_ENDPOINT_METHODS.get(rule.endpoint, set()))]
        if methods and rule.methods & methods
    )
    prefixed_public_rules = sorted(
        (rule.endpoint, rule.rule, tuple(sorted(rule.methods & methods)))
        for rule in app.url_map.iter_rules()
        for prefix, methods in PUBLIC_ENDPOINT_PREFIX_METHODS.items()
        if rule.endpoint.startswith(prefix) and rule.methods & methods
    )

    assert public_rules == [
        ("health", "/health", ("GET",)),
        ("login", "/login", ("GET", "POST")),
        ("metrics_bp.metrics", "/metrics", ("GET",)),
        ("service_worker", "/sw.js", ("GET",)),
        ("setup", "/setup", ("GET",)),
        ("static", "/static/<path:filename>", ("GET",)),
    ]
    assert all(
        endpoint.startswith("module_static_")
        and rule.startswith("/modules/")
        and methods == ("GET",)
        for endpoint, rule, methods in prefixed_public_rules
    )
