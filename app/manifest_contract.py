#!/usr/bin/env python3
"""Pure-stdlib validation for DOCSight module manifests."""

from __future__ import annotations

import sys

# Direct execution otherwise places ``app/`` first on sys.path, where
# ``app/types.py`` would shadow the standard-library ``types`` module.
if __package__ in (None, ""):
    sys.path.pop(0)

import argparse
import json
import ipaddress
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


VALID_TYPES = frozenset({"driver", "integration", "analysis", "theme"})
VALID_CONTRIBUTES = frozenset(
    {
        "driver",
        "collector",
        "routes",
        "settings",
        "tab",
        "dialogs",
        "card",
        "i18n",
        "static",
        "publisher",
        "thresholds",
        "theme",
    }
)
REQUIRED_FIELDS = frozenset(
    {
        "id",
        "name",
        "description",
        "version",
        "author",
        "minAppVersion",
        "type",
        "contributes",
    }
)
OPTIONAL_FIELDS = frozenset(
    {
        "homepage",
        "license",
        "config",
        "config_secrets",
        "configPrivate",
        "menu",
        "hints",
    }
)
ALLOWED_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.]+$")


def valid_driver_hints(module_id: object, hints: object) -> bool:
    """Match the settings/setup browser contract before publishing driver hints."""
    if (not isinstance(module_id, str) or len(module_id) > 128
            or module_id in {"constructor", "prototype", "__proto__"}
            or not isinstance(hints, dict)):
        return False
    booleans = {"needs_user", "needs_password", "username_required", "credentials_required"}
    strings = {"default_url", "default_user", "url_hint", "user_hint", "password_hint"}
    for key, value in hints.items():
        if key in booleans:
            if not isinstance(value, bool):
                return False
        elif key in strings:
            if value is not None and (not isinstance(value, str) or len(value.encode("utf-16-le", errors="surrogatepass")) > 40000):
                return False
        else:
            return False
    url = hints.get("default_url")
    if url:
        try:
            parsed = urlsplit(url)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username or parsed.password
                    or any(c.isspace() or ord(c) < 32 or c == "\\" for c in url)):
                return False
            parsed.port
            host = parsed.hostname.encode("idna").decode("ascii").rstrip(".")
            if "%" in host:
                return False
            if ":" in host or host.rsplit(".", 1)[-1].isdigit() or host.rsplit(".", 1)[-1].startswith("0x"):
                ipaddress.ip_address(host)
            elif not re.fullmatch(r"[A-Za-z0-9_.-]+", host):
                return False
        except (ValueError, UnicodeError):
            return False
    return True


def _validate_unique_string_list(
    raw: dict[str, Any],
    field: str,
    errors: list[str],
) -> list[str]:
    value = raw.get(field, [])
    if (
        not isinstance(value, list)
        or not all(isinstance(item, str) for item in value)
        or len(value) != len(set(value))
    ):
        errors.append(f"'{field}' must be a list of unique strings")
        return []
    return value


def validate_manifest_contract(
    raw: object,
    *,
    builtin: bool = False,
) -> list[str]:
    """Return contract violations for a parsed manifest object."""
    if not isinstance(raw, dict):
        return ["Manifest must be a JSON object"]

    errors: list[str] = []
    fields = set(raw)
    missing = sorted(REQUIRED_FIELDS - fields)
    if missing:
        errors.append(f"Missing required fields: {', '.join(missing)}")
    unsupported = sorted(fields - ALLOWED_FIELDS)
    if unsupported:
        errors.append(f"Unsupported manifest fields: {', '.join(unsupported)}")

    for field in ("name", "description", "version", "author", "minAppVersion"):
        if field in raw and (
            not isinstance(raw[field], str) or not raw[field].strip()
        ):
            errors.append(f"'{field}' must be a non-empty string")

    module_id = raw.get("id")
    if "id" in raw and (
        not isinstance(module_id, str) or ID_PATTERN.fullmatch(module_id) is None
    ):
        errors.append(
            f"Invalid id '{module_id}': must be lowercase alphanumeric with "
            "dots/underscores, starting with a letter (e.g. 'docsight.weather')"
        )

    module_type = raw.get("type")
    if "type" in raw and module_type not in VALID_TYPES:
        errors.append(
            f"Invalid type '{module_type}': must be one of {sorted(VALID_TYPES)}"
        )

    contributes = raw.get("contributes")
    if "contributes" in raw:
        if not isinstance(contributes, dict):
            errors.append("'contributes' must be a dict")
        else:
            unknown = sorted(set(contributes) - VALID_CONTRIBUTES)
            if unknown:
                errors.append(f"Unknown contributes keys: {', '.join(unknown)}")
            invalid_values = sorted(
                key
                for key, value in contributes.items()
                if not isinstance(value, str) or not value
            )
            if invalid_values:
                errors.append(
                    "Contributes values must be non-empty strings: "
                    + ", ".join(invalid_values)
                )
            if module_type == "theme":
                forbidden = sorted(
                    {"collector", "routes", "publisher", "driver"} & set(contributes)
                )
                if forbidden:
                    errors.append(
                        "Theme modules must not contribute "
                        + ", ".join(forbidden)
                        + " (security)"
                    )

            if module_type == "driver" or "driver" in contributes:
                forbidden = sorted({"collector", "publisher"} & set(contributes))
                if forbidden:
                    errors.append("Driver modules must not contribute " + ", ".join(forbidden))
                if not valid_driver_hints(module_id, raw.get("hints", {})):
                    errors.append("Invalid driver hints or driver key")

    config = raw.get("config", {})
    if not isinstance(config, dict):
        errors.append("'config' must be a dict")
        config = {}

    config_secrets = _validate_unique_string_list(raw, "config_secrets", errors)
    undeclared_secrets = set(config_secrets) - set(config)
    if undeclared_secrets:
        # Secret key names are sensitive-adjacent metadata and must not reach
        # CLI output or discovery logs through the validation error.
        errors.append("'config_secrets' references undeclared config keys")
    non_string_secret_defaults = [
        key
        for key in config_secrets
        if key in config and not isinstance(config[key], str)
    ]
    if non_string_secret_defaults:
        errors.append("'config_secrets' defaults must be strings")

    config_private = _validate_unique_string_list(raw, "configPrivate", errors)
    if "configPrivate" in raw and not builtin:
        errors.append("'configPrivate' is available to built-in modules only")
    undeclared_private = sorted(set(config_private) - set(config))
    if undeclared_private:
        errors.append(
            "'configPrivate' references undeclared config keys: "
            + ", ".join(undeclared_private)
        )

    for field in ("menu", "hints"):
        if field in raw and not isinstance(raw[field], dict):
            errors.append(f"'{field}' must be a dict")
    for field in ("homepage", "license"):
        if field in raw and not isinstance(raw[field], str):
            errors.append(f"'{field}' must be a string")

    return errors


def _manifest_paths(arguments: list[str]) -> list[Path]:
    paths: list[Path] = []
    for argument in arguments:
        path = Path(argument)
        if path.is_dir():
            paths.extend(sorted(path.glob("*/manifest.json")))
        else:
            paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate DOCSight module manifests using the core contract."
    )
    parser.add_argument("paths", nargs="+", help="Manifest files or catalog directories")
    parser.add_argument(
        "--builtin",
        action="store_true",
        help="Allow built-in-only manifest capabilities",
    )
    args = parser.parse_args(argv)

    failed = False
    paths = _manifest_paths(args.paths)
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"{path}: invalid JSON: {exc}", file=sys.stderr)
            failed = True
            continue
        errors = validate_manifest_contract(raw, builtin=args.builtin)
        for error in errors:
            print(f"{path}: {error}", file=sys.stderr)
        failed = failed or bool(errors)

    if failed:
        return 1
    print(f"Manifest validation passed ({len(paths)} file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
