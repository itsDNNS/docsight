# Project Research Summary

**Project:** DOCSight — Extensibility and Analysis Milestone
**Domain:** Self-hosted DOCSIS cable modem monitoring tool
**Researched:** 2026-03-01
**Confidence:** HIGH

## Executive Summary

DOCSight is a mature self-hosted DOCSIS monitoring tool (Flask, SQLite, paho-mqtt, Docker) adding six new capabilities in a single milestone: community-contributed modem drivers via the module system, a GenericDriver for non-DOCSIS hardware, daily modulation distribution analysis, before/after signal comparison, a Prometheus-compatible `/metrics` endpoint, and modem restart detection. Research confirms that all six features are buildable entirely on the existing codebase with one new dependency (`prometheus-client>=0.24.1`). The existing module system, driver ABC, storage layer, and event detector already provide the foundation — these are additions and extensions, not new subsystems.

The recommended approach is to implement features in dependency order, not feature request order. GenericDriver comes first because it unblocks testing every other feature on machines without a real DOCSIS modem. The module loader driver hook is the highest-complexity piece (it is a new core extension point) and must be completed early so community driver contributions can be validated against it. The three analysis features (modulation distribution, before/after comparison, Prometheus) are pure read-path additions with zero storage schema changes and can be built in parallel once the driver layer is stable.

The primary risks are not technical but behavioral: community driver modules run with full process privileges and there is no sandbox — this must be prominently documented rather than silently ignored. The modem restart detection heuristic is sound but must guard against 32-bit counter wrap, which is indistinguishable from a restart without a multi-signal confirmation. The modulation distribution endpoint is correct in computing from raw poll samples, but the UI must show wall-clock duration alongside percentages or brief degradations become invisible.

## Key Findings

### Recommended Stack

The existing stack (Flask 3, SQLite, paho-mqtt, waitress, Docker) requires no changes. Only one new pip dependency is needed: `prometheus-client>=0.24.1`, which provides `Gauge`, `Counter`, `Info`, `generate_latest`, and `CONTENT_TYPE_LATEST`. All other features are implementable with Python stdlib (`collections.Counter`, `importlib.util`, `json`) and existing codebase patterns.

**Core technologies:**
- `prometheus-client>=0.24.1`: Prometheus text format exposition — use `generate_latest()` in a Flask route, never `start_http_server()` (opens a second port, breaks single-container model)
- `collections.Counter` (stdlib): Modulation distribution aggregation — no pandas/numpy needed for this aggregation
- `importlib.util` (stdlib): Already used in `module_loader.py` for community modules; driver loading mirrors the existing `load_module_collector()` pattern exactly
- `ModemDriver` ABC (existing): The ABC interface is fixed; all new and community drivers must subclass it — `login()`, `get_docsis_data()`, `get_device_info()`, `get_connection_info()`

**Critical version note:** Use `Gauge` (not `Counter`) for DOCSIS error metrics. DOCSIS error counters reset on modem restart, violating Prometheus `Counter` monotonicity invariant. Use `Gauge` and let Grafana's `increase()` or `delta()` handle rate computation.

### Expected Features

**Must have (table stakes):**
- Prometheus `/metrics` returning valid text format (`Content-Type: text/plain; version=0.0.4`) — wrong content type breaks scrapers silently
- `/metrics` endpoint protected by existing `@require_auth` — consistency with all other routes; unprotected = ISP data leak
- Modem restart detection emits an event to the journal — restarts are currently invisible and corrupt historical delta analysis
- Restart detection must suppress false error-spike event when a restart is detected — without this, a restart triggers both a restart event and a false "error recovered"
- GenericDriver produces `health: "unknown"` (not `"good"`) with a visually distinct dashboard badge — green badge for an unmonitored device is actively misleading
- Community drivers load by dropping a module folder and restarting — no editing of core `DRIVER_REGISTRY` required

**Should have (differentiators):**
- Per-channel Prometheus labels using frequency (MHz) as identifier, not channel ID — channel IDs reassign after restart, causing stale Prometheus time series
- Modulation distribution shows both percentage and wall-clock duration ("256QAM: 96% (23h 2m)") — percentage alone makes brief degradations invisible
- Before/After comparison always displays resolved (actual) snapshot timestamps, with a warning badge if resolution differed by more than 30 minutes from the user's selection
- Driver manifest declares both driver class and driver key (`"driver_key"`) as an explicit field — ambiguous format blocks community contributions

**Defer to v1.x / v2+:**
- OpenMetrics format (`application/openmetrics-text`) — add only when users report Prometheus 3.x compatibility issues
- "Detect modem type" button in Settings — useful but not blocking
- Community segment heatmap (#61) — requires multi-user data sharing infrastructure
- Peering quality check (#70) — external dependency

### Architecture Approach

All six features integrate cleanly into the existing layered architecture (Flask blueprints → Collector orchestrator → Driver ABC → Analysis pipeline → SQLite storage → Module system) without requiring any schema changes or new subsystems. The module loader needs one new contribution key (`driver`), the event detector needs one new private method (`_check_restart`), the analysis blueprint needs two new endpoints, and a new `metrics_bp.py` blueprint handles Prometheus. No collector or storage schema changes are required for any of the six features.

**Major components and their changes:**
1. `app/drivers/generic.py` (NEW) — GenericDriver stub; implements full ModemDriver ABC, returns empty channel lists, sets health to `"unknown"`
2. `app/module_loader.py` (EXTEND) — Add `load_module_driver()`, `driver_class` field to `ModuleInfo`, `"driver"` to `VALID_CONTRIBUTES`; mirrors `load_module_collector()` exactly
3. `app/drivers/__init__.py` (EXTEND) — Register `"generic"` in `DRIVER_REGISTRY`; add bridge to check module driver registry before falling back to `DRIVER_REGISTRY`
4. `app/event_detector.py` (EXTEND) — Add `_check_restart()` using dual-counter drop heuristic (both correctable AND uncorrectable must drop simultaneously)
5. `app/blueprints/metrics_bp.py` (NEW) — Prometheus endpoint; reads from in-memory `web.get_state()["analysis"]`, no SQLite query per scrape
6. `app/storage/analysis.py` (EXTEND) — Add `get_modulation_distribution(date)` on `AnalysisMixin`; queries existing `ds_channels_json` column
7. `app/blueprints/analysis_bp.py` (EXTEND) — Add `/api/analysis/compare` and `/api/analysis/modulation-distribution` endpoints

**Key patterns to follow:**
- Read Prometheus data from in-memory `_state`, never from SQLite on each scrape (avoids lock contention under 15s Prometheus scrape intervals)
- Driver ABC conformance is the isolation boundary — nothing downstream of the driver ever changes when a new driver is added
- EventDetector extension via private methods is the established pattern; do not extract to a strategy pattern (premature)
- Compute modulation distribution on-demand from existing `ds_channels_json`; never create a derived `modulation_stats` table

### Critical Pitfalls

1. **Community driver modules execute arbitrary Python with full process privileges** — No sandbox exists or should be attempted (RestrictedPython is routinely bypassed). Mitigation: add mandatory code review guidance in contribution docs; enforce via manifest validation that community driver modules may not contribute `routes` or `publisher` alongside `driver`; document clearly that users accept security risk when installing community drivers.

2. **GenericDriver empty data produces misleading `health: "good"`** — `analyzer.analyze()` with empty channel lists has no issues to detect, so it returns `"good"`. This must be explicitly caught: if both downstream and upstream are empty lists, set `health = "unknown"` and surface a distinct dashboard badge state. Verify: test `analyze({"downstream": [], "upstream": []})` returns `health: "unknown"`.

3. **Modem restart detection triggers false positives on 32-bit counter wrap** — DOCSIS error counters are 32-bit unsigned integers and wrap at ~4.3 billion. A counter wrap produces `current < previous` identically to a restart. Mitigation: require dual-counter drop (both correctable AND uncorrectable fall simultaneously) AND at least one corroborating signal (channel count change or power level jump > 5 dBmV). Test with fixture values near integer max rolling over to small positive.

4. **Before/After comparison silently resolves to wrong snapshot pair** — `get_closest_snapshot()` uses a 2-hour window; during modem outages, the resolved snapshot can be hours from the intended time. Mitigation: always return actual resolved timestamps in the API response and UI; return explicit error (not silent expansion) when no snapshot exists within the window; warn if resolution differs by more than 30 minutes.

5. **Prometheus label choice causes stale time series after modem restart** — Channel IDs reassign after a modem restart; using channel ID as a label leaves orphaned Prometheus series. Mitigation: use channel frequency (MHz) as the stable identifier label, with `direction` (ds/us) as a secondary label. Cap labels at 3 per metric to prevent cardinality explosion.

## Implications for Roadmap

Based on the dependency graph, architecture boundaries, and pitfall phase mappings, the six features should be implemented as three phases:

### Phase 1: Driver Foundation
**Rationale:** GenericDriver is the prerequisite for testing every other feature on development machines without a real DOCSIS modem. The module loader driver hook is the highest-complexity piece of this milestone and must be stable before community contribution workflows are designed. These two changes share the driver subsystem and should be built together to validate the full driver lifecycle end-to-end.
**Delivers:** Any user can run DOCSight without a supported modem; community authors can contribute drivers via module manifests without touching core code.
**Addresses:** Features #129 (GenericDriver), #131 (Community Driver Modules)
**Avoids:** GenericDriver health mislead (verify `health: "unknown"` before marking complete); community driver security surface (enforce manifest validation rules)
**Research flags:** Standard patterns — module loader extension mirrors `load_module_collector()` exactly, no research needed during planning.

### Phase 2: Signal Intelligence
**Rationale:** Modem restart detection and the Prometheus endpoint are both read-path additions with zero storage risk. They can be built in parallel after Phase 1 provides a stable GenericDriver to test against. Restart detection is a pure `EventDetector` extension; Prometheus is a pure Flask blueprint. Neither blocks the other. The Prometheus endpoint reads from the same in-memory state that GenericDriver already writes to, making it easy to validate end-to-end.
**Delivers:** Restart events appear in the event journal; Grafana/Prometheus integrations can scrape DOCSIS metrics.
**Addresses:** Features #60 (Modem Restart Detection), #59 (Prometheus /metrics)
**Avoids:** Counter wrap false positive (dual-signal heuristic required); Prometheus label cardinality (use frequency not channel ID); unprotected `/metrics` route (apply existing `@require_auth`)
**Research flags:** Standard patterns — EventDetector extension and Flask blueprint are well-established in this codebase, no research needed.

### Phase 3: Analysis Features
**Rationale:** Modulation distribution and before/after comparison are purely additive query-layer features that depend only on existing snapshot data. They share the analysis blueprint and benefit from the stable driver layer (Phase 1) to generate test data. Before/after comparison should come after modulation distribution since the query patterns established for distribution help inform the snapshot selection UX for comparison.
**Delivers:** Users can visualize QAM tier distribution over time and formally verify signal changes before/after maintenance events.
**Addresses:** Features #92 (Daily Modulation Distribution), #50 (Before/After Signal Comparison)
**Avoids:** Modulation distribution mislead (show duration alongside percentage); before/after silent temporal misalignment (display resolved timestamps, warn on > 30-minute gap); modulation query performance (scope to single day, consider caching for large datasets)
**Research flags:** Standard patterns — aggregation via `collections.Counter` and existing storage queries; no external API research needed. One area to validate: ensure `analyzer.analyze()` handles empty channel lists gracefully before Phase 1 ships (affects both GenericDriver and modulation distribution empty states).

### Phase Ordering Rationale

- Dependency order drives sequencing: GenericDriver enables test coverage for everything else; driver hook is the architectural prerequisite for community extensibility
- Architecture boundaries group naturally: driver-layer changes (Phase 1), event/metrics blueprint additions (Phase 2), analysis query extensions (Phase 3)
- Risk-ordered: highest complexity and most architectural impact first (Phase 1 touches module_loader and driver registry), lowest risk last (Phase 3 is pure read path)
- Pitfall avoidance: by building GenericDriver first and verifying `health: "unknown"` before any other work, the false-green health state is caught at the source rather than discovered later when Prometheus starts exposing misleading `docsight_ds_channel_count 0` metrics

### Research Flags

Phases with standard patterns (research-phase not needed):
- **Phase 1 (Driver Foundation):** Module loader extension is a structural copy of `load_module_collector()` — pattern is established and documented in codebase.
- **Phase 2 (Signal Intelligence):** EventDetector extension and Flask blueprint follow established in-codebase patterns.
- **Phase 3 (Analysis Features):** SQLite aggregation + new API endpoints follow established storage mixin + blueprint patterns.

One validation item (not a research gap, but a code review gate): verify `analyzer.analyze()` handles `{"downstream": [], "upstream": []}` gracefully before Phase 1 is marked complete. If it crashes or returns `"good"`, fix the analyzer as part of Phase 1 before any downstream features depend on it.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | `prometheus-client` verified at PyPI v0.24.1 (Jan 2026); all other features confirmed as stdlib-only via direct codebase inspection; no guesswork |
| Features | HIGH | Codebase inspected directly; feature contracts derived from existing ABCs and storage schemas; Prometheus format from official docs |
| Architecture | HIGH | All 7 affected files identified by name with specific methods/changes; data flows traced through actual code paths; no assumptions about unexplored code |
| Pitfalls | HIGH | 5 critical pitfalls derived from codebase-specific failure modes (counter wrap, empty channel analysis, module loading), not generic advice |

**Overall confidence:** HIGH

### Gaps to Address

- **`analyzer.analyze()` empty channel behavior:** Research confirmed the likely failure mode (returns `"good"`) but did not run the code. A code review or test run must confirm the fix is needed and applied before Phase 1 ships. This is a validation step, not a research gap.

- **Counter wrap threshold tuning:** The RESTART_RESET_THRESHOLD (100) in event detector is a starting value. Research recommends making it configurable rather than hardcoded, but the exact default requires field testing against real modem data. Flag for post-ship tuning.

- **Modulation distribution query performance at scale:** Research assessed that 1440 rows/day x N channels is acceptable at current scale but recommended considering background computation for large datasets (7-day range at 10s poll = ~60,000 rows). No benchmarks were run. Add a performance test or time-box the endpoint response before shipping Phase 3.

## Sources

### Primary (HIGH confidence)
- DOCSight codebase direct inspection: `app/drivers/base.py`, `app/drivers/__init__.py`, `app/module_loader.py`, `app/event_detector.py`, `app/storage/snapshot.py`, `app/storage/analysis.py`, `app/collectors/modem.py`, `app/blueprints/analysis_bp.py`, `app/web.py`
- DOCSight plan: `docs/plans/2026-02-28-community-module-registry.md`
- DOCSight PROJECT.md: `.planning/PROJECT.md`
- `prometheus-client` PyPI page: https://pypi.org/project/prometheus-client/ — version 0.24.1 confirmed (released 2026-01-14)
- `prometheus/client_python` GitHub `__init__.py` — `Gauge`, `Counter`, `Info`, `generate_latest`, `CONTENT_TYPE_LATEST` exports confirmed

### Secondary (MEDIUM confidence)
- Prometheus exposition format: https://prometheus.io/docs/instrumenting/exposition_formats/
- Prometheus writing exporters guide: https://prometheus.io/docs/instrumenting/writing_exporters/
- OpenMetrics specification: https://prometheus.io/docs/specs/om/open_metrics_spec/ — informs anti-feature decision (defer OpenMetrics to v1.x)
- Prometheus best practices (BetterStack, ProMLabs) — label cardinality and counter type decisions
- Python sandboxing impossibility: CVE-2025-68668, CVE-2026-27952 — informs no-sandbox recommendation for community drivers

### Tertiary (LOW confidence)
- Before/After comparison patterns: Obkio, PingPlotter — general monitoring ecosystem patterns
- Histogram analysis pitfalls: general statistical presentation guidance

---
*Research completed: 2026-03-01*
*Ready for roadmap: yes*
