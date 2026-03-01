# Feature Research

**Domain:** DOCSIS cable modem monitoring tool — extensibility milestone
**Researched:** 2026-03-01
**Confidence:** HIGH (codebase reviewed directly; Prometheus format from official docs; patterns from monitoring ecosystem)

---

## Context

This research covers the six features in the active milestone, not a greenfield project. DOCSight has a mature codebase (743 tests, module system, 6 built-in drivers, community registry). The question is: what behavior does each feature need to meet user expectations, and where are the traps?

The six features:

1. Community-contributed modem drivers via module system (#131)
2. Non-DOCSIS modem/router support via GenericDriver (#129)
3. Daily modulation performance distribution (#92)
4. Before/After signal quality comparison (#50)
5. Prometheus-compatible /metrics endpoint (#59)
6. Modem restart detection via error counter reset (#60)

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume will "just work." Missing or broken = tool feels unfinished.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Prometheus /metrics endpoint returns valid text format | Anyone integrating with Grafana expects this to work first try. Wrong Content-Type or missing HELP/TYPE lines breaks scrapers silently. | LOW | Must return `Content-Type: text/plain; version=0.0.4`. Prometheus 3.0+ rejects missing Content-Type. Gauge for current readings, Counter with `_total` suffix for error counts. |
| /metrics endpoint requires authentication | DOCSight has auth on all other routes. Users assume consistency. Unprotected metrics = PII leak (ISP info, signal data). | LOW | Use existing `@require_auth` decorator. Same token/session as other API routes. |
| Modem restart detection emits an event | Users who see error counters drop to zero after a restart need an event in the journal. Without this, restarts are invisible and confuse historical data. | MEDIUM | Detect when cumulative error counter resets backward (new value < prev value by significant margin). Store as `modem_restart` event type. The current `_check_errors` in EventDetector only fires on spikes upward — restart detection is the symmetric case. |
| Modem restart detection suppresses false error spike | When a restart occurs, error counters drop to near-zero. The next poll delta will look like a huge negative. Without filtering, a restart triggers both a restart event AND a false "error recovered" event. | MEDIUM | Guard: if delta < 0 by more than threshold, emit `modem_restart`, skip `error_spike` check for that cycle. |
| GenericDriver works in demo/dev setup | Users without a supported modem (or on setup) need to run DOCSight. GenericDriver must produce valid analysis output that satisfies all existing consumers (MQTT, Prometheus, storage). | MEDIUM | Must implement the full `ModemDriver` ABC: `login()`, `get_docsis_data()`, `get_device_info()`, `get_connection_info()`. Return static or configurable stub data. |
| Community driver modules load without code changes to core | Users expect to drop a module folder and restart — no editing of `DRIVER_REGISTRY` in `app/drivers/__init__.py`. | HIGH | The module system does not currently expose a driver registration hook. Core change needed: `module_loader.py` must scan for `contributes.driver` and merge into `DRIVER_REGISTRY` at startup. |
| Driver module manifest declares driver key and class | Community driver authors need a defined, documented contract for what to put in `manifest.json`. Ambiguous format = broken community drivers. | LOW | Define: `"contributes": {"driver": "mydriver.py:MyDriverClass", "driver_key": "mymodem"}`. The `driver_key` is what users put in config (`modem_type: mymodem`). |

### Differentiators (Competitive Advantage)

Features that make DOCSight stand out. Not required by convention, but valued by the self-hoster audience.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Daily modulation distribution shows % time at each QAM tier | Users can see "my DS channels ran at 256QAM for 94% of the day, dropped to 64QAM for 6%" — directly actionable for ISP escalation. No other self-hosted modem tool does this. | HIGH | Computed from poll samples stored in `ds_channels_json`. Aggregate per channel per calendar day: count samples at each modulation. Computed server-side from existing snapshot data — no schema changes needed. Expose via new `/api/analysis/modulation-distribution` endpoint. |
| Before/After snapshot comparison for signal quality | Users who just had a tech visit, replaced a splitter, or got a new cable can formally verify improvement. Compares two snapshots (or date ranges) and shows delta for every metric. | MEDIUM | UI selects two reference points (snapshots or date ranges). Backend computes deltas: power, SNR, error counts, modulation. Return signed diff: `{metric, before, after, delta, improved: bool}`. Already have `get_snapshot()` and `get_daily_snapshot()` in storage — backend is low effort. UI work is the majority. |
| Prometheus metrics include per-channel labels | Grafana users want to alert on individual channels, not just averages. `docsis_ds_power_dbmv{channel="1"}` vs a single `docsis_ds_power_avg`. | MEDIUM | Labels: `channel_id`, `direction` (`ds`/`us`), `modulation`. Per-channel series enable Grafana alert rules on individual channel degradation. |
| Restart detection timestamp enables correlation | When users see a restart event in the journal and overlay it on signal charts, they can correlate outages to restarts. This is the "aha" moment for ISP escalation. | LOW | The existing event journal already stores timestamps and shows on correlation timeline. Just adding the right event type is sufficient — no new infrastructure. |
| Driver module type in registry enables discovery | Community can find "what modems are supported" via the existing module registry. The `"type": "driver"` classification in `registry.json` schema already supports this — just needs drivers to be contributed. | LOW | No code change. Registry schema already has `"type": "driver"`. The value is the ecosystem effect: once one community driver exists, others follow. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem reasonable but create more problems than they solve in this context.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| /metrics endpoint with OpenMetrics format (application/openmetrics-text) | Prometheus 3.0 prefers OpenMetrics. Users want to be forward-compatible. | OpenMetrics has stricter requirements (must end with `# EOF`, different counter semantics, `_created` timestamps). Implementing both content negotiation and OpenMetrics internals doubles complexity for marginal gain. Most Prometheus deployments still default to text format. | Implement standard text format (`text/plain; version=0.0.4`) first. It works with all Prometheus versions. Add OpenMetrics in a future milestone when adoption is higher. |
| Modem restart detection via ping/TCP probing | Users want to know "is the modem actually unreachable?" not just "did error counters reset?" | Adds a new network dependency, requires configuring probe targets, creates false positives on brief packet loss, adds latency to the poll cycle. DOCSight is a passive observer. | Detect via error counter reset (the reliable passive signal). The existing driver poll will naturally fail during a real outage and the notifier handles that. Keep restart detection passive. |
| GenericDriver that generates random/realistic fake data | Useful for demos. Users want to see "what would it look like with data." | Random data pollutes the database. Users forget to switch to a real driver. Historical data becomes meaningless. Confuses correlation (events vs. random noise). | GenericDriver returns static hardcoded values. Real demo mode (the existing `collectors/demo.py`) already handles this — GenericDriver is not a demo, it is an escape hatch for unsupported hardware. Keep them separate. |
| Auto-discover modem type from network scan | Users don't want to configure `modem_type` in settings. | Auto-discovery requires network probing (port scans, HTTP fingerprinting) which is slow, brittle, and raises security concerns in some network environments. Wrong detection = confusing errors. | Provide a "Detect" button in settings that tries each driver against the configured modem IP and reports which one succeeds. User-triggered, not automatic on startup. |
| Modulation distribution as a real-time chart (streaming) | Users want to watch modulation in real time. | The distribution is inherently a daily/period aggregate, not a real-time metric. Real-time modulation is already shown in the channel table. Streaming distribution adds server complexity for no additional insight. | Show distribution for completed days only. Add a "today so far" view as a separate, clearly labeled section. |
| Before/After comparison persists to database | Users want to save comparison results for later. | Comparisons are derived data computed from snapshots already in the database. Persisting them creates sync problems (source data deleted but comparison remains) and doubles storage. | Compute on demand from existing snapshots. No persistence needed. |

---

## Feature Dependencies

```
[Community Driver Modules]
    └── requires ──> [Module Loader driver registration hook] (core change)
    └── requires ──> [ModemDriver ABC] (already exists)
    └── uses ──────> [Community Module Registry] (already exists)

[GenericDriver]
    └── requires ──> [ModemDriver ABC] (already exists)
    └── requires ──> [driver key registered] (either in DRIVER_REGISTRY or via module hook)
    └── enables ───> [Prometheus /metrics] (needs at least one driver to produce data)
    └── enables ───> [Before/After Comparison] (lets users without real modem test the feature)

[Prometheus /metrics]
    └── requires ──> [snapshot data exists] (needs at least one poll cycle)
    └── uses ──────> [existing analysis summary] (no new data needed)
    └── enhanced by> [per-channel labels] (differentiator, optional)

[Modem Restart Detection]
    └── requires ──> [EventDetector._check_errors] (modify existing method)
    └── stores in ─> [existing events table] (no schema change)
    └── surfaces in> [correlation timeline] (already shows events)

[Daily Modulation Distribution]
    └── requires ──> [snapshots with ds_channels_json] (already stored)
    └── computes from> [existing snapshot storage] (no new data collection)
    └── exposes via ─> [new API endpoint] (new route, no schema change)

[Before/After Comparison]
    └── requires ──> [get_snapshot() / get_daily_snapshot()] (already exists)
    └── requires ──> [at least 2 snapshots at different times] (operational dependency)
    └── enhanced by> [Modem Restart Detection] (restart events become reference points)
```

### Dependency Notes

- **Community Driver Modules require module loader change:** The module system currently supports `routes`, `collector`, `publisher`, `settings`, `i18n`, `tab`, `card`, `static`, `thresholds`. Driver contribution is not wired. This is the highest-complexity prerequisite of the milestone.

- **GenericDriver enables testing other features:** Without a GenericDriver, developers without a supported modem cannot test the Prometheus endpoint or Before/After comparison in isolation. Build GenericDriver early in the milestone.

- **Modulation Distribution has no new storage dependency:** All required data (`ds_channels_json` per snapshot) is already stored. The feature is purely a query + aggregation. This is the lowest-risk feature in the milestone.

- **Modem Restart Detection is a modification, not an addition:** The `EventDetector._check_errors` method currently only handles positive spikes. Restart detection is the symmetric case. The change is small, but it must correctly suppress the false positive error-spike that would otherwise fire simultaneously.

- **Before/After Comparison is mostly UI work:** The backend query layer (`get_snapshot`, `get_daily_snapshot`, `get_range_data`) already exists. The new work is the comparison logic (delta computation) and the UI to select two reference points.

---

## MVP Definition

### Launch With (this milestone)

These features compose a coherent milestone — they are interdependent or user-requested in the same theme (extensibility + deeper analysis).

- [ ] **GenericDriver** — enables all other features to be tested without a real modem; unblocks developers contributing community drivers
- [ ] **Community Driver Modules** — the primary extensibility goal; requires the module loader hook
- [ ] **Modem Restart Detection** — small, high-value, low-risk; single EventDetector change + event type
- [ ] **Prometheus /metrics endpoint** — frequently requested; standard Prometheus text format, per-summary metrics + per-channel labeled metrics
- [ ] **Daily Modulation Distribution** — requires no new storage; pure query + aggregation
- [ ] **Before/After Signal Comparison** — primarily UI; backend query layer already exists

All six features are in scope. None can be safely deferred without breaking the milestone's coherence.

### Ordering Within Milestone

Recommended implementation order based on dependencies:

1. **GenericDriver** (unblocks testing everything else)
2. **Module Loader driver hook + Community Driver Modules** (core change; test with GenericDriver as first community driver)
3. **Modem Restart Detection** (isolated, self-contained EventDetector change)
4. **Prometheus /metrics endpoint** (read-only, no storage changes)
5. **Daily Modulation Distribution** (query-only, no schema changes)
6. **Before/After Signal Comparison** (depends on stable snapshot data; highest UI complexity)

### Add After Validation (v1.x)

- [ ] OpenMetrics format support (`application/openmetrics-text`) — trigger: when users report Prometheus 3.x compatibility issues
- [ ] "Detect modem type" button in Settings — trigger: when community reports confusion about `modem_type` config
- [ ] Modulation distribution trend (week-over-week) — trigger: when users ask "is it getting worse?"

### Future Consideration (v2+)

- [ ] Community segment heatmap (#61) — moonshot, requires multi-user data sharing infrastructure
- [ ] Peering quality check (#70) — moonshot, external dependency

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Prometheus /metrics endpoint | HIGH — Grafana integration unlocks for entire self-hoster audience | LOW — text format generation, existing data | P1 |
| Modem Restart Detection | HIGH — invisible gap today; confuses historical data | LOW — modify one method in EventDetector | P1 |
| GenericDriver | HIGH — unblocks testing + non-DOCSIS users | MEDIUM — implement full ModemDriver ABC, register in loader | P1 |
| Community Driver Modules | HIGH — core extensibility goal of milestone | HIGH — module loader hook is new infrastructure | P1 |
| Daily Modulation Distribution | MEDIUM — power users love it; casual users may not notice | MEDIUM — aggregation query + new API endpoint + chart | P2 |
| Before/After Signal Comparison | MEDIUM — ISP escalation use case; compelling but niche | MEDIUM — delta logic easy; UI for selecting reference points harder | P2 |

---

## Competitor Feature Analysis

No direct competitors exist for self-hosted DOCSIS monitoring at this feature depth. Closest reference points:

| Feature | MikroTik RouterOS | Grafana + Prometheus | Our Approach |
|---------|-------------------|----------------------|--------------|
| Plugin/driver extensibility | Built-in scripting, no community marketplace | Exporter ecosystem (hundreds of exporters) | Module system with verified community registry |
| Prometheus metrics | No native /metrics | Native (Prometheus is the product) | Add /metrics endpoint; Grafana users then get full dashboarding |
| Restart detection | Syslog events | Requires custom alerting rules | Automatic passive detection via error counter reset |
| Signal distribution analysis | Not applicable (not DOCSIS) | Possible via custom dashboards with raw data | First-class daily distribution with channel-level granularity |
| Before/After comparison | Manual (screenshot + compare) | Manual (pick time range in Grafana) | Explicit comparison UI with computed deltas |

DOCSight's advantage: deep DOCSIS domain knowledge + integrated experience. Grafana requires the user to know what they're looking at. DOCSight tells them.

---

## Sources

- DOCSight codebase: `app/drivers/base.py`, `app/drivers/__init__.py`, `app/event_detector.py`, `app/storage/snapshot.py`, `app/collectors/modem.py`, `app/modules/mqtt/publisher.py` — direct inspection
- DOCSight plan: `docs/plans/2026-02-28-community-module-registry.md` — module manifest format, contribution types, driver type in registry schema
- DOCSight PROJECT.md: `.planning/PROJECT.md` — requirements, constraints, key decisions
- Prometheus exposition format: [https://prometheus.io/docs/instrumenting/exposition_formats/](https://prometheus.io/docs/instrumenting/exposition_formats/) — MEDIUM confidence (official docs, current)
- Prometheus writing exporters: [https://prometheus.io/docs/instrumenting/writing_exporters/](https://prometheus.io/docs/instrumenting/writing_exporters/) — MEDIUM confidence (official docs)
- OpenMetrics spec: [https://prometheus.io/docs/specs/om/open_metrics_spec/](https://prometheus.io/docs/specs/om/open_metrics_spec/) — MEDIUM confidence (official docs, informs anti-feature decision)
- DOCSIS signal analysis: [https://www.howtogeek.com/240575/how-to-read-your-cable-modems-diagnostic-page-when-something-goes-wrong/](https://www.howtogeek.com/240575/how-to-read-your-cable-modems-diagnostic-page-when-something-goes-wrong/) — LOW confidence (community, supports domain understanding)
- Before/After comparison patterns: Obkio, PingPlotter (WebSearch) — LOW confidence (monitoring ecosystem patterns)

---

*Feature research for: DOCSight — extensibility + analysis milestone*
*Researched: 2026-03-01*
