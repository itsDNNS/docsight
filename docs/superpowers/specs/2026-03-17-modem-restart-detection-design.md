# Modem Restart Detection - Design Spec

**Date:** 2026-03-17
**Issue:** #60
**Status:** Draft

## Summary

Detect modem restarts by observing per-channel DOCSIS error counter resets between consecutive polling cycles. When a modem reboots, its cumulative error counters (correctable and uncorrectable) reset to zero. By comparing per-channel counters across snapshots, DOCSight can emit a `modem_restart_detected` event with high confidence.

## Goals

- Detect silent modem restarts that users would otherwise miss
- Emit an event that appears in the Event Log and Correlation Timeline
- Avoid false positives from channel map changes, parser anomalies, or first-poll scenarios

## Non-Goals

- Dashboard restart marker or dedicated UI surface (event in log is sufficient for MVP)
- Device info refresh after restart (separate scope, requires collector I/O changes)
- Aggressive polling protection or crash-loop detection (different problem class)
- Connection Monitor correlation as a detection condition (useful for timeline context, not as primary signal)

## Architecture

### Location

New method `_check_restart()` in `EventDetector` (`app/event_detector.py`), called from `check()` before `_check_errors()`.

Follows the exact pattern of `_check_errors()` (lines 262-274): compare prev vs current summary/channel data, emit event dict if threshold met.

### Detection Algorithm

```python
def _check_restart(self, events, ts, cur, prev):
    """Detect modem restart via per-channel error counter reset.

    Follows _check_modulation pattern: receives full analysis dicts,
    mutates events list in-place, returns None.
    """
    # 1. Build channel lookup by channel_id for both snapshots
    prev_channels = {ch["channel_id"]: ch for ch in prev.get("ds_channels", [])}
    cur_channels = {ch["channel_id"]: ch for ch in cur.get("ds_channels", [])}

    # 2. Find overlapping channels (present in both snapshots)
    overlap_ids = set(prev_channels.keys()) & set(cur_channels.keys())

    # 3. Guard: insufficient continuity
    prev_count = len(prev_channels)
    cur_count = len(cur_channels)
    if len(overlap_ids) < RESTART_MIN_OVERLAP:
        return
    if prev_count > 0 and len(overlap_ids) / prev_count < RESTART_MIN_CONTINUITY:
        return
    if cur_count > 0 and len(overlap_ids) / cur_count < RESTART_MIN_CONTINUITY:
        return

    # 4. Count channels with declining counters
    #    A channel is "declining" if at least one counter type decreased
    #    and neither counter increased. This correctly handles the common
    #    case where uncorrectable_errors was already 0 before restart:
    #    (N, 0) → (0, 0) counts as declining because correctable declined
    #    and uncorrectable stayed the same.
    valid_channels = 0
    declining_channels = 0

    for ch_id in overlap_ids:
        p = prev_channels[ch_id]
        c = cur_channels[ch_id]
        p_corr = p.get("correctable_errors")
        p_uncorr = p.get("uncorrectable_errors")
        c_corr = c.get("correctable_errors")
        c_uncorr = c.get("uncorrectable_errors")

        # Skip if any counter is None (invalid data)
        if any(v is None for v in (p_corr, p_uncorr, c_corr, c_uncorr)):
            continue

        valid_channels += 1
        corr_declined = c_corr < p_corr
        uncorr_declined = c_uncorr < p_uncorr
        corr_ok = c_corr <= p_corr
        uncorr_ok = c_uncorr <= p_uncorr
        if (corr_declined or uncorr_declined) and corr_ok and uncorr_ok:
            declining_channels += 1

    # 5. Guard: not enough valid channels
    if valid_channels < RESTART_MIN_OVERLAP:
        return

    # 6. Primary signal: >=80% of valid overlapping channels are declining
    if declining_channels / valid_channels < RESTART_CHANNEL_THRESHOLD:
        return

    # 7. Sanity check: at least one summary total must decline
    prev_summary = prev.get("summary", {})
    cur_summary = cur.get("summary", {})
    prev_corr_total = prev_summary.get("ds_correctable_errors", 0)
    prev_uncorr_total = prev_summary.get("ds_uncorrectable_errors", 0)
    cur_corr_total = cur_summary.get("ds_correctable_errors", 0)
    cur_uncorr_total = cur_summary.get("ds_uncorrectable_errors", 0)

    if cur_corr_total >= prev_corr_total and cur_uncorr_total >= prev_uncorr_total:
        return  # Neither total declining — not a restart

    # 8. Emit event
    events.append({
        "timestamp": ts,
        "severity": "info",
        "event_type": "modem_restart_detected",
        "message": "Detected modem restart or counter reset pattern",
        "details": {
            "affected_channels": declining_channels,
            "total_channels": valid_channels,
            "prev_corr_total": prev_corr_total,
            "prev_uncorr_total": prev_uncorr_total,
            "current_corr_total": cur_corr_total,
            "current_uncorr_total": cur_uncorr_total,
        },
    })
```

### Integration into check()

In `check()`, insert before `_check_errors` (between lines 69 and 70, after `_check_modulation`):

```python
self._check_restart(events, ts, analysis, prev)
```

Follows `_check_modulation`'s pattern: receives full analysis dicts, mutates `events` in-place, returns None.

### Constants

```python
RESTART_CHANNEL_THRESHOLD = 0.8    # 80% of valid channels must be declining
RESTART_MIN_OVERLAP = 4            # Minimum overlapping channels for fair comparison
RESTART_MIN_CONTINUITY = 0.5       # Minimum overlap ratio (vs either snapshot)
```

Defined at module level in `event_detector.py`, alongside the existing `UNCORR_SPIKE_THRESHOLD`.

## Edge Cases

| Scenario | Behavior |
|---|---|
| First poll after DOCSight start | `prev is None` → `check()` returns early, `_check_restart` never called |
| Channel map change (new channel IDs) | Overlap drops below 50% → no restart verdict |
| Single channel reset (partial) | Less than 80% declining → no restart verdict |
| All counters were already 0 | Neither counter declined (0 < 0 is false) → not counted as declining. But channels with (N, 0) → (0, 0) ARE counted because correctable declined. |
| Some channels have None counters | Skipped from valid_channels count entirely |
| Counter wrap (32-bit overflow) | Would appear as decline, but extremely rare. Accepted as false positive. |
| Modem restart + channel map change | If ≥50% overlap and ≥80% declining in overlap → still detected |
| Driver returns empty channel list | `overlap_ids` empty → guard catches it |

## Event Format

```json
{
    "timestamp": "2026-03-17T14:30:00Z",
    "severity": "info",
    "event_type": "modem_restart_detected",
    "message": "Detected modem restart or counter reset pattern",
    "details": {
        "affected_channels": 12,
        "total_channels": 14,
        "prev_corr_total": 45230,
        "prev_uncorr_total": 128,
        "current_corr_total": 0,
        "current_uncorr_total": 0
    }
}
```

Severity is `info` (not `warning`) because a restart is an observation, not necessarily a problem. The event appears in the Event Log and Correlation Timeline alongside other events.

## Testing Strategy

### Unit Tests

- `test_restart_detected` — all channels reset to 0
- `test_restart_partial_channels` — 85% declining, 15% unchanged → detected
- `test_no_restart_below_threshold` — 70% declining → not detected
- `test_no_restart_first_poll` — prev is None → no event
- `test_no_restart_counters_increasing` — normal operation, counters go up
- `test_no_restart_insufficient_overlap` — channel map changed, <50% overlap
- `test_no_restart_too_few_channels` — only 3 overlapping channels
- `test_no_restart_totals_not_declining` — per-channel declining but totals still up (edge case)
- `test_no_restart_none_counters` — channels with None values skipped
- `test_restart_with_some_channel_change` — overlap ≥50%, channels declining → detected
- `test_channels_already_zero` — 0→0 not counted as declining
- `test_restart_does_not_trigger_error_spike` — restart pattern does not also emit error_spike (negative delta)
- `test_channel_with_zero_uncorr_before_restart` — (N, 0) → (0, 0) correctly counted as declining

### Integration

- ModemCollector poll cycle with mock data showing restart pattern → event emitted and stored

## i18n

One new key per language (EN/DE/FR/ES), following the existing `event_type_<event_type>` pattern used by the Event Log UI:
- `event_type_modem_restart_detected`: "Modem restart detected" / "Modem-Neustart erkannt" / "Redémarrage du modem détecté" / "Reinicio del módem detectado"

## Migration

No schema changes. Uses existing `events` table. No new config keys.
