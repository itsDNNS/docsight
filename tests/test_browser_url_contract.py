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

EXPECTED_CONTRACT_CALLS = {
    "app/static/js/dashboard.js": 1,
    "app/static/js/service-worker-registration.js": 3,
    "app/static/js/setup.js": 8,
    "app/static/js/bqm.js": 9,
    "app/static/js/channels.js": 7,
    "app/static/js/correlation.js": 5,
    "app/static/js/demo-banner.js": 3,
    "app/static/js/events.js": 5,
    "app/static/js/glossary.js": 1,
    "app/static/js/hero-chart.js": 1,
    "app/static/js/integrations.js": 5,
    "app/static/js/journal.js": 22,
    "app/static/js/notices.js": 1,
    "app/static/js/segment-utilization.js": 2,
    "app/static/js/settings.js": 25,
    "app/static/js/sparklines.js": 1,
    "app/static/js/speedtest.js": 6,
    "app/static/js/trends.js": 2,
    "app/static/js/utils.js": 3,
    "app/modules/comparison/static/main.js": 1,
    "app/modules/evidence/static/main.js": 2,
    "app/modules/connection_monitor/static/js/connection-monitor-card.js": 1,
    "app/modules/connection_monitor/static/js/connection-monitor-detail.js": 13,
    "app/modules/connection_monitor/static/js/connection-monitor-settings.js": 4,
    "app/modules/modulation/static/main.js": 2,
    "app/modules/smokeping/static/main.js": 2,
}

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


REPRESENTATIVE_SITES = [
    (
        "direct fetch",
        ROOT / "app/static/js/bqm.js",
        "fetch(docsightUrl('/api/bqm/data/dates'))",
    ),
    (
        "assigned URL then fetch",
        ROOT / "app/static/js/channels.js",
        "var url = docsightUrl('/api/weather/range?start='",
    ),
    (
        "DOM-constructed link",
        ROOT / "app/static/js/integrations.js",
        "pdfLink.href = docsightUrl('/api/bnetz/pdf/'",
    ),
    (
        "image source",
        ROOT / "app/modules/smokeping/static/main.js",
        "img.src = docsightUrl('/api/smokeping/graph/'",
    ),
    (
        "download href",
        ROOT / "app/static/js/events.js",
        "exportLink.href = docsightUrl('/api/events/export.csv'",
    ),
    (
        "navigation",
        ROOT / "app/static/js/utils.js",
        "window.location.href = docsightUrl('/api/report?'",
    ),
    (
        "built-in module",
        ROOT / "app/modules/comparison/static/main.js",
        "var url = docsightUrl('/api/comparison?from_a='",
    ),
    (
        "connection-monitor settings asset",
        ROOT / "app/modules/connection_monitor/static/js/connection-monitor-settings.js",
        "fetch(docsightUrl('/api/connection-monitor/targets/' + target.id)",
    ),
]


def _missing_representative_sites(overrides: dict[Path, str] | None = None) -> list[str]:
    overrides = overrides or {}
    missing = []
    for label, path, required in REPRESENTATIVE_SITES:
        source = overrides.get(path, path.read_text(encoding="utf-8"))
        if required not in source:
            missing.append(label)
    return missing


def test_representative_real_url_sites_use_the_contract():
    assert _missing_representative_sites() == []


def test_inventoried_files_keep_the_reviewed_contract_sites():
    actual = {
        relative: (ROOT / relative).read_text(encoding="utf-8").count("docsightUrl(")
        for relative in EXPECTED_CONTRACT_CALLS
    }

    assert actual == EXPECTED_CONTRACT_CALLS
    assert sum(actual.values()) == 135  # reviewed browser URL contract sites


def test_inventoried_actual_literal_forms_have_no_unwrapped_url_sink():
    offenders = []
    forbidden_forms = (
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
    for relative in EXPECTED_CONTRACT_CALLS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        for form in forbidden_forms:
            if form in source:
                offenders.append(f"{relative}: {form}")

    assert offenders == []


@pytest.mark.parametrize("label,path,required", REPRESENTATIVE_SITES)
def test_representative_site_mutations_are_detected(label, path, required):
    source = path.read_text(encoding="utf-8")
    mutated = source.replace(required, required.replace("docsightUrl(", "", 1), 1)

    assert mutated != source
    assert label in _missing_representative_sites({path: mutated})


def test_pwa_fetches_use_the_browser_url_contract():
    settings = (ROOT / "app/static/js/settings.js").read_text(encoding="utf-8")
    unwrapped = [
        line.strip()
        for line in settings.splitlines()
        if "fetch('/" in line
    ]

    assert unwrapped == []
    assert "fetch(docsightUrl('/api/notifications/pwa/status'))" in settings
    assert "fetch(docsightUrl('/api/notifications/pwa/subscribe')," in settings
    assert "fetch(docsightUrl('/api/notifications/pwa/unsubscribe')," in settings
