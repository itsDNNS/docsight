"""Contracts for the container-local HTTP health probe."""

from __future__ import annotations

import io

import pytest

from app import healthcheck


class _Response(io.BytesIO):
    def __init__(self, payload=b'{"status":"ok"}', status=200):
        super().__init__(payload)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def _capture_request(payload=b'{"status":"ok"}', status=200):
    captured = {}

    def open_url(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(payload, status)

    return captured, open_url


def _forwarded_prefix(request):
    return dict(request.header_items()).get("X-forwarded-prefix")


@pytest.mark.parametrize(
    ("environ", "expected_header"),
    [
        ({}, None),
        ({"BASE_PATH": "/docsight"}, None),
        (
            {"REVERSE_PROXY_PREFIX": "2"},
            "/container-health-probe, /container-health-probe",
        ),
        (
            {"BASE_PATH": "/docsight", "REVERSE_PROXY_PREFIX": "2"},
            "/docsight, /docsight",
        ),
        (
            {"BASE_PATH": "/", "REVERSE_PROXY_PREFIX": "2"},
            "/, /",
        ),
    ],
    ids=[
        "root",
        "explicit-mount",
        "trusted-prefix",
        "combined-agreement",
        "explicit-root-agreement",
    ],
)
def test_probe_builds_runtime_compatible_request(environ, expected_header):
    captured, open_url = _capture_request()

    assert healthcheck.main(environ, open_url) == 0

    request = captured["request"]
    assert request.full_url == "http://localhost:8765/health"
    assert request.method == "GET"
    assert _forwarded_prefix(request) == expected_header
    assert captured["timeout"] == 4


def test_probe_uses_configured_web_port():
    captured, open_url = _capture_request()

    assert healthcheck.main({"WEB_PORT": "9123"}, open_url) == 0

    assert captured["request"].full_url == "http://localhost:9123/health"


@pytest.mark.parametrize(
    "web_port",
    ["", "0", "65536", " 8765", "8765@198.51.100.7:80", "８７６５"],
)
def test_probe_rejects_invalid_or_nonlocal_web_port_without_request(
    web_port, capsys
):
    called = False

    def open_url(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("request must not be sent")

    assert healthcheck.main({"WEB_PORT": web_port}, open_url) == 1

    assert called is False
    assert capsys.readouterr().err == "DOCSight healthcheck failed\n"


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        (b'{"status":"ok"}', 199),
        (b'{"status":"ok"}', 300),
        (b'{"status":"waiting"}', 200),
        (b'{"healthy":true}', 200),
        (b'[]', 200),
        (b'not-json', 200),
        (b'{"status":"ok"}' + b" " * (64 * 1024), 200),
    ],
    ids=[
        "below-2xx",
        "above-2xx",
        "wrong-status",
        "missing-status",
        "unexpected-shape",
        "malformed-json",
        "oversized-json",
    ],
)
def test_probe_rejects_unhealthy_http_or_json_responses(
    payload, status, capsys
):
    _, open_url = _capture_request(payload, status)

    assert healthcheck.main({}, open_url) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "DOCSight healthcheck failed\n"


@pytest.mark.parametrize(
    "trusted_hops",
    ["-1", "+1", "01", " 1", "1 ", "one", "33"],
)
def test_probe_rejects_invalid_trusted_hop_values_without_request(
    trusted_hops, capsys
):
    called = False

    def open_url(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("request must not be sent")

    assert healthcheck.main(
        {"REVERSE_PROXY_PREFIX": trusted_hops}, open_url
    ) == 1

    assert called is False
    assert capsys.readouterr().err == "DOCSight healthcheck failed\n"


def test_probe_failure_is_generic_and_redacts_configuration(capsys):
    marker = "sensitive-mount-value"

    assert healthcheck.main(
        {
            "BASE_PATH": f"/api/hassio_ingress/{marker}%2f..",
            "REVERSE_PROXY_PREFIX": "1",
        },
        lambda *args, **kwargs: None,
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "DOCSight healthcheck failed\n"
    assert marker not in captured.err


def test_probe_network_failure_is_generic(capsys):
    def fail_request(*args, **kwargs):
        raise OSError("request details must remain private")

    assert healthcheck.main({}, fail_request) == 1

    assert capsys.readouterr().err == "DOCSight healthcheck failed\n"
