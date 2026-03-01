# Architecture Research

**Domain:** DOCSIS Monitoring Tool — Extensibility Milestone
**Researched:** 2026-03-01
**Confidence:** HIGH (based on direct codebase analysis)

---

## Standard Architecture

### Existing System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Flask Web Layer (web.py)                     │
│  ┌───────────┐ ┌───────────┐ ┌────────────┐ ┌───────────────────┐  │
│  │analysis_bp│ │ data_bp   │ │ events_bp  │ │   modules_bp      │  │
│  └─────┬─────┘ └─────┬─────┘ └─────┬──────┘ └────────┬──────────┘  │
├────────┴─────────────┴─────────────┴──────────────────┴─────────────┤
│                       Collector Orchestrator (main.py)               │
│     ThreadPoolExecutor — ticks every 1s, lets collectors self-pace   │
│  ┌──────────────────┐  ┌────────────────┐  ┌────────────────────┐   │
│  │  ModemCollector  │  │SpeedtestCollect│  │  (module collects) │   │
│  └──────┬───────────┘  └────────────────┘  └────────────────────┘   │
│         │ uses                                                        │
│  ┌──────▼──────────────────────────────────────────────────────┐     │
│  │             ModemDriver (base: ModemDriver ABC)              │     │
│  │  CH7465 │ TC4400 │ VFStation │ UltraHub7 │ CM3500 │ FritzBox│     │
│  └──────┬───────────────────────────────────────────────────────┘    │
├─────────┴────────────────────────────────────────────────────────────┤
│                       Core Processing Pipeline                        │
│   Driver → analyzer.analyze() → EventDetector.check() → Storage      │
│                                           └→ MQTT Publisher           │
├──────────────────────────────────────────────────────────────────────┤
│                    Storage Layer (SQLite — mixin pattern)             │
│  ┌─────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────────┐   │
│  │SnapshotMixin│ │AnalysisMix │ │ EventMixin │ │  Other Mixins  │   │
│  └─────────────┘ └────────────┘ └────────────┘ └────────────────┘   │
│                   SnapshotStorage (composes all mixins)               │
├──────────────────────────────────────────────────────────────────────┤
│                    Module System (module_loader.py)                   │
│  Discovers manifest.json → validates → loads: collector, routes,     │
│  publisher, thresholds, theme, i18n, static, settings template       │
│  Types: driver | integration | analysis | theme                       │
│  Contributes: collector | routes | settings | thresholds | theme |   │
│              publisher | tab | card | i18n | static                  │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Communicates With |
|-----------|----------------|-------------------|
| `ModemDriver` (ABC) | Authenticate + fetch raw DOCSIS data | ModemCollector |
| `ModemCollector` | Orchestrate poll cycle (login → fetch → analyze → store → detect → publish) | Driver, Analyzer, EventDetector, Storage, MQTT, Web |
| `analyzer.analyze()` | Convert raw driver data into health-assessed analysis dict | Called by ModemCollector |
| `EventDetector` | Diff consecutive analyses, emit event dicts | Storage (events), Notifier |
| `SnapshotStorage` | Persist and query snapshots, events, speedtests | ModemCollector, Blueprints |
| `ModuleLoader` | Discover/validate/load community modules at startup | Flask app, collectors |
| `DRIVER_REGISTRY` | Maps `modem_type` string → driver class | `load_driver()`, config UI |
| `discover_collectors()` | Instantiate active collector set from config + modules | main.py polling loop |
| Flask blueprints | HTTP API endpoints for dashboard and integrations | Storage, Web state |

---

## Feature Integration Architecture

### Feature 1: Community Modem Drivers via Module System (#131)

**The gap:** `DRIVER_REGISTRY` in `app/drivers/__init__.py` is a hardcoded dict. The module system supports `type: "driver"` in manifests (already in `VALID_TYPES`) but has no `driver` contribution key — only `thresholds` and `theme` are loaded for driver-type modules.

**Integration pattern:** Add a `driver` contribution key to the module system. Module manifests declare `"contributes": {"driver": "driver.py:MyModemDriver"}`. The module loader dynamically imports the class. `load_driver()` checks the module registry before raising `ValueError`.

```
Community Module (manifest.json + driver.py)
    ↓  [module_loader discovers at startup]
ModuleLoader._load_module()
    ↓  [load_module_driver() — new function, mirrors load_module_collector()]
ModuleInfo.driver_class = <MyModemDriver class>
    ↓  [registered into runtime driver registry]
load_driver() checks module_driver_registry before DRIVER_REGISTRY
    ↓
ModemCollector uses driver normally (no change to collector)
```

**Component boundary:** The driver class is the only new artifact. Everything downstream (ModemCollector, analyzer, storage) is unchanged because all drivers conform to the `ModemDriver` ABC.

**Module loader extension needed:**
- Add `"driver"` to `VALID_CONTRIBUTES`
- Add `load_module_driver()` function (same pattern as `load_module_collector`)
- Add `driver_class: type | None` field to `ModuleInfo`
- In `_load_module()`: if `"driver"` in contributes, call `load_module_driver()`
- `load_driver()` must accept an optional module registry param or query web's module_loader

---

### Feature 2: GenericDriver for Non-DOCSIS Modems (#129)

**Purpose:** Allow users with modems that expose no parseable DOCSIS data to still use all modem-agnostic features (speed tests, BQM, events, Prometheus, etc.).

**Integration pattern:** GenericDriver is a built-in driver (lives in `app/drivers/generic.py`), not a community module. It implements `ModemDriver` ABC but returns empty/stub data from `get_docsis_data()`. Registered as `"generic"` in `DRIVER_REGISTRY`.

```
Config: modem_type = "generic"
    ↓
load_driver("generic", ...) → GenericDriver instance
    ↓
ModemCollector.collect():
  driver.login()   → no-op or lightweight check
  get_docsis_data() → {"ds_channels": [], "us_channels": []}
  analyzer.analyze() → summary with health="unknown", no channel data
  storage.save_snapshot() → snapshot saved (enables before/after, Prometheus)
  EventDetector → detects modem_restart events via error counter pattern
```

**Key design decision:** `analyzer.analyze()` must handle empty channel lists gracefully — it likely already does for edge cases, but needs verification. The GenericDriver's `get_device_info()` can return user-supplied model name from config.

**Component boundary:** Only adds `app/drivers/generic.py` and one registry entry. No changes to collector, analyzer, or storage.

---

### Feature 3: Daily Modulation Performance Distribution (#92)

**Purpose:** Show histogram of modulation quality (QAM level distribution) across all polls for a given day.

**Data flow:**
```
Existing snapshots in SQLite (ds_channels_json / us_channels_json)
    ↓  [query by date range — existing get_intraday_data() or new query]
StorageMixin.get_modulation_distribution(date) → new method
    ↓  [aggregate modulation strings across all channel snapshots]
{modulation: count} dict per channel direction
    ↓  [new Flask endpoint: GET /api/analysis/modulation-distribution?date=YYYY-MM-DD]
Dashboard chart — frontend reads and renders
```

**Where it lives:** New method on `AnalysisMixin` (or `SnapshotMixin`) in `app/storage/analysis.py`. New route in `analysis_bp.py`. No schema changes — reads existing `ds_channels_json`/`us_channels_json` columns.

**Component boundary:** Storage query + API endpoint only. No new tables. No collector changes.

---

### Feature 4: Before/After Signal Quality Comparison (#50)

**Purpose:** Let users select two snapshots (or time points) and diff their signal metrics side-by-side.

**Data flow:**
```
User selects snapshot A timestamp + snapshot B timestamp
    ↓
GET /api/analysis/compare?before=<ISO>&after=<ISO>
    ↓
storage.get_closest_snapshot(before_ts) → existing method
storage.get_closest_snapshot(after_ts) → existing method
    ↓
Route handler computes delta per channel metric (power, SNR, errors, modulation)
    ↓  [no complex logic — simple arithmetic diff]
{before: {...}, after: {...}, delta: {...}} response
    ↓
Dashboard renders side-by-side or tabular diff view
```

**Where it lives:** New route in `analysis_bp.py`. Uses existing `get_closest_snapshot()` and `get_snapshot_list()`. No new storage methods needed beyond what exists.

**Component boundary:** API layer only. Pure read path using existing storage.

---

### Feature 5: Prometheus /metrics Endpoint (#59)

**Purpose:** Expose current signal metrics in Prometheus text format for Grafana/alerting stack integration.

**Data flow:**
```
GET /metrics (or /api/metrics — unauthenticated or token-secured)
    ↓
Blueprint handler reads from web state (get_state())
    ↓  [state already holds latest analysis dict — no DB query needed]
Format current analysis summary as Prometheus text exposition format:
  docsight_ds_power_avg, docsight_us_power_avg, docsight_snr_min,
  docsight_ds_uncorrectable_errors, docsight_health_status, etc.
    ↓
Return text/plain; version=0.0.4 Content-Type
```

**Where it lives:** New blueprint `metrics_bp.py` registered in `app/web.py`. Reads from in-memory `_state` (already thread-safe via lock in web.py). No DB access needed — uses the most recent analysis already in memory.

**Security note:** Prometheus convention is unauthenticated `/metrics`. DOCSight should offer an optional bearer token check (config flag) since it's self-hosted. Default: same `require_auth` as other endpoints.

**Component boundary:** New blueprint file only. No storage, no collector changes. Zero impact on polling.

---

### Feature 6: Modem Restart Detection via Error Counter Reset (#60)

**Purpose:** Detect when the modem restarts by observing that cumulative error counters reset to near-zero after being non-zero.

**Integration pattern:** This is an `EventDetector` extension.

```
ModemCollector.collect():
  data = driver.get_docsis_data()
  analysis = analyzer.analyze(data)
  events = event_detector.check(analysis)  ← restart detection added here
    ↓
EventDetector._check_errors() currently: detects spikes (delta > threshold)
    ↓  EXTEND with:
EventDetector._check_restart() — new private method:
  prev_uncorr = prev_summary.ds_uncorrectable_errors
  cur_uncorr = cur_summary.ds_uncorrectable_errors
  if prev_uncorr > RESTART_RESET_THRESHOLD and cur_uncorr < RESTART_FLOOR:
    emit event_type="modem_restart", severity="warning"
    ↓
events saved to storage via storage.save_events()
events appear in event log UI (existing infrastructure)
```

**Where it lives:** `EventDetector._check_restart()` in `app/event_detector.py`. Called at end of `EventDetector.check()`. No schema changes, no new storage methods.

**Component boundary:** Single new method in `event_detector.py`. The event dict format matches existing events — no downstream changes.

---

## Component Boundaries Summary

| Component | Owns | Does NOT Own |
|-----------|------|-------------|
| `app/drivers/generic.py` | Non-DOCSIS stub driver | Analysis logic, storage |
| `app/drivers/__init__.py` | Driver registry + `load_driver()` | Module driver registry (add bridge) |
| `app/module_loader.py` | Module lifecycle; add `load_module_driver()` | Collector instantiation |
| `app/event_detector.py` | Restart detection (`_check_restart`) | Storage writes (passes events back) |
| `app/storage/analysis.py` | Modulation distribution query | API formatting |
| `app/blueprints/analysis_bp.py` | Compare endpoint, modulation dist endpoint | Storage logic |
| `app/blueprints/metrics_bp.py` (new) | Prometheus text format output | Analysis computation |

---

## Recommended Project Structure (additions only)

```
app/
├── drivers/
│   ├── base.py             # unchanged — ModemDriver ABC
│   ├── generic.py          # NEW — GenericDriver stub
│   └── __init__.py         # ADD "generic" to DRIVER_REGISTRY; bridge to module drivers
├── blueprints/
│   ├── analysis_bp.py      # ADD /api/analysis/compare, /api/analysis/modulation-distribution
│   └── metrics_bp.py       # NEW — Prometheus /metrics endpoint
├── storage/
│   └── analysis.py         # ADD get_modulation_distribution() method
├── event_detector.py       # ADD _check_restart() method
└── module_loader.py        # ADD load_module_driver(), driver_class field, VALID_CONTRIBUTES update

modules/ (community-contributed, outside app/)
└── <community_driver>/
    ├── manifest.json       # {"type": "driver", "contributes": {"driver": "driver.py:ClassName"}}
    └── driver.py           # Subclass of ModemDriver
```

---

## Data Flow

### Poll Cycle (Existing + Additions)

```
[Every N seconds]
    ↓
ModemCollector.collect()
    ↓ 1. driver.login()
    ↓ 2. driver.get_docsis_data()          ← GenericDriver returns {} cleanly
    ↓ 3. analyzer.analyze(data)
    ↓ 4. EventDetector.check(analysis)     ← _check_restart() added here
    ↓ 5. storage.save_snapshot(analysis)
    ↓ 6. storage.save_events(events)
    ↓ 7. mqtt_pub.publish_data(analysis)
    ↓ 8. web.update_state(analysis=analysis) ← Prometheus reads from here
```

### Module Driver Registration Flow (New)

```
[App startup]
ModuleLoader.load_all()
    ↓ for each module with contributes.driver:
    load_module_driver() → ModuleInfo.driver_class = <class>
    ↓
load_driver("community.mydriver", ...)
    ↓ checks module_driver_registry first
    ↓ falls back to DRIVER_REGISTRY
    ↓ raises ValueError if not found
```

### Prometheus Scrape Flow (New)

```
Prometheus scraper → GET /metrics
    ↓
metrics_bp → get_state()["analysis"] (in-memory, no DB hit)
    ↓
Format as Prometheus exposition text
    ↓
Return text/plain response
```

### Before/After Comparison Flow (New)

```
Dashboard → GET /api/analysis/compare?before=T1&after=T2
    ↓
analysis_bp → storage.get_closest_snapshot(T1), get_closest_snapshot(T2)
    ↓
Compute per-metric delta (pure Python dict arithmetic)
    ↓
Return {before, after, delta} JSON
```

---

## Architectural Patterns

### Pattern 1: ABC-Conformance Driver Isolation

**What:** All drivers implement `ModemDriver` ABC. The entire downstream pipeline (collector, analyzer, storage, events) depends only on the ABC interface, never on concrete classes.

**When to use:** Any new driver — built-in or community — must subclass `ModemDriver` and implement `login()`, `get_docsis_data()`, `get_device_info()`, `get_connection_info()`.

**Trade-offs:** Strong isolation means community drivers cannot accidentally influence analysis logic. The downside is that drivers cannot extend the analysis contract — they can only surface what the ABC exposes.

**Example:**
```python
# app/drivers/generic.py
from .base import ModemDriver

class GenericDriver(ModemDriver):
    def login(self) -> None:
        pass  # no-op

    def get_docsis_data(self) -> dict:
        return {"ds_channels": [], "us_channels": []}

    def get_device_info(self) -> dict:
        return {"model": "Generic Router", "sw_version": "unknown"}

    def get_connection_info(self) -> dict:
        return {}
```

### Pattern 2: Module Contribution Extension (Mirrors Existing)

**What:** New contribution keys (`driver`) follow the same pattern as existing `collector` and `publisher` keys. The `load_module_driver()` function is a structural copy of `load_module_collector()`.

**When to use:** Whenever a new loadable Python artifact is added to the module system.

**Trade-offs:** Consistency over cleverness — the repetition is intentional and makes each contribution type independently readable. A generic `load_module_class()` helper would be DRY but would obscure intent.

**Example manifest:**
```json
{
  "id": "community.my_modem",
  "type": "driver",
  "contributes": {
    "driver": "driver.py:MyModemDriver"
  }
}
```

### Pattern 3: In-Memory State for Hot Reads

**What:** Prometheus `/metrics` reads from `web._state` (in-memory dict, updated every poll cycle). No SQLite query on each scrape.

**When to use:** Any endpoint that needs the current value only, not historical. Prometheus default scrape interval is 15s; poll interval is typically 60s+. The state is always current enough.

**Trade-offs:** Data is exactly as fresh as the last poll. This is correct behavior — Prometheus will see stale data if polling fails, which accurately reflects the modem state.

### Pattern 4: EventDetector Extension via Private Methods

**What:** Restart detection is added as `_check_restart()` called at the end of `EventDetector.check()`. It follows the exact same signature pattern as `_check_health()`, `_check_errors()`, etc.

**When to use:** Any new signal anomaly detection that compares consecutive analyses.

**Trade-offs:** The EventDetector accumulates methods over time. This is acceptable because all methods are narrowly scoped (compare two summaries, emit events). Extraction to a strategy pattern would be premature.

---

## Build Order (Phase Dependencies)

The 6 features have the following dependency graph:

```
GenericDriver (#129)
    ↓ enables
Modem restart detection (#60) — restart is first observable via GenericDriver's
                                 clean error counter start; also benefits DOCSIS users

Module driver system (#131)
    ↓ independent of analysis features

Modulation distribution (#92) — reads existing snapshots, no dependencies
Before/After comparison (#50) — reads existing snapshots, no dependencies

Prometheus endpoint (#59) — reads in-memory state, no dependencies
```

**Recommended build order based on dependencies and risk:**

1. **GenericDriver** — foundational; unlocks non-DOCSIS users and enables restart detection testing without a real DOCSIS modem. Low risk (adds one file, one registry entry).

2. **Modem restart detection** — builds immediately after GenericDriver so it can be tested via demo mode and GenericDriver. Low risk (extends EventDetector in isolation).

3. **Module driver system** — independent from analysis features but architecturally significant (touches module_loader, driver registry). Should be complete before community testing begins.

4. **Prometheus endpoint** — independent, zero storage risk, high value for monitoring integrations. Very low risk (new blueprint, reads existing state).

5. **Modulation distribution** — new storage query, new endpoint. Medium complexity (aggregate across potentially thousands of snapshots; needs pagination or day-scoping).

6. **Before/After comparison** — uses two existing `get_closest_snapshot()` calls. Simplest of the analysis features once modulation distribution query patterns are established.

---

## Anti-Patterns

### Anti-Pattern 1: Adding Drivers Directly to DRIVER_REGISTRY for Community Use

**What people do:** Tell community contributors to submit PRs adding their driver to `app/drivers/__init__.py`.

**Why it's wrong:** Creates a maintenance burden for the core maintainer, prevents self-contained community distribution, and couples core releases to driver availability.

**Do this instead:** Module system driver contributions. Community drivers ship as installable modules with their own `manifest.json`. Core never changes.

### Anti-Pattern 2: Querying SQLite on Every Prometheus Scrape

**What people do:** Implement `/metrics` as a storage query that fetches the latest snapshot row.

**Why it's wrong:** Prometheus default scrape is every 15s. SQLite under concurrent read/write load adds latency and lock contention. The data in-memory is already current.

**Do this instead:** Read from `web.get_state()["analysis"]` which is the last analyzed dict, updated by the collector. Return immediately.

### Anti-Pattern 3: Storing Modulation Distribution in a New Table

**What people do:** Create a `modulation_stats` table and populate it during each poll.

**Why it's wrong:** Normalizes data that is already present in `ds_channels_json`. Creates a write-time dependency and doubles storage for redundant data.

**Do this instead:** Compute on-demand from existing `ds_channels_json`/`us_channels_json` columns, scoped to a single day. Performance is acceptable because a day is at most ~1440 polls (at 60s intervals) and the JSON is small.

### Anti-Pattern 4: Implementing GenericDriver with Fake DOCSIS Data

**What people do:** Make GenericDriver return plausible-looking fake channel data so the dashboard "looks full."

**Why it's wrong:** Misleads users about their actual signal quality. The entire value of DOCSight is accurate data.

**Do this instead:** Return empty channel lists. The dashboard must handle the "no DOCSIS data" state gracefully (already handles it for the initial poll window). Show a "DOCSIS data not available" notice instead of fake metrics.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Prometheus / Grafana | GET /metrics — text exposition format | No client library needed; hand-craft output. Content-Type must be `text/plain; version=0.0.4; charset=utf-8` |
| Community module registry | manifest.json discovery via filesystem | No network call at runtime; user installs module directory manually or via future installer |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Module loader ↔ Driver registry | Module loader populates a runtime dict; `load_driver()` checks it | Pass module_loader reference or use a module-level registry dict |
| EventDetector ↔ ModemCollector | EventDetector is stateful (holds prev analysis); ModemCollector calls `check()` each poll | Thread-safe already via `_lock` in EventDetector |
| Prometheus blueprint ↔ Web state | Direct function call to `web.get_state()` | Already thread-safe via RLock in web.py |
| Storage ↔ Analysis blueprint | Blueprint calls storage methods directly via `get_storage()` | Existing pattern; new endpoints follow same shape |

---

## Scaling Considerations

This is a self-hosted, single-user tool deployed on NAS hardware.

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Single household (current) | SQLite monolith is correct. No changes needed. |
| Multi-household (hypothetical) | Each instance is independent. No shared state. |
| High-frequency Prometheus scraping | In-memory state read is O(1). No bottleneck at any scrape interval. |

### Scaling Priorities

1. **SQLite modulation distribution query:** At 60s poll interval, one day = 1440 rows × N channels JSON. Query must be bounded to a single date. Add index on `timestamp` if not already present (check `base.py` schema).

2. **Community driver sandbox:** Driver Python code runs in-process. There is no sandbox. Community drivers have full access to the host. This is acceptable for self-hosted use but must be documented clearly.

---

## Sources

- Codebase direct analysis: `app/module_loader.py` (VALID_TYPES, VALID_CONTRIBUTES, load_module_collector pattern)
- Codebase direct analysis: `app/drivers/__init__.py` (DRIVER_REGISTRY, load_driver)
- Codebase direct analysis: `app/collectors/__init__.py` (discover_collectors, module collector loading)
- Codebase direct analysis: `app/event_detector.py` (EventDetector._check_errors, consecutive analysis pattern)
- Codebase direct analysis: `app/storage/snapshot.py` (get_closest_snapshot, get_intraday_data)
- Prometheus exposition format: https://prometheus.io/docs/instrumenting/exposition_formats/ (text format 0.0.4)
- PROJECT.md: constraint — single Docker container, no framework changes, 743+ tests must pass

---

*Architecture research for: DOCSight extensibility milestone (6 features)*
*Researched: 2026-03-01*
