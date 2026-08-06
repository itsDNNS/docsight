"""Pure downstream error-counter aggregation and growth semantics.

Counter availability is a per-channel capability.  Raw totals preserve every
available counter, while ratios use only channels that expose both counter
types so unrelated support cohorts are never combined.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


Counter = int | None


@dataclass(frozen=True)
class CounterCoverage:
    total_channels: int
    correctable_channels: int
    uncorrectable_channels: int
    comparable_channels: int
    partial_channels: int
    unsupported_channels: int

    def as_dict(self) -> dict[str, int]:
        return {
            "total_channels": self.total_channels,
            "correctable_channels": self.correctable_channels,
            "uncorrectable_channels": self.uncorrectable_channels,
            "comparable_channels": self.comparable_channels,
            "partial_channels": self.partial_channels,
            "unsupported_channels": self.unsupported_channels,
        }


@dataclass(frozen=True)
class ErrorCounterAggregate:
    raw_correctable: Counter
    raw_uncorrectable: Counter
    comparable_correctable: Counter
    comparable_uncorrectable: Counter
    coverage: CounterCoverage
    family_coverage: Mapping[str, CounterCoverage]
    comparable_channel_keys: tuple[str, ...]

    @property
    def supported(self) -> bool:
        return self.raw_correctable is not None or self.raw_uncorrectable is not None

    def coverage_dict(self) -> dict[str, object]:
        return {
            **self.coverage.as_dict(),
            "families": {
                family: coverage.as_dict()
                for family, coverage in sorted(self.family_coverage.items())
            },
        }


@dataclass(frozen=True)
class ErrorCounterGrowth:
    comparable_correctable_baseline: Counter
    comparable_uncorrectable_baseline: Counter
    raw_uncorrectable_baseline: Counter
    comparable_correctable_recent_delta: Counter
    comparable_uncorrectable_recent_delta: Counter
    raw_uncorrectable_recent_delta: Counter
    comparable_correctable_delta: Counter
    comparable_uncorrectable_delta: Counter
    raw_uncorrectable_delta: Counter
    comparable_channel_keys: tuple[str, ...]
    comparable_counter_reset: bool
    raw_uncorrectable_counter_reset: bool
    schema_baseline: bool

    @property
    def counter_reset(self) -> bool:
        return self.comparable_counter_reset or self.raw_uncorrectable_counter_reset


def _counter(value: object) -> Counter:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _channel_key(channel: Mapping[str, object]) -> str:
    """Build a stable identity used to reject cross-cohort counter deltas."""
    return "|".join(str(channel.get(key) or "") for key in (
        "docsis_version", "channel_family", "channel_id", "frequency",
    ))


def _coverage(channels: Sequence[Mapping[str, object]]) -> CounterCoverage:
    correctable = sum(_counter(channel.get("correctable_errors")) is not None for channel in channels)
    uncorrectable = sum(_counter(channel.get("uncorrectable_errors")) is not None for channel in channels)
    comparable = sum(
        _counter(channel.get("correctable_errors")) is not None
        and _counter(channel.get("uncorrectable_errors")) is not None
        for channel in channels
    )
    unsupported = sum(
        _counter(channel.get("correctable_errors")) is None
        and _counter(channel.get("uncorrectable_errors")) is None
        for channel in channels
    )
    return CounterCoverage(
        total_channels=len(channels),
        correctable_channels=correctable,
        uncorrectable_channels=uncorrectable,
        comparable_channels=comparable,
        partial_channels=len(channels) - comparable - unsupported,
        unsupported_channels=unsupported,
    )


def aggregate_error_counters(channels: Sequence[Mapping[str, object]]) -> ErrorCounterAggregate:
    """Aggregate raw totals and the cohort with both downstream counters."""
    corr_values = [_counter(channel.get("correctable_errors")) for channel in channels]
    uncorr_values = [_counter(channel.get("uncorrectable_errors")) for channel in channels]
    comparable = [
        (channel, corr, uncorr)
        for channel, corr, uncorr in zip(channels, corr_values, uncorr_values)
        if corr is not None and uncorr is not None
    ]
    families: dict[str, list[Mapping[str, object]]] = {}
    for channel in channels:
        family = str(channel.get("channel_family") or "unknown")
        families.setdefault(family, []).append(channel)

    available_corr = [value for value in corr_values if value is not None]
    available_uncorr = [value for value in uncorr_values if value is not None]
    return ErrorCounterAggregate(
        raw_correctable=sum(available_corr) if available_corr else None,
        raw_uncorrectable=sum(available_uncorr) if available_uncorr else None,
        comparable_correctable=sum(item[1] for item in comparable) if comparable else None,
        comparable_uncorrectable=sum(item[2] for item in comparable) if comparable else None,
        coverage=_coverage(channels),
        family_coverage={family: _coverage(group) for family, group in families.items()},
        comparable_channel_keys=tuple(sorted(_channel_key(item[0]) for item in comparable)),
    )


def uncorrectable_percentage(
    correctable: Counter,
    uncorrectable: Counter,
    *,
    min_codewords: int,
) -> float | None:
    """Return the percentage for comparable values, retaining unknown support."""
    if correctable is None or uncorrectable is None:
        return None
    total = correctable + uncorrectable
    if total < min_codewords:
        return 0.0
    return round((uncorrectable / total) * 100, 2)


def _delta(current: Counter, previous: Counter) -> Counter:
    if current is None or previous is None:
        return None
    return current - previous


def calculate_error_counter_growth(
    current: ErrorCounterAggregate,
    previous: ErrorCounterAggregate,
    *,
    previous_baseline: Mapping[str, object] | None = None,
    force_fresh_baseline: bool = False,
) -> ErrorCounterGrowth:
    """Calculate cumulative growth without crossing support cohorts or resets."""
    baseline = previous_baseline or {}
    previous_keys = previous.comparable_channel_keys
    baseline_keys_raw = baseline.get("comparable_channel_keys")
    baseline_keys = (
        tuple(str(value) for value in baseline_keys_raw)
        if isinstance(baseline_keys_raw, list)
        else previous_keys
    )
    cohort_changed = (
        current.comparable_channel_keys != previous_keys
        or current.comparable_channel_keys != baseline_keys
    )

    base_corr = _counter(baseline.get("ds_comparable_correctable_baseline"))
    base_uncorr = _counter(baseline.get("ds_comparable_uncorrectable_baseline"))
    base_raw_uncorr = _counter(baseline.get("ds_raw_uncorrectable_baseline"))
    if base_corr is None:
        base_corr = previous.comparable_correctable
    if base_uncorr is None:
        base_uncorr = previous.comparable_uncorrectable
    if base_raw_uncorr is None:
        base_raw_uncorr = previous.raw_uncorrectable

    comparable_reset = cohort_changed or any(
        delta is not None and delta < 0
        for delta in (
            _delta(current.comparable_correctable, previous.comparable_correctable),
            _delta(current.comparable_uncorrectable, previous.comparable_uncorrectable),
            _delta(current.comparable_correctable, base_corr),
            _delta(current.comparable_uncorrectable, base_uncorr),
        )
    )
    raw_reset = any(
        delta is not None and delta < 0
        for delta in (
            _delta(current.raw_uncorrectable, previous.raw_uncorrectable),
            _delta(current.raw_uncorrectable, base_raw_uncorr),
        )
    )

    if force_fresh_baseline or comparable_reset:
        base_corr = current.comparable_correctable
        base_uncorr = current.comparable_uncorrectable
        corr_recent = 0 if base_corr is not None else None
        uncorr_recent = 0 if base_uncorr is not None else None
        corr_delta = 0 if base_corr is not None else None
        uncorr_delta = 0 if base_uncorr is not None else None
    else:
        corr_recent = _delta(current.comparable_correctable, previous.comparable_correctable)
        uncorr_recent = _delta(current.comparable_uncorrectable, previous.comparable_uncorrectable)
        corr_delta = _delta(current.comparable_correctable, base_corr)
        uncorr_delta = _delta(current.comparable_uncorrectable, base_uncorr)

    if force_fresh_baseline or raw_reset:
        base_raw_uncorr = current.raw_uncorrectable
        raw_recent = 0 if base_raw_uncorr is not None else None
        raw_delta = 0 if base_raw_uncorr is not None else None
    else:
        raw_recent = _delta(current.raw_uncorrectable, previous.raw_uncorrectable)
        raw_delta = _delta(current.raw_uncorrectable, base_raw_uncorr)

    return ErrorCounterGrowth(
        comparable_correctable_baseline=base_corr,
        comparable_uncorrectable_baseline=base_uncorr,
        raw_uncorrectable_baseline=base_raw_uncorr,
        comparable_correctable_recent_delta=corr_recent,
        comparable_uncorrectable_recent_delta=uncorr_recent,
        raw_uncorrectable_recent_delta=raw_recent,
        comparable_correctable_delta=corr_delta,
        comparable_uncorrectable_delta=uncorr_delta,
        raw_uncorrectable_delta=raw_delta,
        comparable_channel_keys=current.comparable_channel_keys,
        comparable_counter_reset=comparable_reset and not force_fresh_baseline,
        raw_uncorrectable_counter_reset=raw_reset and not force_fresh_baseline,
        schema_baseline=force_fresh_baseline,
    )
