"""Filesystem helpers shared by tests."""

import pytest

# ERROR_PRIVILEGE_NOT_HELD: Windows without Developer Mode or an elevated shell.
_ERROR_PRIVILEGE_NOT_HELD = 1314


def symlink_or_skip(link, target, *, target_is_directory=False):
    """Create ``link`` pointing at ``target``; skip where the OS denies symlinks."""
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if getattr(exc, "winerror", None) == _ERROR_PRIVILEGE_NOT_HELD:
            pytest.skip("creating symlinks needs Windows Developer Mode or an elevated shell")
        raise
