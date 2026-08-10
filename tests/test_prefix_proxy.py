"""Focused response-metadata checks for the E2E prefix proxy."""

from __future__ import annotations

import pytest

from tests.e2e.prefix_proxy import _validate_upstream_response_metadata


def test_accepts_normal_upstream_response_metadata():
    assert _validate_upstream_response_metadata(
        206,
        "Partial Content",
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("ETag", '"abc-123"'),
            ("X-Tabbed", "one\ttwo"),
        ],
    ) == (
        206,
        "Partial Content",
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("ETag", '"abc-123"'),
            ("X-Tabbed", "one\ttwo"),
        ],
    )


def test_reconstructs_validated_metadata_before_emission():
    class UpstreamText(str):
        pass

    reason = UpstreamText("Partial Content")
    name = UpstreamText("X-Upstream")
    value = UpstreamText("safe value")

    _, safe_reason, [(safe_name, safe_value)] = (
        _validate_upstream_response_metadata(206, reason, [(name, value)])
    )

    assert safe_reason == reason and type(safe_reason) is str
    assert safe_name == name and type(safe_name) is str
    assert safe_value == value and type(safe_value) is str


@pytest.mark.parametrize("status", [True, "200", 99, 600])
def test_rejects_invalid_upstream_status(status):
    with pytest.raises(ValueError, match="upstream response metadata"):
        _validate_upstream_response_metadata(status, "OK", [])


@pytest.mark.parametrize(
    "reason",
    [
        "OK\r\nX-Injected: yes",
        "bad\x00reason",
        "bad\x7freason",
        "x" * 257,
        "bad-€",
    ],
)
def test_rejects_unsafe_upstream_status_reason(reason):
    with pytest.raises(ValueError, match="upstream response metadata"):
        _validate_upstream_response_metadata(200, reason, [])


@pytest.mark.parametrize(
    "name",
    ["", "Bad Header", "Bad:Header", "Bad\r\nInjected", "X-Ünicode", "x" * 129],
)
def test_rejects_unsafe_upstream_header_name(name):
    with pytest.raises(ValueError, match="upstream response metadata"):
        _validate_upstream_response_metadata(200, "OK", [(name, "value")])


@pytest.mark.parametrize(
    "value",
    [
        "ok\r\nX-Injected: yes",
        "bad\x00value",
        "bad\x0bvalue",
        "bad\x7fvalue",
        "x" * 8193,
        "bad-€",
    ],
)
def test_rejects_unsafe_upstream_header_value(value):
    with pytest.raises(ValueError, match="upstream response metadata"):
        _validate_upstream_response_metadata(200, "OK", [("X-Test", value)])
