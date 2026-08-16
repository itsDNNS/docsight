"""Provenance-aware historical diagnostic derivation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.analyzer import resolve_ds_power_thresholds, resolve_snr_thresholds
from app.docsis_utils import (
    channel_type_label as _channel_type_label,
)
from app.docsis_utils import (
    classify_channel_family as _classify_channel_family,
)
from app.docsis_utils import (
    modulation_threshold_key as _modulation_threshold_key,
)
from app.threshold_profiles import BUILTIN_THRESHOLD_PROFILES

from .contract import AggregateProvenance, ThresholdContext
from .window import canonical_utc_timestamp

_INVALID_METADATA_VALUE = "invalid"


def _metadata_token(value: Any) -> str | None:
    """Project a controlled metadata token without copying arbitrary payloads."""
    if isinstance(value, str) or value is None:
        return value
    return _INVALID_METADATA_VALUE


def _analyzer_schema(value: Any) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return _INVALID_METADATA_VALUE
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return _INVALID_METADATA_VALUE


def aggregate_provenance(
    snapshots: Sequence[Mapping[str, Any]], *, thresholds: ThresholdContext
) -> AggregateProvenance:
    """Return counted, deterministic, metadata-only aggregate provenance."""
    counts: dict[tuple[int | str | None, str | None, str | None, str | None], int] = {}
    legacy_no_metadata = 0
    for snapshot in snapshots:
        meta = snapshot.get("analysis_meta")
        if not isinstance(meta, Mapping) or not any(
            key in meta for key in ("analyzer_schema", "app_version", "threshold_profile")
        ):
            legacy_no_metadata += 1
            continue

        profile = meta.get("threshold_profile")
        if isinstance(profile, Mapping):
            profile_id = _metadata_token(profile.get("id"))
            profile_version = _metadata_token(profile.get("version"))
        elif profile is None:
            profile_id = None
            profile_version = None
        else:
            profile_id = _INVALID_METADATA_VALUE
            profile_version = _INVALID_METADATA_VALUE
        identity = (
            _analyzer_schema(meta.get("analyzer_schema")),
            _metadata_token(meta.get("app_version")),
            profile_id,
            profile_version,
        )
        counts[identity] = counts.get(identity, 0) + 1

    metadata = [
        {
            "analyzer_schema": identity[0],
            "app_version": identity[1],
            "threshold_profile": {"id": identity[2], "version": identity[3]},
            "count": count,
        }
        for identity, count in sorted(
            counts.items(),
            key=lambda item: tuple(
                (type(value).__name__, str(value)) for value in item[0]
            ),
        )
    ]
    return {
        "source": "stored_snapshots",
        "active_threshold_profile": {
            "id": _metadata_token(thresholds.profile_id),
            "version": _metadata_token(thresholds.profile_version),
        },
        "stored_snapshot_analyzers": {
            "legacy_no_metadata": legacy_no_metadata,
            "metadata": metadata,
        },
    }

def _historical_builtin_thresholds(snapshot):
    """Return immutable built-in thresholds only for an exact provenance match."""
    meta = snapshot.get("analysis_meta")
    profile_ref = meta.get("threshold_profile") if isinstance(meta, dict) else None
    if not isinstance(profile_ref, dict):
        return None

    profile_id = profile_ref.get("id")
    profile_version = profile_ref.get("version")
    for profile in BUILTIN_THRESHOLD_PROFILES:
        if profile.get("id") != profile_id or profile.get("version") != profile_version:
            continue
        thresholds = profile.get("thresholds")
        return thresholds if isinstance(thresholds, dict) else None
    return None


def _has_analyzer_snapshot_semantics(snapshot):
    """Return whether sparse metric-health keys use analyzer-era semantics."""
    meta = snapshot.get("analysis_meta")
    if not isinstance(meta, dict):
        return False

    schema = meta.get("analyzer_schema")
    if isinstance(schema, bool):
        return False
    if isinstance(schema, int):
        return schema >= 1
    if isinstance(schema, float):
        return math.isfinite(schema) and schema.is_integer() and schema >= 1
    return False


def _historical_power_bounds(thresholds, direction, channel, family):
    if thresholds is None:
        return None
    section_name = "upstream_power" if direction == "us" else "downstream_power"
    section = thresholds.get(section_name)
    if not isinstance(section, dict):
        return None

    if direction == "us":
        key = "ofdma" if family == "ofdma" else "sc_qam"
    elif family == "ofdm":
        key = "ofdm"
    else:
        key = _modulation_threshold_key(channel.get("modulation"), section)
    spec = section.get(key)
    critical = spec.get("critical") if isinstance(spec, dict) else None
    if not isinstance(critical, (list, tuple)) or len(critical) != 2:
        return None
    try:
        return float(critical[0]), float(critical[1])
    except (TypeError, ValueError):
        return None


def _historical_snr_min(thresholds, channel, family):
    if thresholds is None:
        return None
    section = thresholds.get("snr")
    if not isinstance(section, dict):
        return None
    key = "ofdm" if family == "ofdm" else _modulation_threshold_key(
        channel.get("modulation"), section
    )
    spec = section.get(key)
    if not isinstance(spec, dict) or "critical_min" not in spec:
        return None
    try:
        return float(spec["critical_min"])
    except (TypeError, ValueError):
        return None


def _stored_metric_direction(channel, metric):
    """Read the analyzer's stored critical direction without reclassification."""
    detail = str(channel.get("health_detail") or "").lower()
    if metric == "snr" and "snr critical" in detail:
        return "low"
    if f"{metric} critical high" in detail:
        return "high"
    if f"{metric} critical low" in detail:
        return "low"
    return None


def _diagnostic_note(
    *, note_type, channel, channel_label, metric, value, boundary=None,
    boundary_key=None, extreme_pct=50,
):
    note = {
        "type": note_type,
        "channel_id": channel.get("channel_id", "?"),
        "channel_type": channel_label,
        "metric": metric,
        "value": value,
        "unit": "dB" if metric == "SNR/MER" else "dBmV",
        "severity": "critical",
    }
    if boundary is None or boundary_key is None:
        return note

    if boundary_key == "spec_max":
        distance = value - boundary
    else:
        distance = boundary - value
    if distance <= 0:
        # The stored critical classification remains authoritative even when a
        # supposedly matching profile is internally inconsistent with it.
        return note

    deviation = round(distance / max(abs(boundary), 1) * 100)
    note.update({boundary_key: boundary, "deviation_pct": deviation})
    note["severity"] = "extreme" if deviation > extreme_pct else "critical"
    return note


def _snapshot_diagnostic_notes(current_analysis, thresholds):
    """Build critical notes without reinterpreting stored analyzer output.

    Analyzer-era metric-health keys are sparse, so an absent key means good.
    Exact numeric claims are reconstructed only from a built-in profile whose
    stored id and version both match. Legacy snapshots without a key retain
    the active-threshold behavior used before provenance was persisted.
    """
    if not current_analysis:
        return []

    notes = []
    analyzer_snapshot = _has_analyzer_snapshot_semantics(current_analysis)
    us_thresholds = (
        {} if analyzer_snapshot else thresholds.raw.get("upstream_power", {})
    )
    historical_thresholds = _historical_builtin_thresholds(current_analysis)

    for ch in current_analysis.get("us_channels", []):
        power = ch.get("power")
        if power is None:
            continue
        family = _classify_channel_family("us", ch)
        key = "ofdma" if family == "ofdma" else "sc_qam"
        channel_label = _channel_type_label("us", ch) or (ch.get("modulation") or key.upper())
        if "power_health" in ch:
            if ch.get("power_health") != "critical":
                continue
            bounds = _historical_power_bounds(historical_thresholds, "us", ch, family)
            stored_direction = _stored_metric_direction(ch, "power")
            if stored_direction is None and bounds is not None:
                if power > bounds[1]:
                    stored_direction = "high"
                elif power < bounds[0]:
                    stored_direction = "low"
            if stored_direction == "high":
                notes.append(_diagnostic_note(
                    note_type="us_power_high", channel=ch, channel_label=channel_label,
                    metric="upstream power", value=power,
                    boundary=bounds[1] if bounds else None, boundary_key="spec_max",
                ))
            elif stored_direction == "low":
                notes.append(_diagnostic_note(
                    note_type="us_power_low", channel=ch, channel_label=channel_label,
                    metric="upstream power", value=power,
                    boundary=bounds[0] if bounds else None, boundary_key="spec_min",
                ))
            continue
        if analyzer_snapshot:
            continue

        # Explicit legacy behavior: only snapshots predating analyzer schema
        # provenance use the currently active analyzer profile.
        spec = us_thresholds.get(key, {})
        crit = spec.get("critical", [35.0, 53.0])
        if power > crit[1]:
            notes.append(_diagnostic_note(
                note_type="us_power_high", channel=ch, channel_label=channel_label,
                metric="upstream power", value=power,
                boundary=crit[1], boundary_key="spec_max",
            ))
        elif power < crit[0]:
            notes.append(_diagnostic_note(
                note_type="us_power_low", channel=ch, channel_label=channel_label,
                metric="upstream power", value=power,
                boundary=crit[0], boundary_key="spec_min",
            ))

    for ch in current_analysis.get("ds_channels", []):
        mod = (ch.get("modulation") or "256QAM").upper()
        family = ch.get("channel_family") or _classify_channel_family("ds", ch)
        channel_label = _channel_type_label("ds", ch) or mod
        power = ch.get("power")
        if power is not None:
            if "power_health" in ch:
                if ch.get("power_health") == "critical":
                    bounds = _historical_power_bounds(historical_thresholds, "ds", ch, family)
                    stored_direction = _stored_metric_direction(ch, "power")
                    if stored_direction is None and bounds is not None:
                        if power > bounds[1]:
                            stored_direction = "high"
                        elif power < bounds[0]:
                            stored_direction = "low"
                    if stored_direction == "high":
                        notes.append(_diagnostic_note(
                            note_type="ds_power_high", channel=ch, channel_label=channel_label,
                            metric="downstream power", value=power,
                            boundary=bounds[1] if bounds else None, boundary_key="spec_max",
                        ))
                    elif stored_direction == "low":
                        notes.append(_diagnostic_note(
                            note_type="ds_power_low", channel=ch, channel_label=channel_label,
                            metric="downstream power", value=power,
                            boundary=bounds[0] if bounds else None, boundary_key="spec_min",
                        ))
            elif not analyzer_snapshot:
                spec = resolve_ds_power_thresholds(mod, channel_family=family, thresholds=thresholds.raw)
                if power > spec["crit_max"]:
                    notes.append(_diagnostic_note(
                        note_type="ds_power_high", channel=ch, channel_label=channel_label,
                        metric="downstream power", value=power,
                        boundary=spec["crit_max"], boundary_key="spec_max",
                    ))
                elif power < spec["crit_min"]:
                    notes.append(_diagnostic_note(
                        note_type="ds_power_low", channel=ch, channel_label=channel_label,
                        metric="downstream power", value=power,
                        boundary=spec["crit_min"], boundary_key="spec_min",
                    ))

        snr = ch.get("snr")
        if snr is not None:
            if "snr_health" in ch:
                if ch.get("snr_health") == "critical":
                    snr_crit = _historical_snr_min(historical_thresholds, ch, family)
                    if _stored_metric_direction(ch, "snr") == "low":
                        notes.append(_diagnostic_note(
                            note_type="snr_low", channel=ch, channel_label=channel_label,
                            metric="SNR/MER", value=snr, boundary=snr_crit,
                            boundary_key="spec_min", extreme_pct=30,
                        ))
            elif not analyzer_snapshot:
                snr_spec = resolve_snr_thresholds(mod, channel_family=family, thresholds=thresholds.raw)
                snr_crit = snr_spec["crit_min"]
                if snr < snr_crit:
                    notes.append(_diagnostic_note(
                        note_type="snr_low", channel=ch, channel_label=channel_label,
                        metric="SNR/MER", value=snr, boundary=snr_crit,
                        boundary_key="spec_min", extreme_pct=30,
                    ))

    return notes


_DIAGNOSTIC_TYPE_ORDER = {
    "us_power_high": 0,
    "us_power_low": 1,
    "ds_power_high": 2,
    "ds_power_low": 3,
    "snr_low": 4,
}


_canonical_snapshot_timestamp = canonical_utc_timestamp

def _stable_channel_identity(note):
    channel_id = note.get("channel_id")
    try:
        return 0, int(channel_id)
    except (TypeError, ValueError):
        return 1, str(channel_id or "")


def _derive_historical(snapshots, *, thresholds: ThresholdContext):
    """Derive latest status and one deterministic worst diagnostic per type."""
    prepared = []
    candidates = []
    for snapshot in snapshots or []:
        observed_at = _canonical_snapshot_timestamp(snapshot.get("timestamp"))
        prepared.append((observed_at, snapshot))
        for note in _snapshot_diagnostic_notes(snapshot, thresholds):
            candidate = dict(note)
            candidate["observed_at"] = observed_at
            candidates.append(candidate)

    latest_snapshot = None
    if prepared:
        latest_snapshot = max(prepared, key=lambda item: item[0])[1]

    selected = {}
    for note in candidates:
        note_type = note.get("type")
        if note_type not in _DIAGNOSTIC_TYPE_ORDER:
            continue
        numeric_provenance = "deviation_pct" in note
        if numeric_provenance:
            try:
                evidence_rank = -float(note["deviation_pct"])
            except (TypeError, ValueError):
                numeric_provenance = False
        if not numeric_provenance:
            try:
                raw_value = float(note.get("value"))
            except (TypeError, ValueError):
                raw_value = 0.0
            evidence_rank = -raw_value if note_type.endswith("_high") else raw_value

        # Exact numeric provenance is preferred because its deviations are
        # historically comparable. Neutral stored-critical evidence is ranked
        # only by its direction-aware raw value; no percentage is fabricated.
        rank = (
            0 if numeric_provenance else 1,
            evidence_rank,
            note["observed_at"],
            _stable_channel_identity(note),
            str(note.get("channel_type") or ""),
            _DIAGNOSTIC_TYPE_ORDER[note_type],
        )
        existing = selected.get(note_type)
        if existing is None or rank < existing[0]:
            selected[note_type] = (rank, note)

    notes = [
        selected[note_type][1]
        for note_type in sorted(selected, key=_DIAGNOSTIC_TYPE_ORDER.get)
    ]
    return {"latest_snapshot": latest_snapshot, "diagnostic_notes": notes}



def derive_historical(snapshots, *, thresholds: ThresholdContext):
    """Derive latest status and deterministic diagnostic notes for a period."""
    return _derive_historical(snapshots, thresholds=thresholds)


def derive_diagnostic_notes(ordered_snapshots, thresholds: ThresholdContext):
    """Derive deterministic provenance-aware notes for ordered snapshots."""
    return _derive_historical(ordered_snapshots, thresholds=thresholds)["diagnostic_notes"]
