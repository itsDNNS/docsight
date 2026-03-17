# Traceroute Burst Capture Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add event-triggered and manual traceroute capture to DOCSight's Connection Monitor module, providing hop-level network path evidence when outages or packet loss occur.

**Architecture:** Extends the existing Connection Monitor module with a new C helper binary (`docsight-traceroute-helper`), a Python wrapper (`TracerouteProbe`), a trigger system (`TracerouteTrigger`) that reacts to existing CM events, and new API endpoints + UI for manual traces and trace history. Data stored in same `connection_monitor.db` via new tables.

**Tech Stack:** C (setuid helper), Python 3.12 (Flask, SQLite, subprocess, ThreadPoolExecutor), pytest, Docker multi-stage build.

**Spec:** `docs/superpowers/specs/2026-03-17-traceroute-burst-capture-design.md`

**Branch:** `feat/196-traceroute-burst-capture` (from `main`)

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `tools/traceroute_helper.c` | Setuid C binary — sends ICMP with incrementing TTL, outputs hop data |
| `app/modules/connection_monitor/traceroute_probe.py` | Python wrapper — runs helper via subprocess, parses output, reverse DNS |
| `app/modules/connection_monitor/traceroute_trigger.py` | Event listener — cooldown logic, async execution, storage save |
| `tests/modules/connection_monitor/test_traceroute_probe.py` | Unit tests for probe wrapper |
| `tests/modules/connection_monitor/test_traceroute_trigger.py` | Unit tests for trigger logic |
| `tests/modules/connection_monitor/test_traceroute_storage.py` | Unit tests for trace storage methods |
| `tests/modules/connection_monitor/test_traceroute_routes.py` | Unit tests for trace API endpoints |

### Modified Files

| File | Changes |
|------|---------|
| `app/modules/connection_monitor/storage.py` | Add trace tables, CRUD, cleanup, purge_demo |
| `app/modules/connection_monitor/collector.py` | Wire TracerouteTrigger in __init__, _check_events, cleanup, stop() |
| `app/modules/connection_monitor/routes.py` | Add traceroute endpoints (POST manual, GET traces, GET trace detail) |
| `app/main.py:295-304` | Add collector stop() calls in finally block |
| `Dockerfile:13-15,24` | Add traceroute helper compile + install |
| `app/modules/connection_monitor/i18n/en.json` | Traceroute i18n keys |
| `app/modules/connection_monitor/i18n/de.json` | Traceroute i18n keys |
| `app/modules/connection_monitor/i18n/fr.json` | Traceroute i18n keys |
| `app/modules/connection_monitor/i18n/es.json` | Traceroute i18n keys |
| `app/modules/connection_monitor/templates/connection_monitor_detail.html` | Trace history table + Run Traceroute button |
| `app/collectors/demo.py` | Demo trace seeder |

---

## Chunk 1: C Helper Binary + Dockerfile

### Task 1: Write traceroute helper C source

**Files:**
- Create: `tools/traceroute_helper.c`

- [ ] **Step 1: Create the C source file**

Write `tools/traceroute_helper.c`. The helper:
- Creates raw ICMP socket, immediately drops privileges via `seteuid(getuid())`
- Sends ICMP Echo Request with TTL=1..max_hops (default 30)
- 3 probes per hop, reports lowest latency + response count
- Outputs tab-separated: `hop_index\thop_ip\tlatency_ms\tprobes_responded`
- `fflush(stdout)` after each hop line (required for partial results on Python timeout)
- Timeout hops: `hop_index\t*\t-1\t0`
- `--check` flag for capability verification
- Exit codes: 0 = target reached, 1 = max hops, 2 = error

Key implementation details:
- Use `setsockopt(sock, IPPROTO_IP, IP_TTL, &ttl, sizeof(ttl))` per hop
- Parse ICMP Time Exceeded (type 11) for intermediate hops
- Parse ICMP Echo Reply (type 0) for target reached
- Fixed 32-byte payload, 2-second default timeout per probe
- No dynamic allocation after init — fixed-size buffers

Reference: `tools/icmp_probe_helper.c` (192 lines) for socket setup and ICMP checksum patterns.

- [ ] **Step 2: Verify it compiles locally**

Run: `gcc -O2 -Wall -Werror -o /tmp/docsight-traceroute-helper tools/traceroute_helper.c`
Expected: Clean compile, no warnings.

- [ ] **Step 3: Test --check flag**

Run: `sudo /tmp/docsight-traceroute-helper --check`
Expected: Exit code 0.

- [ ] **Step 4: Test basic traceroute to localhost**

Run: `sudo /tmp/docsight-traceroute-helper 127.0.0.1 5 2000`
Expected: Single hop line `1\t127.0.0.1\t<latency>\t3`, exit code 0.

- [ ] **Step 5: Test traceroute to external host**

Run: `sudo /tmp/docsight-traceroute-helper 1.1.1.1 30 2000`
Expected: Multiple hop lines with incrementing hop_index, final hop is 1.1.1.1, exit code 0. Verify `fflush` works by observing lines appear progressively (not all at once).

- [ ] **Step 6: Commit**

```bash
git add tools/traceroute_helper.c
git commit -m "feat(cm): add traceroute helper C binary (#196)"
```

### Task 2: Add traceroute helper to Dockerfile

**Files:**
- Modify: `Dockerfile:13-15` (builder stage), `Dockerfile:24` (runtime install)

- [ ] **Step 1: Add compile step to builder stage**

After the existing ICMP helper compile (line 15), add:
```dockerfile
COPY tools/traceroute_helper.c /build/traceroute_helper.c
RUN gcc -O2 -Wall -o /build/out/docsight-traceroute-helper /build/traceroute_helper.c
```

- [ ] **Step 2: Add install step to runtime stage**

After the existing ICMP helper COPY (line 24), add:
```dockerfile
COPY --from=builder /build/out/docsight-traceroute-helper /usr/local/bin/docsight-traceroute-helper
RUN chmod 4755 /usr/local/bin/docsight-traceroute-helper
```

- [ ] **Step 3: Verify Docker build succeeds**

Run: `cd ~/Projects/docsight && docker compose -f docker-compose.dev.yml build`
Expected: Build succeeds, both helpers compiled and installed.

- [ ] **Step 4: Verify helper works inside container**

Run: `docker compose -f docker-compose.dev.yml run --rm docsight docsight-traceroute-helper --check`
Expected: Exit code 0.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile
git commit -m "build: add traceroute helper to Docker build (#196)"
```

---

## Chunk 2: Python Wrapper (TracerouteProbe)

### Task 3: Write TracerouteProbe tests

**Files:**
- Create: `tests/modules/connection_monitor/test_traceroute_probe.py`

- [ ] **Step 1: Write test file with core test cases**

Tests to write (all mock `subprocess.run`):
- `test_parse_successful_trace` — normal output with 3 hops reaching target
- `test_parse_timeout_hops` — output with `*` timeout hops mixed in
- `test_parse_partial_probes` — hops with probes_responded < 3
- `test_target_not_reached` — max hops exceeded, exit code 1
- `test_helper_error` — exit code 2, returns empty result
- `test_helper_not_found` — FileNotFoundError, returns empty result
- `test_timeout_partial_results` — subprocess.TimeoutExpired with partial stdout
- `test_route_fingerprint` — verify SHA256 with `*` sentinel for timeout hops
- `test_reverse_dns_parallel` — mock socket.gethostbyaddr, verify parallel execution
- `test_reverse_dns_timeout` — DNS lookup times out, hop_host is None

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/docsight && python -m pytest tests/modules/connection_monitor/test_traceroute_probe.py -v`
Expected: All tests FAIL (TracerouteProbe not yet implemented).

- [ ] **Step 3: Commit test file**

```bash
git add tests/modules/connection_monitor/test_traceroute_probe.py
git commit -m "test(cm): add TracerouteProbe unit tests (#196)"
```

### Task 4: Implement TracerouteProbe

**Files:**
- Create: `app/modules/connection_monitor/traceroute_probe.py`

- [ ] **Step 1: Write the dataclasses and TracerouteProbe class**

```python
from dataclasses import dataclass
import hashlib
import logging
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger("docsis.traceroute")

HELPER_PATH = "/usr/local/bin/docsight-traceroute-helper"

@dataclass
class TracerouteHop:
    hop_index: int
    hop_ip: str | None
    hop_host: str | None
    latency_ms: float | None
    probes_responded: int

@dataclass
class TracerouteResult:
    hops: list[TracerouteHop]
    reached_target: bool
    route_fingerprint: str

class TracerouteProbe:
    TOTAL_TIMEOUT_S = 30

    def check(self) -> bool:
        """Return True if helper binary is available and functional."""
        try:
            r = subprocess.run(
                [HELPER_PATH, "--check"],
                capture_output=True, timeout=5,
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def run(self, host: str, max_hops: int = 30, timeout_ms: int = 2000) -> TracerouteResult:
        """Run traceroute and return result. Returns partial results on timeout."""
        try:
            result = subprocess.run(
                [HELPER_PATH, host, str(max_hops), str(timeout_ms)],
                capture_output=True, text=True, timeout=self.TOTAL_TIMEOUT_S,
            )
            stdout = result.stdout
            reached = result.returncode == 0
        except subprocess.TimeoutExpired as e:
            stdout = e.stdout or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            reached = False
            log.warning("Traceroute to %s timed out after %ds", host, self.TOTAL_TIMEOUT_S)
        except FileNotFoundError:
            log.error("Traceroute helper not found at %s", HELPER_PATH)
            return TracerouteResult(hops=[], reached_target=False, route_fingerprint="")
        except Exception as e:
            log.error("Traceroute failed: %s", e)
            return TracerouteResult(hops=[], reached_target=False, route_fingerprint="")

        hops = self._parse_output(stdout)
        hops = self._resolve_dns(hops)
        fingerprint = self._compute_fingerprint(hops)
        return TracerouteResult(hops=hops, reached_target=reached, route_fingerprint=fingerprint)

    def _parse_output(self, stdout: str) -> list[TracerouteHop]:
        hops = []
        for line in stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            hop_index = int(parts[0])
            hop_ip = None if parts[1] == "*" else parts[1]
            latency_ms = None if parts[2] == "-1" else float(parts[2])
            probes_responded = int(parts[3])
            hops.append(TracerouteHop(
                hop_index=hop_index, hop_ip=hop_ip, hop_host=None,
                latency_ms=latency_ms, probes_responded=probes_responded,
            ))
        return hops

    DNS_TIMEOUT_S = 3.0  # Hard budget for entire DNS enrichment phase

    def _resolve_dns(self, hops: list[TracerouteHop]) -> list[TracerouteHop]:
        ips_to_resolve = {h.hop_ip for h in hops if h.hop_ip}
        if not ips_to_resolve:
            return hops
        dns_map: dict[str, str | None] = {}
        def _lookup(ip: str) -> tuple[str, str | None]:
            try:
                host, _, _ = socket.gethostbyaddr(ip)
                return ip, host
            except (socket.herror, socket.gaierror, OSError):
                return ip, None
        # Contract: the traceroute API call will not wait longer than
        # DNS_TIMEOUT_S for DNS enrichment. Hanging gethostbyaddr() threads
        # may linger in the background (ThreadPoolExecutor workers are NOT
        # daemon threads), but they hold no docsight resources and will
        # eventually complete at the OS resolver timeout (typically 5-10s).
        # This is acceptable — DNS enrichment is best-effort.
        pool = ThreadPoolExecutor(max_workers=min(len(ips_to_resolve), 16))
        futures = {pool.submit(_lookup, ip): ip for ip in ips_to_resolve}
        try:
            for future in as_completed(futures, timeout=self.DNS_TIMEOUT_S):
                try:
                    ip, host = future.result(timeout=0.1)
                    dns_map[ip] = host
                except Exception:
                    dns_map[futures[future]] = None
        except TimeoutError:
            pass  # Budget exceeded — unfinished lookups produce hop_host=None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        for h in hops:
            if h.hop_ip:
                h.hop_host = dns_map.get(h.hop_ip)
        return hops

    @staticmethod
    def _compute_fingerprint(hops: list[TracerouteHop]) -> str:
        parts = [h.hop_ip if h.hop_ip else "*" for h in hops]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd ~/Projects/docsight && python -m pytest tests/modules/connection_monitor/test_traceroute_probe.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add app/modules/connection_monitor/traceroute_probe.py
git commit -m "feat(cm): implement TracerouteProbe wrapper (#196)"
```

---

## Chunk 3: Storage Extension

### Task 5: Write trace storage tests

**Files:**
- Create: `tests/modules/connection_monitor/test_traceroute_storage.py`

- [ ] **Step 1: Write test file**

Tests to write:
- `test_trace_tables_created` — verify tables exist after init
- `test_save_and_get_trace` — save trace with hops, retrieve by id
- `test_get_traces_by_target` — list traces filtered by target_id and time range
- `test_get_trace_hops` — retrieve hops for a trace_id
- `test_save_trace_returns_id` — verify returned trace_id is valid
- `test_cleanup_traces_respects_retention` — old traces deleted, recent kept
- `test_cleanup_traces_respects_pinned_days` — pinned dates prevent cleanup
- `test_cascade_delete_target` — deleting target cascades to traces and hops
- `test_cascade_delete_trace` — deleting trace cascades to hops
- `test_purge_demo_traces` — is_demo=1 rows deleted, is_demo=0 kept
- `test_empty_trace_list` — no traces returns empty list

All tests use `tmp_path` fixture for isolated SQLite.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/docsight && python -m pytest tests/modules/connection_monitor/test_traceroute_storage.py -v`
Expected: All FAIL.

- [ ] **Step 3: Commit**

```bash
git add tests/modules/connection_monitor/test_traceroute_storage.py
git commit -m "test(cm): add traceroute storage unit tests (#196)"
```

### Task 6: Implement trace storage methods

**Files:**
- Modify: `app/modules/connection_monitor/storage.py`
  - `_init_tables` (line 27): add new CREATE TABLE statements
  - After `cleanup` (line 550): add `cleanup_traces`, `purge_demo_traces`
  - After `get_target` (line 143): add trace CRUD methods

- [ ] **Step 1: Add table creation to `_init_tables`**

Add after existing table creation (around line 80):
```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS traceroute_traces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id INTEGER NOT NULL,
        timestamp REAL NOT NULL,
        trigger_reason TEXT NOT NULL,
        hop_count INTEGER NOT NULL,
        route_fingerprint TEXT,
        reached_target INTEGER NOT NULL DEFAULT 0,
        is_demo INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (target_id) REFERENCES connection_targets(id) ON DELETE CASCADE
    )
""")
conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_traces_target_ts
    ON traceroute_traces(target_id, timestamp)
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS traceroute_hops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trace_id INTEGER NOT NULL,
        hop_index INTEGER NOT NULL,
        hop_ip TEXT,
        hop_host TEXT,
        latency_ms REAL,
        probes_responded INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (trace_id) REFERENCES traceroute_traces(id) ON DELETE CASCADE
    )
""")
conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_hops_trace
    ON traceroute_hops(trace_id)
""")
```

- [ ] **Step 2: Add CRUD methods**

```python
def save_trace(self, target_id, timestamp, trigger_reason, hops,
               route_fingerprint, reached_target, is_demo=False):
    """Save a trace with all its hops in a single transaction."""
    with self._connect() as conn:
        cur = conn.execute(
            """INSERT INTO traceroute_traces
               (target_id, timestamp, trigger_reason, hop_count,
                route_fingerprint, reached_target, is_demo)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (target_id, timestamp, trigger_reason, len(hops),
             route_fingerprint, int(reached_target), int(is_demo)),
        )
        trace_id = cur.lastrowid
        if hops:
            conn.executemany(
                """INSERT INTO traceroute_hops
                   (trace_id, hop_index, hop_ip, hop_host, latency_ms, probes_responded)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [(trace_id, h["hop_index"], h["hop_ip"], h.get("hop_host"),
                  h.get("latency_ms"), h.get("probes_responded", 0)) for h in hops],
            )
        return trace_id

def get_traces(self, target_id, start=None, end=None, limit=100):
    """Return traces for a target, newest first."""
    with self._connect() as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM traceroute_traces WHERE target_id = ?"
        params = [target_id]
        if start is not None:
            sql += " AND timestamp >= ?"
            params.append(start)
        if end is not None:
            sql += " AND timestamp <= ?"
            params.append(end)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

def get_trace(self, trace_id):
    """Return single trace metadata or None."""
    with self._connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM traceroute_traces WHERE id = ?", (trace_id,)
        ).fetchone()
        return dict(row) if row else None

def get_trace_hops(self, trace_id):
    """Return hops for a trace, ordered by hop_index."""
    with self._connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM traceroute_hops WHERE trace_id = ? ORDER BY hop_index",
            (trace_id,),
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 3: Add cleanup and purge methods**

```python
def cleanup_traces(self, retention_days):
    """Delete traces older than retention, respecting pinned days."""
    if not retention_days:
        return
    import time
    cutoff = time.time() - (retention_days * 86400)
    pinned = self.get_pinned_days()
    with self._connect() as conn:
        if pinned:
            # Build date strings for pinned days to exclude
            conn.execute(
                f"""DELETE FROM traceroute_traces
                    WHERE timestamp < ?
                    AND date(timestamp, 'unixepoch') NOT IN ({','.join('?' * len(pinned))})""",
                [cutoff] + list(pinned),
            )
        else:
            conn.execute(
                "DELETE FROM traceroute_traces WHERE timestamp < ?", (cutoff,)
            )
        # Hops auto-deleted via ON DELETE CASCADE

def purge_demo_traces(self):
    """Delete all demo traceroute data."""
    with self._connect() as conn:
        conn.execute("DELETE FROM traceroute_traces WHERE is_demo = 1")
        # Hops auto-deleted via ON DELETE CASCADE
```

- [ ] **Step 4: Run tests**

Run: `cd ~/Projects/docsight && python -m pytest tests/modules/connection_monitor/test_traceroute_storage.py -v`
Expected: All PASS.

- [ ] **Step 5: Run full CM test suite for regressions**

Run: `cd ~/Projects/docsight && python -m pytest tests/modules/connection_monitor/ -v`
Expected: All existing + new tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/modules/connection_monitor/storage.py
git commit -m "feat(cm): add traceroute storage tables and CRUD (#196)"
```

---

## Chunk 4: TracerouteTrigger + Collector Integration

### Task 7: Write TracerouteTrigger tests

**Files:**
- Create: `tests/modules/connection_monitor/test_traceroute_trigger.py`

- [ ] **Step 1: Write test file**

Tests to write:
- `test_ignores_irrelevant_events` — events other than outage/loss are ignored
- `test_triggers_on_outage` — cm_target_unreachable triggers traceroute
- `test_triggers_on_packet_loss` — cm_packet_loss_warning triggers traceroute
- `test_cooldown_prevents_rapid_traces` — second event within 5 min is blocked
- `test_cooldown_per_target` — different targets have independent cooldowns
- `test_cooldown_resets_after_period` — event after 5+ min is allowed
- `test_deleted_target_handled` — storage.get_target returns None, no crash
- `test_shutdown_stops_executor` — executor.shutdown called
- `test_saves_trace_to_storage` — verify save_trace called with correct args

All tests mock `TracerouteProbe.run()` and `ConnectionMonitorStorage`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/docsight && python -m pytest tests/modules/connection_monitor/test_traceroute_trigger.py -v`
Expected: All FAIL.

- [ ] **Step 3: Commit**

```bash
git add tests/modules/connection_monitor/test_traceroute_trigger.py
git commit -m "test(cm): add TracerouteTrigger unit tests (#196)"
```

### Task 8: Implement TracerouteTrigger

**Files:**
- Create: `app/modules/connection_monitor/traceroute_trigger.py`

- [ ] **Step 1: Write TracerouteTrigger class**

```python
import logging
import time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("docsis.traceroute")

class TracerouteTrigger:
    COOLDOWN_S = 300

    def __init__(self, probe, storage):
        self._probe = probe
        self._storage = storage
        self._last_trace: dict[int, float] = {}
        self._executor = ThreadPoolExecutor(max_workers=1)

    def on_event(self, event: dict) -> None:
        event_type = event.get("event_type")
        if event_type not in ("cm_target_unreachable", "cm_packet_loss_warning"):
            return
        target_id = event.get("details", {}).get("target_id")
        if target_id is None:
            return
        if not self._cooldown_ok(target_id):
            return
        target = self._storage.get_target(target_id)
        if not target:
            return
        reason = "outage" if event_type == "cm_target_unreachable" else "packet_loss"
        self._executor.submit(self._run_and_save, target_id, target["host"], reason)

    def _cooldown_ok(self, target_id: int) -> bool:
        last = self._last_trace.get(target_id, 0)
        return (time.time() - last) >= self.COOLDOWN_S

    def _run_and_save(self, target_id: int, host: str, reason: str) -> None:
        try:
            self._last_trace[target_id] = time.time()
            result = self._probe.run(host)
            if not result.hops:
                return
            self._storage.save_trace(
                target_id=target_id,
                timestamp=time.time(),
                trigger_reason=reason,
                hops=[{
                    "hop_index": h.hop_index,
                    "hop_ip": h.hop_ip,
                    "hop_host": h.hop_host,
                    "latency_ms": h.latency_ms,
                    "probes_responded": h.probes_responded,
                } for h in result.hops],
                route_fingerprint=result.route_fingerprint,
                reached_target=result.reached_target,
            )
        except Exception as e:
            log.error("Traceroute save failed for target %d: %s", target_id, e)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
```

- [ ] **Step 2: Run tests**

Run: `cd ~/Projects/docsight && python -m pytest tests/modules/connection_monitor/test_traceroute_trigger.py -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add app/modules/connection_monitor/traceroute_trigger.py
git commit -m "feat(cm): implement TracerouteTrigger (#196)"
```

### Task 9: Wire TracerouteTrigger into collector

**Files:**
- Modify: `app/modules/connection_monitor/collector.py`
  - `__init__` (line 24): instantiate TracerouteProbe + TracerouteTrigger
  - `_check_events` (after line 154): iterate events through trigger
  - Cleanup block (line 89-95): add cleanup_traces
  - Add `stop()` method

- [ ] **Step 1: Add imports and initialization in `__init__`**

At top of file, add:
```python
from app.modules.connection_monitor.traceroute_probe import TracerouteProbe
from app.modules.connection_monitor.traceroute_trigger import TracerouteTrigger
```

In `__init__`, after `self._probe = ProbeEngine(...)` (line 31):
```python
self._traceroute_probe = TracerouteProbe()
self._traceroute_trigger = TracerouteTrigger(
    probe=self._traceroute_probe,
    storage=self._cm_storage,
)
```

- [ ] **Step 2: Wire trigger into `_check_events`**

After line 154 (`all_events.extend(events)` from `check_window_stats`), before line 156 (`if all_events`):
```python
for event in all_events:
    self._traceroute_trigger.on_event(event)
```

- [ ] **Step 3: Wire cleanup_traces into cleanup block**

After `self._cm_storage.cleanup(retention)` (line 95):
```python
self._cm_storage.cleanup_traces(retention)
```

- [ ] **Step 4: Add stop() method**

```python
def stop(self):
    """Shut down traceroute executor on collector stop."""
    self._traceroute_trigger.shutdown()
```

- [ ] **Step 5: Run collector tests**

Run: `cd ~/Projects/docsight && python -m pytest tests/modules/connection_monitor/test_collector.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add app/modules/connection_monitor/collector.py
git commit -m "feat(cm): wire TracerouteTrigger into collector (#196)"
```

### Task 10: Add collector stop() to main.py

**Files:**
- Modify: `app/main.py:295-304` (finally block)

- [ ] **Step 1: Add stop() calls in finally block**

After `executor.shutdown(wait=False, cancel_futures=True)` (line 295), add:
```python
for c in collectors:
    if hasattr(c, "stop"):
        try:
            c.stop()
        except Exception:
            pass
```

- [ ] **Step 2: Commit**

```bash
git add app/main.py
git commit -m "feat: add collector stop() hook in polling loop finally block (#196)"
```

---

## Chunk 5: API Routes

### Task 11: Write traceroute route tests

**Files:**
- Create: `tests/modules/connection_monitor/test_traceroute_routes.py`

- [ ] **Step 1: Write test file**

Tests to write:
- `test_manual_traceroute_success` — POST returns trace with hops
- `test_manual_traceroute_invalid_target` — POST with nonexistent target_id returns 404
- `test_manual_traceroute_requires_auth` — POST without auth returns 401
- `test_get_traces_for_target` — GET returns trace list
- `test_get_traces_empty` — GET for target with no traces returns empty list
- `test_get_trace_detail` — GET returns single trace with hops
- `test_get_trace_detail_not_found` — GET nonexistent trace returns 404
- `test_traces_time_range_filter` — GET with start/end params filters correctly

All tests mock `TracerouteProbe.run()` and use Flask test client.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/docsight && python -m pytest tests/modules/connection_monitor/test_traceroute_routes.py -v`
Expected: All FAIL.

- [ ] **Step 3: Commit**

```bash
git add tests/modules/connection_monitor/test_traceroute_routes.py
git commit -m "test(cm): add traceroute route unit tests (#196)"
```

### Task 12: Implement traceroute routes

**Files:**
- Modify: `app/modules/connection_monitor/routes.py`
  - After line 50: add `_get_traceroute_probe` accessor
  - After line 518: add new endpoints

- [ ] **Step 1: Add traceroute probe accessor**

After `_get_probe_engine()` (line 50):
```python
_traceroute_probe = None

def _get_traceroute_probe():
    global _traceroute_probe
    if _traceroute_probe is None:
        from app.modules.connection_monitor.traceroute_probe import TracerouteProbe
        _traceroute_probe = TracerouteProbe()
    return _traceroute_probe
```

- [ ] **Step 2: Add helper functions**

```python
from datetime import datetime, timezone

def _epoch_to_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _hop_to_dict(hop) -> dict:
    return {
        "hop_index": hop.hop_index,
        "hop_ip": hop.hop_ip,
        "hop_host": hop.hop_host,
        "latency_ms": hop.latency_ms,
        "probes_responded": hop.probes_responded,
    }
```

- [ ] **Step 3: Add POST manual traceroute endpoint**

```python
@bp.route("/api/connection-monitor/traceroute/<int:target_id>", methods=["POST"])
@require_auth
def api_run_traceroute(target_id):
    storage = _get_cm_storage()
    target = storage.get_target(target_id)
    if not target:
        return jsonify({"error": "Target not found"}), 404

    probe = _get_traceroute_probe()
    result = probe.run(target["host"])

    trace_id = storage.save_trace(
        target_id=target_id,
        timestamp=time.time(),
        trigger_reason="manual",
        hops=[{
            "hop_index": h.hop_index, "hop_ip": h.hop_ip,
            "hop_host": h.hop_host, "latency_ms": h.latency_ms,
            "probes_responded": h.probes_responded,
        } for h in result.hops],
        route_fingerprint=result.route_fingerprint,
        reached_target=result.reached_target,
    )

    return jsonify({
        "trace_id": trace_id,
        "timestamp": _epoch_to_iso(time.time()),
        "trigger_reason": "manual",
        "reached_target": result.reached_target,
        "hop_count": len(result.hops),
        "route_fingerprint": result.route_fingerprint,
        "hops": [_hop_to_dict(h) for h in result.hops],
    })
```

- [ ] **Step 4: Add GET traces list and detail endpoints**

```python
@bp.route("/api/connection-monitor/traces/<int:target_id>")
@require_auth
def api_get_traces(target_id):
    storage = _get_cm_storage()
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    limit = request.args.get("limit", 100, type=int)
    limit = max(1, min(limit, 1000))
    traces = storage.get_traces(target_id, start=start, end=end, limit=limit)
    for t in traces:
        t["timestamp"] = _epoch_to_iso(t["timestamp"])
    return jsonify(traces)

@bp.route("/api/connection-monitor/trace/<int:trace_id>")
@require_auth
def api_get_trace_detail(trace_id):
    storage = _get_cm_storage()
    trace = storage.get_trace(trace_id)
    if not trace:
        return jsonify({"error": "Trace not found"}), 404
    hops = storage.get_trace_hops(trace_id)
    trace["timestamp"] = _epoch_to_iso(trace["timestamp"])
    trace["hops"] = hops
    return jsonify(trace)
```

- [ ] **Step 4: Run tests**

Run: `cd ~/Projects/docsight && python -m pytest tests/modules/connection_monitor/test_traceroute_routes.py -v`
Expected: All PASS.

- [ ] **Step 5: Run full CM test suite**

Run: `cd ~/Projects/docsight && python -m pytest tests/modules/connection_monitor/ -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add app/modules/connection_monitor/routes.py
git commit -m "feat(cm): add traceroute API endpoints (#196)"
```

---

## Chunk 6: i18n + UI + Demo

### Task 13: Add i18n keys

**Files:**
- Modify: `app/modules/connection_monitor/i18n/en.json`
- Modify: `app/modules/connection_monitor/i18n/de.json`
- Modify: `app/modules/connection_monitor/i18n/fr.json`
- Modify: `app/modules/connection_monitor/i18n/es.json`

- [ ] **Step 1: Add English keys**

```json
"traceroute.run_button": "Run Traceroute",
"traceroute.running": "Running traceroute...",
"traceroute.result": "Traceroute Result",
"traceroute.trigger_manual": "Manual",
"traceroute.trigger_outage": "Outage",
"traceroute.trigger_packet_loss": "Packet Loss",
"traceroute.hop": "Hop",
"traceroute.hops": "Hops",
"traceroute.reached": "Target reached",
"traceroute.not_reached": "Target not reached",
"traceroute.history": "Traceroute History",
"traceroute.no_traces": "No traceroutes recorded yet.",
"traceroute.probes_responded": "Probes",
"traceroute.partial_result": "Partial result (timeout)"
```

- [ ] **Step 2: Add German, French, Spanish translations**

Add equivalent keys to de.json, fr.json, es.json.

- [ ] **Step 3: Validate i18n**

Run: `cd ~/Projects/docsight && python scripts/i18n_check.py --validate`
Expected: All languages valid, no missing keys.

- [ ] **Step 4: Commit**

```bash
git add app/modules/connection_monitor/i18n/
git commit -m "i18n(cm): add traceroute translation keys (#196)"
```

### Task 14: Extend detail tab UI

**Files:**
- Modify: `app/modules/connection_monitor/templates/connection_monitor_detail.html`
- Modify: `app/modules/connection_monitor/static/js/connection-monitor-detail.js` (if exists)

- [ ] **Step 1: Add "Run Traceroute" button to detail view**

In the target detail section, after the outage log table, add a button that calls POST `/api/connection-monitor/traceroute/<target_id>` and displays the result inline.

- [ ] **Step 2: Add trace history table**

Below the button, add a table that loads from GET `/api/connection-monitor/traces/<target_id>` showing timestamp, trigger reason, hop count, route fingerprint (first 12 chars), and reached_target status.

- [ ] **Step 3: Add trace detail expansion**

Click on a trace row expands to show the hop list with per-hop latency, IP, hostname, and probes_responded.

- [ ] **Step 4: Manual test in browser**

Run dev instance, navigate to Connection Monitor detail, verify button works and trace history loads.

- [ ] **Step 5: Commit**

```bash
git add app/modules/connection_monitor/templates/ app/modules/connection_monitor/static/
git commit -m "ui(cm): add traceroute button and trace history to detail view (#196)"
```

### Task 15: Add demo trace seeder + migration hook

**Files:**
- Modify: `app/collectors/demo.py`
- Modify: `app/blueprints/config_bp.py` (demo→live migration path)

- [ ] **Step 1: Add demo trace data**

In the Connection Monitor demo seeder section, after existing sample data, add 3-5 sample traces with realistic hop data for default targets (1.1.1.1, 8.8.8.8). Mark all with `is_demo=1`.

Example trace: 12 hops from 192.168.178.1 → various ISP routers → 1.1.1.1, with one timeout hop at hop 4 and varying latencies (1ms → 30ms).

- [ ] **Step 2: Wire purge_demo_traces into demo→live migration**

The live migration path is in `app/blueprints/config_bp.py` → `api_demo_migrate()` (around line 107-125), NOT in the demo seeder. Add `ConnectionMonitorStorage(...).purge_demo_traces()` call alongside the existing `_storage.purge_demo_data()` call:

```python
# In api_demo_migrate(), after _storage.purge_demo_data():
from app.modules.connection_monitor.storage import ConnectionMonitorStorage
import os
cm_db = os.path.join(os.environ.get("DATA_DIR", "/data"), "connection_monitor.db")
cm_storage = ConnectionMonitorStorage(cm_db)
cm_storage.purge_demo_traces()
```

- [ ] **Step 3: Test demo mode**

Run: `cd ~/Projects/docsight && DEMO_MODE=true python -m app.main`
Verify: Traces appear in Connection Monitor detail view.

- [ ] **Step 4: Commit**

```bash
git add app/collectors/demo.py
git commit -m "demo(cm): add sample traceroute data (#196)"
```

---

## Chunk 7: Final Integration + PR

### Task 16: Full test suite

- [ ] **Step 1: Run complete test suite**

Run: `cd ~/Projects/docsight && python -m pytest tests/ -v --tb=short --ignore=tests/e2e`
Expected: All ~1100+ tests PASS.

- [ ] **Step 2: Run i18n validation**

Run: `cd ~/Projects/docsight && python scripts/i18n_check.py --validate`
Expected: PASS.

- [ ] **Step 3: Docker build + smoke test**

Run: `cd ~/Projects/docsight && docker compose -f docker-compose.dev.yml up -d --build`
Verify: Container starts, Connection Monitor works, traceroute button functional.

### Task 17: Create Pull Request

- [ ] **Step 1: Push branch**

```bash
git push -u origin feat/196-traceroute-burst-capture
```

- [ ] **Step 2: Create PR**

```bash
gh pr create --title "feat(cm): traceroute burst capture (#196)" --body "$(cat <<'EOF'
## Summary

Adds event-triggered and manual traceroute to the Connection Monitor module (Phase 2, #196).

- New setuid C helper binary (`docsight-traceroute-helper`) with privilege dropping
- `TracerouteProbe` Python wrapper with partial-result support on timeout
- `TracerouteTrigger` fires on outage/packet_loss events with 5-min cooldown
- New API: POST manual traceroute, GET trace history, GET trace detail
- Trace history UI in Connection Monitor detail tab
- Demo mode traces for testing
- i18n in all 4 languages

## Design

Spec: `docs/superpowers/specs/2026-03-17-traceroute-burst-capture-design.md`
Reviewed through 6 rounds (4 internal + 2 external), 18 issues found and resolved.

## Test plan

- [ ] Unit tests for TracerouteProbe, TracerouteTrigger, storage, routes
- [ ] C helper tested with --check, localhost, external host
- [ ] Full test suite passes (~1100+ tests)
- [ ] i18n validation passes
- [ ] Docker build succeeds
- [ ] Manual test: trigger outage, verify traceroute fires
- [ ] Manual test: Run Traceroute button in UI
- [ ] Demo mode shows sample traces
EOF
)"
```
