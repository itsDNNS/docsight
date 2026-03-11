# Connection Monitor - Design Spec

**Date:** 2026-03-11
**Issue:** #194
**Status:** Final (MVP scope)

## Summary

Add a DOCSight-native always-on latency monitor (Connection Monitor) that replaces PingPlotter-style evidence gathering for cable users. The module continuously probes configured targets, stores latency history, and displays results alongside existing DOCSIS signal data.

## Goals

- Provide continuous latency monitoring without requiring a desktop client
- Help non-expert cable users prove intermittent connectivity problems
- Display latency data alongside DOCSIS signal impairments on the same timeline
- Fit seamlessly into DOCSight's existing module architecture

## Non-Goals (V1)

- Full PingPlotter parity
- Traceroute support (V2)
- Remote probe agents (V3)
- Replacing BQM or Smokeping integrations
- Aggregation/downsampling (V2 - raw samples sufficient for V1 volumes)
- Dedicated correlation API (V2 - client-side overlay on shared timeline for V1)

## Architecture Decision

**Approach: Standalone Collector with own Storage (Module Pattern)**

New core module at `app/modules/connection_monitor/` following the existing manifest-based module system. Own collector, own SQLite tables, own routes. Correlation with DOCSIS data via client-side timeline overlay in V1, dedicated API in V2.

Rationale:
- Follows established module pattern (Speedtest, Weather, BQM)
- Independent polling interval (5s vs. DOCSIS 15min)
- Clean separation, independently testable
- Can be enabled/disabled in settings like any other module

## Data Model

### connection_targets

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| label | TEXT | Display name ("Cloudflare DNS") |
| host | TEXT | IP or hostname |
| enabled | BOOLEAN | Default true |
| poll_interval_ms | INTEGER | Default 5000 |
| probe_method | TEXT | "auto", "icmp", "tcp" - Default "auto" |
| tcp_port | INTEGER | For TCP fallback, Default 443 |
| created_at | REAL | UTC timestamp |

### connection_samples (Raw data)

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| target_id | INTEGER FK | -> connection_targets |
| timestamp | REAL | UTC epoch |
| latency_ms | REAL | NULL on timeout |
| timeout | BOOLEAN | Default false |
| probe_method | TEXT | "icmp" or "tcp" (actually used) |

**Index:** `(target_id, timestamp)`

### Retention

V1 uses DOCSight's existing `history_days` pattern: raw samples older than configured days are purged. Default 0 (keep all), matching DOCSight's core behavior. At 5s interval with 3 targets, that is ~52k rows/day (~19M/year) - well within SQLite's capabilities.

Aggregation tables (`connection_aggregates`) are deferred to V2 when long-term query performance becomes a concern.

### Design decisions

- No jitter in raw samples - jitter is derived (variance over time window), computed at query time in the API
- probe_method per sample because auto-fallback can change at runtime
- Packet loss as timeout boolean in raw, percentage computed at query time
- No separate outage table - outages derived from consecutive timeouts in API

## Module Structure

```
app/modules/connection_monitor/
  manifest.json
  collector.py           # ConnectionMonitorCollector(Collector)
  probe.py               # ProbeEngine - ICMP/TCP logic
  storage.py             # ConnectionMonitorStorage
  routes.py              # Route registration, request parsing, response formatting
  event_rules.py         # Event detection rules for connection issues
  templates/
    connection_monitor_settings.html
    connection_monitor_card.html
    connection_monitor_detail.html
  static/js/
    connection-monitor-card.js
    connection-monitor-detail.js
    connection-monitor-charts.js
  i18n/
    en.json
    de.json
    fr.json
    es.json
```

## Probe Engine

### Method selection

1. On init with method="auto": attempt to open ICMP raw socket
2. Success -> use ICMP, failure -> fall back to TCP, log warning
3. Store detected method for UI query via `/capability` endpoint
4. Fallback visible to user in UI (badge on targets + hint in settings)

UX framing: "TCP works everywhere. ICMP is optional and more accurate - requires CAP_NET_RAW in Docker."

### ICMP implementation

- Raw socket: `socket.AF_INET, socket.SOCK_RAW, IPPROTO_ICMP`
- Custom ICMP echo request/reply (no external tools, no `fping`, no `ping`)
- 2s timeout per probe
- Keeps container slim, avoids output parsing

### TCP implementation

- `socket.connect_ex()` to host:port (default 443)
- Measures TCP handshake time
- 2s timeout
- No special capabilities required

### ProbeResult

```python
@dataclass
class ProbeResult:
    latency_ms: float | None  # None on timeout
    timeout: bool
    method: str  # "icmp" or "tcp"
```

## Collector

### Polling model

The Connection Monitor constructor accepts `**kwargs`, passes `poll_interval_seconds=1` to `super().__init__()`, and overrides `should_poll()` to always return True. The 1s base interval means the main loop calls `collect()` every second, while per-target timing is managed internally.

**Important:** The base class penalty/backoff system must not interfere with probe operations. `collect()` always returns `CollectorResult.ok()` even when individual probes time out - timeouts are normal data, not collector failures. Only infrastructure errors (DB write failures, socket creation errors) return a failure result.

This is a pragmatic deviation from the base class semantics, documented here for clarity. The base Collector assumes collect() failure = something is broken. For the Connection Monitor, a target being unreachable is expected data, not an error condition.

### collect() flow

1. Iterate enabled targets
2. Per target: check if `poll_interval_ms` elapsed since last probe
3. If due: submit `probe.probe(host)` to thread pool
4. Await results, build sample batch
5. Bulk-insert batch into `connection_samples`
6. Run retention cleanup (if due, not every cycle)
7. Check event rules (outage detection, recovery)

### Concurrency

- Always use ThreadPoolExecutor for probes (even 3-4 sequential probes with 2s timeout each would cause unacceptable timing drift at 1s collect cadence)
- Pool size = number of enabled targets
- No concurrent collect() calls (inherited `_collect_lock` from base)

## Event Integration

The core `EventDetector` is DOCSIS-specific and has no plugin mechanism. The Connection Monitor manages its own event detection in `event_rules.py` and writes events directly to the core events table via `storage.save_events()` (the `EventMixin` already supports arbitrary event types/sources). This avoids modifying the core EventDetector while still surfacing connection events in the existing event timeline and notification system.

### V1 events (minimal set)

| Event | Trigger | Severity |
|-------|---------|----------|
| cm_target_unreachable | N consecutive timeouts (default 5 = 25s at 5s interval) | critical |
| cm_target_recovered | First success after outage | info |
| cm_packet_loss_warning | Loss > threshold over 1-min window | warning |

### Deferred to V2

- cm_high_latency (sustained latency above threshold)
- cm_jitter_warning (jitter above threshold)
- cm_probe_fallback (TCP instead of ICMP at startup - V1 shows this in UI only)

Events are saved with `cm_` prefix to distinguish from DOCSIS events. They flow into the existing event timeline and notification/webhook system.

## API Endpoints

Blueprint prefix: `/api/connection-monitor`

### Targets

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/targets` | All targets with current status (last latency, method, up/down) |
| POST | `/targets` | Create target |
| PUT | `/targets/<id>` | Update target |
| DELETE | `/targets/<id>` | Delete target + associated data |

### Data

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/samples/<target_id>` | Raw samples (params: start, end, limit) |
| GET | `/summary` | Current status all targets (for dashboard card) |
| GET | `/outages/<target_id>` | Derived outage periods from consecutive timeouts |

### Export & Status

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/export/<target_id>` | CSV export (params: start, end) |
| GET | `/capability` | Probe method info (ICMP/TCP, fallback reason) |

### Deferred to V2

- `GET /aggregates/<target_id>` - requires aggregation tables
- `GET /correlation` - dedicated correlation API, V1 uses client-side overlay instead

### Query-time computations (V1)

Since V1 has no aggregation tables, the `/samples` endpoint supports a `summarize` query param that computes on-the-fly:
- avg/min/max/p95 latency
- packet loss percentage
- jitter (mean absolute deviation between consecutive samples)
- sample count

For timeranges up to 7 days at 5s intervals (~120k rows per target), SQLite handles this in <100ms.

## UI

### Dashboard Summary Card

- Status indicator per target (green/yellow/red based on recent samples)
- Compact: "3/3 Targets OK" or "1/3 degraded"
- Last values: avg latency + packet loss over last minute
- Probe method badge ("ICMP" / "TCP")
- Click -> opens detail view

### Detail View

**Header:**
- Target selector (tabs or dropdown for >3)
- Timerange picker (1h, 6h, 24h, 7d, custom)
- Capability info: "Monitoring via TCP" or "Monitoring via ICMP" with hint for CAP_NET_RAW if TCP fallback active

**Charts (uPlot via shared `chart-engine.js`):**

`connection-monitor-charts.js` wraps the shared `chart-engine.js` API (createChart, threshold zones plugin) with Connection Monitor-specific configs. No chart logic duplication.

| Chart | Data | Threshold zones |
|-------|------|-----------------|
| Latency timeline | latency over time | Green <30ms, Yellow <100ms, Red >100ms |
| Packet loss | % loss per time window as bars | Green 0%, Yellow <2%, Red >2% |
| Availability | Uptime band (green=ok, red=outage) | Binary |

Thresholds are configurable in settings.

**Outage log:**
- Table below charts: start, end, duration, target
- Sorted newest first

**DOCSIS event overlay (V1 client-side correlation):**
- Toggle "Show DOCSIS events" -> fetches events from existing `/api/events` endpoint
- Renders vertical marker lines on latency chart at event timestamps
- No dedicated backend correlation needed - the frontend overlays two data sources on the same time axis

**Export button:**
- CSV download for selected timerange and target

### Settings Page

- Enable/disable toggle
- Default targets (1.1.1.1, 8.8.8.8 pre-filled)
- Poll interval (default 5000ms, min 1000ms)
- Alert thresholds: packet loss percentage, consecutive timeouts for outage
- Retention: days to keep samples (default 0 = keep all)
- Probe method: Auto/ICMP/TCP with active method display and CAP_NET_RAW hint

## Manifest (manifest.json)

```json
{
  "id": "docsight.connection_monitor",
  "name": "Connection Monitor",
  "version": "1.0.0",
  "type": "integration",
  "contributes": {
    "collector": "collector.py:ConnectionMonitorCollector",
    "routes": "routes.py",
    "settings": "templates/connection_monitor_settings.html",
    "card": "templates/connection_monitor_card.html",
    "tab": "templates/connection_monitor_detail.html",
    "static": "static/",
    "i18n": "i18n/"
  },
  "config": {
    "connection_monitor_enabled": false,
    "connection_monitor_poll_interval_ms": 5000,
    "connection_monitor_probe_method": "auto",
    "connection_monitor_tcp_port": 443,
    "connection_monitor_retention_days": 0,
    "connection_monitor_outage_threshold": 5,
    "connection_monitor_loss_warning_pct": 2.0
  }
}
```

Default targets (1.1.1.1, 8.8.8.8) are seeded on first enable, not hardcoded in config.

## Deployment

### Docker capability for ICMP

ICMP probing requires `CAP_NET_RAW`. The shipped `docker-compose.yml` and `docker-compose.dev.yml` must be updated to include:

```yaml
cap_add:
  - NET_RAW
```

Without this capability, the probe engine falls back to TCP automatically. The settings page shows a clear hint explaining how to enable ICMP if the fallback is active. TCP is framed as the normal default that works everywhere.

## i18n

All user-facing strings in 4 languages (EN, DE, FR, ES) following existing namespace pattern. Key areas:
- Target labels and status descriptions
- Chart labels and threshold descriptions
- Settings labels and help text
- Event messages
- Capability/fallback explanations

## Testing Strategy

- Unit tests for ProbeEngine (mock sockets, ICMP + TCP paths, fallback detection)
- Unit tests for Storage (CRUD targets, bulk insert samples, retention cleanup, outage derivation)
- Unit tests for event rules (outage detection after N timeouts, recovery, packet loss warning)
- API tests for all endpoints (Flask test client)
- Integration test: collector cycle with mock probes -> verify samples stored + events emitted

## V2 Roadmap (deferred)

- Aggregation tables (1-min, 5-min) + auto-downsampling in API
- Dedicated correlation API endpoint
- High latency / jitter alerts
- Demo mode seeding
- Jitter chart in detail view
- Configurable per-tier retention (raw, 1-min, 5-min)
- Traceroute burst capture (Phase 2 from issue #194)

## Open Questions (resolved)

- **Probing method**: ICMP with TCP auto-fallback, TCP framed as default that works everywhere
- **Poll interval**: 5s default (configurable, min 1s)
- **Retention**: Configurable days, default 0 (keep all), matching DOCSight core behavior
- **UI placement**: Summary card on dashboard + own detail view
- **Module type**: Core module, enable/disable in settings
- **Correlation V1**: Client-side overlay, no dedicated API
- **Aggregation V1**: Deferred, query-time computation sufficient for V1 data volumes
