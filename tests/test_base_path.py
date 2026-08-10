"""Focused tests for proxy-stripped base-path handling."""

from __future__ import annotations

import pytest
from flask import Flask, jsonify, request, session, url_for

from app.base_path import (
    BasePathConfigurationError,
    configure_base_path,
    normalize_base_path,
    parse_trusted_prefix_hops,
)


def _make_app(
    *,
    base_path: str | None = None,
    trusted_hops: str | None = None,
    cookie_path: str | None = None,
) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.secret_key = "base-path-test-key"
    if cookie_path is not None:
        app.config["SESSION_COOKIE_PATH"] = cookie_path

    environ = {}
    if base_path is not None:
        environ["BASE_PATH"] = base_path
    if trusted_hops is not None:
        environ["REVERSE_PROXY_PREFIX"] = trusted_hops
    configure_base_path(app, environ)

    @app.get("/")
    @app.get("/api/example")
    @app.get("/static/example")
    def index():
        return jsonify(
            path_info=request.environ["PATH_INFO"],
            script_name=request.environ["SCRIPT_NAME"],
            generated=url_for("generated_target"),
        )

    @app.get("/generated-target")
    def generated_target():
        return "ok"

    @app.get("/session")
    def set_session():
        session["base-path-test"] = True
        return "ok"

    return app


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, ""),
        ("", ""),
        ("/", ""),
        ("/docsight", "/docsight"),
        ("/api/hassio_ingress/token-123", "/api/hassio_ingress/token-123"),
    ],
)
def test_normalize_base_path(configured, expected):
    assert normalize_base_path(configured) == expected


def test_accepts_every_base_path_segment_character_at_the_length_limit():
    segment = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~-"
    segment += "a" * (128 - len(segment))

    assert normalize_base_path(f"/{segment}") == f"/{segment}"


@pytest.mark.parametrize(
    "character",
    ["!", "$", "&", "'", "(", ")", "+", ",", ":", ";", "=", "@", "["],
)
def test_rejects_characters_outside_the_base_path_segment_grammar(character):
    with pytest.raises(BasePathConfigurationError, match="BASE_PATH is invalid"):
        normalize_base_path(f"/safe{character}segment")


def test_rejects_overlong_repetitive_segment_without_regex_backtracking():
    with pytest.raises(BasePathConfigurationError, match="BASE_PATH is invalid"):
        normalize_base_path("/" + "-" * 128 + "!")


@pytest.mark.parametrize(
    "configured",
    [
        "docsight",
        "/docsight/",
        "//docsight",
        "/docsight//settings",
        "http://example.test/docsight",
        "https://example.test/docsight",
        "//example.test/docsight",
        "/docsight?mode=1",
        "/docsight#fragment",
        "/doc sight",
        " /docsight",
        "/docsight ",
        "/docsight\\settings",
        "/docsight%2f..",
        "/%2e%2e/admin",
        "/.",
        "/..",
        "/docsight/./settings",
        "/docsight/../admin",
        "/docsight\nadmin",
        "/docsight\x00admin",
        "/döcsight",
        "/docsight:admin",
        "/" + "a" * 1025,
    ],
)
def test_rejects_malformed_or_ambiguous_base_paths(configured):
    with pytest.raises(BasePathConfigurationError, match="BASE_PATH is invalid"):
        normalize_base_path(configured)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [(None, 0), ("", 0), ("0", 0), ("1", 1), ("3", 3), ("32", 32)],
)
def test_parse_trusted_prefix_hops(configured, expected):
    assert parse_trusted_prefix_hops(configured) == expected


@pytest.mark.parametrize(
    "configured",
    [
        "-1",
        "+1",
        "00",
        "01",
        " 1",
        "1 ",
        "1.0",
        "one",
        "33",
        "999999999999999999999",
    ],
)
def test_rejects_invalid_trusted_prefix_hops(configured):
    with pytest.raises(
        BasePathConfigurationError,
        match="REVERSE_PROXY_PREFIX is invalid",
    ):
        parse_trusted_prefix_hops(configured)


def test_main_rejects_invalid_base_path_before_runtime_setup(monkeypatch, caplog):
    from app import main as app_main

    sentinel = "STARTUP_SENSITIVE_MOUNT_VALUE"
    config_calls = []
    monkeypatch.setenv("BASE_PATH", f"/api/hassio_ingress/{sentinel}%2f..")
    monkeypatch.delenv("REVERSE_PROXY_PREFIX", raising=False)
    monkeypatch.setattr(
        app_main,
        "ConfigManager",
        lambda *args, **kwargs: config_calls.append((args, kwargs)),
    )

    with pytest.raises(BasePathConfigurationError) as exc_info:
        app_main.main()

    assert config_calls == []
    assert sentinel not in str(exc_info.value)
    assert sentinel not in caplog.text


@pytest.mark.parametrize("trusted_hops", [None, "0"])
def test_untrusted_forwarded_prefix_is_ignored(trusted_hops):
    client = _make_app(trusted_hops=trusted_hops).test_client()

    response = client.get("/", headers={"X-Forwarded-Prefix": "/attacker"})

    assert response.status_code == 200
    assert response.get_json() == {
        "generated": "/generated-target",
        "path_info": "/",
        "script_name": "",
    }


def test_disabled_prefix_trust_does_not_require_forwarded_prefix():
    client = _make_app(trusted_hops="0").test_client()

    response = client.get("/session")

    assert response.status_code == 200
    assert "Path=/" in response.headers["Set-Cookie"]


def test_missing_trusted_forwarded_prefix_returns_400_without_cookie():
    client = _make_app(trusted_hops="1").test_client()

    response = client.get("/session")

    assert response.status_code == 400
    assert response.data == b"Bad Request\n"
    assert "Set-Cookie" not in response.headers


@pytest.mark.parametrize("header", ["", ",", '""', '"unterminated'])
def test_empty_or_malformed_forwarded_prefix_list_returns_400_without_cookie(header):
    client = _make_app(trusted_hops="1").test_client()

    response = client.get("/session", headers={"X-Forwarded-Prefix": header})

    assert response.status_code == 400
    assert response.data == b"Bad Request\n"
    assert "Set-Cookie" not in response.headers


def test_trusted_prefix_uses_proxyfix_right_to_left_hop_selection():
    client = _make_app(trusted_hops="2").test_client()

    response = client.get(
        "/",
        headers={"X-Forwarded-Prefix": "/docsight, /untrusted-edge"},
    )

    assert response.status_code == 200
    assert response.get_json()["script_name"] == "/docsight"


def test_malformed_unselected_forwarded_prefix_is_ignored():
    client = _make_app(trusted_hops="1").test_client()

    response = client.get(
        "/",
        headers={"X-Forwarded-Prefix": "/bad%2f.., /docsight"},
    )

    assert response.status_code == 200
    assert response.get_json()["script_name"] == "/docsight"


def test_incomplete_trusted_chain_returns_400_without_cookie():
    client = _make_app(trusted_hops="2").test_client()

    response = client.get(
        "/session",
        headers={"X-Forwarded-Prefix": "/attacker"},
    )

    assert response.status_code == 400
    assert response.data == b"Bad Request\n"
    assert "Set-Cookie" not in response.headers


def test_missing_trusted_forwarded_prefix_with_fixed_base_path_returns_400():
    client = _make_app(base_path="/docsight", trusted_hops="1").test_client()

    response = client.get("/session")

    assert response.status_code == 400
    assert response.data == b"Bad Request\n"
    assert "Set-Cookie" not in response.headers


def test_selected_malformed_forwarded_prefix_returns_safe_unreflected_400(caplog):
    sentinel = "REQUEST_SENSITIVE_MOUNT_VALUE"
    client = _make_app(trusted_hops="1").test_client()

    response = client.get(
        "/",
        headers={"X-Forwarded-Prefix": f"/api/hassio_ingress/{sentinel}%2f.."},
    )

    assert response.status_code == 400
    assert sentinel.encode() not in response.data
    assert sentinel not in caplog.text
    assert response.data == b"Bad Request\n"


@pytest.mark.parametrize(
    ("base_path", "header", "existing_script_name"),
    [
        ("/docsight", "/docsight", "/docsight"),
        (None, "/docsight", "/docsight"),
    ],
)
def test_explicit_header_and_existing_script_name_may_match(
    base_path,
    header,
    existing_script_name,
):
    client = _make_app(base_path=base_path, trusted_hops="1").test_client()
    headers = {"X-Forwarded-Prefix": header} if header is not None else {}

    response = client.get(
        "/",
        headers=headers,
        environ_overrides={"SCRIPT_NAME": existing_script_name},
    )

    assert response.status_code == 200
    assert response.get_json()["script_name"] == "/docsight"


@pytest.mark.parametrize(
    ("base_path", "header", "existing_script_name"),
    [
        ("/docsight", "/other", ""),
        ("/docsight", None, "/other"),
        (None, "/docsight", "/other"),
        ("/", "/docsight", ""),
    ],
)
def test_disagreeing_prefix_sources_fail_closed(
    base_path,
    header,
    existing_script_name,
):
    client = _make_app(base_path=base_path, trusted_hops="1").test_client()
    headers = {"X-Forwarded-Prefix": header} if header is not None else {}

    response = client.get(
        "/",
        headers=headers,
        environ_overrides={"SCRIPT_NAME": existing_script_name},
    )

    assert response.status_code == 400
    assert response.data == b"Bad Request\n"


@pytest.mark.parametrize("path", ["/", "/api/example", "/static/example"])
def test_proxy_stripped_path_info_is_never_rewritten(path):
    client = _make_app(base_path="/docsight").test_client()

    response = client.get(path)

    assert response.status_code == 200
    assert response.get_json()["path_info"] == path
    assert response.get_json()["script_name"] == "/docsight"


def test_url_for_uses_request_script_name():
    client = _make_app(trusted_hops="1").test_client()

    response = client.get(
        "/api/example",
        headers={"X-Forwarded-Prefix": "/api/hassio_ingress/token-123"},
    )

    assert response.status_code == 200
    assert response.get_json()["generated"] == "/api/hassio_ingress/token-123/generated-target"


@pytest.mark.parametrize(
    ("base_path", "trusted_hops", "headers", "expected_path"),
    [
        ("/docsight", None, {}, "/docsight/"),
        (None, "1", {"X-Forwarded-Prefix": "/docsight"}, "/docsight/"),
        (None, None, {}, "/"),
        ("/", None, {}, "/"),
    ],
)
def test_session_cookie_is_scoped_to_request_script_name(
    base_path,
    trusted_hops,
    headers,
    expected_path,
):
    client = _make_app(base_path=base_path, trusted_hops=trusted_hops).test_client()

    response = client.get("/session", headers=headers)

    assert response.status_code == 200
    assert f"Path={expected_path}" in response.headers["Set-Cookie"]
    if expected_path == "/docsight/":
        assert "Path=/docsight-other" not in response.headers["Set-Cookie"]


def test_explicit_session_cookie_path_override_is_preserved():
    client = _make_app(
        base_path="/docsight",
        cookie_path="/operator-choice/",
    ).test_client()

    response = client.get("/session")

    assert response.status_code == 200
    assert "Path=/operator-choice/" in response.headers["Set-Cookie"]
