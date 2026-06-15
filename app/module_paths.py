"""Shared runtime paths for community module storage."""

import os

DEFAULT_MODULES_DIR = "/data/modules"


def get_modules_dir() -> str:
    """Return the directory used for installed community modules and themes."""
    return os.environ.get("MODULES_DIR", DEFAULT_MODULES_DIR)
