# Synthetic dashboard trend benchmark

Run this script from the changed checkout with its Python environment, passing
any baseline and changed source directories. It imports each source in a fresh
subprocess and runs that source's production `create_app`, runtime, storage,
routes, templates and frontend on a real loopback HTTP server with **four
Waitress threads**. Install the repository's hashed Python requirements plus
`pytest-playwright==0.7.2 playwright==1.58.0`, then install Chromium with
`python -m playwright install chromium`.

```sh
.venv/bin/python scripts/benchmark_dashboard_trends.py \
  --repo /path/to/baseline --repo /path/to/changed \
  --seed-dir /tmp/docsight-signal-synthetic \
  --output /tmp/dashboard-trends-comparison.json \
  --runs 5 --browser-runs 3 --parallel 4 --modules both
```

Supply any baseline with `--repo`; no fixed commit is assumed. The seed directory is created only when absent. Existing inputs require
the synthetic marker and matching database SHA-256 hashes. Never point it at a
user data directory. Every measurement copies the same input databases into a
new temporary directory, including fresh config/session state. No collectors
are constructed or started; update checking is disabled, integration settings
are not inherited, community module search paths are empty, and outbound socket
connections are blocked. Browser requests outside the loopback server are
blocked and reported. API data is never mocked or replaced.

The default seed has 92 days at five-minute intervals (26,496 snapshots), exactly
288 visible snapshots, eight recent speedtests and 34,560 Connection Monitor
samples for two synthetic targets. Shipped synthetic channel definitions pass
through the real analyzer and cumulative-baseline builder, producing realistic
`signal_families`, `error_baseline` and `error_counter_coverage` objects. Their
sizes and database hashes are recorded. `--days` changes the history length for
scaling probes. Fixed rolling-window clocks in `app.tz`, the trend blueprint and
the browser keep the identical 288 snapshots visible even in later comparisons.
Performance clocks are real. The Connection Monitor card's separate live summary
uses real time; its rolling trend window uses the fixed API clock.

`--modules both` measures enabled built-ins and an app without module registration
or the optional Connection Monitor database. The shared snapshot database still
contains speedtest tables in both cases: this preserves the generic API's
existing behavior even when no speedtest module card is registered.

Each stage records an ordinary first run separately from the warm repetitions.
This is **not a controlled cold OS/SQLite-cache benchmark**. Warm medians, minima,
maxima and standard deviations accompany raw runs. Measurements include:

- Storage calls, HTTP API times, decoded payload bytes and row counts.
- Concurrent dashboard API cycles: baseline's two actual legacy requests run in
  parallel; updated cycles request signals then the retained legacy API. All
  requests contend for the same four Waitress threads. Raw critical, legacy and
  total times remain separate.
- Real Chromium full-page loads, original or updated frontend from each repo,
  DOM/load completion, completion of all resource requests, request counts,
  decoded and transferred bytes, trend request start/TTFB/duration and payload.
- First actual Hero curve rendering: a probe observes real uPlot draws and
  checks opaque signal-colored pixels inside the plotting area, requiring at
  least two real data values. Blank canvases, axes and translucent fills do not
  qualify. The next animation-frame callback records the completed draw's paint
  opportunity; this is a browser rendering milestone, not physical display
  scanout. The probe also reports curve point/pixel counts and active charts.
- Parallel real browser navigations with the frontend's actual requests,
  including legacy work, against the same server.

Chromium uses a 1440×1000 viewport, UTC, blocked service workers and disabled HTTP
cache (Playwright request interception). There is no proxy or compression. The
report records Python, platform and Chromium versions. Use an otherwise idle
machine for comparison; do not run tests at the same time as authoritative
measurements. A local smoke run validates the harness, not production latency.
Failures (including no detected curve) fail the command; inspect page errors and
blocked outbound requests before interpreting timings. There are no hardware
timing assertions in CI. Signal API <100 ms warm median / <50 kB at 288 points
and query-to-curve <1 s are evaluation targets, not asserted results. The retained
legacy request is still expensive and its total/parallel overhead is not fixed
by the compact route.
