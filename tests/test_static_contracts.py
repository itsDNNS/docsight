"""Durable static asset and catalog contract tests."""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from jinja2 import Template

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
STATIC = APP / "static"
TEMPLATES = APP / "templates"
MODULES = APP / "modules"
APP_I18N_DIR = APP / "i18n"
LUCIDE_JS = STATIC / "vendor" / "lucide.min.js"
DYNAMIC_LUCIDE_ICONS = {
    "book-open",  # built-in journal module menu icon
    "corner-left-up",  # settings backup directory browser parent row
    "folder",  # settings backup directory browser row
    "gamepad-2",  # built-in feature card
    "gauge",  # built-in feature card
    "octagon-alert",  # dynamically rendered critical event severity
    "puzzle",  # community module fallback icon
    "shield-alert",  # dynamically rendered critical maintainer notice
}

EUROPEAN_LANGUAGE_PACK = {
    "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr",
    "ga", "hr", "hu", "it", "lt", "lv", "nb", "nl", "pl", "pt",
    "ro", "sk", "sl", "sv",
}

I18N_PLACEHOLDER_RE = re.compile(
    r"(</?[A-Za-z][^>]*>|&[a-zA-Z0-9#]+;|\{\{[^}]+\}\}|\{[^}]+\}|%\([^)]+\)[sd]|%[sd])"
)
I18N_PROTECTED_LITERALS = {"Apprise", "DOCSight", "DOCSIS", "DSL", "SC-QAM", "dBmV", "Smokeping"}
I18N_EMPTY_TAG_RE = re.compile(r"<([A-Za-z][^>]*)>\s*</\1>")
I18N_LEADING_SENTINEL_RE = re.compile(r"^\s*@")

STATIC_URL_RE = re.compile(r"(?:href|src)=['\"](/(?:static|modules)/[^'\"?#]+)(?:\?[^'\"]*)?['\"]")
QUOTED_ASSET_RE = re.compile(r"['\"](/(?:static|modules)/[^'\"?#]+)(?:\?[^'\"]*)?['\"]")
STATIC_JS_CSS_TAG_RE = re.compile(
    r"<(?:script|link)\b[^>]+(?:src|href)=['\"](/(?:static|modules)/[^'\"]+\.(?:js|css)(?:\?[^'\"]*)?)['\"]",
    re.IGNORECASE,
)
STATIC_URL_FOR_JS_CSS_TAG_RE = re.compile(
    r"<(?:script|link)\b[^>]+(?:src|href)=(['\"])(\{\{.*?\}\}(?:\?[^'\"]*)?)\1",
    re.IGNORECASE,
)
STATIC_URL_FOR_RE = re.compile(
    r"url_for\(\s*['\"]static['\"]\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]([^)]*)\)"
)
MODULE_STATIC_LITERAL_RE = re.compile(
    r"module_static_url\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]([^)]*)\)"
)
MODULE_STATIC_DYNAMIC_RE = re.compile(
    r"module_static_url\(\s*mod\.id\s*,\s*['\"]([^'\"]+)['\"]([^)]*)\)"
)
ROOT_RELATIVE_ATTRIBUTE_RE = re.compile(
    r"<[^>]*\b(?:href|src|action)\s*=\s*['\"]/"
)
MISMATCHED_HEADING_RE = re.compile(r"<(span|h2)\b[^>]*>[^\n]*</(?!\1>)(span|h2)>")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def module_id_to_dir() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for manifest_path in MODULES.glob("*/manifest.json"):
        manifest = read_json(manifest_path)
        result[manifest["id"]] = manifest_path.parent
    return result


def local_asset_path(url: str, module_dirs: dict[str, Path] | None = None) -> Path | None:
    if "{" in url or "}" in url:
        return None
    if url.startswith("/static/"):
        return STATIC / url.removeprefix("/static/")
    if url.startswith("/modules/"):
        module_dirs = module_dirs or module_id_to_dir()
        match = re.match(r"^/modules/([^/]+)/static/(.+)$", url)
        if not match:
            return None
        module_id, rel_path = match.groups()
        module_dir = module_dirs.get(module_id)
        if module_dir is None:
            return ROOT / "__missing_module__" / module_id / rel_path
        return module_dir / "static" / rel_path
    return None


def collect_template_asset_urls(text: str) -> set[str]:
    """Return statically resolvable literal and Jinja-generated asset URLs."""
    urls = {match.group(1) for match in STATIC_URL_RE.finditer(text)}
    urls.update(f"/static/{match.group(1)}" for match in STATIC_URL_FOR_RE.finditer(text))
    urls.update(
        f"/modules/{match.group(1)}/static/{match.group(2)}"
        for match in MODULE_STATIC_LITERAL_RE.finditer(text)
    )
    return urls


def executable_inline_scripts(text: str):
    """Return executable inline scripts using an HTML parser, not filtering regexes."""
    soup = BeautifulSoup(text, "html.parser")
    return [
        script
        for script in soup.find_all("script")
        if not script.get("src")
        and str(script.get("type", "")).strip().lower() != "application/json"
    ]


def generated_js_css_reference_is_versioned(value: str) -> bool:
    return (
        "?v={{ version|urlencode }}" in value
        or re.search(r"\bv\s*=\s*version\b", value) is not None
    )


def collect_required_lucide_icons() -> set[str]:
    icons = set(DYNAMIC_LUCIDE_ICONS)
    for path in APP.rglob("*"):
        if path.is_dir() or path == LUCIDE_JS or path.suffix not in {".html", ".js"}:
            continue
        text = path.read_text(encoding="utf-8")
        icons.update(
            match.group(1)
            for match in re.finditer(r"data-lucide=[\"']([^\"']+)[\"']", text)
            if "{{" not in match.group(1) and "{%" not in match.group(1) and "+" not in match.group(1)
        )
        icons.update(
            match.group(1)
            for match in re.finditer(r"setAttribute\(['\"]data-lucide['\"],\s*['\"]([^'\"]+)['\"]\)", text)
        )
    for manifest_path in MODULES.glob("*/manifest.json"):
        manifest = read_json(manifest_path)
        icon = manifest.get("menu", {}).get("icon")
        if isinstance(icon, str):
            icons.add(icon)
    return icons


def test_lucide_bundle_is_app_subset_and_covers_rendered_icons() -> None:
    js = LUCIDE_JS.read_text(encoding="utf-8")
    required_icons = collect_required_lucide_icons()

    assert LUCIDE_JS.stat().st_size < 60_000
    assert "DOCSight ships a generated subset" in js
    assert "AArrowDown" not in js  # full Lucide runtime marker
    assert "createIcons" in js
    missing = sorted(icon for icon in required_icons if f'"{icon}"' not in js)
    assert missing == []


def test_pwa_manifest_metadata_and_declared_assets_are_valid() -> None:
    manifest = read_json(STATIC / "manifest.json")
    manifest_url = "https://docsight.test/static/manifest.json"

    assert manifest["name"].startswith("DOCSight")
    assert manifest["short_name"] == "DOCSight"
    assert manifest["display"] == "standalone"
    assert "id" not in manifest
    assert urljoin(manifest_url, manifest["start_url"]) == (
        "https://docsight.test/?source=pwa"
    )
    assert urljoin(manifest_url, manifest["scope"]) == "https://docsight.test/"
    assert {item["form_factor"] for item in manifest["screenshots"]} == {"narrow", "wide"}

    declared_assets = [urljoin(manifest_url, icon["src"]) for icon in manifest["icons"]]
    declared_assets += [
        urljoin(manifest_url, shot["src"]) for shot in manifest["screenshots"]
    ]
    for shortcut in manifest["shortcuts"]:
        assert urljoin(manifest_url, shortcut["url"]).startswith(
            "https://docsight.test/?source=pwa#"
        )
        declared_assets.extend(
            urljoin(manifest_url, icon["src"]) for icon in shortcut["icons"]
        )

    missing = []
    for url in declared_assets:
        path = local_asset_path(urlsplit(url).path)
        if path is None or not path.is_file():
            missing.append(url)
    assert missing == []


def test_templates_reference_existing_static_assets() -> None:
    template_paths = sorted(TEMPLATES.rglob("*.html")) + sorted(MODULES.glob("*/templates/*.html"))
    module_dirs = module_id_to_dir()

    missing = []
    for source in template_paths:
        urls = collect_template_asset_urls(source.read_text(encoding="utf-8"))
        for url in sorted(urls):
            path = local_asset_path(url, module_dirs)
            if path is not None and not path.is_file():
                missing.append(f"{source.relative_to(ROOT)} -> {url}")

    assert missing == []


def test_inline_script_scanner_handles_malformed_end_tag_variants() -> None:
    source = '<script type="text/javascript">alert(1)</script\t\n bogus>'

    scripts = executable_inline_scripts(source)

    assert len(scripts) == 1
    assert "alert(1)" in scripts[0].get_text()


def test_templates_have_no_executable_inline_script_bodies_and_new_assets_exist() -> None:
    """Bootstrap data may be inline JSON, but browser behavior must live in assets."""
    template_paths = sorted(TEMPLATES.rglob("*.html")) + sorted(MODULES.glob("*/templates/*.html"))
    offenders = []
    for path in template_paths:
        text = path.read_text(encoding="utf-8")
        for script in executable_inline_scripts(text):
            offenders.append(f"{path.relative_to(ROOT)}:{script.sourceline or '?'}")

    required_assets = {
        TEMPLATES / "index.html": [
            STATIC / "js" / "browser-contracts.js",
            STATIC / "js" / "dashboard-donuts.js",
            STATIC / "js" / "dashboard.js",
            STATIC / "js" / "dashboard-routing.js",
            STATIC / "js" / "service-worker-registration.js",
        ],
        TEMPLATES / "setup.html": [
            STATIC / "js" / "browser-contracts.js",
            STATIC / "js" / "setup.js",
        ],
        TEMPLATES / "settings.html": [
            STATIC / "js" / "browser-contracts.js",
            STATIC / "js" / "settings-bootstrap.js",
        ],
        MODULES / "connection_monitor" / "templates" / "connection_monitor_settings.html": [
            MODULES / "connection_monitor" / "static" / "js" / "connection-monitor-settings.js",
        ],
    }
    missing_or_unreferenced = []
    for template, assets in required_assets.items():
        source = template.read_text(encoding="utf-8")
        for asset in assets:
            if not asset.is_file() or asset.name not in source:
                missing_or_unreferenced.append(
                    f"{template.relative_to(ROOT)} -> {asset.relative_to(ROOT)}"
                )

    assert offenders == []
    assert missing_or_unreferenced == []


def test_template_static_js_and_css_urls_are_versioned() -> None:
    """Cache-first static JS/CSS references must change when the app version changes."""
    offenders = []
    template_paths = sorted(TEMPLATES.rglob("*.html")) + sorted(MODULES.glob("*/templates/*.html"))

    for path in template_paths:
        text = path.read_text(encoding="utf-8")
        for match in STATIC_JS_CSS_TAG_RE.finditer(text):
            url = match.group(1)
            if "?v={{ version|urlencode }}" not in url:
                offenders.append(f"{path.relative_to(ROOT)} -> {url}")
        for match in STATIC_URL_FOR_JS_CSS_TAG_RE.finditer(text):
            value = match.group(2)
            if re.search(r"\.(?:js|css)(?:['\"]|\))", value) and not generated_js_css_reference_is_versioned(value):
                offenders.append(f"{path.relative_to(ROOT)} -> {value}")

    assert offenders == []


def test_template_asset_extraction_supports_url_helpers() -> None:
    text = """
    <link href="{{ url_for('static', filename='css/main.css', v=version) }}">
    <script src="{{ module_static_url('docsight.bqm', 'js/bqm-chart.js', v=version) }}"></script>
    """

    assert collect_template_asset_urls(text) == {
        "/static/css/main.css",
        "/modules/docsight.bqm/static/js/bqm-chart.js",
    }
    missing = collect_template_asset_urls(
        "{{ module_static_url('docsight.bqm', 'js/missing.js', v=version) }}"
    )
    assert missing == {"/modules/docsight.bqm/static/js/missing.js"}
    assert not local_asset_path(missing.pop()).is_file()
    assert not generated_js_css_reference_is_versioned(
        "{{ url_for('static', filename='css/main.css') }}"
    )


def test_dynamic_module_asset_helpers_are_gated_by_the_matching_module_flag() -> None:
    template_paths = sorted(TEMPLATES.rglob("*.html")) + sorted(MODULES.glob("*/templates/*.html"))
    bindings = set()
    for path in template_paths:
        text = path.read_text(encoding="utf-8")
        for match in MODULE_STATIC_DYNAMIC_RE.finditer(text):
            loop_start = text.rfind("{% for", 0, match.start())
            loop_header_end = text.find("%}", loop_start)
            loop_end = text.find("{% endfor %}", match.end())
            assert loop_start >= 0 and loop_header_end < match.start() < loop_end
            loop_header = text[loop_start:loop_header_end + 2]
            flag = re.search(r"\bmod\.(has_css|has_js)\b", loop_header)
            assert flag is not None, f"{path.relative_to(ROOT)} -> {match.group(0)}"
            bindings.add((flag.group(1), match.group(1)))

    assert bindings == {("has_css", "style.css"), ("has_js", "main.js")}


def test_disabled_bqm_does_not_resolve_or_render_fixed_module_asset() -> None:
    index = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    guarded_script = re.search(
        r"({%\s*if\s+modules\|selectattr\(\s*['\"]id['\"]\s*,\s*"
        r"['\"]equalto['\"]\s*,\s*['\"]docsight\.bqm['\"]\s*\)\|list\s*%}"
        r"\s*<script\s+src=\"{{\s*module_static_url\(\s*['\"]docsight\.bqm['\"]\s*,"
        r"\s*['\"]js/bqm-chart\.js['\"]\s*,\s*v=version\s*\)\s*}}\"></script>"
        r"\s*{%\s*endif\s*%})",
        index,
        re.DOTALL,
    )
    assert guarded_script is not None

    helper_calls = []

    def module_static_url(*args, **kwargs):
        helper_calls.append((args, kwargs))
        return "/must-not-render"

    rendered = Template(guarded_script.group(1)).render(
        modules=[], version="test", module_static_url=module_static_url
    )

    assert helper_calls == []
    assert "/modules/docsight.bqm/" not in rendered
    assert "/must-not-render" not in rendered


def test_templates_do_not_emit_root_relative_application_attributes() -> None:
    offenders = []
    template_paths = sorted(TEMPLATES.rglob("*.html")) + sorted(MODULES.glob("*/templates/*.html"))
    for path in template_paths:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if ROOT_RELATIVE_ATTRIBUTE_RE.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}")

    assert offenders == []


def test_server_redirects_do_not_use_literal_root_relative_targets() -> None:
    offenders = []
    for path in [APP / "web.py", MODULES / "backup" / "routes.py"]:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"redirect\(\s*f?['\"]/", line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}")

    assert offenders == []


def test_setup_navigation_targets_are_server_generated() -> None:
    setup = (TEMPLATES / "setup.html").read_text(encoding="utf-8")

    assert not re.search(r"window\.location\.(?:href\s*=|assign\()\s*['\"]/", setup)
    assert "url_for('index')" in setup
    assert "url_for('login')" in setup


def test_font_sources_are_relative_to_the_stylesheet() -> None:
    fonts_css = (STATIC / "css" / "fonts.css").read_text(encoding="utf-8")
    sources = re.findall(r"src:\s*url\(([^)]+)\)", fonts_css)

    assert len(sources) == 4
    assert all(source.startswith("../fonts/") for source in sources)


def test_service_worker_precache_references_existing_public_assets() -> None:
    sw_js = (STATIC / "sw.js").read_text(encoding="utf-8")
    module_dirs = module_id_to_dir()

    assert re.search(r"var CACHE_VERSION = 'v\d+';", sw_js)
    for required in [
        "/static/manifest.json",
        "/static/logo.svg",
        "/static/icon.png",
    ]:
        assert required in sw_js

    missing = []
    for url in sorted(set(QUOTED_ASSET_RE.findall(sw_js))):
        path = local_asset_path(url, module_dirs)
        if path is not None and not path.is_file():
            missing.append(url)

    assert missing == []


def test_dead_static_js_helpers_stay_removed() -> None:
    assert not (STATIC / "js" / "icons.js").exists()

    settings_js = (STATIC / "js" / "settings.js").read_text(encoding="utf-8")
    utils_js = (STATIC / "js" / "utils.js").read_text(encoding="utf-8")
    sw_js = (STATIC / "sw.js").read_text(encoding="utf-8")
    templates = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(TEMPLATES.rglob("*.html")) + sorted(MODULES.glob("*/templates/*.html"))
    )

    assert "function escHtml" not in settings_js
    assert "function validateBqmMonitor" not in settings_js
    assert "function toggleCard(" not in utils_js
    assert "/static/js/icons.js" not in sw_js
    assert "/static/js/icons.js" not in templates
    assert "toggleCard(" not in templates


def test_settings_small_button_rule_is_defined_once() -> None:
    """Settings small buttons share one .btn-sm size and touch target."""
    css = (STATIC / "css" / "settings.css").read_text(encoding="utf-8")
    definitions = re.findall(r"(?m)^\.btn-sm\s*\{[^}]*\}", css)
    assert len(definitions) == 1
    rule = definitions[0]
    assert "padding: 8px 14px" in rule
    assert "min-height: 36px" in rule


def test_unused_inter_font_assets_stay_removed() -> None:
    for rel_path in [
        "fonts/inter-latin.woff2",
        "fonts/inter-latin-ext.woff2",
    ]:
        assert not (STATIC / rel_path).exists()

    app_static_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(APP.rglob("*"))
        if path.is_file() and path.suffix in {".css", ".html", ".js", ".json"}
    )
    fonts_css = (STATIC / "css" / "fonts.css").read_text(encoding="utf-8")
    tokens_css = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")

    assert "inter-latin" not in app_static_sources.lower()
    assert "/static/fonts/inter" not in app_static_sources.lower()
    assert re.search(r"font-family:\s*['\"]?Inter['\"]?", fonts_css) is None
    assert "--font-sans: 'Outfit'" in tokens_css
    for retained in [
        "fonts/outfit-latin.woff2",
        "fonts/outfit-latin-ext.woff2",
        "fonts/jetbrains-mono-latin.woff2",
        "fonts/jetbrains-mono-latin-ext.woff2",
    ]:
        assert (STATIC / retained).is_file()


def test_builtin_module_manifests_reference_existing_declared_files() -> None:
    path_contributions = {"routes", "settings", "card", "tab", "static", "i18n", "thresholds"}
    missing = []
    for manifest_path in sorted(MODULES.glob("*/manifest.json")):
        module_dir = manifest_path.parent
        manifest = read_json(manifest_path)
        assert manifest["id"].startswith("docsight.")
        assert manifest["type"] in {"analysis", "integration", "theme"}
        for key, value in manifest.get("contributes", {}).items():
            if key in {"collector", "publisher"}:
                value = value.split(":", 1)[0]
            elif key not in path_contributions:
                continue
            target = module_dir / value.rstrip("/")
            if not target.exists():
                missing.append(f"{manifest_path.relative_to(ROOT)} {key}={value}")

    assert missing == []


def test_static_templates_keep_basic_heading_markup_well_formed() -> None:
    offenders = []
    for path in sorted(TEMPLATES.rglob("*.html")) + sorted(MODULES.glob("*/templates/*.html")):
        text = path.read_text(encoding="utf-8")
        offenders.extend(f"{path.relative_to(ROOT)}: {match.group(0)}" for match in MISMATCHED_HEADING_RE.finditer(text))

    assert offenders == []


def test_snapshot_storage_uses_single_storage_base() -> None:
    storage_init = (ROOT / "app" / "storage" / "__init__.py").read_text(encoding="utf-8")
    assert "_STORAGE_METHOD_GROUPS" not in storage_init
    assert "setattr(SnapshotStorage" not in storage_init

    from app.storage import SnapshotStorage
    from app.storage.base import StorageBase

    assert SnapshotStorage.__mro__.count(StorageBase) == 1
    assert SnapshotStorage.__bases__[-1] is StorageBase
    assert hasattr(SnapshotStorage, "save_snapshot")
    assert hasattr(SnapshotStorage, "save_event")
    assert hasattr(SnapshotStorage, "create_api_token")


def test_shared_modals_use_native_dialog_contract() -> None:
    index = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    backup_settings = (
        MODULES / "backup" / "templates" / "backup_settings.html"
    ).read_text(encoding="utf-8")
    modal_script = (STATIC / "js" / "modals.js").read_text(encoding="utf-8")

    for modal_id in (
        "bqm-import-modal",
        "entry-modal",
        "incident-container-modal",
        "import-modal",
        "speedtest-setup-modal",
        "bqm-setup-modal",
        "smokeping-setup-modal",
        "report-modal",
        "chart-zoom-overlay",
        "export-modal",
    ):
        assert re.search(rf"<dialog\b[^>]*\bid=\"{modal_id}\"", index)
    assert re.search(r'<dialog\b[^>]*\bid="browse-modal"', backup_settings)

    assert ".showModal()" in modal_script
    assert ".close()" in modal_script
    for removed_helper in (
        "activeStack",
        "FOCUSABLE",
        "handleTab",
        "focusin",
        "MutationObserver",
        "ensureModalSemantics",
    ):
        assert removed_helper not in modal_script


def test_modal_consumers_have_no_absent_api_fallbacks() -> None:
    consumers = [
        STATIC / "js" / "bqm.js",
        STATIC / "js" / "journal.js",
        STATIC / "js" / "utils.js",
        STATIC / "js" / "demo-banner.js",
        MODULES / "smokeping" / "static" / "main.js",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in consumers)

    assert "if (window.DOCSightModal)" not in combined
    assert "typeof window.docsightConfirm" not in combined
    assert "window.confirm(" not in combined


def test_frontend_simplifications_keep_single_owners() -> None:
    settings = (STATIC / "js" / "settings.js").read_text(encoding="utf-8")
    connection_charts = (
        MODULES
        / "connection_monitor"
        / "static"
        / "js"
        / "connection-monitor-charts.js"
    ).read_text(encoding="utf-8")
    index = (TEMPLATES / "index.html").read_text(encoding="utf-8")

    assert "function _runModuleAction(" in settings
    assert "_runModuleAction(e, id, 'install', downloadUrl);" in settings
    assert "_runModuleAction(e, id, 'uninstall');" in settings
    assert "function bandPlugin(" not in connection_charts
    assert "bandPlugin(datasets.length - 1, datasets.length, bandColor)" in connection_charts
    assert "Escape key closes topmost open modal" not in index


def test_smart_capture_speedtest_adapter_tests_are_consolidated() -> None:
    files = sorted(path.name for path in ROOT.glob("tests/test_smart_capture*speedtest*.py"))
    assert files == ["test_smart_capture_adapter_speedtest.py"]

    tests = (ROOT / "tests" / files[0]).read_text(encoding="utf-8")
    assert "test_recent_tracker_result_suppresses_before_post" in tests
    assert "test_configured_match_window_can_reject_late_results" in tests


def test_smart_capture_uses_direct_speedtest_execution_wiring() -> None:
    assert not (ROOT / "app" / "smart_capture" / "adapters" / "base.py").exists()

    engine = (ROOT / "app" / "smart_capture" / "engine.py").read_text(encoding="utf-8")
    speedtest = (ROOT / "app" / "smart_capture" / "adapters" / "speedtest.py").read_text(encoding="utf-8")
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    trigger_types = (ROOT / "app" / "smart_capture" / "types.py").read_text(encoding="utf-8")

    assert "register_speedtest_adapter" in engine
    assert "register_adapter" not in engine
    assert "ActionAdapter" not in speedtest
    assert "action_type: str" not in trigger_types
    assert "CAPTURE_ACTION_TYPE = \"capture\"" in trigger_types
    assert "register_speedtest_adapter(stt_adapter)" in main


def test_module_driver_registration_path_is_not_supported() -> None:
    """Module manifests should not expose modem-driver registration plumbing."""
    module_loader = (ROOT / "app" / "module_loader.py").read_text(encoding="utf-8")
    driver_registry = (ROOT / "app" / "drivers" / "registry.py").read_text(encoding="utf-8")
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    for removed in [
        "load_module_driver",
        "driver_class",
        "get_driver_modules",
        "register_module_drivers",
        "register_module_driver",
        "_module_drivers",
    ]:
        assert removed not in module_loader
        assert removed not in driver_registry
        assert removed not in main

    assert '"driver"' not in module_loader
    assert not (MODULES / "thresholds_vfkd" / "manifest.json").exists()
    assert "BUILTIN_THRESHOLD_PROFILES" in (ROOT / "app" / "threshold_profiles.py").read_text(encoding="utf-8")


def test_core_i18n_template_is_generated_on_demand_not_tracked() -> None:
    """The translator template is generated locally from en.json when needed."""
    template_path = APP_I18N_DIR / "template.json"
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    loader = (APP_I18N_DIR / "__init__.py").read_text(encoding="utf-8")

    assert "app/i18n/template.json" in gitignore
    assert "python scripts/i18n_check.py --generate" in contributing
    assert "Copy the generated file to `app/i18n/<lang>.json`" in contributing
    assert '_fname == "template.json"' in loader

    if (ROOT / ".git").exists():
        tracked = subprocess.run(
            ["git", "ls-files", "--", str(template_path.relative_to(ROOT))],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        assert tracked == ""


def test_european_language_pack_files_cover_core_catalogs() -> None:
    present = {path.stem for path in APP_I18N_DIR.glob("*.json") if path.stem != "template"}
    missing = sorted(EUROPEAN_LANGUAGE_PACK - present)

    assert missing == []


def test_builtin_module_i18n_catalogs_keep_only_runtime_sources() -> None:
    """Built-in module catalogs are intentional: reports and modulation ship locales."""
    offenders = []
    allowed_locale_modules = {"reports", "modulation"}
    for i18n_dir in sorted(MODULES.glob("*/i18n")):
        if not (i18n_dir / "en.json").exists():
            continue
        module_name = i18n_dir.parent.name
        generated = sorted(path.name for path in i18n_dir.glob("*.json") if path.name != "en.json")
        if module_name in allowed_locale_modules:
            generated = [name for name in generated if name == "template.json"]
        if generated:
            offenders.append(f"{i18n_dir.relative_to(ROOT)}: {', '.join(generated)}")

    assert offenders == []


def test_european_language_pack_metadata_and_key_parity() -> None:
    """Core locale files are selectable and structurally complete."""
    en = read_json(APP_I18N_DIR / "en.json")
    expected_keys = set(en.keys())
    offenders = []
    for code in sorted(EUROPEAN_LANGUAGE_PACK):
        path = APP_I18N_DIR / f"{code}.json"
        data = read_json(path)
        meta = data.get("_meta", {})
        if not meta.get("language_name") or meta.get("language_name") == code:
            offenders.append(f"{code}: missing native language_name")
        if not meta.get("flag"):
            offenders.append(f"{code}: missing flag")
        missing = sorted(expected_keys - set(data.keys()))
        extra = sorted(set(data.keys()) - expected_keys)
        if missing or extra:
            offenders.append(f"{code}: missing={missing[:5]} extra={extra[:5]}")

    assert offenders == []


def test_european_language_pack_preserves_catalog_contracts() -> None:
    """Every catalog keeps key, list, and placeholder contracts intact."""
    offenders = []

    def walk(path_label: str, source: Any, target: Any) -> None:
        if isinstance(source, dict) and isinstance(target, dict):
            missing = sorted(set(source) - set(target))
            extra = sorted(set(target) - set(source))
            if missing or extra:
                offenders.append(f"{path_label}: missing={missing[:5]} extra={extra[:5]}")
            for key in source:
                if key in target:
                    walk(f"{path_label}.{key}", source[key], target[key])
        elif isinstance(source, list) and isinstance(target, list):
            if len(source) != len(target) and not path_label.endswith(".isp_options"):
                offenders.append(f"{path_label}: list length {len(target)} != {len(source)}")
            for idx, (source_item, target_item) in enumerate(zip(source, target)):
                walk(f"{path_label}[{idx}]", source_item, target_item)
        elif isinstance(source, str) and isinstance(target, str):
            if "ZXQ" in target or "@@@" in target:
                offenders.append(f"{path_label}: leaked translation sentinel")
            if I18N_LEADING_SENTINEL_RE.search(target):
                offenders.append(f"{path_label}: leaked leading translation sentinel")
            if I18N_EMPTY_TAG_RE.search(target):
                offenders.append(f"{path_label}: empty HTML tag")
            for literal in I18N_PROTECTED_LITERALS:
                if literal in source and literal not in target:
                    offenders.append(f"{path_label}: missing protected literal {literal}")
            source_placeholders = Counter(I18N_PLACEHOLDER_RE.findall(source))
            target_placeholders = Counter(I18N_PLACEHOLDER_RE.findall(target))
            if source_placeholders != target_placeholders:
                offenders.append(f"{path_label}: placeholder mismatch")

    i18n_dirs = [APP_I18N_DIR, MODULES / "reports" / "i18n", MODULES / "modulation" / "i18n"]
    module_i18n_dirs = sorted(MODULES.glob("*/i18n"))
    allowed_locale_modules = {"reports", "modulation"}
    for i18n_dir in module_i18n_dirs:
        if i18n_dir.parent.name in allowed_locale_modules:
            continue
        module_catalogs = sorted(path for path in i18n_dir.glob("*.json") if path.name != "en.json")
        if module_catalogs:
            offenders.append(
                f"{i18n_dir.relative_to(ROOT)}: module catalogs must be en.json only; "
                f"found {[path.name for path in module_catalogs]}"
            )
    for i18n_dir in i18n_dirs:
        source_path = i18n_dir / "en.json"
        if not source_path.exists():
            continue
        source = read_json(source_path)
        for code in sorted(EUROPEAN_LANGUAGE_PACK):
            path = i18n_dir / f"{code}.json"
            data = read_json(path)
            walk(f"{path.relative_to(ROOT)}", source, data)

    assert offenders == []
