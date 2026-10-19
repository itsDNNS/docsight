"""Symlink-based tests stay portable to Windows without hiding real failures."""

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.fs_helpers import symlink_or_skip


TESTS_DIR = Path(__file__).resolve().parent
RAW_SYMLINK = re.compile(r"\.symlink_to\(|os\.symlink\(")


def _os_error(winerror):
    exc = OSError("symlink failed")
    exc.winerror = winerror
    return exc


def test_missing_windows_symlink_privilege_skips():
    with patch.object(Path, "symlink_to", side_effect=_os_error(1314)):
        with pytest.raises(pytest.skip.Exception, match="Developer Mode"):
            symlink_or_skip(Path("link"), Path("target"))


@pytest.mark.parametrize("winerror", [None, 5])
def test_other_symlink_errors_still_fail(winerror):
    with patch.object(Path, "symlink_to", side_effect=_os_error(winerror)):
        with pytest.raises(OSError, match="symlink failed"):
            symlink_or_skip(Path("link"), Path("target"))


def test_tests_create_symlinks_through_the_helper():
    offenders = [
        str(path.relative_to(TESTS_DIR))
        for path in TESTS_DIR.rglob("*.py")
        if path.name not in {"fs_helpers.py", Path(__file__).name}
        and RAW_SYMLINK.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], "use tests.fs_helpers.symlink_or_skip"
