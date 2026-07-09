# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DOCSight Desktop Preview.

Build with:
    pyinstaller packaging/windows/docsight.spec --noconfirm --clean

The PowerShell build wrapper prepares packaging/windows/build/VERSION before
calling this spec. Data files are placed so app/version.py can resolve
<app package>/../VERSION inside PyInstaller's onedir runtime root.
"""

from pathlib import Path

ROOT = Path(SPECPATH).parents[1]
APP_DIR = ROOT / "app"
BUILD_DIR = Path(SPECPATH) / "build"
VERSION_FILE = BUILD_DIR / "VERSION"

EXCLUDED_DIRS = {"__pycache__", ".pytest_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3"}


def _relative_posix(path):
    return path.relative_to(ROOT).as_posix()


def collect_app_datas():
    datas = []
    for path in APP_DIR.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        target_dir = Path("app") / path.relative_to(APP_DIR).parent
        datas.append((str(path), target_dir.as_posix()))
    return datas


def collect_app_hiddenimports():
    hiddenimports = []
    for path in APP_DIR.rglob("*.py"):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        module_path = Path("app") / path.relative_to(APP_DIR)
        module = module_path.with_suffix("").as_posix().replace("/", ".")
        if module.endswith(".__init__"):
            module = module[: -len(".__init__")]
        hiddenimports.append(module)
    return sorted(set(hiddenimports))


if not VERSION_FILE.exists():
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text("dev\n", encoding="utf-8")


datas = collect_app_datas() + [(str(VERSION_FILE), ".")]
hiddenimports = collect_app_hiddenimports() + [
    "waitress",
]


a = Analysis(
    [str(Path(SPECPATH) / "docsight_desktop.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "pytest",
        "unittest",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DOCSight",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DOCSight",
)
