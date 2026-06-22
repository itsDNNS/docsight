"""Durable static asset and catalog contract tests."""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

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
I18N_PROTECTED_LITERALS = {"Apprise", "DOCSight", "dBmV", "Smokeping"}
I18N_EMPTY_TAG_RE = re.compile(r"<([A-Za-z][^>]*)>\s*</\1>")
I18N_LEADING_SENTINEL_RE = re.compile(r"^\s*@")

STATIC_URL_RE = re.compile(r"(?:href|src)=['\"](/(?:static|modules)/[^'\"?#]+)(?:\?[^'\"]*)?['\"]")
QUOTED_ASSET_RE = re.compile(r"['\"](/(?:static|modules)/[^'\"?#]+)(?:\?[^'\"]*)?['\"]")
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


def collect_literal_asset_urls(paths: Iterable[Path]) -> dict[Path, set[str]]:
    urls: dict[Path, set[str]] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        matches = {match.group(1) for match in STATIC_URL_RE.finditer(text)}
        if matches:
            urls[path] = matches
    return urls


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

    assert manifest["name"].startswith("DOCSight")
    assert manifest["short_name"] == "DOCSight"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"].startswith("/")
    assert manifest["scope"] == "/"
    assert {item["form_factor"] for item in manifest["screenshots"]} == {"narrow", "wide"}

    declared_assets = [icon["src"] for icon in manifest["icons"]]
    declared_assets += [shot["src"] for shot in manifest["screenshots"]]
    for shortcut in manifest["shortcuts"]:
        assert shortcut["url"].startswith("/")
        declared_assets.extend(icon["src"] for icon in shortcut["icons"])

    missing = []
    for url in declared_assets:
        path = local_asset_path(url)
        if path is None or not path.is_file():
            missing.append(url)
    assert missing == []


def test_templates_reference_existing_literal_static_assets() -> None:
    template_paths = sorted(TEMPLATES.rglob("*.html")) + sorted(MODULES.glob("*/templates/*.html"))
    references = collect_literal_asset_urls(template_paths)
    module_dirs = module_id_to_dir()

    missing = []
    for source, urls in references.items():
        for url in sorted(urls):
            path = local_asset_path(url, module_dirs)
            if path is not None and not path.is_file():
                missing.append(f"{source.relative_to(ROOT)} -> {url}")

    assert missing == []


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
    assert "class SnapshotStorage(StorageBase):" in storage_init
    assert "class SnapshotStorage(\n" not in storage_init
    assert "_STORAGE_METHOD_GROUPS" in storage_init
    assert "Mixin" not in storage_init


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
    module_card = (ROOT / "app" / "templates" / "settings" / "_module_card.html").read_text(encoding="utf-8")

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
    assert "mod.type == 'driver'" not in module_card
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
    """Built-in module UI catalogs use en.json fallback; reports keeps PDF locale files."""
    offenders = []
    allowed_locale_modules = {"reports"}
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

    i18n_dirs = [APP_I18N_DIR, MODULES / "reports" / "i18n"]
    module_i18n_dirs = sorted(MODULES.glob("*/i18n"))
    for i18n_dir in module_i18n_dirs:
        if i18n_dir.parent.name == "reports":
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
