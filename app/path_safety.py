"""Shared path-sanitization helpers for module/theme installation."""

import os
import re

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.]+$")
_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")

_ALLOWED_CHILD_FILES = frozenset({"manifest.json", "theme.json"})


def safe_child_path(base_dir: str, child_name: str) -> str:
    """Resolve *child_name* inside *base_dir* safely.

    Validates *child_name* against ``ID_PATTERN`` (lowercase alphanum,
    dots, underscores) and ensures the resolved path is a strict descendant
    of *base_dir*, using a normalized, separator-aware prefix check.

    Returns the resolved absolute path on success.
    Raises ``ValueError`` for any invalid or escaping name.
    """
    if not isinstance(child_name, str) or not ID_PATTERN.match(child_name):
        raise ValueError(f"Invalid ID: {child_name!r}")

    candidate = os.path.join(base_dir, child_name)
    real_base = os.path.realpath(base_dir)
    real_candidate = os.path.realpath(candidate)

    if os.path.normcase(real_candidate) == os.path.normcase(real_base) or not os.path.normcase(real_candidate).startswith(
        os.path.normcase(real_base).rstrip(os.sep) + os.sep
    ):
        raise ValueError(f"Path escapes base directory: {child_name!r}")

    return real_candidate


def safe_child_file(validated_dir: str, filename: str) -> str:
    """Return the path to a known child file inside a validated directory.

    *validated_dir* must already be the output of :func:`safe_child_path`.
    *filename* must be in the ``_ALLOWED_CHILD_FILES`` allowlist.

    Raises ``ValueError`` if *filename* is not allowed or the resolved
    path escapes *validated_dir*.
    """
    if filename not in _ALLOWED_CHILD_FILES:
        raise ValueError(f"Filename not in allowlist: {filename!r}")

    candidate = os.path.join(validated_dir, filename)
    real_dir = os.path.realpath(validated_dir)
    real_candidate = os.path.realpath(candidate)

    if os.path.commonpath([real_dir, real_candidate]) != real_dir:
        raise ValueError(f"Child file escapes directory: {filename!r}")

    return real_candidate


def safe_manifest_subpath(module_dir: str, subpath: str) -> str:
    """Resolve a manifest-supplied sub-path safely inside *module_dir*.

    Accepts paths with forward slashes (e.g. ``templates/tab.html``,
    ``i18n/``) but rejects ``..`` components and backslashes.

    Use this for ``contributes`` values that legitimately contain
    subdirectory references (templates, i18n directories, static dirs).

    Raises ``ValueError`` if the path contains traversal sequences or
    escapes the module directory.
    """
    if not isinstance(subpath, str) or not subpath:
        raise ValueError(f"Unsafe manifest subpath: {subpath!r}")

    # Reject traversal components and backslashes
    if ".." in subpath.split("/") or "\\" in subpath:
        raise ValueError(
            f"Unsafe manifest subpath: {subpath!r} "
            "(must not contain '..' or backslashes)"
        )

    candidate = os.path.join(module_dir, subpath)
    real_base = os.path.realpath(module_dir)
    real_candidate = os.path.realpath(candidate)

    if not real_candidate.startswith(real_base + os.sep) and real_candidate != real_base:
        raise ValueError(f"Manifest subpath escapes module directory: {subpath!r}")

    return real_candidate


def safe_manifest_ref(module_dir: str, filename: str) -> str:
    """Resolve a manifest-supplied filename safely inside *module_dir*.

    Unlike :func:`safe_child_file` (which uses a hardcoded allowlist),
    this accepts any filename that matches a safe pattern (alphanumeric,
    dots, hyphens, underscores -- no slashes, no ``..``).

    Use this for values read from ``contributes`` in a module's manifest
    where the exact filename is author-chosen.

    Raises ``ValueError`` if the filename contains path separators,
    traversal sequences, or escapes the module directory.
    """
    if not isinstance(filename, str) or not _SAFE_FILENAME_RE.match(filename):
        raise ValueError(
            f"Unsafe manifest reference: {filename!r} "
            "(must be a plain filename with no path separators)"
        )

    candidate = os.path.join(module_dir, filename)
    real_base = os.path.realpath(module_dir)
    real_candidate = os.path.realpath(candidate)

    if os.path.commonpath([real_base, real_candidate]) != real_base:
        raise ValueError(f"Manifest reference escapes module directory: {filename!r}")

    return real_candidate
