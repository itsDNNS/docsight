# DOCSight Architecture

> Documentation current as of **v2026-02-18.4**

This document describes the technical architecture of DOCSight.

## Overview

DOCSight is built around a **modular collector pattern** that separates data collection, analysis, storage, and presentation into independent, testable components.

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
│  │         ┌──────────┬─────────────┼──────────────┬───────────┐  │  │
│  │         │          │             │              │           │  │  │
│  │         ▼          ▼             ▼              ▼           ▼  │  │
│  │  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐│
│  │  │  Modem   │ │   Demo   │ │ Speedtest  │ │    BQM     │ │  BNetzA    ││
│  │  │ Collect. │ │ Collect. │ │ Collector  │ │ Collector  │ │  Watcher   ││
│  │  │          │ │          │ │            │ │            │ │            ││
│  │  │ Poll:900s│ │ Poll:900s│ │ Poll: 300s │ │ Poll: 24h  │ │ Poll: 300s ││
│  │  └────┬─────┘ └────┬─────┘ └─────┬──────┘ └─────┬──────┘ └─────┬──────┘│
│  │       │             │             │              │              │       │
│  │       └─────────────┴─────────────┼──────────────┴──────────────┘       │
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
| `_state_lock` | `web.py` | Shared `_state` dict (written by collectors, read by Flask) |
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
          → web.update_state()
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
**Activation:** `DEMO_MODE=true` environment variable

**Pipeline:**
```
_generate_data() (base channels + variation)
  → analyzer.analyze() (real analysis!)
    → event_detector.check()
      → storage.save_snapshot()
        → mqtt_pub.publish_data()
          → web.update_state()
```

**Features:**
- 25 DS channels (24× DOCSIS 3.0 + 1× DOCSIS 3.1) and 4 US channels
- Per-poll variation: ±0.3 dBmV power, ±0.5 dB SNR, slowly accumulating errors
- Seeds 90 days of historical snapshots on first run (8640 data points)
- Pre-populated event log (48 events), journal entries (6), and incident groups (2 containers with assigned entries)
- Time-based patterns: diurnal cycles, seasonal drift, periodic "bad periods"
- Device info: "DOCSight Demo Router", Connection: 250/40 Mbit/s Cable

### BQMCollector (`app/collectors/bqm.py`)

**Purpose:** Download broadband quality graphs
**Poll Interval:** 86400s (24 hours)
**Data Source:** ThinkBroadband BQM service

**Output:** PNG graph image saved to storage

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
- `docker-compose.bnetz.yml` - Sidecar compose for automated measurements

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
| `vodafone_station` | `vodafone_station.py` | CGA6444VF, CGA4322DE, TG3442DE | Auto-detected (see below) |

### Driver Registry (`app/drivers/__init__.py`)

Drivers are loaded by name via `load_driver(modem_type, url, user, password)`. The registry maps type strings to fully qualified class paths for lazy importing.

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
│    • Load thresholds from thresholds.json                    │
│    • Parse DS/US channels                                    │
│    • Assess power, SNR, errors per channel                   │
│    • Aggregate to overall health (good/marginal/poor)        │
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

**Schema:**

```sql
-- DOCSIS signal snapshots
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    summary_json TEXT,
    ds_channels_json TEXT,
    us_channels_json TEXT
);

-- Speed test results (cached from Speedtest Tracker)
CREATE TABLE speedtest_results (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    download_mbps REAL,
    upload_mbps REAL,
    ping_ms REAL,
    ...
);

-- Event log (anomaly detection)
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    severity TEXT,  -- info|warning|critical
    event_type TEXT,  -- health_change, power_shift, snr_drop, etc.
    message TEXT,
    acknowledged INTEGER
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
    updated_at TEXT
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
    updated_at TEXT
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
    image_blob BLOB
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
**Auth:** Optional password protection (bcrypt hashing)

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
| `/api/journal/import/*` | POST | Excel/CSV import (preview + confirm) |
| `/api/incidents` | GET/POST | Incident containers (list, create) |
| `/api/incidents/<id>` | GET/PUT/DELETE | Single incident container CRUD |
| `/api/incidents/<id>/assign` | POST | Assign entries to incident |
| `/api/export` | GET | LLM-optimized report |
| `/api/report` | GET | PDF incident report |
| `/api/bnetz/upload` | POST | Upload BNetzA measurement (PDF or CSV) |
| `/api/bnetz/measurements` | GET | List BNetzA measurements |
| `/api/bnetz/pdf/<id>` | GET | Download original measurement PDF |
| `/api/bnetz/<id>` | DELETE | Delete a BNetzA measurement |

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
  ...
}
```

**Override:** Environment variables take precedence over config.json

**Demo Mode:** Set `DEMO_MODE=true` to run without a real modem. The DemoCollector replaces the ModemCollector and generates realistic simulated data. No modem password required, setup page is bypassed.

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
            
            return CollectorResult.ok(self.name, data)
        except Exception as e:
            return CollectorResult.failure(self.name, str(e))
    
    def is_enabled(self) -> bool:
        # Check if configured
        return bool(self._config.get("my_source_url"))
```

2. **Register in discovery:**

```python
# app/collectors/__init__.py
from .my_collector import MyCollector

COLLECTOR_REGISTRY = {
    "modem": ModemCollector,
    "demo": DemoCollector,
    "speedtest": SpeedtestCollector,
    "bqm": BQMCollector,
    "bnetz_watcher": BnetzWatcherCollector,
    "my_source": MyCollector,  # Add here
}

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
- SameSite=Strict policy
- Persistent session key in `/data/.session_key`

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
**Coverage:** 330 tests

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
- Chart.js loaded from CDN (reduces image size)

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
    environment:
      - TZ=Europe/Berlin

volumes:
  docsight_data:
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
