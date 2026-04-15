"""Modulation performance computation engine — v2.

Pure functions — no Flask dependencies. Per-protocol-group health index,
multi-day overview distribution, and intraday per-channel timeline.
"""

import math
import re
from datetime import datetime
from collections import defaultdict

from app.tz import to_local


# Maximum QAM order per (direction, docsis_version) — used for health index scaling.
MAX_QAM = {
    ("ds", "3.0"): 256,    # log2 = 8
    ("ds", "3.1"): 4096,   # log2 = 12
    ("us", "3.0"): 64,     # log2 = 6
    ("us", "3.1"): 1024,   # log2 = 10
}

DEGRADED_QAM_THRESHOLDS = {
    ("us", "3.1"): 256,
}

DISCLAIMER = (
    "Health indices and modulation statistics are estimates based on periodic "
    "polling samples and may not reflect every modulation change between polls."
)


# ── Parsing helpers ──────────────────────────────────────────────────


def _parse_qam_order(modulation_str):
    """Extract QAM order from modulation string. Returns None if unparseable.

    Mirrors app.analyzer._parse_qam_order but kept local to avoid circular imports.
    """
    if not modulation_str:
        return None
    mod = modulation_str.upper().replace("-", "").strip()
    if mod in ("QPSK",):
        return 4
    m = re.match(r"(\d+)\s{0,5}QAM", mod)
    if m:
        return int(m.group(1))
    return None


def _canonical_label(modulation_str):
    """Return a canonical display label for a modulation string.

    Returns (label, qam_order_or_none).
    - Known QAM → ("64QAM", 64)
    - QPSK/4QAM → ("4QAM", 4)
    - OFDM/OFDMA → ("OFDM"/"OFDMA", None)
    - Unknown → ("Unknown", None)
    """
    if not modulation_str:
        return ("Unknown", None)
    raw = modulation_str.upper().replace("-", "").strip()

    qam = _parse_qam_order(modulation_str)
    if qam is not None:
        return (f"{qam}QAM", qam)

    if raw in ("OFDM", "OFDMA"):
        return (raw, None)

    return ("Unknown", None)


def _channel_modulation(ch):
    """Return the modulation value to use for modulation analytics."""
    return ch.get("profile_modulation") or ch.get("modulation") or ch.get("type") or ""


# ── Health index (per-protocol-group) ────────────────────────────────


def _health_index_for_group(observations, direction, docsis_version):
    """Compute health index scaled to the protocol group's max QAM.

    Formula: 100 * (log2(observed_avg) - 2) / (log2(max_qam) - 2)

    This ensures US 3.0 at 64QAM → 100, DS 3.0 at 256QAM → 100, etc.
    Returns None if no numeric-QAM observations.
    """
    numeric = [(label, qam) for label, qam in observations if qam is not None]
    if not numeric:
        return None

    max_qam = MAX_QAM.get((direction, docsis_version))
    if not max_qam:
        max_qam = 4096  # fallback

    max_bits = math.log2(max_qam)
    denominator = max_bits - 2  # log2(QPSK)=2 is the floor
    if denominator <= 0:
        return 100.0

    total_bits = sum(math.log2(qam) for _, qam in numeric)
    avg_bits = total_bits / len(numeric)

    index = 100 * (avg_bits - 2) / denominator
    return round(max(0, min(100, index)), 1)


def _health_index_for_channel_baselines(observations, channel_baselines):
    """Compute health index relative to each channel's observed baseline.

    Used for downstream groups where some channels are expected to top out at a
    lower QAM order (for example fixed 64QAM channels in mixed DOCSIS 3.0
    segments). Each observation is scored against the highest numeric QAM seen
    for that channel in the selected dataset.
    """
    numeric = [
        (channel_id, qam)
        for channel_id, _, qam in observations
        if channel_id is not None and qam is not None
    ]
    if not numeric:
        return None

    scores = []
    for channel_id, qam in numeric:
        baseline_qam = channel_baselines.get(channel_id) or qam
        baseline_bits = math.log2(max(baseline_qam, 4))
        denominator = baseline_bits - 2
        if denominator <= 0:
            score = 100.0
        else:
            score = 100 * (math.log2(qam) - 2) / denominator
        scores.append(max(0, min(100, score)))

    return round(sum(scores) / len(scores), 1)


# ── Distribution helpers ─────────────────────────────────────────────


def _distribution_pct(observations):
    """Compute percentage distribution of modulation labels."""
    if not observations:
        return {}
    counts = defaultdict(int)
    for label, _ in observations:
        counts[label] += 1
    total = len(observations)
    return {label: round(count / total * 100, 1) for label, count in sorted(counts.items())}


def _low_qam_pct(observations, threshold):
    """Compute % of numeric-QAM observations where qam_order <= threshold."""
    numeric = [(label, qam) for label, qam in observations if qam is not None]
    if not numeric:
        return 0
    low_count = sum(1 for _, qam in numeric if qam <= threshold)
    return round(low_count / len(numeric) * 100, 1)


def _group_channels_by_protocol(channels):
    """Group a list of channel dicts by docsis_version.

    Returns dict: {"3.0": [ch, ...], "3.1": [ch, ...]}
    Channels without docsis_version default to "3.0".
    """
    groups = defaultdict(list)
    for ch in channels:
        ver = ch.get("docsis_version", "3.0")
        groups[ver].append(ch)
    return dict(groups)


def _degraded_qam_threshold(direction, docsis_version, default_threshold):
    """Return the modulation threshold that counts as degraded.

    Most protocol groups keep the legacy threshold. US DOCSIS 3.1 is stricter
    because 128QAM already represents a substantial drop from the normal
    1024QAM operating point.
    """
    return DEGRADED_QAM_THRESHOLDS.get((direction, docsis_version), default_threshold)


def _channel_identity(ch):
    """Return a stable per-channel identity for modulation baselines."""
    return ch.get("channel_id", ch.get("frequency"))


def _build_channel_baselines(by_date, version):
    """Return highest numeric QAM observed per channel across the full range."""
    baselines = {}
    for date_groups in by_date.values():
        for channels in date_groups:
            for ch in channels:
                if ch.get("docsis_version", "3.0") != version:
                    continue
                channel_id = _channel_identity(ch)
                if channel_id is None:
                    continue
                _, qam = _canonical_label(_channel_modulation(ch))
                if qam is None:
                    continue
                baselines[channel_id] = max(baselines.get(channel_id, 0), qam)
    return baselines


# ── Multi-day overview (distribution v2) ─────────────────────────────


def compute_distribution_v2(snapshots, direction, tz_name, low_qam_threshold=16):
    """Compute per-protocol-group daily distribution from snapshot data.

    Returns dict with protocol_groups[], aggregate{}, sample metadata, disclaimer.
    """
    channel_key = "us_channels" if direction == "us" else "ds_channels"

    # Collect all snapshots grouped by local date
    by_date = defaultdict(list)  # date_str → [(channels_list, timestamp), ...]
    for snap in snapshots:
        ts = snap.get("timestamp", "")
        local_ts = to_local(ts, tz_name) if tz_name else ts.rstrip("Z")
        date_str = local_ts[:10]
        channels = snap.get(channel_key, [])
        if channels:
            by_date[date_str].append(channels)

    if not by_date:
        return {
            "direction": direction,
            "protocol_groups": [],
            "aggregate": {"health_index": None, "low_qam_pct": 0},
            "sample_count": 0,
            "expected_samples": 0,
            "sample_density": 0,
            "disclaimer": DISCLAIMER,
        }

    sorted_dates = sorted(by_date.keys())

    # Discover all protocol groups from all snapshots
    all_versions = set()
    for date_groups in by_date.values():
        for channels in date_groups:
            for ch in channels:
                all_versions.add(ch.get("docsis_version", "3.0"))

    # Build per-protocol-group results
    protocol_groups = []
    all_health_indices = []
    all_low_qam_pcts = []
    total_sample_count = 0

    for version in sorted(all_versions):
        group = _build_protocol_group(
            version, direction, by_date, sorted_dates, low_qam_threshold
        )
        protocol_groups.append(group)
        if group["health_index"] is not None:
            all_health_indices.append((group["health_index"], group["channel_count"]))
        all_low_qam_pcts.append((group["low_qam_pct"], group["channel_count"]))

    # Total samples = number of snapshots (each snapshot is one poll)
    total_sample_count = sum(len(groups) for groups in by_date.values())
    num_days = len(sorted_dates)

    # Estimate expected samples from actual poll cadence rather than assuming 15min
    if num_days >= 2:
        # Use median daily count from complete days (exclude first/last partial days)
        daily_counts = sorted(len(by_date[d]) for d in sorted_dates)
        # Use the median of all days as the expected per-day rate
        mid = len(daily_counts) // 2
        expected_per_day = daily_counts[mid] if daily_counts else 96
    elif num_days == 1 and total_sample_count > 0:
        expected_per_day = total_sample_count
    else:
        expected_per_day = 96
    expected_samples = num_days * expected_per_day
    density = round(total_sample_count / expected_samples, 2) if expected_samples > 0 else 0
    density = min(density, 1.0)

    # Weighted aggregate across groups
    agg_hi = _weighted_avg(all_health_indices)
    agg_lq = _weighted_avg(all_low_qam_pcts)

    return {
        "direction": direction,
        "protocol_groups": protocol_groups,
        "aggregate": {
            "health_index": round(agg_hi, 1) if agg_hi is not None else None,
            "low_qam_pct": round(agg_lq, 1) if agg_lq is not None else 0,
        },
        "sample_count": total_sample_count,
        "expected_samples": expected_samples,
        "sample_density": density,
        "disclaimer": DISCLAIMER,
    }


def _weighted_avg(values_weights):
    """Compute weighted average from list of (value, weight) tuples."""
    total_w = sum(w for _, w in values_weights if w > 0)
    if total_w == 0:
        return None
    return sum(v * w for v, w in values_weights) / total_w


def _build_protocol_group(version, direction, by_date, sorted_dates, threshold):
    """Build a single protocol group result dict."""
    effective_threshold = _degraded_qam_threshold(direction, version, threshold)
    channel_baselines = _build_channel_baselines(by_date, version)

    # Collect observations per day, only for channels of this version
    all_observations = []
    all_health_observations = []
    channel_ids = set()
    days = []

    for date_str in sorted_dates:
        day_observations = []
        day_health_observations = []

        for channels in by_date[date_str]:
            group_channels = [ch for ch in channels if ch.get("docsis_version", "3.0") == version]
            if not group_channels:
                continue
            for ch in group_channels:
                channel_id = _channel_identity(ch)
                channel_ids.add(channel_id)
                mod_str = _channel_modulation(ch)
                label, qam = _canonical_label(mod_str)
                day_observations.append((label, qam))
                day_health_observations.append((channel_id, label, qam))

        if not day_observations:
            continue

        all_observations.extend(day_observations)
        all_health_observations.extend(day_health_observations)
        if direction == "ds":
            hi = _health_index_for_channel_baselines(day_health_observations, channel_baselines)
        else:
            hi = _health_index_for_group(day_observations, direction, version)
        lq = _low_qam_pct(day_observations, effective_threshold)

        # Count degraded channels for this day
        degraded = _count_degraded_channels_day(
            by_date[date_str],
            version,
            direction,
            effective_threshold,
        )

        days.append({
            "date": date_str,
            "health_index": hi,
            "low_qam_pct": lq,
            "distribution": _distribution_pct(day_observations),
            "degraded_channel_count": degraded,
        })

    max_qam = MAX_QAM.get((direction, version), 4096)
    max_qam_label = f"{max_qam}QAM"
    if direction == "ds":
        overall_hi = _health_index_for_channel_baselines(all_health_observations, channel_baselines)
    else:
        overall_hi = _health_index_for_group(all_observations, direction, version)
    overall_lq = _low_qam_pct(all_observations, effective_threshold)
    overall_dist = _distribution_pct(all_observations)
    dominant = max(overall_dist, key=overall_dist.get) if overall_dist else None

    # Overall degraded channels
    degraded_overall = _count_degraded_channels_overall(
        by_date,
        sorted_dates,
        version,
        direction,
        effective_threshold,
    )

    return {
        "docsis_version": version,
        "max_qam": max_qam_label,
        "channel_count": len(channel_ids),
        "channel_ids": sorted(channel_ids),
        "health_index": overall_hi,
        "low_qam_pct": overall_lq,
        "dominant_modulation": dominant,
        "degraded_channel_count": degraded_overall,
        "distribution": overall_dist,
        "days": days,
    }


def _count_degraded_channels_day(snapshot_groups, version, direction, threshold):
    """Count how many channels had any observation at or below the low-QAM threshold."""
    degraded = set()
    for channels in snapshot_groups:
        for ch in channels:
            if ch.get("docsis_version", "3.0") != version:
                continue
            mod_str = _channel_modulation(ch)
            _, qam = _canonical_label(mod_str)
            if qam is not None and qam <= threshold:
                degraded.add(ch.get("channel_id"))
    return len(degraded)


def _count_degraded_channels_overall(by_date, sorted_dates, version, direction, threshold):
    """Count channels that were degraded on any day in the range."""
    degraded = set()
    for date_str in sorted_dates:
        for channels in by_date[date_str]:
            for ch in channels:
                if ch.get("docsis_version", "3.0") != version:
                    continue
                mod_str = _channel_modulation(ch)
                _, qam = _canonical_label(mod_str)
                if qam is not None and qam <= threshold:
                    degraded.add(ch.get("channel_id"))
    return len(degraded)


# ── Intraday per-channel timeline ────────────────────────────────────


def compute_intraday(snapshots, direction, tz_name, date_str, low_qam_threshold=16):
    """Compute per-channel modulation timeline for a single day.

    Returns dict with protocol_groups[] each containing channels[] with timeline.
    """
    channel_key = "us_channels" if direction == "us" else "ds_channels"

    # Filter snapshots for the requested day, sorted by time
    day_snapshots = []
    for snap in snapshots:
        ts = snap.get("timestamp", "")
        local_ts = to_local(ts, tz_name) if tz_name else ts.rstrip("Z")
        snap_date = local_ts[:10]
        if snap_date == date_str:
            local_time = local_ts[11:16]  # HH:MM
            channels = snap.get(channel_key, [])
            if channels:
                day_snapshots.append((local_time, channels))

    day_snapshots.sort(key=lambda x: x[0])

    if not day_snapshots:
        return {
            "direction": direction,
            "date": date_str,
            "protocol_groups": [],
            "disclaimer": DISCLAIMER,
        }

    # Build per-channel timelines, grouped by protocol
    # channel_id → {version, frequency, timeline: [(time, label, qam)]}
    channel_data = {}
    for local_time, channels in day_snapshots:
        for ch in channels:
            cid = ch.get("channel_id")
            if cid not in channel_data:
                channel_data[cid] = {
                    "version": ch.get("docsis_version", "3.0"),
                    "frequency": ch.get("frequency", ""),
                    "timeline": [],
                }
            mod_str = _channel_modulation(ch)
            label, qam = _canonical_label(mod_str)
            channel_data[cid]["timeline"].append((local_time, label, qam))

    # Group by protocol version
    by_version = defaultdict(list)
    for cid, cdata in channel_data.items():
        by_version[cdata["version"]].append((cid, cdata))

    protocol_groups = []
    for version in sorted(by_version.keys()):
        max_qam = MAX_QAM.get((direction, version), 4096)
        max_qam_label = f"{max_qam}QAM"
        channels_result = []

        for cid, cdata in sorted(by_version[version], key=lambda x: x[0]):
            timeline = cdata["timeline"]
            periods = _modulation_periods(timeline)
            if direction == "ds":
                channel_baseline = max((q for _, _, q in timeline if q is not None), default=None)
                hi = _health_index_for_channel_baselines(
                    [(cid, l, q) for _, l, q in timeline],
                    {cid: channel_baseline} if channel_baseline is not None else {},
                )
            else:
                hi = _health_index_for_group(
                    [(l, q) for _, l, q in timeline], direction, version
                )
            degraded_threshold = _degraded_qam_threshold(direction, version, low_qam_threshold)
            degraded_events = _build_degraded_events(periods, degraded_threshold)
            degraded = len(degraded_events) > 0
            summary = _channel_summary(periods, max_qam, degraded_threshold)
            degraded_sample_pct = round(sum(evt["pct"] for evt in degraded_events))
            worst_event = min(
                degraded_events,
                key=lambda evt: (evt["qam"], -evt["count"]),
            ) if degraded_events else None

            # Simplify timeline to transition points only
            simplified = _simplify_timeline(timeline)

            channels_result.append({
                "channel_id": cid,
                "frequency": cdata["frequency"],
                "health_index": hi,
                "degraded": degraded,
                "summary": summary,
                "degraded_events": degraded_events,
                "degraded_sample_pct": degraded_sample_pct,
                "worst_modulation": worst_event["label"] if worst_event else "",
                "timeline": [{"time": t, "modulation": l} for t, l in simplified],
            })

        protocol_groups.append({
            "docsis_version": version,
            "max_qam": max_qam_label,
            "channels": channels_result,
        })

    return {
        "direction": direction,
        "date": date_str,
        "protocol_groups": protocol_groups,
        "disclaimer": DISCLAIMER,
    }


def _modulation_periods(timeline):
    """Collapse consecutive same-modulation observations into periods.

    Input: [(time, label, qam), ...]
    Returns: [(start_time, end_time, label, qam, count)]
    """
    if not timeline:
        return []

    periods = []
    current_start = timeline[0][0]
    current_label = timeline[0][1]
    current_qam = timeline[0][2]
    current_end = current_start
    count = 1

    for i in range(1, len(timeline)):
        t, label, qam = timeline[i]
        if label == current_label:
            current_end = t
            count += 1
        else:
            periods.append((current_start, current_end, current_label, current_qam, count))
            current_start = t
            current_label = label
            current_qam = qam
            current_end = t
            count = 1

    periods.append((current_start, current_end, current_label, current_qam, count))
    return periods


def _simplify_timeline(timeline):
    """Reduce timeline to only transition points (where modulation changes).

    Returns [(time, label), ...] — first point always included.
    """
    if not timeline:
        return []

    result = [(timeline[0][0], timeline[0][1])]
    for i in range(1, len(timeline)):
        if timeline[i][1] != timeline[i - 1][1]:
            result.append((timeline[i][0], timeline[i][1]))
    return result


def _channel_summary(periods, max_qam, threshold=16):
    """Generate human-readable summary of degraded periods for a channel.

    Example: "4.5h (30%) at 16QAM between 14:00–18:30"
    Returns empty string if channel never hit the low-QAM threshold.
    """
    degraded_periods = [
        p for p in periods if p[3] is not None and p[3] <= threshold
    ]
    if not degraded_periods:
        return ""

    # Estimate total observation count
    total_obs = sum(p[4] for p in periods)

    parts = []
    for start, end, label, qam, count in degraded_periods:
        pct = round(count / total_obs * 100) if total_obs > 0 else 0
        # Estimate hours (each observation ≈ 15 min)
        hours = round(count * 0.25, 1)
        if start == end:
            parts.append(f"{hours}h ({pct}%) at {label} around {start}")
        else:
            parts.append(f"{hours}h ({pct}%) at {label} between {start}\u2013{end}")

    return "; ".join(parts)


def _event_duration_minutes(start, end):
    """Return the observed clock duration between two HH:MM timestamps."""
    try:
        start_dt = datetime.strptime(start, "%H:%M")
        end_dt = datetime.strptime(end, "%H:%M")
    except (TypeError, ValueError):
        return 0

    minutes = int((end_dt - start_dt).total_seconds() // 60)
    if minutes < 0:
        minutes += 24 * 60
    return minutes


def _build_degraded_events(periods, threshold=16):
    """Return structured degraded periods for UI rendering."""
    degraded_periods = [
        p for p in periods if p[3] is not None and p[3] <= threshold
    ]
    if not degraded_periods:
        return []

    total_obs = sum(p[4] for p in periods)
    events = []
    for start, end, label, qam, count in degraded_periods:
        pct = round(count / total_obs * 100) if total_obs > 0 else 0
        duration_minutes = _event_duration_minutes(start, end)
        hours = round(count * 0.25, 1)
        events.append({
            "start": start,
            "end": end,
            "label": label,
            "qam": qam,
            "count": count,
            "hours": hours,
            "duration_minutes": duration_minutes,
            "pct": pct,
            "point_in_time": start == end,
        })
    return events


# ── Legacy compat: keep old functions available for tests ────────────


def _health_index(observations):
    """Legacy health index (global scale QPSK→4096QAM).

    weight = log2(qam_order) → range 2 (QPSK) to 12 (4096QAM)
    index = 100 * (weighted_avg - 2) / (12 - 2), clamped 0–100

    Returns None if no numeric-QAM observations exist.
    """
    numeric = [(label, qam) for label, qam in observations if qam is not None]
    if not numeric:
        return None

    total_weight = sum(math.log2(qam) for _, qam in numeric)
    weighted_avg = total_weight / len(numeric)

    index = 100 * (weighted_avg - 2) / (12 - 2)
    return round(max(0, min(100, index)), 1)


def compute_distribution(snapshots, direction, tz_name, low_qam_threshold=16):
    """Legacy v1 distribution — delegates to v2 and reshapes for backwards compat."""
    v2 = compute_distribution_v2(snapshots, direction, tz_name, low_qam_threshold)

    # Flatten protocol_groups days into unified days list
    all_dates = set()
    for pg in v2.get("protocol_groups", []):
        for day in pg.get("days", []):
            all_dates.add(day["date"])

    # Merge per-day across groups
    days = []
    for date_str in sorted(all_dates):
        day_obs = []
        sample_count = 0
        for pg in v2.get("protocol_groups", []):
            for day in pg.get("days", []):
                if day["date"] == date_str:
                    # Reconstruct observations from distribution
                    for label, pct in day.get("distribution", {}).items():
                        qam = _parse_qam_order(label)
                        day_obs.append((label, qam))
                    sample_count = max(sample_count, 1)
        days.append({
            "date": date_str,
            "sample_count": sample_count,
            "distribution": _distribution_pct(day_obs),
            "health_index": _health_index(day_obs),
            "low_qam_pct": _low_qam_pct(day_obs, low_qam_threshold),
        })

    # Aggregate
    all_obs = []
    for pg in v2.get("protocol_groups", []):
        dist = pg.get("distribution", {})
        for label, pct in dist.items():
            qam = _parse_qam_order(label)
            all_obs.append((label, qam))

    return {
        "direction": direction,
        "date_range": {
            "start": days[0]["date"] if days else None,
            "end": days[-1]["date"] if days else None,
        },
        "sample_count": v2["sample_count"],
        "expected_samples": v2["expected_samples"],
        "sample_density": v2["sample_density"],
        "low_qam_threshold": low_qam_threshold,
        "days": days,
        "aggregate": {
            "distribution": _distribution_pct(all_obs),
            "health_index": _health_index(all_obs),
            "low_qam_pct": _low_qam_pct(all_obs, low_qam_threshold),
        },
    }


def compute_trend(snapshots, direction, tz_name, low_qam_threshold=16):
    """Compute per-day trend data (lighter subset for trend chart).

    Returns list of dicts with date, health_index, low_qam_pct,
    dominant_modulation, sample_count.
    """
    result = compute_distribution(snapshots, direction, tz_name, low_qam_threshold)
    trend = []
    for day in result["days"]:
        dominant = None
        if day["distribution"]:
            dominant = max(day["distribution"], key=day["distribution"].get)
        trend.append({
            "date": day["date"],
            "health_index": day["health_index"],
            "low_qam_pct": day["low_qam_pct"],
            "dominant_modulation": dominant,
            "sample_count": day["sample_count"],
        })
    return trend
