"""Focused behavior and migration checks for the browser URL contract."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "app/static/js/url-contract.js"
DEMO_BANNER = ROOT / "app/static/js/demo-banner.js"

# Every script the browser runs, except the vendor bundles and the helper itself.
BROWSER_SCRIPTS = sorted(
    path for path in [*ROOT.glob("app/static/js/**/*.js"), *ROOT.glob("app/modules/*/static/**/*.js")]
    if "vendor" not in path.parts and path != HELPER
)

NODE_HARNESS = r"""
const fs = require('fs');
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
global.window = {};
global.document = {
    getElementById: function(id) {
        if (id !== 'docsight-url-bootstrap' || !request.hasElement) return null;
        return {textContent: request.bootstrapText};
    }
};
let initError = null;
try {
    eval(fs.readFileSync(process.argv[1], 'utf8'));
} catch (error) {
    initError = error.name + ': ' + error.message;
}
const results = request.inputs.map(function(value) {
    try {
        return {ok: true, value: window.docsightUrl(value)};
    } catch (error) {
        return {ok: false, error: error.name + ': ' + error.message};
    }
});
process.stdout.write(JSON.stringify({initError: initError, results: results}));
"""

DEMO_REDIRECT_HARNESS = r"""
const fs = require('fs');
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
const button = {disabled: false};
const banner = {querySelectorAll: function() { return [button]; }};
const result = {textContent: ''};
const assignments = [];
global.window = {
    T: {},
    docsightConfirm: async function() { return true; },
    location: {assign: function(value) { assignments.push(value); }}
};
global.document = {
    getElementById: function(id) {
        if (id === 'demo-banner') return banner;
        if (id === 'demo-banner-result') return result;
        return null;
    }
};
global.docsightUrl = function(value) {
    if (typeof value !== 'string' || value.charAt(0) !== '/' || value.charAt(1) === '/') {
        throw new TypeError('unsafe URL');
    }
    return '/docsight' + value;
};
global.fetch = async function() {
    return {
        status: 200,
        ok: true,
        json: async function() { return {success: true, next: request.responseNext}; }
    };
};
eval(fs.readFileSync(process.argv[1], 'utf8'));
window.leaveDemo(request.nextChoice, button).then(function() {
    process.stdout.write(JSON.stringify({assignments: assignments, disabled: button.disabled}));
});
"""


def _run_helper(
    bootstrap: object = None,
    inputs: list[object] | None = None,
    *,
    bootstrap_text: str | None = None,
    has_element: bool = True,
) -> dict[str, object]:
    if bootstrap_text is None:
        bootstrap_text = json.dumps(
            {"basePath": ""} if bootstrap is None else bootstrap,
            separators=(",", ":"),
        )
    completed = subprocess.run(
        ["node", "-e", NODE_HARNESS, str(HELPER)],
        input=json.dumps(
            {
                "hasElement": has_element,
                "bootstrapText": bootstrap_text,
                "inputs": inputs or [],
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _run_demo_redirect(next_choice: str, response_next: str) -> dict[str, object]:
    completed = subprocess.run(
        ["node", "-e", DEMO_REDIRECT_HARNESS, str(DEMO_BANNER)],
        input=json.dumps({"nextChoice": next_choice, "responseNext": response_next}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize(
    ("base_path", "source", "expected"),
    [
        ("", "/api/poll", "/api/poll"),
        ("", "/api/export?q=a%20b#part", "/api/export?q=a%20b#part"),
        ("/docsight", "/", "/docsight/"),
        ("/docsight", "/api/poll", "/docsight/api/poll"),
        (
            "/docsight",
            "/api/export?q=a%20b#part%2Fkept",
            "/docsight/api/export?q=a%20b#part%2Fkept",
        ),
        ("/docsight", "/docsight", "/docsight"),
        ("/docsight", "/docsight/api/poll", "/docsight/api/poll"),
        ("/docsight", "/docsight-extra/api", "/docsight/docsight-extra/api"),
        ("/docsight", "/file%20name", "/docsight/file%20name"),
        ("/A.z_~-/b", "/api/poll", "/A.z_~-/b/api/poll"),
    ],
)
def test_docsight_url_root_and_prefixed_behavior(base_path, source, expected):
    outcome = _run_helper({"basePath": base_path}, [source])

    assert outcome["initError"] is None
    assert outcome["results"] == [{"ok": True, "value": expected}]


@pytest.mark.parametrize(
    "source",
    [
        None,
        1,
        {},
        "",
        "api/poll",
        "?lang=en",
        "#events",
        "http://evil.example/",
        "https://evil.example/",
        "javascript:alert(1)",
        "data:text/plain,hello",
        "blob:https://example.test/id",
        "//evil.example/path",
        "///evil.example/path",
        "/api\\poll",
        "/api\x00poll",
        "/api\x1fpoll",
        "/api\x7fpoll",
        "/api/%",
        "/api/%2",
        "/api/%GG",
        "/api?value=%",
        "/api#value=%GG",
        "/api/./poll",
        "/api/../poll",
        "/api/%2e/poll",
        "/api/%2E%2e/poll",
        "/api%2fpoll",
        "/api%2Fpoll",
        "/api%5cpoll",
        "/api%00poll",
        "/api%1fpoll",
        "/api%7fpoll",
        "/api/%252e%252e/poll",
        "/api%252fpoll",
        "/api%255cpoll",
        "/api%2500poll",
        "/api/%25252e%25252e/poll",
        "/api/%25GG",
    ],
)
def test_docsight_url_rejects_unsafe_or_ambiguous_inputs(source):
    outcome = _run_helper({"basePath": "/docsight"}, [source])

    assert outcome["initError"] is None
    assert outcome["results"][0]["ok"] is False


@pytest.mark.parametrize(
    ("bootstrap", "bootstrap_text", "has_element"),
    [
        ({}, None, True),
        ({"basePath": "", "token": "secret"}, None, True),
        ({"basePath": None}, None, True),
        ({"basePath": "/"}, None, True),
        ({"basePath": "/docsight/"}, None, True),
        ({"basePath": "docsight"}, None, True),
        ({"basePath": "//docsight"}, None, True),
        ({"basePath": "/doc%73ight"}, None, True),
        ({"basePath": "/docsight?x"}, None, True),
        (None, "not json", True),
        (None, "null", True),
        (None, None, False),
    ],
)
def test_invalid_or_missing_bootstrap_fails_closed(
    bootstrap, bootstrap_text, has_element
):
    outcome = _run_helper(
        bootstrap,
        ["/api/poll"],
        bootstrap_text=bootstrap_text,
        has_element=has_element,
    )

    assert outcome["initError"] is not None
    assert outcome["results"][0]["ok"] is False


def test_helper_does_not_patch_browser_primitives():
    source = HELPER.read_text(encoding="utf-8")

    assert "Object.defineProperty(window, 'docsightUrl'" in source
    assert "configurable: false" in source
    assert "writable: false" in source
    assert "window.docsightUrl =" not in source
    assert "window.fetch" not in source
    assert "XMLHttpRequest" not in source
    assert re.search(
        r"\b(?:Document|Element|Location|Node|Window)\.prototype\b", source
    ) is None
    assert "window.location" not in source


def test_bootstrap_base_path_is_rebuilt_from_encoded_validated_segments():
    source = HELPER.read_text(encoding="utf-8")

    assert "canonicalSegments.push(encodeURIComponent(segments[" in source
    assert "basePath = '/' + canonicalSegments.join('/')" in source


def test_demo_next_navigation_uses_the_strict_contract():
    source = DEMO_BANNER.read_text(encoding="utf-8")

    assert "payload.next !== expectedNext" in source
    assert "window.location.assign(docsightUrl(expectedNext));" in source
    assert "window.location.assign(payload.next);" not in source
    outcome = _run_helper(
        {"basePath": "/docsight"},
        ["/settings#modules", "https://evil.example/", "//evil.example/"],
    )
    assert outcome["results"][0] == {
        "ok": True,
        "value": "/docsight/settings#modules",
    }
    assert all(not item["ok"] for item in outcome["results"][1:])


def test_demo_redirect_navigates_only_to_the_allowlisted_response():
    assert _run_demo_redirect("exit", "/setup") == {
        "assignments": ["/docsight/setup"],
        "disabled": True,
    }


@pytest.mark.parametrize(
    "response_next",
    [
        "/unexpected",
        "//evil.example/",
        "https://evil.example/",
        "javascript:alert(1)",
    ],
)
def test_demo_redirect_fails_closed_on_unexpected_api_destination(response_next):
    assert _run_demo_redirect("exit", response_next) == {
        "assignments": [],
        "disabled": False,
    }


_FORBIDDEN_FORMS = (
    "fetch('/api",
    'fetch("/api',
    "fetch('/health",
    'fetch("/health',
    "var url = '/api",
    'var url = "/api',
    "return '/api",
    'return "/api',
    'href="/api',
    "href='/api",
    'src="/api',
    "src='/api",
    "window.location.assign('/login')",
    'window.location.assign("/login")',
    "window.location.href = '/api",
    'window.location.href = "/api',
)
# Assets and DOM/navigation assignments, including fallback expressions.
_UNWRAPPED_SINK = re.compile(
    r"(?:\b(?:href|src)\s*=(?:(?!docsightUrl\()[^;\n])*?"
    r"|(?:\breturn\b|\b(?:var|let|const)\s+\w+\s*="
    r"|\b(?:window\.)?location(?:\.href)?\s*="
    r"|\b(?:fetch|(?:window\.)?location\.(?:assign|replace))\s*\()\s*)"
    r"['\"]/(?:api|static|modules)\b"
)


def _unwrapped_url_sinks(source: str) -> list[str]:
    """Root-relative app URLs that reach a request, link, asset or navigation without docsightUrl()."""
    found = [form for form in _FORBIDDEN_FORMS if form in source]
    found += [match.group() for match in _UNWRAPPED_SINK.finditer(source)]
    return found


@pytest.mark.parametrize("unwrapped,wrapped", [
    ("fetch('/api/bqm/data/dates')", "fetch(docsightUrl('/api/bqm/data/dates'))"),
    ("var url = '/api/weather/range?start=' + start;", "var url = docsightUrl('/api/weather/range?start=' + start);"),
    ("icon.src = iconMap[isp] || '/static/img/generic.svg';", "icon.src = docsightUrl(iconMap[isp] || '/static/img/generic.svg');"),
    ("pdfLink.href = '/api/bnetz/pdf/' + id;", "pdfLink.href = docsightUrl('/api/bnetz/pdf/' + id);"),
    ("img.src = '/api/smokeping/graph/' + target;", "img.src = docsightUrl('/api/smokeping/graph/' + target);"),
    ("window.location.href = '/api/report?' + query;", "window.location.href = docsightUrl('/api/report?' + query);"),
    ("window.location.assign('/login')", "window.location.assign(docsightUrl('/login'))"),
    ("return '/api/events';", "return docsightUrl('/api/events');"),
])
def test_the_scanner_finds_an_unwrapped_app_url(unwrapped, wrapped):
    assert _unwrapped_url_sinks(unwrapped)
    assert _unwrapped_url_sinks(wrapped) == []


def test_browser_scripts_send_every_app_url_through_the_contract():
    assert BROWSER_SCRIPTS
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}: {sink}"
        for path in BROWSER_SCRIPTS
        for sink in _unwrapped_url_sinks(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_settings_requests_go_through_the_contract():
    form = (ROOT / "app/static/js/settings/form.js").read_text(encoding="utf-8")
    assert "fetch(docsightUrl(url)" in form
