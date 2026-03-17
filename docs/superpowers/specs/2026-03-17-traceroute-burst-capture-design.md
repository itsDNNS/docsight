# Traceroute Burst Capture - Design Spec

**Date:** 2026-03-17
**Issue:** #196
**Status:** Draft
**Depends on:** Connection Monitor Phase 1 (#194, merged)

## Summary

Add on-demand and event-triggered traceroute capture to the Connection Monitor module. Instead of continuous traceroute data (expensive), run traceroute bursts when problems are detected or when the user requests one, capturing hop-level evidence at the moments it matters most.

## Goals

- Provide hop-level network path evidence when outages or packet loss occur
- Allow manual traceroute from the UI for ad-hoc debugging
- Store route fingerprints for future route-change detection (Phase 3)
- Fit into the existing Connection Monitor architecture without disrupting probe cycles

## Non-Goals

- Periodic/scheduled traceroute (generates data without clear purpose)
- Route-change detection as a trigger (complex, deferred to Phase 3; fingerprints are stored for later use)
- Route-change API endpoint (deferred to Phase 3; fingerprint data is stored now for future use)
- Remote traceroute from probe agents (#197)
- Visual hop-map or geographic visualization
- Paris traceroute or multi-path detection

## Architecture

### Components

```
ConnectionMonitorCollector
├── ProbeEngine (existing: ICMP/TCP)
├── TracerouteProbe (new: wraps C helper)
├── ConnectionEventRules (existing: emits outage/loss events)
├── TracerouteTrigger (new: listens to events, enforces cooldown, owns its own executor)
├── ConnectionMonitorStorage (extended: trace tables)
└── Routes (extended: trace endpoints)
```

### Data Flow

**Event-triggered:**
```
ProbeEngine detects outage/loss
  → ConnectionEventRules emits cm_target_unreachable or cm_packet_loss_warning
  → Collector iterates events, calls TracerouteTrigger.on_event() for each
  → TracerouteTrigger checks cooldown (5 min per target)
  → If allowed: resolves target_id → host via storage
  → TracerouteProbe.run() in TracerouteTrigger's own ThreadPoolExecutor (non-blocking)
  → Result saved to traceroute_traces + traceroute_hops
```

**Manual:**
```
POST /api/connection-monitor/traceroute/<target_id>
  → Looks up target host from storage
  → TracerouteProbe.run() (synchronous, ignores cooldown, 30s total timeout)
  → Result returned in response + saved to storage
```

## Traceroute Helper Binary

### `docsight-traceroute-helper`

Separate setuid C binary. Shares build infrastructure with `docsight-icmp-helper` (same Dockerfile stage, same install pattern) but is a distinct binary with its own scope.

**Note:** Unlike the existing ICMP helper, this binary introduces explicit privilege dropping after socket creation (`seteuid(getuid())`). This is a security improvement — the ICMP helper should be updated to match in a follow-up, but that is out of scope for this spec.

**Usage:**
```
docsight-traceroute-helper [--check] <host> [max_hops] [timeout_ms]
```

**Behavior:**
- Sends ICMP Echo Request with TTL=1, TTL=2, ... up to `max_hops` (default 30)
- 3 probes per hop, reports lowest latency and response count
- Output: one line per hop, tab-separated: `hop_index\thop_ip\tlatency_ms\tprobes_responded`
- Timeout hops (0 responses): `hop_index\t*\t-1\t0`
- Partial response hops (1-2 of 3): `hop_index\thop_ip\tlatency_ms\t1` or `\t2`
- Stops when target is reached (ICMP Echo Reply instead of TTL Exceeded)
- **MUST `fflush(stdout)` after each hop line** — required for partial results on Python-side timeout. Without this, pipe-buffered stdio would hold all output until process exit, making `TimeoutExpired.stdout` empty.
- `--check`: verifies capability (exit 0 if usable)
- Exit codes: 0 = target reached, 1 = max hops exceeded, 2 = error

**Security:**
- Setuid root with immediate privilege drop: `seteuid(getuid())` after raw socket creation
- No dynamic memory allocation after init
- No string formatting with user input
- Fixed-size buffers only
- ~150-200 lines of C, independently auditable
- Installed at `/usr/local/bin/docsight-traceroute-helper` with `chmod 4755`

**Build:** Same Dockerfile build stage as `docsight-icmp-helper`. GCC compile + strip in builder, copy binary to runtime image.

### Python Wrapper

```python
@dataclass
class TracerouteHop:
    hop_index: int
    hop_ip: str | None        # None on timeout
    hop_host: str | None       # Reverse DNS, None on timeout or DNS failure
    latency_ms: float | None   # None on timeout
    probes_responded: int       # 0-3

@dataclass
class TracerouteResult:
    hops: list[TracerouteHop]
    reached_target: bool
    route_fingerprint: str   # SHA256 of ordered hop IPs ("*" for timeout hops)

class TracerouteProbe:
    TOTAL_TIMEOUT_S = 30  # Hard cap on total execution time

    def run(self, host: str, max_hops: int = 30, timeout_ms: int = 2000) -> TracerouteResult:
        # subprocess.run() on helper binary with timeout=TOTAL_TIMEOUT_S
        #
        # Partial results on timeout:
        #   The C helper MUST fflush(stdout) after each hop line (see C helper spec below).
        #   Python calls subprocess.run(capture_output=True, timeout=TOTAL_TIMEOUT_S).
        #   On subprocess.TimeoutExpired: catch exception, read e.stdout for hops
        #   already flushed to the pipe, kill the process, parse partial output.
        #   This is the ONLY path for partial results — without explicit fflush in
        #   the helper, pipe-buffered stdout would be empty on timeout.
        #
        # Parallel reverse DNS for hop IPs:
        #   Per-call ThreadPoolExecutor (context manager, not long-lived)
        #   with ThreadPoolExecutor(max_workers=min(hop_count, 16)) as dns_pool:
        #     futures = {dns_pool.submit(socket.gethostbyaddr, ip): ... }
        #   2s timeout per lookup, failures → hop_host=None
        # Compute route_fingerprint = sha256("ip1|*|ip3|...")
        #   Timeout hops contribute "*" to the fingerprint
```

Reverse DNS is done in Python (not the helper) to keep the setuid binary minimal. DNS lookups are parallelized with a 2-second per-lookup timeout to avoid blocking the manual API endpoint. Failed lookups result in `hop_host: null`.

## Data Model

### New Tables (in `connection_monitor.db`)

```sql
CREATE TABLE traceroute_traces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id       INTEGER NOT NULL,
    timestamp       REAL NOT NULL,          -- Unix epoch float (matches connection_samples convention)
    trigger_reason  TEXT NOT NULL,           -- "manual", "outage", "packet_loss"
    hop_count       INTEGER NOT NULL,
    route_fingerprint TEXT,
    reached_target  INTEGER NOT NULL DEFAULT 0,
    is_demo         INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (target_id) REFERENCES connection_targets(id) ON DELETE CASCADE
);

CREATE INDEX idx_traces_target_ts ON traceroute_traces(target_id, timestamp);

CREATE TABLE traceroute_hops (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id        INTEGER NOT NULL,
    hop_index       INTEGER NOT NULL,
    hop_ip          TEXT,                    -- NULL on timeout
    hop_host        TEXT,                    -- NULL on timeout or DNS failure
    latency_ms      REAL,                    -- NULL on timeout
    probes_responded INTEGER NOT NULL DEFAULT 0,  -- 0-3
    FOREIGN KEY (trace_id) REFERENCES traceroute_traces(id) ON DELETE CASCADE
);

CREATE INDEX idx_hops_trace ON traceroute_hops(trace_id);
```

**Note on `is_demo`:** This is the first `is_demo` column in the Connection Monitor database. The core `purge_demo_data()` in `app/storage/cleanup.py` does not know about CM tables. A dedicated `purge_demo_traces()` method is added to `ConnectionMonitorStorage` and called from the demo-to-live migration path.

**Note on timestamps:** `REAL` (Unix epoch float) matches the existing `connection_samples.timestamp` convention in this database. API responses convert to ISO 8601 strings at the serialization layer.

### Storage Methods (added to `ConnectionMonitorStorage`)

- `save_trace(target_id, timestamp, trigger_reason, hops, route_fingerprint, reached_target) → trace_id`
- `get_traces(target_id, start=None, end=None, limit=100) → list[dict]`
- `get_trace_hops(trace_id) → list[dict]`
- `cleanup_traces(retention_days)` — deletes traces older than cutoff, respects pinned days, relies on `ON DELETE CASCADE` for hop cleanup
- `purge_demo_traces()` — deletes all rows where `is_demo=1` from both trace tables

### Retention

Same `retention_days` config as connection samples. Pinned days protect traces from cleanup (same float-based timestamp comparison as existing samples). `cleanup_traces()` is called alongside the existing `self._cm_storage.cleanup(retention)` in the collector's 15-minute cleanup cycle.

## Trigger Logic

### TracerouteTrigger

```python
class TracerouteTrigger:
    COOLDOWN_S = 300  # 5 minutes per target

    def __init__(self, probe: TracerouteProbe, storage: ConnectionMonitorStorage):
        self._probe = probe
        self._storage = storage
        self._last_trace: dict[int, float] = {}  # target_id → unix timestamp
        self._executor = ThreadPoolExecutor(max_workers=1)  # Dedicated executor

    def on_event(self, event: dict) -> None:
        """Called by collector after event detection in _check_events()."""
        if event["event_type"] not in ("cm_target_unreachable", "cm_packet_loss_warning"):
            return
        target_id = event["details"]["target_id"]
        if not self._cooldown_ok(target_id):
            return
        # Resolve host from storage
        target = self._storage.get_target(target_id)
        if not target:
            return  # Target deleted between event and trigger
        host = target["host"]
        trigger_reason = "outage" if event["event_type"] == "cm_target_unreachable" else "packet_loss"
        self._executor.submit(self._run_and_save, target_id, host, trigger_reason)

    def shutdown(self) -> None:
        """Called when collector stops."""
        self._executor.shutdown(wait=False)
```

### Collector Integration

The `TracerouteTrigger` is wired into the existing collector as follows:

**In `__init__`:**
```python
self._traceroute_probe = TracerouteProbe()
self._traceroute_trigger = TracerouteTrigger(
    probe=self._traceroute_probe,
    storage=self._cm_storage,
)
```

**In `_check_events()`, after all events are populated (after line 154, before the `if all_events` save block at line 156).** This ensures both `cm_target_unreachable` (from `check_probe_result`) and `cm_packet_loss_warning` (from `check_window_stats`) are included:
```python
for event in all_events:
    self._traceroute_trigger.on_event(event)
```

**In cleanup cycle (alongside existing `self._cm_storage.cleanup(retention)`):**
```python
self._cm_storage.cleanup_traces(retention)
```

**On collector shutdown (new `stop()` method on `ConnectionMonitorCollector`):**

The base `Collector` class does not define a `stop()` method. Add one to `ConnectionMonitorCollector`:
```python
def stop(self):
    """Called by orchestrator during graceful shutdown."""
    self._traceroute_trigger.shutdown()
```
In `polling_loop()`'s existing `finally` block (after `executor.shutdown()` at line 295), call `c.stop()` for each collector that defines it. This is the natural cleanup point — scoped correctly and follows the existing pattern.

**Route endpoint access to TracerouteTrigger:**

The manual traceroute endpoint needs a `TracerouteProbe` instance. Following the existing pattern where routes access the probe engine via `_get_probe()` (routes.py lines 171-177), add a module-level accessor:
```python
_traceroute_probe = None

def _get_traceroute_probe():
    global _traceroute_probe
    if _traceroute_probe is None:
        _traceroute_probe = TracerouteProbe()
    return _traceroute_probe
```
The manual endpoint uses the probe directly — no trigger needed. The route handler calls `probe.run(host)`, then saves the result to storage via the route's own `_get_cm_storage()` instance. The `TracerouteTrigger` is only used by the collector for event-driven traces and does not need to be accessible from routes.

### Event Mapping

| Event | trigger_reason |
|-------|---------------|
| `cm_target_unreachable` | `"outage"` |
| `cm_packet_loss_warning` | `"packet_loss"` |
| Manual API call | `"manual"` |

## API Endpoints

### New

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/connection-monitor/traceroute/<target_id>` | Run manual traceroute (sync, 30s max, returns result) |
| GET | `/api/connection-monitor/traces/<target_id>` | List traces for target (with time range filter) |
| GET | `/api/connection-monitor/trace/<trace_id>` | Single trace with all hops |

All endpoints require `@require_auth`.

**Note:** Route-change endpoint (`/api/connection-monitor/route-changes/<target_id>`) is deferred to Phase 3. The `route_fingerprint` data is stored now so the endpoint can be added later without backfill.

### Response Format

**POST traceroute:**
```json
{
  "trace_id": 42,
  "timestamp": "2026-03-17T04:05:48Z",
  "trigger_reason": "manual",
  "reached_target": true,
  "hop_count": 12,
  "route_fingerprint": "a1b2c3...",
  "hops": [
    {"hop_index": 1, "hop_ip": "192.168.178.1", "hop_host": "fritz.box", "latency_ms": 1.2, "probes_responded": 3},
    {"hop_index": 2, "hop_ip": "10.0.0.1", "hop_host": null, "latency_ms": 8.4, "probes_responded": 3},
    {"hop_index": 3, "hop_ip": null, "hop_host": null, "latency_ms": null, "probes_responded": 0}
  ]
}
```

**Note:** `timestamp` is stored as `REAL` (epoch) in SQLite but serialized to ISO 8601 in API responses.

### Timeout Handling

The manual traceroute endpoint has a 30-second hard cap (`TracerouteProbe.TOTAL_TIMEOUT_S`). The timeout contract works as follows:

1. `subprocess.run(timeout=30)` raises `subprocess.TimeoutExpired` if the helper exceeds 30s
2. Python catches `TimeoutExpired`, reads `e.stdout` which contains hop lines already flushed by the helper (the C helper `fflush(stdout)` after each hop line — this is mandatory)
3. The helper process is killed via `e.process.kill()` (or subprocess handles it)
4. Partial output is parsed into hops as usual
5. Response includes `reached_target: false` and whatever hops were collected

This stays within Waitress and reverse proxy default timeouts.

## UI

### Settings

No new settings required. Traceroute uses the existing Connection Monitor target configuration. The only implicit config is the 5-minute cooldown (hardcoded, not user-facing).

### Detail Tab Extension

In the existing Connection Monitor detail view per target:

- **"Run Traceroute" button** — triggers POST, shows result inline with loading spinner
- **Trace history table** — below the existing outage log, shows past traces with timestamp, trigger reason, hop count, route fingerprint (truncated)
- **Trace detail** — click a trace row to expand hop list with per-hop latency and response count

### Dashboard Card

No change. Traceroute is a detail/debugging feature, not a dashboard-level metric.

## Testing Strategy

### Unit Tests

- `test_traceroute_probe.py` — mock subprocess, test output parsing, edge cases (timeout hops, unreachable target, empty output, partial results on timeout)
- `test_traceroute_trigger.py` — cooldown enforcement, event filtering (`event_type` key), host resolution, target-deleted edge case, manual override, executor shutdown
- `test_traceroute_storage.py` — CRUD, retention cleanup (with pinned days), `purge_demo_traces()`, `ON DELETE CASCADE` verification
- `test_traceroute_routes.py` — API endpoints, auth, error cases, timeout handling

### Integration

- Collector cycle with event → traceroute trigger chain (mocked probe)
- Manual traceroute via API → storage → retrieval
- Cleanup cycle includes `cleanup_traces()`

### C Helper

- `--check` returns 0
- Known host (localhost/127.0.0.1) returns at least 1 hop
- Invalid host returns exit code 2
- Output format validation (tab-separated, correct column count)
- Tested in CI via the Docker build (same as ICMP helper)

## Demo Mode

Demo seeder creates sample traces with realistic hop data for default targets (1.1.1.1, 8.8.8.8). Traces marked `is_demo=1`, purged via `purge_demo_traces()` on demo→live migration. This method must be called from the same migration path that handles other Connection Monitor demo data.

## i18n

New keys added to all 4 languages (EN/DE/FR/ES):
- `traceroute.run_button`, `traceroute.running`, `traceroute.result`
- `traceroute.trigger_manual`, `traceroute.trigger_outage`, `traceroute.trigger_packet_loss`
- `traceroute.hop`, `traceroute.hops`, `traceroute.reached`, `traceroute.not_reached`
- `traceroute.history`, `traceroute.no_traces`
- `traceroute.probes_responded`, `traceroute.partial_result`

## Migration

Tables are created via `_ensure_table()` pattern (CREATE TABLE IF NOT EXISTS) — no migration script needed. Existing Connection Monitor installations get the tables on first startup after update.
