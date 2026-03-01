# Stack Research

**Domain:** DOCSIS monitoring tool — milestone feature additions
**Researched:** 2026-03-01
**Confidence:** HIGH (Prometheus library verified via PyPI/GitHub; driver and analysis patterns verified from codebase inspection)

---

## Scope

This research covers only the **6 new features** being added. It does not re-research the existing stack (Flask 3, SQLite, paho-mqtt, waitress, Docker).

---

## Recommended Stack

### New Dependencies

| Library | Version | Purpose | Why Recommended |
|---------|---------|---------|-----------------|
| `prometheus-client` | `>=0.24.1` | `/metrics` HTTP endpoint (feature #59) | Official Prometheus Python client. Provides `Gauge`, `Counter`, `Info`, `generate_latest`, `CONTENT_TYPE_LATEST`. Version 0.24.1 released 2026-01-14. Zero-config text-format exposition — Grafana, VictoriaMetrics, any Prometheus-compatible scraper works out of the box. |

**That is the only new pip dependency.** All other features (#131, #129, #92, #50, #60) are implementable with Python stdlib, the existing codebase patterns, and SQLite queries already in use.

---

### Feature-by-Feature Stack Breakdown

#### Feature #131 — Community-Contributed Modem Drivers via Module System

**Approach:** Extend existing `DRIVER_REGISTRY` in `app/drivers/__init__.py` to also scan the `ModuleLoader` for driver contributions. The module system already loads collectors, publishers, routes, and thresholds via `importlib.util.spec_from_file_location`. The same pattern applies to drivers.

**New manifest key:** Add `"driver"` to `VALID_CONTRIBUTES` in `module_loader.py`. Modules declare:
```json
{
  "type": "driver",
  "contributes": {
    "driver": "driver.py:MyModemDriver"
  }
}
```

**Loading pattern:** `load_module_driver()` mirrors `load_module_collector()` — already in `module_loader.py`. Loaded class is stored on `ModuleInfo.driver_class`. In `app/drivers/__init__.py`, `load_driver()` checks the module registry after the static `DRIVER_REGISTRY`.

**Libraries:** None new. Uses `importlib.util` (stdlib), already used in `module_loader.py`.

**Validation requirement:** Community driver module must subclass `ModemDriver` (ABC from `app/drivers/base.py`). The loader should `issubclass()` check on load and reject with a warning if violated.

**Confidence:** HIGH. Pattern is a direct extension of what `load_module_collector` already does. Zero new libraries.

---

#### Feature #129 — Non-DOCSIS Modem/Router Support (GenericDriver)

**Approach:** New concrete driver `app/drivers/generic.py` implementing `ModemDriver`. Returns empty/minimal DOCSIS data structures so the analyzer and collector pipeline continue to function.

**Interface contract:** The existing `ModemDriver` ABC requires:
- `login() -> None`
- `get_docsis_data() -> dict`
- `get_device_info() -> dict`
- `get_connection_info() -> dict`

`GenericDriver` implements all four. `get_docsis_data()` returns `{"ds_channels": [], "us_channels": []}` (or whatever minimal shape `analyzer.analyze()` expects without crashing). `login()` is a no-op. `get_device_info()` returns user-configured model/manufacturer strings from config.

**Registration:** Add `"generic": "app.drivers.generic.GenericDriver"` to `DRIVER_REGISTRY` in `app/drivers/__init__.py`.

**Libraries:** None new.

**Confidence:** HIGH. The ABC interface is fixed and known. The only risk is ensuring `analyzer.analyze()` handles empty channel lists gracefully — this is a code review concern, not a library choice concern.

---

#### Feature #92 — Daily Modulation Performance Distribution

**Approach:** SQLite-backed aggregation using existing `ds_channels_json` column in `snapshots` table (already populated by every poll). No new table needed — query existing data.

**Algorithm:** For a given date range, load all snapshot rows for that period, deserialize `ds_channels_json`, count each `modulation` value across all channels and all samples using `collections.Counter`. Return `{modulation: count, total_samples: N}`.

```python
from collections import Counter
import json, sqlite3

def get_modulation_distribution(db_path, start_ts, end_ts):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ds_channels_json FROM snapshots WHERE timestamp >= ? AND timestamp <= ?",
            (start_ts, end_ts)
        ).fetchall()
    counter = Counter()
    total = 0
    for (channels_json,) in rows:
        for ch in json.loads(channels_json):
            mod = ch.get("modulation", "unknown")
            if mod:
                counter[mod] += 1
                total += 1
    return {"distribution": dict(counter), "total_samples": total}
```

**Libraries:** `collections.Counter` (stdlib). No new dependencies.

**API shape:** New Flask route (Blueprint or extension of `analysis_bp`) at `/api/modulation-distribution?date=YYYY-MM-DD` or `?days=7`. Returns JSON with `{distribution: {"256QAM": 1420, "128QAM": 12, ...}, total_samples: 1432}`.

**Confidence:** HIGH. Data already exists in the snapshots table. Pattern matches `get_channel_history()` in `storage/analysis.py`.

---

#### Feature #50 — Before/After Signal Quality Comparison

**Approach:** Expose a comparison endpoint that accepts two timestamps (or two snapshot IDs) and returns the signal summary delta. Uses existing `get_snapshot()` method in `storage/snapshot.py`.

**Algorithm:**
1. Load snapshot A and snapshot B via `storage.get_snapshot(ts)`
2. Compute per-metric deltas: `power_avg_delta = b["ds_power_avg"] - a["ds_power_avg"]`, etc.
3. Return structured diff: `{before: <summary_A>, after: <summary_B>, delta: {ds_power_avg: X, ds_snr_min: Y, ...}}`

**API shape:** `GET /api/snapshot/compare?before=<ts>&after=<ts>` — matches convention of existing `?hours=`, `?days=` parameters.

**Libraries:** None new. Pure Python arithmetic on existing snapshot dicts.

**Confidence:** HIGH. `get_snapshot()` already exists and returns the exact structure needed.

---

#### Feature #59 — Prometheus-Compatible `/metrics` Endpoint

**Library:** `prometheus-client==0.24.1` (latest as of 2026-01-14).

**Installation:**
```bash
pip install prometheus-client>=0.24.1
```

**Flask integration pattern (verified from official client_python source):**
```python
from prometheus_client import (
    Gauge, Counter, Info,
    generate_latest, CONTENT_TYPE_LATEST,
    REGISTRY,
)
from flask import Response

# Module-level metric definitions (created once, global)
DS_POWER_AVG = Gauge("docsight_ds_power_avg_dbmv", "Average downstream power level")
DS_SNR_MIN   = Gauge("docsight_ds_snr_min_db", "Minimum downstream SNR")
US_POWER_AVG = Gauge("docsight_us_power_avg_dbmv", "Average upstream power level")
DS_UNCORR    = Counter("docsight_ds_uncorrectable_errors_total", "Cumulative uncorrectable errors")
HEALTH_INFO  = Info("docsight_health", "Current DOCSIS health status")

@metrics_bp.route("/metrics")
def prometheus_metrics():
    # Update gauges from current web state before responding
    state = get_state()
    analysis = state.get("analysis") or {}
    summary = analysis.get("summary", {})
    DS_POWER_AVG.set(summary.get("ds_power_avg", 0))
    DS_SNR_MIN.set(summary.get("ds_snr_min", 0))
    # ... etc.
    return Response(generate_latest(REGISTRY), mimetype=CONTENT_TYPE_LATEST)
```

**Important design decision — do NOT use `start_http_server()`:** DOCSight runs as a single-process waitress WSGI server. The built-in `start_http_server()` opens a second port, which conflicts with the single-container deployment model. The correct approach is a Flask route that calls `generate_latest()` directly. This is the standard pattern for embedded Flask/WSGI apps.

**Important design decision — do NOT use `prometheus_flask_exporter`:** That library auto-instruments every Flask route with request latency metrics. DOCSight's `/metrics` endpoint is a DOCSIS data exporter, not a web app performance monitor. Using the base `prometheus-client` directly gives full control over exactly which metrics are exposed.

**Metric types to use:**
| Metric | Type | Rationale |
|--------|------|-----------|
| DS/US power levels | `Gauge` | Can go up or down between polls |
| DS/US SNR | `Gauge` | Can go up or down |
| Error counts | `Gauge` | Resets on modem restart; Counter semantics misleading |
| Health status | `Info` | Categorical string, not numeric |
| DS/US channel count | `Gauge` | Changes with modem DOCSIS bonding |
| Per-channel power/SNR | `Gauge` with `channel_id` label | Enables per-channel Grafana panels |

**Note on `Counter` vs `Gauge` for errors:** DOCSIS error counters in modem firmware are cumulative but reset to zero on modem restart. Using Prometheus `Counter` type here is semantically wrong (Counters must be monotonically increasing). Use `Gauge` and let Prometheus/Grafana's `increase()` or `delta()` functions handle rate computation.

**Confidence:** HIGH. Library verified at PyPI (v0.24.1, Jan 2026). API verified from official GitHub `__init__.py`. Flask integration pattern verified via multiple community sources.

---

#### Feature #60 — Modem Restart Detection via Error Counter Reset

**Approach:** Extend `EventDetector` (in `app/event_detector.py`) with restart detection logic. The existing `_check_errors()` method already compares consecutive `ds_uncorrectable_errors` values. A modem restart is detectable when the new value is significantly lower than the previous (counter reset to zero or near-zero).

**Detection logic:**
```python
def _check_restart(self, events, ts, cur, prev):
    RESTART_RESET_THRESHOLD = 100  # errors dropped by at least this many = likely reset
    uncorr_cur = cur.get("ds_uncorrectable_errors", 0)
    uncorr_prev = prev.get("ds_uncorrectable_errors", 0)
    corr_cur = cur.get("ds_correctable_errors", 0)
    corr_prev = prev.get("ds_correctable_errors", 0)

    # Both counters dropped significantly = modem restarted
    if (uncorr_prev - uncorr_cur > RESTART_RESET_THRESHOLD and
            corr_prev - corr_cur > RESTART_RESET_THRESHOLD):
        events.append({
            "timestamp": ts,
            "severity": "warning",
            "event_type": "modem_restart",
            "message": "Modem restart detected (error counters reset)",
            "details": {
                "prev_uncorr": uncorr_prev,
                "cur_uncorr": uncorr_cur,
                "prev_corr": corr_prev,
                "cur_corr": corr_cur,
            },
        })
```

**Caveat:** Error counters can also reset if the modem reinitializes the DOCSIS connection without a full restart. The event label `modem_restart` is accurate for the symptom (counter reset) even if the underlying cause is a partial re-ranging. Calling it `"modem_restart_detected"` in the message is more honest than claiming certainty.

**Heuristic robustness:** Requiring both correctable AND uncorrectable to drop guards against false positives from normal counter fluctuations. Single-counter drops happen legitimately. Dual-counter simultaneous drop near zero is a reliable modem restart fingerprint.

**Libraries:** None new. Pure Python extension of existing `EventDetector`.

**Confidence:** MEDIUM. The heuristic (dual counter drop) is sound and matches how experienced DOCSIS engineers detect restarts. The specific threshold (100) will need tuning — it should be configurable rather than hardcoded. No official DOCSIS specification document was found that defines a canonical restart detection algorithm; this is field-proven practice.

---

## Alternatives Considered

| Feature | Recommended | Alternative | Why Not |
|---------|-------------|-------------|---------|
| Prometheus endpoint | `prometheus-client` directly | `prometheus_flask_exporter` | Auto-instruments Flask routes with request metrics — wrong scope for a DOCSIS data exporter |
| Prometheus endpoint | `prometheus-client` directly | `statsd` + `statsd_exporter` | Extra infrastructure (statsd daemon + exporter). DOCSight targets single-container self-hosters. |
| Driver plugin system | Extend existing `ModuleLoader` | `pluggy` (pytest's plugin system) | DOCSight already has a working module system. Adding `pluggy` would be a third dependency for no benefit. |
| Driver plugin system | Extend existing `ModuleLoader` | `importlib.metadata` entry points | Entry points require pip-installable packages. DOCSight community modules are dropped into `/modules/` as directories, not installed via pip. The existing filesystem-scan approach is correct for this deployment model. |
| Modulation distribution | `collections.Counter` + SQLite query | `pandas` + dataframe groupby | `pandas` is a 30+ MB dependency for what is a 10-line aggregation. Overkill. |
| Restart detection | `EventDetector._check_restart()` | ML anomaly detection | The counter reset pattern is deterministic and interpretable. ML would add complexity without meaningful accuracy gain. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `prometheus_flask_exporter` | Adds unwanted per-route request metrics; correct for web app monitoring, wrong for DOCSIS data export | `prometheus-client` directly with a manual Flask route |
| `pluggy` | DOCSight's module system already handles driver loading. Third dependency with no benefit | Extend `ModuleLoader` + `app/drivers/__init__.py` |
| `pandas` / `numpy` for modulation stats | 30-60 MB of dependencies for aggregations already expressible with `collections.Counter` and SQLite GROUP BY | Python stdlib `collections.Counter` |
| `prometheus_client.start_http_server()` | Opens a second TCP port. Breaks single-container model. | `generate_latest()` in a Flask route |
| `prometheus_client.Counter` for DOCSIS error metrics | DOCSIS error counters reset on modem restart, violating Prometheus Counter monotonicity invariant | `prometheus_client.Gauge` for all DOCSIS error metrics |

---

## Installation

```bash
# requirements.txt addition
prometheus-client>=0.24.1
```

No other new dependencies. All 5 remaining features use Python stdlib and existing codebase patterns.

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `prometheus-client>=0.24.1` | `flask>=3.0`, `waitress>=3.0` | No conflict. Works as a standalone metrics formatter called from any Flask route. |
| `prometheus-client>=0.24.1` | Python >=3.9 | DOCSight's existing code uses `dict[str, str]` type hints (Python 3.9+), so this is already satisfied. |

---

## Sources

- [prometheus-client PyPI page](https://pypi.org/project/prometheus-client/) — version 0.24.1 confirmed (released 2026-01-14)
- [prometheus/client_python GitHub `__init__.py`](https://github.com/prometheus/client_python/blob/master/prometheus_client/__init__.py) — confirmed: `Gauge`, `Counter`, `Info`, `Enum`, `Histogram`, `generate_latest`, `CONTENT_TYPE_LATEST`, `make_wsgi_app` all exported (HIGH confidence)
- [Python Packaging User Guide — Creating and discovering plugins](https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/) — entry_points vs filesystem scan comparison; filesystem scan confirmed correct for non-pip-installed modules (HIGH confidence)
- [prometheus.github.io/client_python](https://prometheus.github.io/client_python/) — framework integrations overview; WSGI/Flask support confirmed (HIGH confidence)
- Existing codebase `app/module_loader.py`, `app/drivers/__init__.py`, `app/event_detector.py`, `app/storage/analysis.py` — inspected directly to confirm all non-Prometheus features are achievable without new libraries (HIGH confidence)

---

*Stack research for: DOCSight milestone — driver extensibility, analysis features, Prometheus export*
*Researched: 2026-03-01*
