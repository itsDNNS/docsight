from __future__ import annotations

import json
import re
from pathlib import Path

from app import web

ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = ROOT / "app" / "i18n"
INDEX_TEMPLATE = ROOT / "app" / "templates" / "index.html"
SETTINGS_TEMPLATE = ROOT / "app" / "templates" / "settings.html"
README_DOC = ROOT / "README.md"
DESKTOP_DOC = ROOT / "docs" / "windows-desktop-preview.md"
INSTALL_DOC = ROOT / "INSTALL.md"
WINDOWS_QUICK_START = ROOT / "docs" / "windows-quick-start.md"
CODE_SIGNING_DOC = ROOT / "CODE_SIGNING.md"
WINDOWS_PACKAGING_DOC = ROOT / "packaging" / "windows" / "README.md"
LATEST_RELEASE_URL = "https://github.com/itsDNNS/docsight/releases/latest"

DESKTOP_KEYS = {
    "desktop_preview_badge",
    "desktop_preview_notice_title",
    "desktop_preview_notice_body",
    "desktop_preview_notice_link",
}


def test_desktop_preview_mode_requires_explicit_env_flag(monkeypatch):
    monkeypatch.delenv("DOCSIGHT_DESKTOP_MODE", raising=False)
    assert web.is_desktop_preview_mode() is False

    monkeypatch.setenv("DOCSIGHT_DESKTOP_MODE", "0")
    assert web.is_desktop_preview_mode() is False

    monkeypatch.setenv("DOCSIGHT_DESKTOP_MODE", "1")
    assert web.is_desktop_preview_mode() is True


def test_desktop_preview_badge_and_notice_are_template_gated():
    for template_path in (INDEX_TEMPLATE, SETTINGS_TEMPLATE):
        template = template_path.read_text(encoding="utf-8")
        assert "{% if desktop_mode" in template
        assert "desktop_preview_badge" in template
        assert "desktop_preview_notice_dismissed" in template
        assert "dismissMaintainerNotice('{{ desktop_preview_notice_id }}')" in template
        assert "desktop_preview_doc_url" in template


def test_desktop_preview_i18n_keys_exist_in_every_core_locale():
    missing: dict[str, set[str]] = {}
    for path in I18N_DIR.glob("*.json"):
        if path.name == "template.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        absent = {key for key in DESKTOP_KEYS if not data.get(key)}
        if absent:
            missing[path.name] = absent

    assert missing == {}


def test_desktop_preview_docs_cover_plain_language_capabilities_and_limits():
    doc = DESKTOP_DOC.read_text(encoding="utf-8")
    capabilities = doc.split("## What works in the Desktop Preview", maxsplit=1)[
        1
    ].split("## Known v0 limitations", maxsplit=1)[0]
    limitations = doc.split("## Known v0 limitations", maxsplit=1)[1].split(
        "## Where data lives", maxsplit=1
    )[0]
    data_location = doc.split("## Where data lives", maxsplit=1)[1].split(
        "## Remove the Desktop Preview", maxsplit=1
    )[0]

    for capability in (
        "- Demo Mode.",
        "- Initial setup wizard.",
        "- Evidence Journey and local diagnostic exports.",
        "- Connection Monitor with TCP-based checks.",
    ):
        assert capability in capabilities
    for limitation in (
        "**Not an always-on monitor.**",
        "**Sleep and hibernate pause collection.**",
        "**No native ICMP probing in v0.**",
        "**No Windows service or autostart setup.**",
        "**Local-only browser app.**",
    ):
        assert limitation in limitations
    assert "%LOCALAPPDATA%\\DOCSight" in data_location
    assert "For continuous monitoring, use Docker on an always-on machine instead." in limitations


def test_windows_install_docs_link_tryout_to_preview_and_monitoring_to_docker():
    install = INSTALL_DOC.read_text(encoding="utf-8")
    quick_start = WINDOWS_QUICK_START.read_text(encoding="utf-8")

    assert "docs/windows-desktop-preview.md" in install
    assert "docs/windows-quick-start.md" in install
    assert "windows-desktop-preview.md" in quick_start
    assert "24/7" in install
    assert "24/7" in quick_start
    assert "Docker" in install
    assert "Docker" in quick_start


def test_windows_preview_is_visible_from_landing_and_uses_public_releases():
    readme = README_DOC.read_text(encoding="utf-8")
    install = INSTALL_DOC.read_text(encoding="utf-8")
    quick_start = WINDOWS_QUICK_START.read_text(encoding="utf-8")
    preview = DESKTOP_DOC.read_text(encoding="utf-8")

    assert f'<a href="{LATEST_RELEASE_URL}">Windows Preview</a>' in readme
    assert (
        f"[Download the portable Desktop Preview]({LATEST_RELEASE_URL})"
        in install
    )
    assert (
        f"[Download the portable Desktop Preview]({LATEST_RELEASE_URL})"
        in quick_start
    )
    assert f"[latest DOCSight release]({LATEST_RELEASE_URL})" in preview

    assert "unsigned portable" in readme.lower()
    assert "unsigned portable" in quick_start.lower()


def test_windows_preview_main_path_does_not_require_checksum_or_powershell():
    preview = DESKTOP_DOC.read_text(encoding="utf-8")
    main_path = preview.split("## Download and start", maxsplit=1)[1].split(
        "## Optional: verify download integrity", maxsplit=1
    )[0]
    optional_check = preview.split(
        "## Optional: verify download integrity", maxsplit=1
    )[1].split("## First start and SmartScreen", maxsplit=1)[0]

    assert "DOCSight-Desktop-Preview-win64-<version>.zip" in main_path
    assert ".zip.sha256" not in main_path
    assert "```powershell" not in main_path
    assert "You do not need a GitHub account for this download path." in main_path
    assert "PowerShell and checksum verification are optional." in main_path

    assert "DOCSight-Desktop-Preview-win64-<version>.zip.sha256" in optional_check
    assert "```powershell" in optional_check
    for verification_contract in (
        "$checksumText = Get-Content",
        "[string]::IsNullOrWhiteSpace($checksumText)",
        "$expectedHash =",
        "-split '\\s+', 2",
        "$actualHash = (Get-FileHash",
        "[System.StringComparison]::OrdinalIgnoreCase",
        "$checksumMatches",
        "returns `True` only when",
        "first hash value in the checksum file",
        "compared case-insensitively",
        "does not verify publisher identity",
    ):
        assert verification_contract in optional_check

    signing_text = CODE_SIGNING_DOC.read_text(encoding="utf-8")
    signing = " ".join(signing_text.split())
    for shared_contract in (
        "$checksumText = Get-Content",
        "[string]::IsNullOrWhiteSpace($checksumText)",
        "$expectedHash =",
        "$actualHash = (Get-FileHash",
        "[System.StringComparison]::OrdinalIgnoreCase",
        "$checksumMatches",
        "returns `True` only when",
        "first hash value in the checksum file",
        "compared case-insensitively",
        "does not verify publisher identity",
    ):
        assert shared_contract in signing

    preview_comparison = re.search(
        r"```powershell\n(?P<code>\$zip = .*?)\n```",
        optional_check,
        re.DOTALL,
    )
    signing_comparison = re.search(
        r"```powershell\n(?P<code>\$zip = .*?)\n```",
        signing_text,
        re.DOTALL,
    )
    assert preview_comparison
    assert signing_comparison
    assert preview_comparison.group("code") == signing_comparison.group("code")


def test_windows_release_docs_keep_actions_artifacts_as_ci_evidence_only():
    packaging = WINDOWS_PACKAGING_DOC.read_text(encoding="utf-8")
    signing = CODE_SIGNING_DOC.read_text(encoding="utf-8")

    assert "Workflow artifacts are CI evidence only." in packaging
    assert LATEST_RELEASE_URL in packaging
    assert "optional integrity checks" in packaging
    assert (
        "Each Windows Preview ZIP on the official release has a corresponding "
        "`.sha256` asset for an optional advanced integrity check."
        in " ".join(signing.split())
    )
