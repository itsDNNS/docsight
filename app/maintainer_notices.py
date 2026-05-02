"""Local maintainer notices for DOCSight.

Notices in this module are bundled with the installed release and evaluated
locally. They never fetch remote content, execute remote HTML, or report
telemetry when displayed or dismissed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlparse

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
ALLOWED_SEVERITIES = frozenset(SEVERITY_ORDER)
ALLOWED_LOCATIONS = frozenset({"dashboard", "settings"})
PLAIN_TEXT_FIELDS = ("title", "body", "link_label")
NOTICE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,80}$")
MAX_DISMISSED_NOTICE_IDS = 200

LOCAL_NOTICES: tuple[dict[str, Any], ...] = (
    {
        "id": "docsight-local-notices-2026-05",
        "severity": "info",
        "title": "Maintainer notices are now local-first",
        "body": (
            "DOCSight can show bundled project notices without contacting a remote "
            "feed or sending telemetry. Dismissals are stored only in your local "
            "DOCSight configuration."
        ),
        "locations": ("dashboard", "settings"),
        "link_label": "View release notes",
        "link_url": "https://github.com/itsDNNS/docsight/releases",
    },
)


class NoticeValidationError(ValueError):
    """Raised when a bundled notice violates the local notice contract."""


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _version_parts(value: str) -> tuple[tuple[int, Any], ...]:
    raw = (value or "").strip().lstrip("v")
    if not raw or raw == "dev":
        return ()
    parts: list[tuple[int, Any]] = []
    for token in raw.replace("-", ".").split("."):
        if token.isdigit():
            parts.append((0, int(token)))
        else:
            parts.append((1, token))
    return tuple(parts)


def _version_gte(current: str, minimum: str) -> bool:
    cur = _version_parts(current)
    min_parts = _version_parts(minimum)
    if not cur or not min_parts:
        return True
    return cur >= min_parts


def _version_lte(current: str, maximum: str) -> bool:
    cur = _version_parts(current)
    max_parts = _version_parts(maximum)
    if not cur or not max_parts:
        return True
    return cur <= max_parts


def is_valid_notice_id(value: str) -> bool:
    """Return True when value is safe as a stable notice identifier."""
    return bool(NOTICE_ID_PATTERN.fullmatch(value))


def _is_plain_text(value: str) -> bool:
    return "<" not in value and ">" not in value


def _is_safe_link(value: str | None) -> bool:
    if not value:
        return True
    if not isinstance(value, str):
        return False
    if value.startswith("/") and not value.startswith("//"):
        return True
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def validate_notice_schema(notice: dict[str, Any]) -> None:
    """Validate the strict local-only notice schema."""
    if not isinstance(notice, dict):
        raise NoticeValidationError("Notice must be a mapping")

    notice_id = notice.get("id")
    if not isinstance(notice_id, str) or not is_valid_notice_id(notice_id):
        raise NoticeValidationError("Notice requires a stable safe string id")

    severity = notice.get("severity", "info")
    if severity not in ALLOWED_SEVERITIES:
        raise NoticeValidationError(f"Unsupported notice severity: {severity}")

    title = notice.get("title")
    body = notice.get("body")
    if not isinstance(title, str) or not title.strip():
        raise NoticeValidationError("Notice requires a plain-text title")
    if not isinstance(body, str) or not body.strip():
        raise NoticeValidationError("Notice requires a plain-text body")

    for field in PLAIN_TEXT_FIELDS:
        value = notice.get(field)
        if value is not None:
            if not isinstance(value, str):
                raise NoticeValidationError(f"Notice field {field} must be text")
            if not _is_plain_text(value):
                raise NoticeValidationError(f"Notice field {field} must not contain HTML")

    locations = notice.get("locations", ("dashboard", "settings"))
    if not isinstance(locations, (list, tuple, set)) or not locations:
        raise NoticeValidationError("Notice requires at least one location")
    if not all(isinstance(location, str) for location in locations):
        raise NoticeValidationError("Notice locations must be text")
    unknown = set(locations) - ALLOWED_LOCATIONS
    if unknown:
        raise NoticeValidationError(f"Unsupported notice locations: {', '.join(sorted(unknown))}")

    if not _is_safe_link(notice.get("link_url")):
        raise NoticeValidationError("Notice links must be relative or HTTPS URLs")

    for key in ("starts_at", "expires_at"):
        value = notice.get(key)
        if value:
            if not isinstance(value, str):
                raise NoticeValidationError(f"Invalid {key} timestamp")
            try:
                _parse_datetime(value)
            except ValueError as exc:
                raise NoticeValidationError(f"Invalid {key} timestamp") from exc


def coerce_dismissed_notice_ids(dismissed_ids: Any) -> list[str]:
    """Normalize persisted dismissal values into bounded stable IDs."""
    if not dismissed_ids:
        return []
    if isinstance(dismissed_ids, str):
        values = [item.strip() for item in dismissed_ids.split(",")]
    elif isinstance(dismissed_ids, (list, tuple, set)):
        values = [str(item).strip() for item in dismissed_ids]
    else:
        return []

    normalized = list(dict.fromkeys(item for item in values if item and is_valid_notice_id(item)))
    return normalized[-MAX_DISMISSED_NOTICE_IDS:]


def _coerce_dismissed_ids(dismissed_ids: Any) -> set[str]:
    return set(coerce_dismissed_notice_ids(dismissed_ids))


def _matches_constraints(
    notice: dict[str, Any],
    *,
    app_version: str,
    location: str | None,
    now: datetime,
) -> bool:
    locations = set(notice.get("locations", ("dashboard", "settings")))
    if location and location not in locations:
        return False

    starts_at = _parse_datetime(notice.get("starts_at"))
    if starts_at and starts_at > now:
        return False

    expires_at = _parse_datetime(notice.get("expires_at"))
    if expires_at and expires_at <= now:
        return False

    min_version = notice.get("min_version")
    if min_version and not _version_gte(app_version, str(min_version)):
        return False

    max_version = notice.get("max_version")
    if max_version and not _version_lte(app_version, str(max_version)):
        return False

    return True


def serialize_notice(notice: dict[str, Any]) -> dict[str, Any]:
    """Return the public notice fields safe for APIs and templates."""
    validate_notice_schema(notice)
    data = {
        "id": notice["id"],
        "severity": notice.get("severity", "info"),
        "title": notice["title"],
        "body": notice["body"],
    }
    for key in ("link_label", "link_url", "min_version", "max_version"):
        if notice.get(key):
            data[key] = notice[key]
    return data


def get_active_notices(
    app_version: str,
    dismissed_ids: Any = None,
    location: str | None = None,
    *,
    now: datetime | None = None,
    notices: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return active bundled notices after local filtering and dismissal."""
    if location is not None and location not in ALLOWED_LOCATIONS:
        return []

    dismissed = _coerce_dismissed_ids(dismissed_ids)
    evaluated_at = now or datetime.now(timezone.utc)
    source = LOCAL_NOTICES if notices is None else notices
    active: list[dict[str, Any]] = []

    for notice in source:
        try:
            validate_notice_schema(notice)
            if notice["id"] in dismissed:
                continue
            if not _matches_constraints(notice, app_version=app_version, location=location, now=evaluated_at):
                continue
            active.append(serialize_notice(notice))
        except (NoticeValidationError, AttributeError, TypeError, ValueError):
            # Notices must never block the local dashboard/settings surfaces.
            # Invalid bundled entries are treated as inactive instead of
            # turning core pages into 500s.
            continue

    active.sort(key=lambda item: (SEVERITY_ORDER[item["severity"]], item["id"]))
    return active
