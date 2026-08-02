"""Stable channel identity and exact selector matching for channel history views."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation


_FREQUENCY_RE = re.compile(
    r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(hz|khz|mhz)?$",
    re.IGNORECASE,
)


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise InvalidOperation
    normalized = format(value.normalize(), "f")
    return "0" if normalized in ("-0", "") else normalized


def normalize_channel_id(value) -> str:
    """Normalize numeric IDs across int/float/string storage representations."""
    if value is None or isinstance(value, bool):
        return "z:"
    text = str(value).strip()
    try:
        return "n:" + _canonical_decimal(Decimal(text))
    except (InvalidOperation, ValueError):
        return "t:" + text


def legacy_channel_id(value) -> int | None:
    """Return the legacy integer ID representation, or None when invalid."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def normalize_frequency(value) -> str:
    """Normalize stored numeric and unit-bearing frequency forms to MHz."""
    if value is None or isinstance(value, bool):
        return "z:"
    text = str(value).strip()
    match = _FREQUENCY_RE.fullmatch(text)
    if match:
        try:
            frequency = Decimal(match.group(1))
            unit = (match.group(2) or "mhz").lower()
            if unit == "hz":
                frequency /= Decimal(1_000_000)
            elif unit == "khz":
                frequency /= Decimal(1_000)
            return "n:" + _canonical_decimal(frequency)
        except (InvalidOperation, ValueError):
            pass
    return "t:" + " ".join(text.lower().split())


def channel_selector(channel: dict) -> str:
    """Build an opaque, stable selector from modem ID and channel frequency."""
    identity = [
        normalize_channel_id(channel.get("channel_id")),
        normalize_frequency(channel.get("frequency")),
    ]
    payload = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).digest()[:18]
    encoded = base64.urlsafe_b64encode(digest).decode("ascii")
    return "c1_" + encoded.rstrip("=")


def attach_channel_selectors(channels: list[dict]) -> list[dict]:
    """Copy current channel rows and add selector metadata for frontend use."""
    id_counts = Counter(
        normalize_channel_id(channel.get("channel_id")) for channel in channels
    )
    result = []
    for channel in channels:
        row = dict(channel)
        normalized_id = normalize_channel_id(channel.get("channel_id"))
        legacy_id = legacy_channel_id(channel.get("channel_id"))
        row["selector"] = channel_selector(channel)
        row["selector_required"] = legacy_id is None or id_counts[normalized_id] > 1
        if legacy_id is not None:
            row["legacy_channel_id"] = legacy_id
        result.append(row)
    return result


def match_channel(
    channels: list[dict], *, selector: str | None = None, channel_id=None
) -> dict | None:
    """Return exactly one matching row; unmatched or ambiguous matches return None."""
    requested = [selector] if selector is not None else [channel_id]
    matches = match_channels(
        channels,
        selectors=requested if selector is not None else None,
        channel_ids=requested if selector is None else None,
    )
    return matches.get(requested[0])


def match_channels(
    channels: list[dict], *, selectors=None, channel_ids=None
) -> dict:
    """Match multiple identities after indexing each snapshot channel once."""
    selectors = list(selectors or [])
    requested = selectors if selectors else list(channel_ids or [])
    if not requested:
        return {}

    grouped = defaultdict(list)
    if selectors:
        for channel in channels:
            grouped[channel_selector(channel)].append(channel)
    else:
        for channel in channels:
            normalized_id = legacy_channel_id(channel.get("channel_id"))
            if normalized_id is not None:
                grouped[normalized_id].append(channel)

    result = {}
    for identity in requested:
        key = identity if selectors else legacy_channel_id(identity)
        matches = grouped.get(key, [])
        result[identity] = matches[0] if len(matches) == 1 else None
    return result
