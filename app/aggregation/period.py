"""Deterministic aggregation of stored DOCSIS snapshots."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.analyzer import resolve_snr_thresholds
from app.docsis_utils import classify_channel_family

from .contract import (
    AGGREGATION_SCHEMA_VERSION,
    Coverage,
    PeriodAggregate,
    ThresholdContext,
    Window,
)
from .provenance import aggregate_provenance, derive_historical
from .window import canonical_utc_timestamp

_AVERAGE_FIELDS = {
    "ds_power": "ds_power_avg",
    "ds_snr": "ds_snr_avg",
    "us_power": "us_power_avg",
}
_RAW_WORST_FIELDS = {
    "ds_power_max": "ds_power_max",
    "ds_power_min": "ds_power_min",
    "us_power_max": "us_power_max",
    "ds_snr_min": "ds_snr_min",
    "ds_uncorrectable_max": "ds_uncorrectable_errors",
    "ds_correctable_max": "ds_correctable_errors",
}
_COUNTER_FIELDS = {"ds_uncorrectable_max", "ds_correctable_max"}
_WORST_FIELDS = (*_RAW_WORST_FIELDS, "ds_snr_warn_min")


def _content_digest(snapshot: Mapping[str, Any]) -> str:
    payload = json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _ordered_snapshots(
    snapshots: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    return sorted(
        snapshots,
        key=lambda snapshot: (
            canonical_utc_timestamp(snapshot.get("timestamp")),
            _content_digest(snapshot),
        ),
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _empty_coverage(total: int) -> Coverage:
    return {
        "samples": 0,
        "nulls": 0,
        "unsupported": 0,
        "invalid": 0,
        "missing": 0,
        "total": total,
    }


def _full_coverage(total: int) -> Coverage:
    coverage = _empty_coverage(total)
    coverage["samples"] = total
    return coverage


def _value_state(
    values: Mapping[str, Any], key: str, *, unsupported: bool = False
) -> str:
    if unsupported:
        return "unsupported"
    if key not in values:
        return "missing"
    value = values[key]
    if value is None:
        return "nulls"
    return "samples" if _number(value) is not None else "invalid"


def _snr_warning_threshold(
    snapshot: Mapping[str, Any], numeric_snr: float, thresholds: ThresholdContext
) -> tuple[str, Any]:
    """Classify a derived threshold without treating its source SNR as a sample.

    Null/invalid/absent source SNR states are propagated by the caller. A valid
    source is counted as a derived sample only when a matching channel yields a
    finite warning threshold; otherwise the derived value is missing/invalid.
    """
    for channel in snapshot.get("ds_channels") or []:
        if not isinstance(channel, Mapping) or _number(channel.get("snr")) != numeric_snr:
            continue
        family = channel.get("channel_family") or classify_channel_family("ds", channel)
        spec = resolve_snr_thresholds(
            channel.get("modulation"),
            channel_family=family,
            thresholds=thresholds.raw,
        )
        raw_warning = spec.get("warn_min")
        if _number(raw_warning) is not None:
            return "samples", raw_warning
        return "invalid", None
    return "missing", None


def _bad_channels(
    ordered: Sequence[Mapping[str, Any]], direction: str
) -> list[tuple[Any, int]]:
    counts: dict[Any, int] = {}
    key = "ds_channels" if direction == "ds" else "us_channels"
    for snapshot in ordered:
        for channel in snapshot.get(key) or []:
            if channel.get("health") in ("good", "tolerated"):
                continue
            channel_id = channel.get("channel_id", 0)
            counts[channel_id] = counts.get(channel_id, 0) + 1
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[:5]


def aggregate_snapshot_period(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    window: Window,
    thresholds: ThresholdContext,
) -> PeriodAggregate:
    """Aggregate stored snapshots deterministically within inclusive UTC bounds.

    The caller owns storage filtering. This pure function preserves duplicate
    multiplicity, orders equal timestamps by a content digest, keeps semantic
    nulls distinct from numeric zero, and never mutates snapshots or thresholds.
    """
    ordered = _ordered_snapshots(list(snapshots or []))
    total = len(ordered)
    worst: dict[str, Any] = {
        "ds_power_max": None,
        "ds_power_min": None,
        "us_power_max": None,
        "ds_snr_min": None,
        "ds_snr_warn_min": None,
        "ds_uncorrectable_max": None,
        "ds_correctable_max": None,
        "health_critical_count": 0,
        "health_marginal_count": 0,
        "health_tolerated_count": 0,
        "total_snapshots": total,
    }
    metric_coverage = {
        key: _empty_coverage(total)
        for key in (*_AVERAGE_FIELDS, *_WORST_FIELDS)
    }
    average_values: dict[str, list[float]] = {
        "ds_power": [],
        "ds_snr": [],
        "us_power": [],
    }
    counter_totals = {"ds_correctable_errors": 0, "ds_uncorrectable_errors": 0}
    counter_supported = {"ds_correctable_errors": False, "ds_uncorrectable_errors": False}
    health_distribution: dict[Any, int] = {}
    samples: list[dict[str, Any]] = []

    for snapshot in ordered:
        raw_summary = snapshot.get("summary")
        summary = raw_summary if isinstance(raw_summary, Mapping) else {}
        errors_supported = bool(summary.get("errors_supported", True))

        for output_key, summary_key in _AVERAGE_FIELDS.items():
            state = _value_state(summary, summary_key)
            metric_coverage[output_key][state] += 1
        for output_key, summary_key in _RAW_WORST_FIELDS.items():
            state = _value_state(
                summary,
                summary_key,
                unsupported=output_key in _COUNTER_FIELDS and not errors_supported,
            )
            metric_coverage[output_key][state] += 1

        snr_source_state = _value_state(summary, "ds_snr_min")
        derived_warning = None
        if snr_source_state == "samples":
            numeric_snr = _number(summary.get("ds_snr_min"))
            assert numeric_snr is not None
            warning_state, derived_warning = _snr_warning_threshold(
                snapshot, numeric_snr, thresholds
            )
        else:
            warning_state = snr_source_state
        metric_coverage["ds_snr_warn_min"][warning_state] += 1

        health = summary.get("health", "unknown")
        health_distribution[health] = health_distribution.get(health, 0) + 1
        if health == "critical":
            worst["health_critical_count"] += 1
        elif health == "marginal":
            worst["health_marginal_count"] += 1
        elif health == "tolerated":
            worst["health_tolerated_count"] += 1

        for output_key, summary_key in _AVERAGE_FIELDS.items():
            value = _number(summary.get(summary_key))
            if value is not None:
                average_values[output_key].append(value)

        for key in ("ds_power_max", "ds_power_min"):
            raw = summary.get(key)
            numeric = _number(raw)
            if numeric is None:
                continue
            current = worst[key]
            if current is None or abs(numeric) > abs(float(current)):
                worst[key] = raw

        raw = summary.get("us_power_max")
        numeric = _number(raw)
        if numeric is not None:
            current = _number(worst["us_power_max"])
            if current is None or numeric > current:
                worst["us_power_max"] = raw

        raw_snr = summary.get("ds_snr_min")
        numeric_snr = _number(raw_snr)
        if numeric_snr is not None:
            current_snr = _number(worst["ds_snr_min"])
            if current_snr is None or numeric_snr < current_snr:
                worst["ds_snr_min"] = raw_snr
                worst["ds_snr_warn_min"] = None
            if (
                numeric_snr == _number(worst["ds_snr_min"])
                and worst["ds_snr_warn_min"] is None
                and derived_warning is not None
            ):
                worst["ds_snr_warn_min"] = derived_warning

        for summary_key, worst_key in (
            ("ds_uncorrectable_errors", "ds_uncorrectable_max"),
            ("ds_correctable_errors", "ds_correctable_max"),
        ):
            raw_counter = summary.get(summary_key) if errors_supported else None
            numeric_counter = _number(raw_counter)
            if numeric_counter is None:
                continue
            current = _number(worst[worst_key])
            if current is None or numeric_counter > current:
                worst[worst_key] = raw_counter
            counter_supported[summary_key] = True
            counter_totals[summary_key] += (
                raw_counter
                if isinstance(raw_counter, (int, float)) and not isinstance(raw_counter, bool)
                else numeric_counter
            )

        uncorr = summary.get("ds_uncorrectable_errors") if errors_supported else None
        if _number(uncorr) is None:
            uncorr = None
        samples.append({
            "timestamp": canonical_utc_timestamp(snapshot.get("timestamp")),
            "ds_power_avg": summary.get("ds_power_avg") if _number(summary.get("ds_power_avg")) is not None else None,
            "ds_snr_avg": summary.get("ds_snr_avg") if _number(summary.get("ds_snr_avg")) is not None else None,
            "us_power_avg": summary.get("us_power_avg") if _number(summary.get("us_power_avg")) is not None else None,
            "uncorr_errors": uncorr,
            "health": health,
        })

    historical = derive_historical(ordered, thresholds=thresholds)
    metric_coverage.update({
        "health_critical_count": _full_coverage(total),
        "health_marginal_count": _full_coverage(total),
        "health_tolerated_count": _full_coverage(total),
        "total_snapshots": _full_coverage(total),
    })
    return {
        "schema_version": AGGREGATION_SCHEMA_VERSION,
        "window": {"start": window.start, "end": window.end},
        "snapshot_count": total,
        "first_observed_at": samples[0]["timestamp"] if samples else None,
        "last_observed_at": samples[-1]["timestamp"] if samples else None,
        "latest_snapshot": ordered[-1] if ordered else None,
        "provenance": aggregate_provenance(ordered, thresholds=thresholds),
        "health_distribution": health_distribution,
        "worst": worst,
        "metric_coverage": metric_coverage,
        "averages": {
            key: (sum(values) / len(values) if values else None)
            for key, values in average_values.items()
        },
        "totals": {
            "ds_correctable_errors": (
                counter_totals["ds_correctable_errors"]
                if counter_supported["ds_correctable_errors"] else None
            ),
            "ds_uncorrectable_errors": (
                counter_totals["ds_uncorrectable_errors"]
                if counter_supported["ds_uncorrectable_errors"] else None
            ),
            "correctable_supported": counter_supported["ds_correctable_errors"],
            "uncorrectable_supported": counter_supported["ds_uncorrectable_errors"],
            "errors_supported": any(counter_supported.values()),
        },
        "worst_channels": {
            "ds": _bad_channels(ordered, "ds"),
            "us": _bad_channels(ordered, "us"),
        },
        "samples": samples,
        "diagnostic_notes": historical["diagnostic_notes"],
    }
