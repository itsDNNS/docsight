"""Static packaging contract tests for the Windows Desktop Preview build."""

from __future__ import annotations

import ast
import importlib.util
import re
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_PACKAGING = ROOT / "packaging" / "windows"
CODE_SIGNING_POLICY = ROOT / "CODE_SIGNING.md"
WINDOWS_WORKFLOW = ROOT / ".github" / "workflows" / "windows-desktop.yml"


def load_windows_module(name: str):
    path = WINDOWS_PACKAGING / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(WINDOWS_PACKAGING))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def safe_version_rule(text: str, assignment: str) -> tuple[str, str]:
    match = re.search(
        rf"{re.escape(assignment)}.*?-replace\s+"
        r"'(?P<pattern>[^']+)',\s*'(?P<replacement>[^']*)'",
        text,
    )
    assert match, f"safe-version replacement not found for {assignment}"
    return match.group("pattern"), match.group("replacement")


def test_windows_packaging_files_exist():
    for relative in (
        "docsight_desktop.py",
        "tray.py",
        "docsight.spec",
        "docsight.ico",
        "build.ps1",
        "pe_version.py",
        "verify_pe.py",
        "requirements-build.in",
        "requirements-build.txt",
        "requirements-runtime-windows.in",
        "requirements-runtime-windows.txt",
        "requirements-test-windows.in",
        "requirements-test-windows.txt",
        "smoke_test.ps1",
        "README.md",
        "QA-CHECKLIST.md",
    ):
        assert (WINDOWS_PACKAGING / relative).is_file()


def test_pyinstaller_spec_collects_app_tree_and_version_file():
    spec_text = (WINDOWS_PACKAGING / "docsight.spec").read_text(encoding="utf-8")

    assert "collect_app_datas()" in spec_text
    assert "collect_app_hiddenimports()" in spec_text
    assert "VERSION_FILE" in spec_text
    assert "(str(VERSION_FILE), \".\")" in spec_text
    assert "docsight-icmp-helper" not in spec_text
    assert "docsight-traceroute-helper" not in spec_text


def test_pyinstaller_spec_uses_generated_version_info_and_checked_in_icon():
    spec_path = WINDOWS_PACKAGING / "docsight.spec"
    tree = ast.parse(spec_path.read_text(encoding="utf-8"), filename=str(spec_path))
    exe_call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "EXE"
    )
    keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in exe_call.keywords}

    assert keywords["icon"] == "str(ICON_FILE)"
    assert keywords["version"] == "str(VERSION_INFO_FILE)"
    assert "write_text" not in spec_path.read_text(encoding="utf-8")


def test_checked_in_windows_icon_has_required_transparent_sizes():
    icon_path = WINDOWS_PACKAGING / "docsight.ico"
    required_sizes = {16, 24, 32, 48, 64, 128, 256}

    with Image.open(icon_path) as icon:
        available = {width for width, height in icon.ico.sizes() if width == height}
        assert required_sizes <= available
        for size in required_sizes:
            frame = icon.ico.getimage((size, size)).convert("RGBA")
            alpha_min, alpha_max = frame.getchannel("A").getextrema()
            assert alpha_min == 0
            assert alpha_max == 255
            bounds = frame.getbbox()
            assert bounds is not None
            assert bounds[2] - bounds[0] >= size * 0.75
            assert bounds[3] - bounds[1] >= size * 0.75


def test_exact_release_version_mapping_preserves_release_components():
    pe_version = load_windows_module("pe_version")

    assert pe_version.map_file_version("v2026-07-29.1") == (2026, 7, 29, 1)
    assert pe_version.map_file_version("v2026-07-29.65535") == (
        2026,
        7,
        29,
        65535,
    )
    assert pe_version.file_version_string("v2026-07-29.1") == "2026.7.29.1"

    overflow = pe_version.map_file_version("v2026-07-29.65536")
    assert overflow != (2026, 7, 29, 65536)
    assert all(0 <= component <= 65535 for component in overflow)


def test_git_describe_version_mapping_is_stable_and_suffix_sensitive():
    pe_version = load_windows_module("pe_version")
    label = "v2026-07-29.1-8-ga5344fe"

    first = pe_version.map_file_version(label)
    assert first == pe_version.map_file_version(label)
    assert first[:3] == (2026, 7, 29)
    assert first != pe_version.map_file_version("v2026-07-29.1-9-ga5344fe")
    assert all(0 <= component <= 65535 for component in first)


def test_generic_and_invalid_release_like_labels_map_to_valid_versions():
    pe_version = load_windows_module("pe_version")

    for label in ("dev", "feature/desktop-preview", "v2026-13-40.99999"):
        first = pe_version.map_file_version(label)
        assert first == pe_version.map_file_version(label)
        assert len(first) == 4
        assert all(0 <= component <= 65535 for component in first)

    assert pe_version.map_file_version("dev") != pe_version.map_file_version("dev-2")


@pytest.mark.parametrize(
    "label",
    ["", "   ", "dev\x00x", "dev\nx", "dev\x7fx", "bad\ud800", "x" * 4097],
)
def test_version_mapping_rejects_invalid_or_control_character_labels(label):
    pe_version = load_windows_module("pe_version")

    with pytest.raises((TypeError, ValueError)):
        pe_version.map_file_version(label)


def test_version_info_contains_approved_strings_and_exact_product_label():
    pe_version = load_windows_module("pe_version")
    label = "v2026-07-29.1-8-ga5344fe+preview"
    rendered = pe_version.render_version_info(label)

    expected = {
        "ProductName": "DOCSight",
        "FileDescription": "DOCSight Desktop Preview",
        "CompanyName": "DOCSight Project",
        "LegalCopyright": "Copyright (c) 2026 Dennis Braun",
        "OriginalFilename": "DOCSight.exe",
        "FileVersion": pe_version.file_version_string(label),
        "ProductVersion": label,
    }
    ast.parse(rendered)
    assert pe_version.version_strings(label) == expected
    for key, value in expected.items():
        assert repr(key) in rendered
        assert repr(value) in rendered


def test_version_info_uses_pyinstaller_fixed_file_info_constructor():
    pe_version = load_windows_module("pe_version")

    rendered = pe_version.render_version_info("v2026-07-29.1")

    assert "ffi=FixedFileInfo(" in rendered
    assert "VSFixedFileInfo" not in rendered


def test_pe_verifier_rejects_stale_fixed_or_string_versions():
    pe_version = load_windows_module("pe_version")
    verify_pe = load_windows_module("verify_pe")
    label = "v2026-07-29.1-8-ga5344fe"
    numeric = pe_version.map_file_version(label)
    fixed = SimpleNamespace(
        FileVersionMS=(numeric[0] << 16) | numeric[1],
        FileVersionLS=(numeric[2] << 16) | numeric[3],
        ProductVersionMS=(numeric[0] << 16) | numeric[1],
        ProductVersionLS=(numeric[2] << 16) | numeric[3],
    )
    strings = pe_version.version_strings(label)
    pe = SimpleNamespace(
        VS_FIXEDFILEINFO=[fixed],
        FileInfo=[[SimpleNamespace(StringTable=[SimpleNamespace(entries=strings)])]],
    )

    assert verify_pe.verify_version_resources(pe, label) == numeric
    fixed.FileVersionLS ^= 1
    with pytest.raises(verify_pe.VerificationError, match="fixed FileVersion is stale"):
        verify_pe.verify_version_resources(pe, label)
    fixed.FileVersionLS ^= 1
    strings["ProductVersion"] = "stale"
    with pytest.raises(verify_pe.VerificationError, match="ProductVersion"):
        verify_pe.verify_version_resources(pe, label)


def test_pe_verifier_compares_icon_group_headers_and_payloads():
    verify_pe = load_windows_module("verify_pe")
    icon_path = WINDOWS_PACKAGING / "docsight.ico"
    expected = verify_pe.read_ico(icon_path)
    payloads = {}
    group_entries = []
    icon_names = []
    for resource_id, image in enumerate(expected, start=1):
        payloads[resource_id] = image.payload
        group_entries.append(
            struct.pack(
                "<BBBBHHIH",
                image.width_byte,
                image.height_byte,
                image.color_count,
                image.reserved,
                image.planes,
                image.bit_count,
                len(image.payload),
                resource_id,
            )
        )
        icon_names.append(
            SimpleNamespace(
                id=resource_id,
                directory=SimpleNamespace(
                    entries=[
                        SimpleNamespace(
                            id=0,
                            data=SimpleNamespace(
                                struct=SimpleNamespace(
                                    OffsetToData=resource_id,
                                    Size=len(image.payload),
                                )
                            ),
                        )
                    ]
                ),
            )
        )
    group_payload = struct.pack("<HHH", 0, 1, len(expected)) + b"".join(group_entries)
    group_offset = len(expected) + 1
    payloads[group_offset] = group_payload
    root = SimpleNamespace(
        entries=[
            SimpleNamespace(id=verify_pe.RT_ICON, directory=SimpleNamespace(entries=icon_names)),
            SimpleNamespace(
                id=verify_pe.RT_GROUP_ICON,
                directory=SimpleNamespace(
                    entries=[
                        SimpleNamespace(
                            id=1,
                            directory=SimpleNamespace(
                                entries=[
                                    SimpleNamespace(
                                        id=0,
                                        data=SimpleNamespace(
                                            struct=SimpleNamespace(
                                                OffsetToData=group_offset,
                                                Size=len(group_payload),
                                            )
                                        ),
                                    )
                                ]
                            ),
                        )
                    ]
                ),
            ),
        ]
    )
    pe = SimpleNamespace(
        DIRECTORY_ENTRY_RESOURCE=root,
        get_data=lambda offset, size: payloads[offset][:size],
    )

    assert verify_pe.verify_icon_resources(pe, icon_path) == [image.size for image in expected]
    payloads[1] = b"stale" + payloads[1][5:]
    with pytest.raises(verify_pe.VerificationError, match="do not match"):
        verify_pe.verify_icon_resources(pe, icon_path)


def test_pyinstaller_spec_bundles_tk_and_keeps_test_exclusion():
    spec_path = WINDOWS_PACKAGING / "docsight.spec"
    spec_text = spec_path.read_text(encoding="utf-8")
    tree = ast.parse(spec_text, filename=str(spec_path))
    analysis_call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Analysis"
    )
    excludes_keyword = next(
        keyword for keyword in analysis_call.keywords if keyword.arg == "excludes"
    )
    exclusions = ast.literal_eval(excludes_keyword.value)

    assert '"tkinter"' in spec_text
    assert '"tkinter.ttk"' in spec_text
    assert "tkinter" not in exclusions
    assert "pytest" in exclusions
    assert "unittest" not in exclusions


def test_pyinstaller_spec_disables_windowed_tracebacks():
    spec_text = (WINDOWS_PACKAGING / "docsight.spec").read_text(encoding="utf-8")

    assert "disable_windowed_traceback=True" in spec_text
    assert "disable_windowed_traceback=False" not in spec_text


def test_build_script_uses_hash_pinned_requirements_and_creates_zip_hash():
    script = (WINDOWS_PACKAGING / "build.ps1").read_text(encoding="utf-8")

    assert "--require-hashes" in script
    assert "requirements-runtime-windows.txt" in script
    assert "requirements-build.txt" in script
    assert "Invoke-Checked" in script
    assert "[System.IO.Path]::IsPathRooted($OutputDirectory)" in script
    assert "[System.Text.UTF8Encoding]::new($false)" in script
    assert "PyInstaller" in script
    assert "DOCSight-Desktop-Preview-win64-$SafeVersion.zip" in script
    assert "Compress-Archive -Path $BundleDir" in script
    assert "Get-FileHash -Algorithm SHA256" in script


def test_build_generates_resources_and_verifies_the_actual_executable_before_zip():
    script = (WINDOWS_PACKAGING / "build.ps1").read_text(encoding="utf-8")

    generate_call = "pe_version.py"
    verify_call = "verify_pe.py"
    exe_path = 'Join-Path $BundleDir "DOCSight.exe"'
    assert generate_call in script
    assert "--label=$ResolvedVersion" in script
    assert verify_call in script
    assert exe_path in script
    assert "--icon" in script
    assert "docsight.ico" in script
    generation = "Invoke-Checked $VenvPython $VersionScript"
    pyinstaller = "Invoke-Checked $VenvPython -m PyInstaller"
    verification = "Invoke-Checked $VenvPython $VerifierScript"
    assert script.index(generation) < script.index(pyinstaller)
    assert script.index(pyinstaller) < script.index(verification)
    assert script.index(verification) < script.index("Compress-Archive")
    assert "if ($Version.Length -gt 0)" in script
    assert "return $Version.Trim()" not in script


def test_windows_packaging_docs_cover_pe_mapping_and_manual_explorer_checks():
    readme = (WINDOWS_PACKAGING / "README.md").read_text(encoding="utf-8")
    checklist = (WINDOWS_PACKAGING / "QA-CHECKLIST.md").read_text(encoding="utf-8")

    assert "v2026-07-29.1` maps to `2026.7.29.1" in readme
    assert "namespaced SHA-256 hash of the complete label" in readme
    assert "stops the build before ZIP creation" in readme
    assert "final application icon and PE version metadata remain separate work" not in readme
    assert "No final application icon or PE version metadata" not in readme
    for expected in (
        "Properties** → **Details",
        "DOCSight Desktop Preview",
        "DOCSight Project",
        "Copyright (c) 2026 Dennis Braun",
        "Original filename",
        "Exact build label / artifact version",
        "small, medium, large, and extra-large icon views",
    ):
        assert expected in checklist


def test_workflow_and_build_script_apply_the_same_versioned_zip_convention():
    build_script = (WINDOWS_PACKAGING / "build.ps1").read_text(encoding="utf-8")
    workflow = WINDOWS_WORKFLOW.read_text(encoding="utf-8")
    build_rule = safe_version_rule(build_script, "return ($Value")
    workflow_rule = safe_version_rule(workflow, '$safeVersion = "')
    versions = {
        "v1.2.3": "v1.2.3",
        "2026-07-28_rc.1": "2026-07-28_rc.1",
        "v1.2.3+build 7": "v1.2.3-build-7",
        "release/1:beta?x": "release-1-beta-x",
        "ä/1": "--1",
    }

    for version, expected_safe_version in versions.items():
        expected_name = (
            f"DOCSight-Desktop-Preview-win64-{expected_safe_version}.zip"
        )
        build_name = (
            "DOCSight-Desktop-Preview-win64-"
            f"{re.sub(build_rule[0], build_rule[1], version)}.zip"
        )
        workflow_name = (
            "DOCSight-Desktop-Preview-win64-"
            f"{re.sub(workflow_rule[0], workflow_rule[1], version)}.zip"
        )
        assert build_name == expected_name
        assert workflow_name == expected_name


def test_build_lock_contains_windows_pyinstaller_dependencies():
    lock_text = (WINDOWS_PACKAGING / "requirements-build.txt").read_text(encoding="utf-8")

    assert "pefile==" in lock_text
    assert "pywin32-ctypes==" in lock_text
    assert "sys_platform == 'win32'" in lock_text


def test_runtime_windows_lock_contains_windows_marked_dependencies():
    lock_text = (WINDOWS_PACKAGING / "requirements-runtime-windows.txt").read_text(encoding="utf-8")

    assert "click==8.4.2" in lock_text
    assert "colorama==0.4.6" in lock_text
    assert "tzdata==2026.2" in lock_text
    assert "pystray==0.19.5" in lock_text


def test_windows_runtime_and_test_locks_keep_separate_hashed_ownership():
    runtime_lock = (WINDOWS_PACKAGING / "requirements-runtime-windows.txt").read_text(
        encoding="utf-8"
    )
    test_lock = (WINDOWS_PACKAGING / "requirements-test-windows.txt").read_text(
        encoding="utf-8"
    )

    assert "pystray==0.19.5 \\\n    --hash=sha256:" in runtime_lock
    assert "six==1.17.0 \\\n    --hash=sha256:" in runtime_lock
    assert re.search(r"(?m)^pytest==\S+ \\\n    --hash=sha256:", test_lock)
    for runtime_package in ("colorama", "pystray", "six", "tzdata"):
        assert not re.search(rf"(?m)^{runtime_package}==", test_lock)


def test_pyinstaller_spec_bundles_native_tray_adapter():
    spec_text = (WINDOWS_PACKAGING / "docsight.spec").read_text(encoding="utf-8")

    assert '"tray"' in spec_text
    assert '"pystray"' in spec_text
    assert '"pystray._win32"' in spec_text


def test_docker_context_excludes_windows_packaging():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "packaging" in {line.strip("/") for line in dockerignore.splitlines()}


def test_gitignore_excludes_windows_build_outputs():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "packaging/windows/build/" in gitignore
    assert "packaging/windows/dist/" in gitignore


def test_windows_code_signing_policy_public_contract():
    policy = CODE_SIGNING_POLICY.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    windows_readme = (WINDOWS_PACKAGING / "README.md").read_text(encoding="utf-8")
    normalized_policy = " ".join(policy.split())
    policy_lower = normalized_policy.lower()
    windows_readme_lower = " ".join(windows_readme.split()).lower()
    attribution = (
        "Free code signing provided by SignPath.io, "
        "certificate by SignPath Foundation"
    )
    conditional_heading = "## Conditional provider attribution"
    status_text, conditional_text = policy.split(conditional_heading, maxsplit=1)

    assert policy.startswith("# Code signing policy\n")
    assert attribution not in status_text
    assert attribution in conditional_text
    assert (
        "will apply only if provider approval and onboarding succeed"
        in policy_lower
    )
    assert "windows artifacts remain unsigned" in policy_lower
    assert "still in progress" in policy_lower
    assert "official tagged release" in policy_lower
    for excluded_context in ("pull request", "fork", "untrusted context"):
        assert excluded_context in policy_lower
    assert "not eligible for signing" in policy_lower
    assert "source-control account" in policy_lower
    assert "future signing-approval account" in policy_lower
    assert "must use multi-factor authentication (mfa)" in policy_lower
    for approval_check in (
        "release source",
        "workflow result",
        "artifact identity",
        "expected version",
    ):
        assert approval_check in policy_lower
    assert "## Revocation and incidents" in policy
    assert "stop approving and publishing" in policy_lower
    assert "request revocation" in policy_lower
    assert "impact and verification guidance" in policy_lower
    assert "https://github.com/itsDNNS/docsight/releases" in policy
    assert "[SECURITY.md](SECURITY.md)" in policy
    assert '<a href="CODE_SIGNING.md">Code signing</a>' in readme
    assert "[code signing policy](../../CODE_SIGNING.md)" in windows_readme
    assert "preview artifacts are unsigned" in windows_readme_lower
    assert "provider onboarding is pending" in windows_readme_lower
