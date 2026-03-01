# Pitfalls Research

**Domain:** DOCSIS monitoring tool — plugin extensibility, signal analysis, metrics export, restart detection
**Researched:** 2026-03-01
**Confidence:** HIGH (codebase read directly; external patterns verified via web search)

---

## Critical Pitfalls

### Pitfall 1: Community Driver Module Executes Arbitrary Python With Full Process Privileges

**What goes wrong:**
A community-contributed modem driver is a Python module loaded via `importlib.util.spec_from_file_location` and executed directly in the DOCSight process. There is no sandbox, no process isolation, and no capability restriction. A malicious or buggy driver can read `/data/docsis_history.db`, write to the filesystem, make network requests to arbitrary hosts, or crash the entire process — including the web server thread.

**Why it happens:**
The existing module system was designed for trusted built-in modules (weather, MQTT, BQM) where the author is the project maintainer. The security model was appropriate for that scope. When extended to community-contributed drivers, the same trust model is silently applied to untrusted code. The `validate_manifest` function checks schema conformance but cannot inspect Python logic. The theme security exception (themes must not contribute `collector`, `routes`, `publisher`) shows awareness of this risk, but no equivalent guard exists for driver modules.

**How to avoid:**
- Add a mandatory warning in the driver contribution docs: "Driver modules run with full process privileges — review code before installing."
- Consider a `driver` type distinction in the manifest `type` field (currently `VALID_TYPES = {"driver", "integration", "analysis", "theme"}` — `driver` is already defined but not yet distinguished in security checks).
- At minimum, enforce that driver modules can only contribute `driver` — not `routes`, `collector`, or `publisher` — to limit surface area.
- Document clearly: no sandboxing is provided. Users who install community drivers accept the risk.
- Do NOT attempt Python-level sandboxing (RestrictedPython, etc.) — it is fragile and routinely bypassed (ref: CVE-2025-68668, CVE-2026-27952).

**Warning signs:**
- A community driver manifest declares `contributes.routes` or `contributes.publisher` alongside `contributes.driver`.
- A driver module imports `subprocess`, `socket`, or other network/system modules in unexpected ways.
- Users report unexpected network traffic or filesystem changes after installing a community driver.

**Phase to address:** Driver extensibility phase (community drivers via module system)

---

### Pitfall 2: GenericDriver Returns Empty Fields That Break Downstream Analysis

**What goes wrong:**
`analyzer.analyze()` is written assuming DOCSIS data with populated channels. The `get_docsis_data()` contract on `ModemDriver` returns a `dict`, but the GenericDriver (non-DOCSIS modem/router) has nothing meaningful to put in `downstream` or `upstream` channels. If it returns `{"downstream": [], "upstream": []}`, the analyzer produces a snapshot with `ds_total: 0`, zero power/SNR, health is computed as `"good"` (no channels = no issues = pass), and the event detector sees a perpetual clean signal.

Downstream consequences:
- `EventDetector._check_modulation()` iterates channel IDs — empty lists, no crash, but also no meaningful events.
- `ModemCollector` stores every empty snapshot. After 7 days, the history database contains thousands of empty-channel snapshots.
- Before/After comparison (#50) selects snapshots and finds nothing to compare.
- Prometheus metrics endpoint (#59) exposes `docsight_ds_channel_count 0` which looks like a misconfigured modem.

**Why it happens:**
The abstract base class `get_docsis_data()` says "Retrieve raw DOCSIS channel data" — it is undefined what a non-DOCSIS device should return. Developers building GenericDriver will be tempted to return empty lists to avoid crashes, which is technically correct but semantically wrong.

**How to avoid:**
- Define an explicit contract for GenericDriver in the docstring: what fields must be present, what fields are optional, and what to return when a field is not applicable (e.g., `None` vs. empty list vs. absent key).
- In `analyzer.analyze()`, add a guard: if both `downstream` and `upstream` are empty lists AND the source is a GenericDriver, set `summary.health = "unknown"` (not `"good"`), and add a `health_issues` entry like `["no_docsis_channels"]`.
- The health badge on the dashboard must distinguish `"unknown"` from `"good"` — a separate badge state, not silence.

**Warning signs:**
- Dashboard shows green health with zero DS/US channel count.
- `get_daily_snapshot()` returns data but all power/SNR fields are zero.
- Modulation distribution analysis shows 100% of samples in a single "none" bucket.

**Phase to address:** GenericDriver phase

---

### Pitfall 3: Modem Restart Detection Triggers False Positives on Cumulative Counter Wrap

**What goes wrong:**
DOCSIS error counters (`corrErrors`, `nonCorrErrors`) are cumulative integers that increment since last modem boot. The restart detection logic (#60) would look for a large negative delta (current - previous < 0, or current << previous) as evidence of a reset. The trap: these counters are 32-bit unsigned integers on most modem firmware. They wrap at 4,294,967,295. A modem that has been running for weeks with heavy noise will wrap this counter, producing `current < previous` even with no restart. This fires a false restart event.

A secondary trap: the delta-based `_check_errors()` in `EventDetector` already uses `delta > UNCORR_SPIKE_THRESHOLD` (1000) — this correctly handles increases. Restart detection will need to go the other direction, and the wrap ambiguity is the critical edge case.

**Why it happens:**
Modem firmware documentation for consumer devices is sparse. Developers assume counters are monotonic indefinitely. The existing `_check_errors()` only looks upward (spikes), so the wrap case was never encountered. Restart detection requires looking downward for the first time.

**How to avoid:**
- Treat any delta where `current < previous` AND `previous - current > threshold` (e.g., > 100,000) as ambiguous: it could be a restart OR a counter wrap.
- Use a multi-signal heuristic: restart is confirmed when (1) error counters reset AND (2) channel count changes, OR (3) power levels jump by > 5 dBmV simultaneously. A restart typically causes the modem to re-acquire all channels, which leaves a visible signature across multiple metrics simultaneously.
- Store the previous raw counter values per-poll in the event detector's `_prev` state. Never compute restart probability from a single counter alone.
- Test against a simulated wrap: a test fixture that sends `prev=4_294_967_200, current=5_000` must produce `"ambiguous"` or `"counter_wrap"`, not `"restart_detected"`.

**Warning signs:**
- False restart events appear in the event log with no corresponding health change.
- Restart events fire during periods when the dashboard shows stable signal quality.
- Counter wrap can happen on noisy lines that accumulate many millions of error codewords per day.

**Phase to address:** Modem restart detection phase

---

### Pitfall 4: Modulation Distribution Analysis Double-Counts Snapshots Within the Same Day

**What goes wrong:**
The daily modulation distribution feature (#92) aggregates modulation observations per channel across a 24-hour period. The storage layer in `get_intraday_data()` returns all snapshots for a day — at default 60s poll interval, that is ~1440 snapshots per day. If the distribution is computed naively (count occurrences of each modulation string across all snapshots), the result is heavily weighted toward the most common stable state (256QAM for 23.5 hours) and completely obscures brief degradations (64QAM for 30 minutes = ~30 out of 1440 samples = 2%). This is accurate as a percentage but visually misleading when shown as a bar chart where the dominant bar fills the screen.

A related trap: if poll interval is user-configurable (currently it is), the same 30-minute degradation produces 30 samples at 60s or 180 samples at 10s. The distribution's "shape" changes based on a configuration value, not based on the signal behavior.

**Why it happens:**
Project context confirms the decision: "compute from poll samples, not inferred time ranges — avoids misleading data." This is the right call but introduces the presentation problem. The trap is presenting raw counts rather than time-weighted percentages or duration-in-state.

**How to avoid:**
- Always display modulation distribution as **percentage of poll samples** (the current decision is correct), not raw counts.
- Add a "total duration in state" annotation alongside the percentage: "256QAM: 96.0% (23h 2m), 64QAM: 4.0% (58m)" — this makes small degradations visible in wall-clock terms.
- Normalize: if the distribution is showing proportions, the UI must be clear that the baseline changes with poll interval. If poll interval is 10s, 2% = 2.4 minutes; if 60s, 2% = 14.4 minutes.
- Do not infer duration from count x poll_interval without validating that snapshots are actually that far apart (gaps occur during modem outages, collector failures).

**Warning signs:**
- The distribution chart shows a single bar at 99%+ for 256QAM, making it look like there are no problems even when the journal logs show user complaints.
- The percentages change significantly when a user changes poll interval without any real signal change.

**Phase to address:** Daily modulation distribution phase

---

### Pitfall 5: Before/After Comparison Uses Wrong Snapshot Pair — Silent Temporal Misalignment

**What goes wrong:**
Before/After comparison (#50) asks users to select two points in time to compare signal quality. The actual snapshot used for each point is determined by `get_closest_snapshot()` which finds the nearest snapshot within a 2-hour window. If the user selects "before: Monday 6:00 AM" and "after: Monday 7:00 AM", but the modem was offline from 5:45 AM to 7:30 AM (causing a gap in snapshots), the "before" snapshot resolves to Sunday 9:58 PM and "after" resolves to Monday 7:31 AM. The comparison looks valid but compares night signal quality with morning quality, not the intended window.

A more subtle version: the user intends to compare before/after a technician visit on a specific day. The closest snapshot may be from before the technician arrived (no snapshot during the visit since modem was offline) and after (the first snapshot after service restoration). This is actually the correct pair — but the timestamp display must make this explicit, not hide it behind rounded times.

**Why it happens:**
`get_closest_snapshot()` is designed for "show me the state at approximately this time" — it is fine for trend views. For before/after comparison, the user has a specific semantic intent that is not captured by proximity search alone.

**How to avoid:**
- The comparison UI must always display the **actual timestamps** of the resolved snapshots, not the user-selected input times.
- Add a warning badge if the resolved snapshot is more than 30 minutes from the requested time: "Closest snapshot found was X minutes from your selected time."
- If no snapshot exists within the 2-hour window, return an explicit error — do not silently expand the window.
- Do not allow the "before" snapshot to be newer than the "after" snapshot after resolution (validate after resolving both).

**Warning signs:**
- A comparison shows power levels that are consistent with nighttime patterns when the user expects daytime readings.
- The "before" snapshot timestamp is later in the day than the "after" snapshot.
- Comparisons across modem restart events show dramatic apparent improvement that is actually modem re-registration.

**Phase to address:** Before/After comparison phase

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Return `{}` from GenericDriver `get_docsis_data()` | Quick unblock, no crash | Produces `"good"` health for non-DOCSIS devices indefinitely; corrupts history | Never — define explicit empty-channel contract instead |
| Use per-channel-ID as Prometheus label value | Easy to implement, granular data | If modem reassigns channel IDs after restart (common), Prometheus accumulates stale time series | Never for channel ID; use channel frequency as stable identifier instead |
| Detect restarts only via error counter delta | Simple, single-signal | False positives on counter wrap; false negatives when modem restarts cleanly | Never alone — always use multi-signal heuristic |
| Compute modulation distribution in the route handler at request time | No pre-computation needed | At 60s poll, 7-day history = ~10,000 snapshots x N channels; slow for large datasets | MVP only — move to background computation if datasets grow |
| Skip `minAppVersion` validation for driver modules | Faster community contribution | A driver written for a future API may be loaded into an older app version, crashing on missing methods | Never — validate on load, fail gracefully |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Prometheus `/metrics` endpoint | Exposing raw channel IDs as label values (`channel_id="42"`) — channel IDs reassign after modem restart, creating phantom stale series in Prometheus | Use channel frequency (MHz) as the stable channel identifier label; add a `direction` label (ds/us) |
| Prometheus `/metrics` endpoint | Exposing error counter raw values as gauges — they reset on modem restart, so Prometheus sees a negative delta and marks them as broken | Expose error counters as `Counter` type (monotonic) but document that modem restart causes a reset; or expose as gauge with explicit `modem_restart_total` counter alongside |
| Community driver via module system | A driver manifest declares `contributes.routes` to add a configuration page — this is legitimate but bypasses the collector lifecycle, creating confusion about where driver state lives | Define whether driver modules are permitted to contribute routes; if yes, document the lifecycle contract explicitly |
| GenericDriver with MQTT/Home Assistant | GenericDriver returns empty channels; analyzer returns `health: "good"`; MQTT publishes `good` to Home Assistant; HA shows green for a device that has no real monitoring | Add a `monitoring_mode` field to the MQTT payload: `"docsis"` or `"generic"` so downstream systems can distinguish |
| Before/After comparison with snapshot storage | `get_closest_snapshot()` has a 2-hour window; if user selects timestamps far from any snapshot, the function returns `None` but the UI may not handle `None` gracefully | Always validate both timestamps resolve to non-None before building the comparison response |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Computing modulation distribution per-request by scanning all intraday snapshots | Response latency spikes on the distribution endpoint; SQLite busy errors when collector is also writing | Pre-aggregate daily distributions in a background step or cache the result per date | With 7-day history at 60s poll, ~10,000 snapshots — noticeable at > 30 channels |
| Prometheus `/metrics` endpoint holds open a SQLite connection for the full scrape duration | Modem poll collector sees SQLite lock contention; `save_snapshot` fails silently | Use short-lived connections (context managers), never hold connection across yield; DOCSight already does this correctly — maintain the pattern | Any concurrent scrape + poll cycle, typically visible at > 5s scrape intervals |
| Using modulation as a Prometheus label value | Cardinality: 32 DS channels x 8 possible modulation values = 256 time series per metric; this is fine. But adding channel_type, docsis_version, frequency cross-product causes explosion | Keep labels to: `direction`, `channel_id` (or frequency), `docsis_version` — no more than 3 labels per metric | Cardinality exceeding ~10,000 unique time series degrades Prometheus performance |
| Before/After comparison scanning full channel JSON for both snapshots | Each snapshot is up to 32 DS + 8 US channel objects serialized to JSON; comparing two snapshots requires two deserializations | Acceptable at current scale — SQLite + JSON deserialization for 2 rows is fast; do not pre-optimize | Only relevant if Before/After is extended to compare N snapshots over a range |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Community driver module allowed to contribute `routes` without review | Driver registers a route that leaks config secrets (`modem_user`, `modem_password`, MQTT credentials) from `ConfigManager` | Add a manifest validation rule: community driver modules (non-builtin) may not contribute `routes` without explicit allowlisting; or accept the risk and document it clearly |
| Prometheus `/metrics` endpoint exposed without authentication | Anyone on the local network who can reach port 8765 can scrape modem signal data and connection info — low severity for a homelab tool but worth noting | The existing auth system (if enabled) should protect `/metrics` the same as any other route; do not exempt it from middleware |
| Community driver module reads `config.json` directly from `/data/` | Exposes all credentials stored in the config file to a potentially malicious module | This is an inherent risk of the in-process model; document it, do not pretend it is solved |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Modulation distribution shows only percentages with no wall-clock duration | User sees "64QAM: 3.2%" and does not know if this was 5 minutes or 5 hours of degradation | Show both: percentage AND equivalent duration in hours/minutes |
| Before/After comparison resolves to wrong snapshots silently | User draws wrong conclusions about whether a technician visit improved their signal | Always show resolved timestamps prominently; add a warning badge if resolution differed by > 30 minutes from selection |
| Prometheus `/metrics` endpoint returns non-zero status code when modem is unreachable | Grafana stops scraping; alerting fires on scrape failure rather than signal degradation | Return valid metrics with a `docsight_up 0` gauge when modem is unreachable; never return HTTP 5xx from `/metrics` |
| GenericDriver health badge shows "good" for unsupported device | Users think the tool is monitoring their device when it is not | Show a distinct "unsupported" or "generic mode" badge that is visually different from "good" |
| Restart detection events appear for counter wraps | Users get alert fatigue from false restart events; start ignoring all events | Use multi-signal heuristic and confidence scoring; only emit restart event when high confidence |

---

## "Looks Done But Isn't" Checklist

- [ ] **Community driver loading:** Often missing test that verifies a driver module with malformed `get_docsis_data()` return format does not crash the collector — verify with a fixture driver that returns incomplete data
- [ ] **GenericDriver health assessment:** Often missing the `health: "unknown"` state — verify the dashboard renders an "unknown" badge state before calling GenericDriver complete
- [ ] **Prometheus `/metrics` endpoint:** Often missing scrape validation — run `curl -H "Accept: text/plain" /metrics | promtool check metrics` to verify format is valid before shipping
- [ ] **Modem restart detection:** Often missing counter wrap test — verify that counter values near integer max rolling over to a small positive number does not produce a false restart event
- [ ] **Before/After comparison:** Often missing the timestamp display of resolved (not requested) snapshots — verify the UI shows actual snapshot timestamps, not the user's input
- [ ] **Modulation distribution:** Often missing the duration annotation alongside percentage — verify both are shown
- [ ] **Driver via module system:** Often missing `minAppVersion` enforcement for driver type — verify loading a driver that requires a future app version fails gracefully rather than crashing

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Malicious community driver caused process crash | LOW | Identify the driver from logs, remove from `/modules/`, restart container. No data corruption if crash was in driver thread (collector lock is released on exception). |
| False restart events flooded the event log | LOW | Add a filter for `event_type = "modem_restart"` — delete events by type via the events API or direct SQLite query |
| GenericDriver produced thousands of empty-channel snapshots in history | MEDIUM | The cleanup mechanism respects `history_days`; wait for natural expiry, or truncate `snapshots` table for the affected date range |
| Wrong Prometheus labels caused cardinality explosion in Grafana/Prometheus | MEDIUM | Rename metrics (new metric name), add a `docsight_metrics_version` label, and prune old series in Prometheus via `admin/tsdb/delete_series` API |
| Before/After UI stored comparison bookmarks using input timestamps instead of resolved timestamps | HIGH | Bookmarked comparisons will resolve differently after storage format fix; old bookmarks are semantically ambiguous and should be invalidated |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Community driver arbitrary code execution | Driver extensibility phase | Code review checklist for PR template; manifest validation test for community driver with routes rejected |
| GenericDriver empty data breaks analysis | GenericDriver phase | Test: `analyze({"downstream": [], "upstream": []})` returns `health: "unknown"`, not `"good"` |
| Error counter wrap triggers false restart event | Modem restart detection phase | Test fixture with wrap-around values; multi-signal heuristic implemented and tested |
| Modulation distribution misleads without duration | Daily modulation distribution phase | UI review: distribution view shows both percentage and duration; tested with simulated degradation data |
| Before/After resolves wrong snapshots silently | Before/After comparison phase | Integration test: request timestamp with no nearby snapshot returns error; resolved timestamps visible in API response |
| Prometheus cardinality via bad label choice | Prometheus endpoint phase | Run `promtool check metrics` on output; count unique time series: DS channels (max 32) x labels (<=3) should stay below 200 total series |
| GenericDriver health shows "good" when no DOCSIS data | GenericDriver phase | Manual test: configure GenericDriver, verify dashboard shows "generic mode" badge, not green "good" |

---

## Sources

- DOCSight codebase: `app/drivers/base.py`, `app/drivers/__init__.py`, `app/module_loader.py`, `app/event_detector.py`, `app/analyzer.py`, `app/storage/snapshot.py`, `app/collectors/modem.py` (direct read, HIGH confidence)
- Prometheus exposition format best practices: [Prometheus Best Practices: 8 Dos and Don'ts](https://betterstack.com/community/guides/monitoring/prometheus-best-practices/) (MEDIUM confidence)
- Prometheus cardinality explosion: [How to Manage High Cardinality Metrics in Prometheus](https://last9.io/blog/how-to-manage-high-cardinality-metrics-in-prometheus/) (MEDIUM confidence)
- ProMLabs common mistakes: [Avoid These 6 Mistakes When Getting Started With Prometheus](https://promlabs.com/blog/2022/12/11/avoid-these-6-mistakes-when-getting-started-with-prometheus/) (MEDIUM confidence)
- Python sandboxing impossibility: [The Glass Sandbox - The Complexity of Python Sandboxing](https://checkmarx.com/zero-post/glass-sandbox-complexity-of-python-sandboxing/) (MEDIUM confidence)
- Python sandbox CVEs: [CVE-2025-68668: n8n Python Code Node](https://socradar.io/blog/cve-2025-68668-n8n-python-code-node/) (MEDIUM confidence)
- Histogram analysis pitfalls: [Use Histograms with Caution](https://blog.dailydoseofds.com/p/use-histograms-with-caution) (LOW confidence — general, not domain-specific)
- OpenMetrics specification: [OpenMetrics 1.0](https://prometheus.io/docs/specs/om/open_metrics_spec/) (HIGH confidence — official Prometheus docs)

---
*Pitfalls research for: DOCSight — monitoring tool extensibility milestone*
*Researched: 2026-03-01*
