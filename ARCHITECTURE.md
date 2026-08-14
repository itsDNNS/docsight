# DOCSight Architecture

> Documentation current as of **v2026-03-07.1**

This document describes the technical architecture of DOCSight.

## Overview

DOCSight is built around a **modular collector pattern** that separates data collection, analysis, storage, and presentation into independent, testable components.

### Reverse-proxy mount contract and wrapper boundary

DOCSight Core implements a generic proxy-stripped mount contract in
`app/base_path.py`. An operator can provide an explicit `BASE_PATH`, or can opt
into an exact trusted `X-Forwarded-Prefix` hop count with
`REVERSE_PROXY_PREFIX`. Core validates all selected sources, sets the request
`SCRIPT_NAME`, and leaves the already-stripped upstream `PATH_INFO` unchanged.
Browser URLs, cookies, the manifest, and the service worker then remain scoped
to that effective same-origin mount.

This contract is independent of Home Assistant. DOCSight Core does not call the
Supervisor API, query Supervisor app information, or consume Home Assistant
identity or authentication headers. A Home Assistant wrapper may query
Supervisor app information and set an explicit `BASE_PATH` before starting
DOCSight, but the wrapper owns that platform integration. Core continues to
use its own authentication and generic reverse-proxy contract.

### Application factory

`app.app_factory.create_app()` is the single production construction path for
the Flask application. Importing `app.web` defines the core HTTP surface and
its accessor facade, but does not construct an application. Factory creation
has a fixed order: configure Flask, establish the durable signing key, attach
runtime state, synchronize authentication state, register core routes,
register core blueprints, load module contributions and templates, install
base-path handling, then apply reverse-proxy handling as the outer WSGI layer.

Each application owns a typed `DocsightRuntime` at
`app.extensions["docsight"]`. It contains the configuration manager, storage,
authentication state, rate limiter, update checker, module loader, collector
references, derived-storage cache, and lock-protected dashboard state. Route
and module code reaches the current application through the accessors in
`app.web`; it must not retain app-specific values in module globals.

Collector threads receive the same runtime explicitly through the existing
`web=` duck-type parameter. The runtime implements `update_state()`,
`clear_speedtest_latest()`, `get_state()`, `get_module_loader()`, and the
read-only `_state` snapshot expected by existing collectors, without requiring
a Flask request or application context.

Module schema registries in `app.config`, analyzer threshold selection,
translation catalogs, driver/theme registries, and dynamic Python imports are
process-wide. Per-application configuration values, storage paths, signing and
authentication state, rate-limit buckets, update caches, module loader,
templates, collectors, and derived storages remain isolated.

---

## System Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         Main Process (main.py)                      │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              Collector Discovery & Registry                   │  │
│  │                                                               │  │
│  │  discover_collectors() →  ┌─────────────┐                    │  │
│  │                           │ Config Check │                    │  │
│  │                           └──────┬───────┘                    │  │
│  │                                  │                            │  │
│  │      ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐│  │
│  │      │          │          │          │          │          │          ││  │
│  │      ▼          ▼          ▼          ▼          ▼          ▼          ││  │
│  │ ┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────┐│  │
│  │ │  Modem   ││   Demo   ││ Speedtest││   BQM    ││  BNetzA  ││  Backup  ││  │
│  │ │ Collect. ││ Collect. ││ Collect. ││ Collect. ││ Watcher  ││ Collect. ││  │
│  │ │          ││          ││          ││          ││          ││          ││  │
│  │ │Poll:900s ││Poll:900s ││Poll: 300s││Poll: 24h ││Poll: 300s││Poll: 24h ││  │
│  │ └────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘│  │
│  │      │           │           │           │           │           │      │  │
│  │      └───────────┴───────────┼───────────┴───────────┴───────────┘      │  │
│  │                                │                              │  │
│  └────────────────────────────────┼──────────────────────────────┘  │
│                                   │                                 │
│                                   ▼                                 │
│                      ┌─────────────────────────┐                    │
│                      │  Polling Loop (1s tick) │                    │
│                      │                         │                    │
│                      │  ThreadPoolExecutor:    │                    │
│                      │    submit all due       │                    │
│                      │    collectors in        │                    │
│                      │    parallel threads     │                    │
│                      └────────────┬────────────┘                    │
│                                   │                                 │
└───────────────────────────────────┼─────────────────────────────────┘
                                    │
         ┌──────────────────────────┴──────────────────────────┐
         │                                                      │
         ▼                                                      ▼
  ┌─────────────┐                                      ┌──────────────┐
  │   Analyzer  │                                      │    Event     │
  │             │                                      │   Detector   │
  │ DOCSIS data │                                      │              │
  │  → health   │                                      │  Anomaly     │
  │  assessment │                                      │  detection   │
  └──────┬──────┘                                      └──────┬───────┘
         │                                                    │
         └────────────────────┬───────────────────────────────┘
                              │
                              ▼
                  ┌────────────────────────┐
                  │  SQLite Storage        │
                  │                        │
                  │  • Snapshots           │
                  │  • Trends              │
                  │  • Events              │
                  │  • Speedtest cache     │
                  │  • Incident journal    │
                  └───────────┬────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
  ┌───────────┐      ┌──────────────┐    ┌───────────────┐
  │   MQTT    │      │  Flask Web   │    │ PDF Reports   │
  │ Publisher │      │  UI + API    │    │  (fpdf2)      │
  │           │      │              │    │               │
  │ Home      │      │ 11 views     │    │ Complaint     │
  │ Assistant │      │ + REST API   │    │ letters       │
  └───────────┘      └──────────────┘    └───────────────┘
```

---

## Collector Pattern

### Base Collector Class

All data collectors inherit from `app/collectors/base.py`:

```python
class Collector(ABC):
    """Abstract base for all data collectors."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier."""
    
    @abstractmethod
    def collect(self) -> CollectorResult:
        """Fetch and return data."""
    
    def should_poll(self) -> bool:
        """True if enough time elapsed."""
    
    def record_success(self):
        """Reset penalty counter."""
    
    def record_failure(self):
        """Increment penalty counter."""
```

### Collector Lifecycle

```
┌──────────────────────────────────────────────────────────────┐
│                    Collector Lifecycle                        │
│                                                               │
│  START                                                        │
│    │                                                          │
│    ▼                                                          │
│  ┌─────────────────────┐                                     │
│  │  should_poll()?     │ ──No──┐                             │
│  │  (time + penalty)   │       │                             │
│  └───────┬─────────────┘       │                             │
│          │ Yes                 │                             │
│          ▼                     │                             │
│  ┌─────────────────────┐       │                             │
│  │    collect()        │       │                             │
│  │  (fetch data)       │       │                             │
│  └───────┬─────────────┘       │                             │
│          │                     │                             │
│          ▼                     │                             │
│     Success?                   │                             │
│      /    \                    │                             │
│    Yes    No                   │                             │
│     │      │                   │                             │
│     │      ▼                   │                             │
│     │  ┌──────────────────┐    │                             │
│     │  │ record_failure() │    │                             │
│     │  │  • failures++    │    │                             │
│     │  │  • penalty 2^N   │    │                             │
│     │  │  • max 3600s     │    │                             │
│     │  └────────┬─────────┘    │                             │
│     │           │              │                             │
│     ▼           ▼              │                             │
│  ┌─────────────────────┐       │                             │
│  │ record_success()    │       │                             │
│  │  • failures = 0     │       │                             │
│  │  • penalty = 0      │       │                             │
│  └──────────┬──────────┘       │                             │
│             │                  │                             │
│             └──────────────────┘                             │
│             │                                                │
│             ▼                                                │
│        Wait 1 second                                         │
│             │                                                │
│             └──────────────────────────────────────┐         │
│                                                    │         │
│  ┌─────────────────────────────────────────────────┘         │
│  │ Auto-reset check:                                        │
│  │  if idle > 24h: failures = 0                             │
│  └──────────────────────────────────────────────────────────┘
│                                                               │
│  REPEAT                                                       │
└───────────────────────────────────────────────────────────────┘
```

### Parallel Execution

Collectors run in parallel via `concurrent.futures.ThreadPoolExecutor` (one thread per collector). A blocking external call (e.g. Speedtest Tracker timeout) never delays the local modem poll.

```python
# main.py (simplified)
with ThreadPoolExecutor(max_workers=len(collectors)) as executor:
    while not stop_event.is_set():
        futures = {}
        for c in collectors:
            if c.is_enabled() and c.should_poll():
                futures[executor.submit(_run_collector, c)] = c
        for future in as_completed(futures, timeout=120):
            collector = futures[future]
            result = future.result()
            # record_success() or record_failure()
        stop_event.wait(1)
```

### Thread Safety

All shared state is protected by locks:

| Lock | Location | Protects |
|------|----------|----------|
| `_lock` | `Collector` base | Scheduling state (`_last_poll`, `_consecutive_failures`) |
| `_collect_lock` | `Collector` base | Prevents concurrent `collect()` (manual poll vs auto-poll) |
| `RuntimeState._lock` | `runtime.py` | Per-application dashboard state (written by collectors, read by Flask) |
| `LoginRateLimiter._lock` | `runtime.py` | Per-application login failure buckets |
| `UpdateChecker._lock` | `runtime.py` | Per-application update-check state |
| `_lock` | `EventDetector` | Previous snapshot comparison (`_prev`) |

SQLite uses **WAL mode** (`PRAGMA journal_mode=WAL`) for concurrent reads during writes.

### Fail-Safe Mechanism

**Exponential Backoff:**
```
Failure #1:   30s  penalty
Failure #2:   60s  penalty
Failure #3:  120s  penalty
Failure #4:  240s  penalty
Failure #5:  480s  penalty
Failure #6:  960s  penalty
Failure #7: 1920s  penalty
Failure #8: 3600s  penalty (cap reached)
Failure #9: 3600s  (stays at cap)
...
After 24h idle: auto-reset to 0
```

**Why:** Prevents hammering external services during outages, with automatic recovery.

---

## Implemented Collectors

### ModemCollector (`app/collectors/modem.py`)

**Purpose:** Fetch DOCSIS channel data from cable modem/router
**Poll Interval:** 900s (15 minutes, configurable)
**Data Source:** Pluggable modem driver (see Driver Architecture below)

**Pipeline:**
```
Driver.get_docsis_data()
  → analyzer.analyze()
    → event_detector.check()
      → storage.save_snapshot()
        → mqtt_pub.publish_data()
          → runtime.update_state()
```

**Output:** `CollectorResult` with channel health assessment

### SpeedtestCollector (`app/collectors/speedtest.py`)

**Purpose:** Fetch speed test results from Speedtest Tracker  
**Poll Interval:** 300s (5 minutes)  
**Data Source:** Speedtest Tracker REST API  

**Features:**
- Delta fetching (only new results since last poll)
- Local SQLite caching for performance
- Correlation with DOCSIS signal snapshots

### DemoCollector (`app/collectors/demo.py`)

**Purpose:** Generate realistic DOCSIS data for testing without a real modem
**Poll Interval:** Configurable (default 900s)
**Data Source:** `app/fixtures/demo_channels.json` with per-poll random variation
**Activation:** `DEMO_MODE=true` environment variable, or the fresh first-run action backed by `POST /api/demo/start`

**Pipeline:**
```
_generate_data() (base channels + variation)
  → analyzer.analyze() (real analysis!)
    → event_detector.check()
      → storage.save_snapshot()
        → mqtt_pub.publish_data()
          → runtime.update_state()
```

**Features:**
- 25 DS channels (24× DOCSIS 3.0 + 1× DOCSIS 3.1) and 4 US channels
- Per-poll variation: ±0.3 dBmV power, ±0.5 dB SNR, slowly accumulating errors
- Seeds 9 months (270 days) of historical snapshots retroactive from current date
- Pre-populated event log, journal entries (12), incident groups (3), speedtest results (270 days), BQM graphs (30 days), and BNetzA measurement campaigns (9 monthly)
- Time-based patterns: diurnal cycles, seasonal drift, periodic "bad periods"
- All demo rows marked with `is_demo=1` flag for clean separation from user data
- Purge-before-seed on container rebuild prevents duplicate data
- Device info: "DOCSight Demo Router", Connection: 250/40 Mbit/s Cable
- Demo discovery selects only `DemoCollector`; optional module collectors are not started while Demo Mode is active

**Live Migration:**
Users can switch from demo to live mode via Settings UI or `POST /api/demo/migrate`. This purges all `is_demo=1` rows while preserving user-created entries, disables demo mode, and restarts polling for real modem data.

### BQMCollector (`app/collectors/bqm.py`)

**Purpose:** Download and store ThinkBroadband BQM evidence for the BQM view
**Poll Interval:** 86400s (24 hours), gated by `bqm_collect_time` plus spread offset
**Data Source:** ThinkBroadband BQM service

**Primary Output:** CSV Yesterday data parsed into `bqm_data` for interactive uPlot charts
**Legacy Output:** PNG graph image saved to `bqm_graphs` when a PNG share URL is configured

**Collection behavior:**
- Settings save with a new ThinkBroadband CSV share URL triggers an immediate authenticated initial fetch through `POST /api/bqm/fetch-now` / `run_bqm_initial_fetch()`.
- Daily polling uses the CSV Yesterday share link and records collection metadata in `bqm_meta` (`last_success_target_date`, mode, rows, timestamp).
- Legacy PNG collection also stores the previous day as the target date so restart skip logic stays consistent with daily BQM evidence.
- A fresh collector instance checks persisted metadata before fetching so restarts after a successful collection do not duplicate the same target date.
- DOCSight does not silently invent multi-day backfill from the daily collector. Longer gaps should be filled with the BQM CSV bulk import.
- The UI labels cached PNG fallback separately from live refresh so cached evidence is not presented as live freshness.

### BnetzWatcherCollector (`app/collectors/bnetz_watcher.py`)

**Purpose:** Auto-import BNetzA measurement protocols from a watched directory
**Poll Interval:** 300s (5 minutes)
**Data Source:** Local filesystem (PDF and CSV files)
**Activation:** `BNETZ_WATCH_ENABLED=true` + `BNETZ_WATCH_DIR=/data/bnetz`

**Pipeline:**
```
Scan watch_dir for new .pdf/.csv files (not in .imported marker)
  -> PDF: parse_bnetz_pdf(bytes) -> storage.save_bnetz_measurement(parsed, pdf_bytes, source="watcher")
  -> CSV: parse_bnetz_csv(content) -> storage.save_bnetz_measurement(parsed, None, source="csv_import")
    -> Move processed files to processed/ subdirectory
      -> Append filenames to .imported marker
```

**Features:**
- Watches for `.pdf` and `.csv` files in configured directory
- Tracks already-imported files via `.imported` marker (set of filenames)
- Moves processed files to `processed/` subdirectory
- PDF parsing: reuses `app/bnetz_parser.py` (official BNetzA Messprotokoll format)
- CSV parsing: `app/bnetz_csv_parser.py` (semicolon-separated, German locale numbers)
- Partial failure handling: continues importing remaining files on individual errors
- `get_status()` includes `watch_dir` and `last_import_count` for UI banner

**Related files:**
- `app/bnetz_parser.py` - PDF parser for official BNetzA Messprotokolle
- `app/bnetz_csv_parser.py` - CSV parser for BNetzA Desktop App exports
- See wiki [Example Compose Stacks](https://github.com/itsDNNS/docsight/wiki/Example-Compose-Stacks) for sidecar examples

### BackupCollector (`app/collectors/backup.py`)

**Purpose:** Automatically create scheduled backups of all DOCSight data
**Poll Interval:** Configurable via `backup_interval_hours` (default: 24h)
**Data Source:** Local `/data` directory (SQLite DB, config, keys)
**Activation:** `backup_enabled=true` + `backup_path` configured in Settings

**Pipeline:**
```
create_backup_to_file(data_dir, dest_dir)
  -> VACUUM INTO for atomic, consistent DB copy
    -> Strip demo data (is_demo=1) from copy
      -> Pack into .tar.gz with backup_meta.json
        -> cleanup_old_backups(dest_dir, keep=retention)
```

**Features:**
- Atomic SQLite copy via `VACUUM INTO` (no WAL issues, consistent snapshot)
- `backup_meta.json` with format version, timestamp, app version, table row counts
- Configurable retention (number of backups to keep)
- Server-side directory browser for selecting backup path
- Manual download (in-memory .tar.gz) via Settings UI
- Restore from setup wizard on fresh instances

**Related files:**
- `app/backup.py` - Core backup/restore logic (no Flask dependency)
- `app/templates/setup.html` - Restore option in setup wizard

### Notifier (`app/notifier.py`)

**Purpose:** Route event notifications to external channels
**Trigger:** Called by EventDetector when anomalies are detected
**Channels:** Direct webhook (ntfy, Discord, Gotify, custom endpoints), optional Apprise API sidecar, and optional PWA Web Push for subscribed browsers/apps

**Features:**
- Severity filtering (minimum severity threshold)
- Cooldown period to prevent notification spam
- Template-based message formatting
- Configurable via Settings UI (webhook URL, Apprise API URL/key/token/tags, PWA Web Push VAPID keys/subject, headers, severity)
- DOCSight decides when to notify; Apprise handles fan-out to provider-specific targets, while PWA Web Push delivers to locally subscribed browser endpoints

---

## Driver Architecture

Modem drivers live in `app/drivers/` and implement the `ModemDriver` base class:

```python
class ModemDriver(ABC):
    def __init__(self, url: str, user: str, password: str): ...

    @abstractmethod
    def login(self) -> None: ...

    @abstractmethod
    def get_docsis_data(self) -> dict: ...

    @abstractmethod
    def get_device_info(self) -> dict: ...

    @abstractmethod
    def get_connection_info(self) -> dict: ...
```

### Supported Drivers

| Driver | Module | Hardware | Auth |
|--------|--------|----------|------|
| `fritzbox` | `fritzbox.py` | AVM FRITZ!Box | SID-based (data.lua) |
| `tc4400` | `tc4400.py` | Technicolor TC4400 | SNMP |
| `ultrahub7` | `ultrahub7.py` | Vodafone Ultra Hub 7 | Session cookie |
| `cm3500` | `cm3500.py` | Arris CM3500B | Form POST (IP-based session) |
| `connectbox` | `connectbox.py` | Unitymedia Connect Box (CH7465) | Session cookie |
| `vodafone_station` | `vodafone_station.py` | CGA6444VF, CGA4322DE, TG3442DE | Auto-detected (see below) |
| `cm1000` | `cm1000.py` | Netgear CM1000 | HTTP Basic or local Genie form |
| `cm3000` | `cm3000.py` | Netgear CM3000 | HTTP Basic Auth |
| `surfboard` | `surfboard.py` | Arris SURFboard S33/S34/SB8200 | HNAP1 HMAC-SHA256 |
| `sb6183` | `sb6183.py` | Arris SB6183 | None (HTTP status pages) |
| `cm8200` | `cm8200.py` | Arris Touchstone CM8200A | Base64 query string |
| `hitron_coda_4680` | `hitron_coda_4680.py` | Hitron CODA-4680 | Form POST (`/1/Device/Users/Login`) |
| `generic` | `generic.py` | Generic Router (no DOCSIS) | None |

### Driver Registry (`app/drivers/__init__.py`)

Drivers are loaded by name via `load_driver(modem_type, url, user, password)`. The registry maps type strings to fully qualified class paths for lazy importing.

### Extension module state

Installed non-theme modules are discovered by `ModuleLoader` and persisted through the comma-separated `disabled_modules` config key. The Settings Extensions panel treats installed module toggles as pending form state: users can change multiple modules and save them once through `POST /api/modules/batch`. Built-in themes are registered from the static theme registry in `app/theme_registry.py`; installed community themes still use their manifest and `theme.json` package format and remain on the dedicated theme APIs because preview and active-theme handling are separate flows.

Module manifests can declare module-owned config defaults through the top-level `config` object. Normal module config remains plain local configuration. A community manifest may opt specific declared string-default keys into write-only secret handling with `config_secrets`; the value must be a list of unique strings, every listed key must exist in that manifest's `config`, and each corresponding default must itself be a string so encrypted values never enter scalar coercion paths. The pure-stdlib validator in `app/manifest_contract.py` is the authoritative manifest capability contract used by the runtime loader and can also validate external catalogs without importing Flask.

Before any enabled module loads, `ModuleLoader` reserves secret ownership from every discovered community manifest, including disabled modules. Core secret, hash-backed, private, and core configuration keys cannot be claimed. A secret key must also be exclusive to its declaring module's `config`; claims that overlap another module's plain or secret config fail every affected module and grant no owner. The installer performs the same ownership evaluation against installed modules and rejects a conflicting package before it can be persisted. Valid module secrets are encrypted by `ConfigManager`, masked in Settings responses, and exposed through the community config proxy only to their owning module; other module secrets and all core protected values are removed.

Settings receives the active module-secret and saved-secret key sets from the server, so installed templates from before the explicit field-marker contract still preserve masked values safely during a coordinated catalog rollout. Current templates also represent saved secrets locally with empty password inputs plus explicit `data-config-secret` and `data-saved-secret` metadata. Untouched saved fields submit the standard mask, which `ConfigManager` treats as preserve-existing, while edited fields submit the replacement value. Saved plaintext is never rendered into HTML.

Built-in manifests may separately mark declared config keys with the built-in-only `configPrivate` field. Those values are encrypted at rest but remain displayable and editable private metadata, so `configPrivate` is not a password/secret mechanism and its semantics are unchanged.

Threshold profiles are mutually exclusive. The bundled VF/KD profile is registered from the static analyzer profile registry in `app/threshold_profiles.py`; installed community threshold profiles still use the module manifest `thresholds` contribution. The UI renders threshold profiles as a single radio group, and the batch API validates the invariant server-side so exactly one threshold profile remains active after save.

### Vodafone Station Auto-Detection

The Vodafone Station driver supports two hardware variants with different auth flows:

- **CGA** (CGA6444VF / CGA4322DE): Double PBKDF2-SHA256 + JSON REST API
- **TG** (TG3442DE): AES-CCM encrypted credentials + HTML/AJAX endpoints

Variant is auto-detected on first login: CGA is tried first, then TG on failure.

---

## Data Flow

### Modem Data Collection

```
┌──────────────────────────────────────────────────────────────┐
│ 1. Polling Loop (main.py)                                    │
│    if modem_collector.should_poll():                         │
│      result = modem_collector.collect()                      │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. ModemCollector (collectors/modem.py)                      │
│    driver.login()                                            │
│    data = driver.get_docsis_data()                           │
│    analysis = analyzer.analyze(data)                         │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. Analyzer (analyzer.py)                                    │
│    • Load active thresholds from analyzer profile registry   │
│    • Parse DS/US channels                                    │
│    • Assess power, SNR, errors per channel                   │
│    • Estimate SC-QAM gross channel capacity where supported   │
│    • Aggregate to overall health (good/tolerated/marginal/critical) │
│    • Return structured analysis dict                         │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────────┐
│ 4. Event Detector (event_detector.py)                        │
│    events = detector.check(analysis)                         │
│    • Compare to previous snapshot                            │
│    • Detect power shifts, SNR drops, modulation changes      │
│    • Generate event records with severity                    │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ├──────────────┬──────────────┬────────────┐
                     │              │              │            │
                     ▼              ▼              ▼            ▼
         ┌────────────────┐ ┌────────────┐ ┌──────────┐ ┌──────────┐
         │    Storage     │ │    MQTT    │ │   Web    │ │  Return  │
         │ save_snapshot()│ │  publish() │ │  update  │ │  Result  │
         │ save_events()  │ │  (HA)      │ │  _state()│ │          │
         └────────────────┘ └────────────┘ └──────────┘ └──────────┘
```

### Web API Request Flow

```
User clicks refresh button
    │
    ▼
POST /api/poll  (web.py)
    │
    ├─ Rate limit check (10s cooldown)
    │
    ├─ Acquire _collect_lock (non-blocking)
    │   └─ If busy → 429 "Poll already in progress"
    │
    ▼
result = modem_collector.collect()
    │
    ├─ (same flow as automatic polling)
    │
    ▼
Return JSON { success: true, analysis: {...} }
```

**Key:** Manual refresh uses the **same collector** as automatic polling, ensuring consistent fail-safe behavior. The `_collect_lock` prevents collision with a parallel auto-poll.

---

## Storage Layer

**Database:** SQLite (`/data/docsis_history.db`) with WAL mode for concurrent access

**Timestamp convention:** All `timestamp`, `created_at`, `updated_at`, and `last_used_at` columns store UTC with Z-suffix (`YYYY-MM-DDTHH:MM:SSZ`). Date-only columns (`date`, `start_date`, `end_date`) store calendar dates (`YYYY-MM-DD`) without timezone conversion. On first startup after upgrade, existing naive local timestamps are automatically migrated to UTC using the configured timezone. A safety backup (`docsis_history.db.pre_utc_migration`) is created before conversion.

**Schema:**

```sql
-- DOCSIS signal snapshots
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,  -- UTC with Z-suffix
    summary_json TEXT,
    ds_channels_json TEXT,
    us_channels_json TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0
);

-- Speed test results (cached from Speedtest Tracker)
CREATE TABLE speedtest_results (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    download_mbps REAL,
    upload_mbps REAL,
    ping_ms REAL,
    ...,
    is_demo INTEGER NOT NULL DEFAULT 0
);

-- Event log (anomaly detection)
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    severity TEXT,  -- info|warning|critical
    event_type TEXT,  -- health_change, power_shift, snr_drop, etc.
    message TEXT,
    acknowledged INTEGER,
    is_demo INTEGER NOT NULL DEFAULT 0
);

-- Incident containers (groups)
CREATE TABLE incidents (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'open',  -- open|resolved|escalated
    start_date TEXT,
    end_date TEXT,
    icon TEXT,
    created_at TEXT,
    updated_at TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0
);

-- Journal entries (formerly "incidents")
CREATE TABLE journal_entries (
    id INTEGER PRIMARY KEY,
    date TEXT,
    title TEXT,
    description TEXT,
    icon TEXT,
    incident_id INTEGER,  -- FK to incidents.id, nullable
    created_at TEXT,
    updated_at TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0
);

-- Journal attachments
CREATE TABLE journal_attachments (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER,  -- FK to journal_entries.id
    filename TEXT,
    mime_type TEXT,
    data BLOB,
    created_at TEXT
);

-- BQM graphs
CREATE TABLE bqm_graphs (
    id INTEGER PRIMARY KEY,
    date TEXT UNIQUE,
    timestamp TEXT,
    image_blob BLOB,
    is_demo INTEGER NOT NULL DEFAULT 0
);

-- BNetzA broadband measurements
CREATE TABLE bnetz_measurements (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    provider TEXT,
    tariff TEXT,
    download_max_tariff REAL,
    download_normal_tariff REAL,
    download_min_tariff REAL,
    upload_max_tariff REAL,
    upload_normal_tariff REAL,
    upload_min_tariff REAL,
    download_measured_avg REAL,
    upload_measured_avg REAL,
    measurement_count INTEGER,
    verdict_download TEXT,
    verdict_upload TEXT,
    measurements_json TEXT,
    pdf_blob BLOB,               -- NULL for CSV imports
    source TEXT DEFAULT 'upload'  -- 'upload', 'watcher', 'csv_import'
);
```

**Retention:** Configurable via `history_days` setting (default: 7 days)

---

## Web Layer

**Framework:** Flask  
**Port:** 8765 (configurable)  
**Auth:** Optional password protection (bcrypt hashing) + API token authentication (Bearer tokens)

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Main dashboard |
| `/settings` | GET | Configuration UI |
| `/api/poll` | POST | Manual data refresh |
| `/api/config` | POST | Save configuration |
| `/api/test-modem` | POST | Test modem connection |
| `/api/collectors/status` | GET | **NEW:** Collector health monitoring |
| `/api/snapshots` | GET | Available snapshot timestamps |
| `/api/trends` | GET | Trend data (day/week/month) |
| `/api/speedtest` | GET | Cached speedtest results |
| `/api/speedtest/<id>/signal` | GET | Correlated DOCSIS snapshot |
| `/api/events` | GET | Event log with filters |
| `/api/correlation` | GET | Cross-source timeline |
| `/api/journal` | GET/POST | Journal entries (list, create) |
| `/api/journal/<id>` | GET/PUT/DELETE | Single journal entry CRUD |
| `/api/journal/<id>/attachments` | POST | Upload entry attachments |
| `/api/journal/import/*` | POST | Excel/CSV import preview + confirm; UI keeps invalid or skipped rows visible before import |
| `/api/incidents` | GET/POST | Incident containers (list, create) |
| `/api/incidents/<id>` | GET/PUT/DELETE | Single incident container CRUD |
| `/api/incidents/<id>/assign` | POST | Assign entries to incident |
| `/api/journal/export` | GET | Export journal entries (CSV, JSON, or Markdown) |
| `/api/tokens` | GET/POST | List or create API tokens (POST requires session auth) |
| `/api/tokens/<id>` | DELETE | Revoke an API token (requires session auth) |
| `/api/export` | GET | AI/LLM-oriented markdown export; browser UI applies local preview, scope, and redaction controls |
| `/api/report` | GET | PDF evidence package from stored snapshots; accepts rolling `days` or an exact timezone-aware `from`/`to` window (maximum 90 days) |
| `/api/complaint` | GET | Localized complaint text from the same stored-snapshot window; returns the normalized UTC window with the generated text |
| `/api/bnetz/upload` | POST | Upload BNetzA measurement (PDF or CSV) |
| `/api/bnetz/measurements` | GET | List BNetzA measurements |
| `/api/bnetz/pdf/<id>` | GET | Download original measurement PDF |
| `/api/bnetz/<id>` | DELETE | Delete a BNetzA measurement |
| `/api/demo/migrate` | POST | Switch from demo to live mode (purges demo data, preserves user data) |
| `/api/backup` | POST | Create and download backup (.tar.gz) |
| `/api/backup/scheduled` | POST | Create backup in configured backup path |
| `/api/backup/list` | GET | List existing backups in backup path |
| `/api/backup/<filename>` | DELETE | Delete a backup file |
| `/api/restore/validate` | POST | Validate uploaded backup archive |
| `/api/restore` | POST | Restore from uploaded backup archive |
| `/api/browse` | GET | Server-side directory browser for path selection |

**New in v2.0:**

```json
GET /api/collectors/status

[
  {
    "name": "modem",
    "enabled": true,
    "consecutive_failures": 0,
    "penalty_seconds": 0,
    "poll_interval": 900,
    "effective_interval": 900,
    "last_poll": 1771140669.27,
    "next_poll_in": 890
  },
  {
    "name": "speedtest",
    "enabled": true,
    "consecutive_failures": 2,
    "penalty_seconds": 60,
    "poll_interval": 300,
    "effective_interval": 360,
    "last_poll": 1771140670.19,
    "next_poll_in": 120
  },
  ...
]
```

---

## Configuration

**File:** `/data/config.json` (AES-128 encrypted)  
**Format:** JSON  

**Key Settings:**
```json
{
  "modem_type": "fritzbox",
  "modem_url": "http://192.168.178.1",
  "modem_user": "user",
  "modem_password": "<encrypted>",
  "poll_interval": 900,
  "history_days": 7,
  "mqtt_host": "localhost",
  "speedtest_tracker_url": "http://...",
  "speedtest_tls_insecure": false,
  ...
}
```

**Override:** Environment variables take precedence over config.json

**Demo Mode:** Set `DEMO_MODE=true` to run without a real modem. The DemoCollector replaces the ModemCollector and generates 9 months of realistic simulated data. No modem password required, setup page is bypassed. All demo-seeded rows are tagged with `is_demo=1` so they can be cleanly purged when switching to live mode via `POST /api/demo/migrate`.

---

## Extending DOCSight

### Adding a New Collector

1. **Create collector class:**

```python
# app/collectors/my_collector.py
from .base import Collector, CollectorResult

class MyCollector(Collector):
    name = "my_source"
    
    def __init__(self, config_mgr, storage, poll_interval):
        super().__init__(poll_interval)
        self._config = config_mgr
        self._storage = storage
    
    def collect(self) -> CollectorResult:
        try:
            # Fetch data from external API
            data = self._fetch_data()
            
            # Store results
            self._storage.save_my_data(data)
            
            return CollectorResult(source=self.name, data=data)
        except Exception as e:
            return CollectorResult(source=self.name, success=False, error=str(e))
    
    def is_enabled(self) -> bool:
        # Check if configured
        return bool(self._config.get("my_source_url"))
```

2. **Add it to discovery:**

```python
# app/collectors/__init__.py
from .my_collector import MyCollector

def discover_collectors(...):
    collectors = []
    
    # ... existing collectors ...
    
    # My new collector
    if config_mgr.get("my_source_url"):
        collectors.append(MyCollector(
            config_mgr=config_mgr,
            storage=storage,
            poll_interval=3600,  # 1 hour
        ))
    
    return collectors
```

3. **Add configuration UI:**

Update `app/templates/settings.html` to include configuration fields for your collector.

4. **Add tests:**

```python
# tests/test_my_collector.py
def test_my_collector_success():
    collector = MyCollector(...)
    result = collector.collect()
    assert result.success
```

**That's it!** The collector will:
- Poll automatically at your specified interval
- Apply fail-safe on errors
- Report health via `/api/collectors/status`
- Integrate with the rest of the system

---

## Security

**Password Storage:**
- Admin password: scrypt/pbkdf2 hashed
- Modem password: AES-128 encrypted
- MQTT password: AES-128 encrypted
- Config file: chmod 600 (owner-only)

**Session Management:**
- Flask sessions with HTTPOnly cookies
- Rolling 30-day lifetime by default (`SESSION_LIFETIME_DAYS`, bounded to 1–365 days)
- SameSite=Lax policy; reverse-proxy deployments retain Secure HTTPS-only cookies
- Password-bound session markers invalidate existing logins when the effective admin password changes
- Persistent session key in `/data/.session_key`
- Keyed effective-auth state in `/data/.auth_state` detects changes across restarts

**Rate Limiting:**
- Login: 5 attempts per 15 minutes per IP
- Manual poll: 10 second cooldown

**Headers:**
- HSTS (Strict-Transport-Security)
- X-Frame-Options: DENY
- X-Content-Type-Options: nosniff
- CSP (Content Security Policy) for XSS protection

---

## Testing

**Framework:** pytest
**Coverage:** Extensive pytest suite across analyzers, collectors, storage, web, config, and integrations

**Run tests:**
```bash
python -m pytest tests/ -v
```

**Test Categories:**
- Analyzer: DOCSIS threshold logic
- Collectors: Data collection and fail-safe
- Storage: Database operations
- Web: API endpoints and auth
- Event detection: Anomaly detection
- Config: Configuration management
- BNetzA: PDF/CSV parsing and file watcher
- Demo mode: is_demo marking, purge, migration, idempotency
- Backup: create, validate, restore, cleanup, directory browser
- CM3500: HTML parsing, service flow parsing, HTTPS enforcement
- Notifier: webhook delivery, severity filtering, cooldown
- i18n: Translation completeness

---

## Performance

**Memory:** ~50-100 MB typical (depends on history_days)  
**CPU:** <1% average (spikes during polling)  
**Disk:** ~1-5 MB per day (depends on poll_interval and enabled collectors)  
**Network:** Minimal (only modem queries + optional external APIs)

**Optimization:**
- Speedtest results cached locally (reduces API calls)
- SQLite with indexes for fast queries
- uPlot for lightweight charting (~50KB vs Chart.js 204KB)

---

## Deployment

**Recommended:** Docker Compose

```yaml
services:
  docsight:
    image: ghcr.io/itsdnns/docsight:latest
    container_name: docsight
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - docsight_data:/data
      - docsight_backup:/backup  # Optional: for scheduled backups
    environment:
      - TZ=Europe/Berlin

volumes:
  docsight_data:
  docsight_backup:
```

**Data persistence:** All data in `/data` volume

---

## Troubleshooting

**Check collector status:**
```bash
curl http://localhost:8765/api/collectors/status | jq .
```

**Check logs:**
```bash
docker logs docsight
```

**Common issues:**

1. **Modem collector failing:**
   - Check modem URL and credentials
   - Verify modem is on same network
   - Check `/api/collectors/status` for penalty state

2. **Speedtest not updating:**
   - Verify Speedtest Tracker URL and token
   - Check `/api/collectors/status` for errors

3. **High penalty on collector:**
   - Auto-resets after 24h idle
   - Fix underlying issue (credentials, network)
   - Restart container to reset immediately

---

## License

MIT

---

## Further Reading

- [CONTRIBUTING.md](CONTRIBUTING.md) - Development guide
- [Wiki](https://github.com/itsDNNS/docsight/wiki) - User documentation
- [Roadmap](https://github.com/itsDNNS/docsight/wiki/Roadmap) - Future plans
