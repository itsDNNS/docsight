"""Offline self-hosted diagnostics for DOCSight.

The doctor command is intentionally passive by default: it inspects the same
local files, environment, and SQLite databases that the application uses, but it
must not contact modems, DNS servers, MQTT brokers, webhooks, or other optional
services unless a future explicit probe mode is added.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sqlite3
import stat
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .config import DEFAULTS, DEMO_HIDE_KEYS, ENV_MAP, HASH_KEYS, SECRET_KEYS

DOCTOR_VERSION = 1
STATUS_ORDER = ("pass", "warn", "fail", "skipped")
_MASK = "<redacted>"
_SENSITIVE_NAME_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "credential",
    "private_key",
    "apikey",
    "api_key",
    "webhook",
)
_URL_NAME_PARTS = ("url", "host", "endpoint", "registry")
_PATH_NAME_PARTS = ("path", "dir", "file")
_MAC_RE = re.compile(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_SERIAL_CUSTOMER_RE = re.compile(
    r"\b(?:SERIAL|CUSTOMER|ACCOUNT|KUNDEN|CLIENT|CONTRACT)[-_A-Z0-9]*\b",
    re.IGNORECASE,
)
_LONG_SECRET_RE = re.compile(r"(?i)(?:token|secret|password|passwd|key)=([^&\s]+)")
_ALLOWED_ENV_KEYS = {
    "DATA_DIR",
    "DEMO_MODE",
    "REVERSE_PROXY",
    "DOCSIGHT_AUDIT_JSON",
    "LOG_LEVEL",
    "MODULES_DIR",
    *ENV_MAP.values(),
}


@dataclass
class CheckResult:
    """Serializable doctor check result."""

    id: str
    category: str
    status: str
    message: str
    core: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "status": self.status,
            "message": self.message,
            "core": self.core,
            "details": self.details,
        }


def _is_sensitive_key(key: str | None) -> bool:
    if not key:
        return False
    lowered = key.lower()
    return (
        key in SECRET_KEYS
        or key in HASH_KEYS
        or key in DEMO_HIDE_KEYS
        or any(part in lowered for part in _SENSITIVE_NAME_PARTS)
    )


def _looks_like_url_key(key: str | None) -> bool:
    if not key:
        return False
    lowered = key.lower()
    return any(part in lowered for part in _URL_NAME_PARTS)


def _looks_like_path_key(key: str | None) -> bool:
    if not key:
        return False
    lowered = key.lower()
    return any(part in lowered for part in _PATH_NAME_PARTS)


def _scrub_text(value: str) -> str:
    value = _MAC_RE.sub("<mac:redacted>", value)
    value = _IPV4_RE.sub("<ip:redacted>", value)
    value = _SERIAL_CUSTOMER_RE.sub("<id:redacted>", value)
    value = _LONG_SECRET_RE.sub(lambda m: m.group(0).split("=", 1)[0] + "=" + _MASK, value)
    return value


def _redact_url(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return "<host:redacted>"
    try:
        parsed_port = parsed.port
    except ValueError:
        parsed_port = None
    port = f":{parsed_port}" if parsed_port else ""
    return f"{parsed.scheme}://<host:redacted>{port}"


def _collapse_home(value: str) -> str:
    home = str(Path.home())
    if home and value == home:
        return "~"
    if home and value.startswith(home + os.sep):
        return "~" + value[len(home):]
    return value


def redact_value(value: Any, key: str | None = None) -> Any:
    """Return a support-safe representation of a value.

    The redactor is intentionally conservative. Keyed secrets are reduced to a
    fixed placeholder; URLs and host-like fields keep only the scheme and port;
    free-form strings are scrubbed for common private identifiers.
    """

    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, Mapping):
        return {str(k): redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_value(item, key) for item in value]

    text = str(value)
    if not text:
        return text
    if _is_sensitive_key(key):
        return _MASK
    if _looks_like_url_key(key) or re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
        return _redact_url(text)
    if _looks_like_path_key(key):
        return _scrub_text(_collapse_home(text))
    return _scrub_text(text)


def _safe_path(path: str | Path) -> str:
    return redact_value(str(path), "path")


def _get_version() -> str:
    for candidate in (Path("/app/VERSION"), Path(__file__).resolve().parents[1] / "VERSION"):
        try:
            version = candidate.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        if version:
            return version
    return "dev"


def _load_config_file(data_dir: Path) -> tuple[dict[str, Any], CheckResult]:
    config_path = data_dir / "config.json"
    if not config_path.exists():
        return {}, CheckResult(
            id="config.file",
            category="configuration",
            status="warn",
            message="config.json was not found; setup may not be completed yet",
            core=False,
            details={"path": _safe_path(config_path)},
        )
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, CheckResult(
            id="config.file",
            category="configuration",
            status="fail",
            message="config.json could not be parsed",
            core=True,
            details={"path": _safe_path(config_path), "error": redact_value(str(exc), "error")},
        )
    if not isinstance(payload, dict):
        return {}, CheckResult(
            id="config.file",
            category="configuration",
            status="fail",
            message="config.json must contain a JSON object",
            core=True,
            details={"path": _safe_path(config_path)},
        )
    return payload, CheckResult(
        id="config.file",
        category="configuration",
        status="pass",
        message="config.json is readable JSON",
        core=True,
        details={"path": _safe_path(config_path), "keys": len(payload)},
    )


def _check_runtime(environ: Mapping[str, str]) -> list[CheckResult]:
    docker_detected = Path("/.dockerenv").exists() or bool(environ.get("container"))
    return [
        CheckResult(
            id="runtime.version",
            category="runtime",
            status="pass",
            message="DOCSight runtime information collected",
            details={
                "app_version": _get_version(),
                "python": platform.python_version(),
                "platform": redact_value(platform.platform(), "platform"),
                "deployment": "docker" if docker_detected else "native_python",
                "uid": os.getuid() if hasattr(os, "getuid") else None,
                "gid": os.getgid() if hasattr(os, "getgid") else None,
            },
        )
    ]


def _check_data_dir(data_dir: Path) -> CheckResult:
    if not data_dir.exists():
        return CheckResult(
            id="storage.data_dir",
            category="storage",
            status="fail",
            message="data directory does not exist",
            details={"path": _safe_path(data_dir)},
        )
    if not data_dir.is_dir():
        return CheckResult(
            id="storage.data_dir",
            category="storage",
            status="fail",
            message="data directory path is not a directory",
            details={"path": _safe_path(data_dir)},
        )

    writable = os.access(data_dir, os.W_OK | os.X_OK)
    error = "" if writable else "current user cannot write to or traverse the data directory"

    usage = shutil.disk_usage(data_dir)
    details = {
        "path": _safe_path(data_dir),
        "writable": writable,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
    }
    if error:
        details["error"] = redact_value(error, "error")
    return CheckResult(
        id="storage.data_dir",
        category="storage",
        status="pass" if writable else "fail",
        message="data directory is writable" if writable else "data directory is not writable",
        details=details,
    )


def _check_database(data_dir: Path) -> CheckResult:
    db_path = data_dir / "docsis_history.db"
    if not db_path.exists():
        return CheckResult(
            id="storage.database",
            category="storage",
            status="skipped",
            message="history database does not exist yet",
            details={"path": _safe_path(db_path)},
        )
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2) as conn:
            integrity = conn.execute("PRAGMA quick_check").fetchone()
            integrity_value = integrity[0] if integrity else "unknown"
            journal = conn.execute("PRAGMA journal_mode").fetchone()
            journal_mode = journal[0] if journal else "unknown"
            table_count = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
            snapshot_count = 0
            latest_snapshot = None
            has_snapshots = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='snapshots'"
            ).fetchone()[0]
            if has_snapshots:
                snapshot_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()
                }
                if "timestamp" in snapshot_columns:
                    row = conn.execute("SELECT COUNT(*), MAX(timestamp) FROM snapshots").fetchone()
                    snapshot_count = int(row[0] or 0)
                    latest_snapshot = row[1]
    except sqlite3.DatabaseError as exc:
        return CheckResult(
            id="storage.database",
            category="storage",
            status="fail",
            message="history database could not be opened or failed integrity checks",
            details={"path": _safe_path(db_path), "error": redact_value(str(exc), "error")},
        )
    except Exception as exc:
        return CheckResult(
            id="storage.database",
            category="storage",
            status="fail",
            message="history database check failed",
            details={"path": _safe_path(db_path), "error": redact_value(str(exc), "error")},
        )

    if integrity_value != "ok":
        return CheckResult(
            id="storage.database",
            category="storage",
            status="fail",
            message="history database quick check failed",
            details={"path": _safe_path(db_path), "quick_check": redact_value(integrity_value, "error")},
        )

    return CheckResult(
        id="storage.database",
        category="storage",
        status="pass",
        message="history database is readable",
        details={
            "path": _safe_path(db_path),
            "journal_mode": journal_mode,
            "quick_check": integrity_value,
            "tables": table_count,
            "snapshots": snapshot_count,
            "latest_snapshot": redact_value(latest_snapshot, "timestamp"),
        },
    )


def _check_secret_files(data_dir: Path, raw_config: Mapping[str, Any]) -> CheckResult:
    details: dict[str, Any] = {}
    statuses: list[str] = []
    for filename in (".config_key", ".session_key"):
        path = data_dir / filename
        if not path.exists():
            statuses.append("warn")
            details[filename] = "missing"
            continue
        try:
            path_stat = path.stat()
            mode = stat.S_IMODE(path_stat.st_mode)
            size = path_stat.st_size
        except OSError as exc:
            statuses.append("warn")
            details[filename] = redact_value(str(exc), "error")
            continue
        statuses.append("pass" if size > 0 else "warn")
        details[filename] = {"present": True, "mode": oct(mode), "size_bytes": size}

    details["admin_password_set"] = bool(raw_config.get("admin_password"))
    status = "warn" if "warn" in statuses else "pass"
    return CheckResult(
        id="auth.secret_state",
        category="security",
        status=status,
        message=(
            "secret key files are present and non-empty"
            if status == "pass"
            else "one or more local secret key files are missing or empty"
        ),
        core=False,
        details=details,
    )


def _config_value(raw_config: Mapping[str, Any], environ: Mapping[str, str], key: str) -> Any:
    env_name = ENV_MAP.get(key)
    if env_name and environ.get(env_name) not in (None, ""):
        return environ[env_name]
    if key in raw_config:
        return raw_config[key]
    return DEFAULTS.get(key, "")


def _check_configured_mode(raw_config: Mapping[str, Any], environ: Mapping[str, str]) -> CheckResult:
    demo_mode = str(_config_value(raw_config, environ, "demo_mode")).lower() in {"true", "1", "yes", "on"}
    modem_type = _config_value(raw_config, environ, "modem_type")
    configured = demo_mode or "modem_type" in raw_config or bool(environ.get("MODEM_TYPE"))
    env_overrides = sorted(name for name in _ALLOWED_ENV_KEYS if environ.get(name) not in (None, ""))
    details = {
        "configured": configured,
        "demo_mode": demo_mode,
        "modem_type": redact_value(modem_type, "modem_type") if configured else "unset",
        "env_overrides": {
            name: redact_value(environ[name], name.lower()) for name in env_overrides
        },
    }
    if not configured:
        return CheckResult(
            id="config.setup",
            category="configuration",
            status="warn",
            message="DOCSight setup does not appear to be completed yet",
            core=False,
            details=details,
        )
    return CheckResult(
        id="config.setup",
        category="configuration",
        status="pass",
        message="DOCSight setup state is present",
        details=details,
    )


def _check_backup(raw_config: Mapping[str, Any], environ: Mapping[str, str]) -> CheckResult:
    enabled = str(_config_value(raw_config, environ, "backup_enabled")).lower() in {"true", "1", "yes", "on"}
    backup_path = _config_value(raw_config, environ, "backup_path")
    if not enabled and not backup_path:
        return CheckResult(
            id="storage.backup_path",
            category="storage",
            status="skipped",
            message="automatic backups are not configured",
            core=False,
        )
    if enabled and not backup_path:
        return CheckResult(
            id="storage.backup_path",
            category="storage",
            status="warn",
            message="automatic backups are enabled but no backup path is configured",
            core=False,
        )
    path = Path(str(backup_path))
    exists = path.exists()
    writable = exists and os.access(path, os.W_OK)
    return CheckResult(
        id="storage.backup_path",
        category="storage",
        status="pass" if writable else "warn",
        message="backup path is writable" if writable else "backup path is not currently writable or does not exist",
        core=False,
        details={"path": _safe_path(path), "enabled": enabled, "exists": exists, "writable": writable},
    )


def _integration_check(
    check_id: str,
    name: str,
    required: Mapping[str, str],
    raw_config: Mapping[str, Any],
    environ: Mapping[str, str],
    enabled_key: str | None = None,
) -> CheckResult:
    enabled = True
    if enabled_key:
        enabled = str(_config_value(raw_config, environ, enabled_key)).lower() in {"true", "1", "yes", "on"}
    values = {key: _config_value(raw_config, environ, key) for key in required}
    present = {key: bool(value) for key, value in values.items()}
    if enabled_key and not enabled and not any(present.values()):
        return CheckResult(
            id=check_id,
            category="integrations",
            status="skipped",
            message=f"{name} is not configured",
            core=False,
        )
    if not any(present.values()) and not enabled_key:
        return CheckResult(
            id=check_id,
            category="integrations",
            status="skipped",
            message=f"{name} is not configured",
            core=False,
        )
    missing = [label for key, label in required.items() if not present[key]]
    status = "warn" if missing or (enabled_key and not enabled) else "pass"
    message = f"{name} configuration is present" if status == "pass" else f"{name} configuration is incomplete"
    return CheckResult(
        id=check_id,
        category="integrations",
        status=status,
        message=message,
        core=False,
        details={
            "enabled": enabled,
            "present": present,
            "missing": missing,
        },
    )


def _check_integrations(raw_config: Mapping[str, Any], environ: Mapping[str, str]) -> list[CheckResult]:
    return [
        _integration_check(
            "integration.speedtest",
            "Speedtest Tracker",
            {"speedtest_tracker_url": "URL", "speedtest_tracker_token": "token"},
            raw_config,
            environ,
        ),
        _integration_check(
            "integration.bqm",
            "BQM",
            {"bqm_url": "URL"},
            raw_config,
            environ,
        ),
        _integration_check(
            "integration.smokeping",
            "Smokeping",
            {"smokeping_url": "URL", "smokeping_targets": "targets"},
            raw_config,
            environ,
        ),
        _integration_check(
            "integration.mqtt",
            "MQTT/Home Assistant",
            {"mqtt_host": "host"},
            raw_config,
            environ,
        ),
        _integration_check(
            "integration.apprise",
            "Apprise",
            {"notify_apprise_url": "URL"},
            raw_config,
            environ,
            enabled_key="notify_apprise_enabled",
        ),
        _integration_check(
            "integration.pwa_push",
            "PWA Web Push",
            {
                "notify_pwa_push_vapid_public_key": "public key",
                "notify_pwa_push_vapid_private_key": "private key",
            },
            raw_config,
            environ,
            enabled_key="notify_pwa_push_enabled",
        ),
    ]


def _summarize(checks: list[CheckResult]) -> dict[str, Any]:
    counts = {status: 0 for status in STATUS_ORDER}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    core_fail = any(check.core and check.status == "fail" for check in checks)
    return {**counts, "total": len(checks), "core_fail": core_fail}


def build_report(data_dir: str | None = None, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Build a local, redacted doctor report without active network probes."""

    env = dict(os.environ if environ is None else environ)
    root = Path(data_dir or env.get("DATA_DIR") or "/data")
    raw_config, config_check = _load_config_file(root)
    checks: list[CheckResult] = []
    checks.extend(_check_runtime(env))
    checks.append(_check_data_dir(root))
    checks.append(config_check)
    checks.append(_check_configured_mode(raw_config, env))
    checks.append(_check_secret_files(root, raw_config))
    checks.append(_check_database(root))
    checks.append(_check_backup(raw_config, env))
    checks.extend(_check_integrations(raw_config, env))

    serializable_checks = [check.as_dict() for check in checks]
    # Final defensive scrub in case a future check forgot to redact details.
    serializable_checks = redact_value(serializable_checks)  # type: ignore[assignment]
    return {
        "doctor_version": DOCTOR_VERSION,
        "app_version": _get_version(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "data_dir": _safe_path(root),
        "checks": serializable_checks,
        "summary": _summarize(checks),
    }


def format_human(report: Mapping[str, Any], color: bool = True) -> str:
    """Render a concise human-readable report."""

    symbols = {
        "pass": "PASS",
        "warn": "WARN",
        "fail": "FAIL",
        "skipped": "SKIP",
    }
    ansi = {
        "pass": "\033[32m",
        "warn": "\033[33m",
        "fail": "\033[31m",
        "skipped": "\033[2m",
        "reset": "\033[0m",
    }
    lines = [
        f"DOCSight doctor v{report.get('doctor_version')} (app {report.get('app_version')})",
        f"Data directory: {report.get('data_dir')}",
        "",
    ]
    for check in report.get("checks", []):
        status = str(check.get("status", "skipped"))
        label = symbols.get(status, status.upper())
        if color and status in ansi:
            label = f"{ansi[status]}{label}{ansi['reset']}"
        lines.append(f"[{label}] {check.get('id')}: {check.get('message')}")
        details = check.get("details") or {}
        if details:
            rendered = json.dumps(redact_value(details), sort_keys=True, ensure_ascii=False)
            lines.append(f"       {rendered}")
    summary = report.get("summary", {})
    lines.append("")
    lines.append(
        "Summary: "
        + ", ".join(f"{status}={summary.get(status, 0)}" for status in STATUS_ORDER)
    )
    if summary.get("core_fail"):
        lines.append("Core installation checks failed.")
    else:
        lines.append("Core installation checks did not fail.")
    return "\n".join(lines) + "\n"


def _exit_code(report: Mapping[str, Any]) -> int:
    return 1 if report.get("summary", {}).get("core_fail") else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline DOCSight self-hosted diagnostics.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--data-dir", default=None, help="DOCSight data directory (default: DATA_DIR or /data)")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors in human output")
    args = parser.parse_args(argv)

    try:
        report = build_report(data_dir=args.data_dir)
    except Exception as exc:  # pragma: no cover - last-resort CLI guard
        payload = {
            "doctor_version": DOCTOR_VERSION,
            "error": redact_value(str(exc), "error"),
            "summary": {"core_fail": True},
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"DOCSight doctor failed: {payload['error']}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(format_human(report, color=(not args.no_color and sys.stdout.isatty())), end="")
    return _exit_code(report)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
