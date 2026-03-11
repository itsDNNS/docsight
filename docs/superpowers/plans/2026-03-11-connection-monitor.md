# Connection Monitor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a DOCSight-native always-on latency monitor as a core module that probes configured targets and displays results alongside DOCSIS data.

**Architecture:** New module at `app/modules/connection_monitor/` following DOCSight's manifest-based module system. Own collector with internal per-target timing (1s base tick, configurable per-target interval). Own SQLite storage for targets and raw samples. ICMP probing with automatic TCP fallback. Dashboard summary card + detail view with uPlot charts.

**Tech Stack:** Python 3.12, Flask, SQLite (WAL), uPlot, socket (raw ICMP + TCP), ThreadPoolExecutor

**Spec:** `docs/superpowers/specs/2026-03-11-connection-monitor-design.md`

---

## File Structure

### New files (app/modules/connection_monitor/)

| File | Responsibility |
|------|---------------|
| `manifest.json` | Module declaration: collector, routes, settings, card, tab, static, i18n |
| `__init__.py` | Empty (package marker) |
| `probe.py` | ProbeEngine class: ICMP/TCP auto-detection, single-probe execution |
| `storage.py` | ConnectionMonitorStorage: targets CRUD, samples bulk-insert, retention, outage derivation, summary queries |
| `collector.py` | ConnectionMonitorCollector: per-target timing, thread pool probing, event checking |
| `event_rules.py` | ConnectionEventRules: outage detection (N consecutive timeouts), recovery, packet loss warning |
| `routes.py` | Flask blueprint: targets API, samples API, summary, outages, export, capability |
| `templates/connection_monitor_settings.html` | Settings form: enable toggle, targets, poll interval, thresholds, retention, probe method |
| `templates/connection_monitor_card.html` | Dashboard summary card: status per target, avg latency, probe method badge |
| `templates/connection_monitor_detail.html` | Detail view: target selector, timerange picker, chart containers, outage log, export button |
| `static/js/connection-monitor-card.js` | Card rendering: fetch summary, update status indicators |
| `static/js/connection-monitor-detail.js` | Detail view: timerange picker, target switching, data fetching, outage log |
| `static/js/connection-monitor-charts.js` | uPlot chart configs: latency timeline, packet loss bars, availability band |
| `i18n/en.json` | English translations |
| `i18n/de.json` | German translations |
| `i18n/fr.json` | French translations |
| `i18n/es.json` | Spanish translations |

### New test files

| File | Tests |
|------|-------|
| `tests/modules/connection_monitor/test_probe.py` | ProbeEngine: ICMP success/timeout, TCP success/timeout, auto-detection, fallback |
| `tests/modules/connection_monitor/test_storage.py` | Storage: target CRUD, sample insert/query, retention cleanup, outage derivation, summary |
| `tests/modules/connection_monitor/test_collector.py` | Collector: timing logic, batch insert, event rule triggering, always-ok result |
| `tests/modules/connection_monitor/test_event_rules.py` | Event rules: outage after N timeouts, recovery, packet loss threshold |
| `tests/modules/connection_monitor/test_routes.py` | API endpoints: targets CRUD, samples query, summary, outages, export CSV, capability |

### Modified files

| File | Change |
|------|--------|
| `docker-compose.yml` | Add `cap_add: [NET_RAW]` |
| `docker-compose.dev.yml` | Add `cap_add: [NET_RAW]` |

---

## Chunk 1: Module Scaffold + Storage + Probe Engine

### Task 1: Module scaffold

**Files:**
- Create: `app/modules/connection_monitor/__init__.py`
- Create: `app/modules/connection_monitor/manifest.json`

- [ ] **Step 1: Create module directory and package marker**

```bash
mkdir -p app/modules/connection_monitor/templates app/modules/connection_monitor/static/js app/modules/connection_monitor/i18n
```

Create `app/modules/connection_monitor/__init__.py` (empty file).

- [ ] **Step 2: Create manifest.json**

Create `app/modules/connection_monitor/manifest.json`:

```json
{
  "id": "docsight.connection_monitor",
  "name": "Connection Monitor",
  "description": "Always-on latency monitoring with ICMP/TCP probing for cable troubleshooting",
  "version": "1.0.0",
  "author": "itsDNNS",
  "minAppVersion": "2026.2",
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
  },
  "menu": {
    "label_key": "docsight.connection_monitor.connection_monitor",
    "icon": "activity",
    "order": 25
  }
}
```

- [ ] **Step 3: Commit scaffold**

```bash
git add app/modules/connection_monitor/__init__.py app/modules/connection_monitor/manifest.json
git commit -m "feat(connection-monitor): add module scaffold with manifest"
```

---

### Task 2: Probe Engine - ICMP and TCP probing

**Files:**
- Create: `app/modules/connection_monitor/probe.py`
- Create: `tests/modules/connection_monitor/__init__.py`
- Create: `tests/modules/connection_monitor/test_probe.py`

- [ ] **Step 1: Create test package marker**

Create empty `tests/modules/__init__.py` (if missing) and `tests/modules/connection_monitor/__init__.py`.

- [ ] **Step 2: Write ProbeResult dataclass and ProbeEngine skeleton tests**

Create `tests/modules/connection_monitor/test_probe.py`:

```python
"""Tests for the Connection Monitor probe engine."""

import socket
from unittest.mock import patch, MagicMock
import pytest

from app.modules.connection_monitor.probe import ProbeEngine, ProbeResult


class TestProbeResult:
    def test_success_result(self):
        r = ProbeResult(latency_ms=12.5, timeout=False, method="icmp")
        assert r.latency_ms == 12.5
        assert r.timeout is False
        assert r.method == "icmp"

    def test_timeout_result(self):
        r = ProbeResult(latency_ms=None, timeout=True, method="tcp")
        assert r.latency_ms is None
        assert r.timeout is True


class TestProbeEngineAutoDetection:
    def test_auto_selects_icmp_when_raw_socket_available(self):
        with patch("socket.socket") as mock_sock:
            mock_sock.return_value.__enter__ = MagicMock()
            mock_sock.return_value.__exit__ = MagicMock(return_value=False)
            engine = ProbeEngine(method="auto")
            assert engine.detected_method == "icmp"

    def test_auto_falls_back_to_tcp_on_permission_error(self):
        with patch("socket.socket", side_effect=PermissionError):
            engine = ProbeEngine(method="auto")
            assert engine.detected_method == "tcp"

    def test_auto_falls_back_to_tcp_on_os_error(self):
        with patch("socket.socket", side_effect=OSError):
            engine = ProbeEngine(method="auto")
            assert engine.detected_method == "tcp"

    def test_explicit_icmp(self):
        engine = ProbeEngine(method="icmp")
        assert engine.detected_method == "icmp"

    def test_explicit_tcp(self):
        engine = ProbeEngine(method="tcp")
        assert engine.detected_method == "tcp"

    def test_capability_info(self):
        with patch("socket.socket", side_effect=PermissionError):
            engine = ProbeEngine(method="auto")
            info = engine.capability_info()
            assert info["method"] == "tcp"
            assert "reason" in info


class TestTCPProbe:
    def test_tcp_success(self):
        engine = ProbeEngine(method="tcp")
        with patch("socket.socket") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.connect_ex.return_value = 0
            result = engine.probe("1.1.1.1", tcp_port=443)
            assert result.timeout is False
            assert result.method == "tcp"
            assert result.latency_ms is not None
            assert result.latency_ms >= 0

    def test_tcp_timeout(self):
        engine = ProbeEngine(method="tcp")
        with patch("socket.socket") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.connect_ex.side_effect = socket.timeout
            result = engine.probe("1.1.1.1", tcp_port=443)
            assert result.timeout is True
            assert result.latency_ms is None
            assert result.method == "tcp"

    def test_tcp_connection_refused(self):
        engine = ProbeEngine(method="tcp")
        with patch("socket.socket") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.connect_ex.return_value = 111  # ECONNREFUSED
            result = engine.probe("1.1.1.1", tcp_port=443)
            assert result.timeout is True
            assert result.latency_ms is None


class TestICMPProbe:
    def test_icmp_success(self):
        engine = ProbeEngine(method="icmp")
        with patch.object(engine, "_icmp_probe") as mock_icmp:
            mock_icmp.return_value = ProbeResult(
                latency_ms=5.2, timeout=False, method="icmp"
            )
            result = engine.probe("1.1.1.1")
            assert result.timeout is False
            assert result.latency_ms == 5.2
            assert result.method == "icmp"

    def test_icmp_timeout(self):
        engine = ProbeEngine(method="icmp")
        with patch.object(engine, "_icmp_probe") as mock_icmp:
            mock_icmp.return_value = ProbeResult(
                latency_ms=None, timeout=True, method="icmp"
            )
            result = engine.probe("1.1.1.1")
            assert result.timeout is True
            assert result.latency_ms is None
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
SECRET_KEY=test python -m pytest tests/modules/connection_monitor/test_probe.py -v
```

Expected: ImportError (module not found).

- [ ] **Step 4: Implement ProbeEngine**

Create `app/modules/connection_monitor/probe.py`:

```python
"""Probe engine for Connection Monitor - ICMP and TCP latency probing."""

import logging
import os
import socket
import struct
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 2.0


@dataclass
class ProbeResult:
    """Result of a single probe attempt."""

    latency_ms: float | None  # None on timeout
    timeout: bool
    method: str  # "icmp" or "tcp"


class ProbeEngine:
    """Probes targets via ICMP or TCP with auto-detection."""

    def __init__(self, method: str = "auto"):
        self._fallback_reason: str | None = None
        if method == "auto":
            self.detected_method = self._detect_method()
        elif method in ("icmp", "tcp"):
            self.detected_method = method
        else:
            raise ValueError(f"Unknown probe method: {method}")
        self._seq = 0

    def _detect_method(self) -> str:
        """Try ICMP raw socket; fall back to TCP if not permitted."""
        try:
            with socket.socket(
                socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP
            ):
                pass
            logger.info("ICMP raw socket available - using ICMP probing")
            return "icmp"
        except (PermissionError, OSError) as exc:
            self._fallback_reason = str(exc)
            logger.warning(
                "ICMP raw socket not available (%s) - falling back to TCP",
                exc,
            )
            return "tcp"

    def capability_info(self) -> dict:
        """Return probe method info for the UI."""
        info = {"method": self.detected_method}
        if self._fallback_reason:
            info["reason"] = self._fallback_reason
            info["hint"] = (
                "Add cap_add: [NET_RAW] to your Docker Compose file "
                "for ICMP probing (more accurate)."
            )
        return info

    def probe(self, host: str, tcp_port: int = 443) -> ProbeResult:
        """Run a single probe against the target."""
        if self.detected_method == "icmp":
            return self._icmp_probe(host)
        return self._tcp_probe(host, tcp_port)

    def _tcp_probe(self, host: str, port: int) -> ProbeResult:
        """Measure TCP handshake latency."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(PROBE_TIMEOUT_S)
        try:
            start = time.monotonic()
            result_code = sock.connect_ex((host, port))
            elapsed = (time.monotonic() - start) * 1000
            if result_code == 0:
                return ProbeResult(
                    latency_ms=round(elapsed, 2), timeout=False, method="tcp"
                )
            return ProbeResult(latency_ms=None, timeout=True, method="tcp")
        except (socket.timeout, OSError):
            return ProbeResult(latency_ms=None, timeout=True, method="tcp")
        finally:
            sock.close()

    def _icmp_probe(self, host: str) -> ProbeResult:
        """Send ICMP echo request and measure round-trip time."""
        try:
            dest = socket.gethostbyname(host)
        except socket.gaierror:
            return ProbeResult(latency_ms=None, timeout=True, method="icmp")

        sock = socket.socket(
            socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP
        )
        sock.settimeout(PROBE_TIMEOUT_S)
        try:
            self._seq = (self._seq + 1) & 0xFFFF
            packet = self._build_icmp_packet(
                seq=self._seq, ident=os.getpid() & 0xFFFF
            )
            start = time.monotonic()
            sock.sendto(packet, (dest, 0))
            while True:
                remaining = PROBE_TIMEOUT_S - (time.monotonic() - start)
                if remaining <= 0:
                    return ProbeResult(
                        latency_ms=None, timeout=True, method="icmp"
                    )
                sock.settimeout(remaining)
                data, _ = sock.recvfrom(1024)
                # Skip IP header (20 bytes), check ICMP type=0 (echo reply)
                icmp_header = data[20:28]
                icmp_type, _, _, pkt_id, pkt_seq = struct.unpack(
                    "!BBHHH", icmp_header
                )
                if (
                    icmp_type == 0
                    and pkt_id == (os.getpid() & 0xFFFF)
                    and pkt_seq == self._seq
                ):
                    elapsed = (time.monotonic() - start) * 1000
                    return ProbeResult(
                        latency_ms=round(elapsed, 2),
                        timeout=False,
                        method="icmp",
                    )
        except (socket.timeout, OSError):
            return ProbeResult(latency_ms=None, timeout=True, method="icmp")
        finally:
            sock.close()

    @staticmethod
    def _build_icmp_packet(seq: int, ident: int) -> bytes:
        """Build ICMP echo request packet with checksum."""
        # Type 8 = echo request, code 0
        header = struct.pack("!BBHHH", 8, 0, 0, ident, seq)
        payload = b"\x00" * 32
        checksum = ProbeEngine._icmp_checksum(header + payload)
        header = struct.pack("!BBHHH", 8, 0, checksum, ident, seq)
        return header + payload

    @staticmethod
    def _icmp_checksum(data: bytes) -> int:
        """Compute ICMP checksum per RFC 1071."""
        if len(data) % 2:
            data += b"\x00"
        total = 0
        for i in range(0, len(data), 2):
            total += (data[i] << 8) + data[i + 1]
        total = (total >> 16) + (total & 0xFFFF)
        total += total >> 16
        return ~total & 0xFFFF
```

- [ ] **Step 5: Run tests**

```bash
SECRET_KEY=test python -m pytest tests/modules/connection_monitor/test_probe.py -v
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/modules/connection_monitor/probe.py tests/modules/connection_monitor/
git commit -m "feat(connection-monitor): add probe engine with ICMP/TCP auto-detection"
```

---

### Task 3: Storage layer - targets and samples

**Files:**
- Create: `app/modules/connection_monitor/storage.py`
- Create: `tests/modules/connection_monitor/test_storage.py`

- [ ] **Step 1: Write storage tests**

Create `tests/modules/connection_monitor/test_storage.py`:

```python
"""Tests for Connection Monitor storage layer."""

import os
import tempfile
import time
import pytest

from app.modules.connection_monitor.storage import ConnectionMonitorStorage


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test_cm.db")
    return ConnectionMonitorStorage(db_path)


class TestTargetCRUD:
    def test_create_target(self, storage):
        tid = storage.create_target("Cloudflare", "1.1.1.1")
        assert tid == 1
        targets = storage.get_targets()
        assert len(targets) == 1
        assert targets[0]["label"] == "Cloudflare"
        assert targets[0]["host"] == "1.1.1.1"
        assert targets[0]["enabled"] is True
        assert targets[0]["poll_interval_ms"] == 5000

    def test_create_target_custom_settings(self, storage):
        tid = storage.create_target(
            "Google", "8.8.8.8",
            poll_interval_ms=2500, probe_method="tcp", tcp_port=80,
        )
        target = storage.get_target(tid)
        assert target["poll_interval_ms"] == 2500
        assert target["probe_method"] == "tcp"
        assert target["tcp_port"] == 80

    def test_update_target(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        storage.update_target(tid, label="Updated", enabled=False)
        target = storage.get_target(tid)
        assert target["label"] == "Updated"
        assert target["enabled"] is False

    def test_delete_target_cascades_samples(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        storage.save_samples([
            {"target_id": tid, "timestamp": time.time(), "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        storage.delete_target(tid)
        assert storage.get_target(tid) is None
        assert storage.get_samples(tid) == []

    def test_get_nonexistent_target(self, storage):
        assert storage.get_target(999) is None


class TestSamples:
    def test_save_and_get_samples(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        samples = [
            {"target_id": tid, "timestamp": now - 2, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 1, "latency_ms": 15.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
        ]
        storage.save_samples(samples)
        result = storage.get_samples(tid)
        assert len(result) == 3

    def test_get_samples_with_time_range(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        samples = [
            {"target_id": tid, "timestamp": now - 100, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 50, "latency_ms": 15.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
        ]
        storage.save_samples(samples)
        result = storage.get_samples(tid, start=now - 60, end=now - 10)
        assert len(result) == 1
        assert result[0]["latency_ms"] == 15.0

    def test_get_samples_with_limit(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        samples = [
            {"target_id": tid, "timestamp": now - i, "latency_ms": float(i), "timeout": False, "probe_method": "tcp"}
            for i in range(20)
        ]
        storage.save_samples(samples)
        result = storage.get_samples(tid, limit=5)
        assert len(result) == 5


class TestRetention:
    def test_cleanup_old_samples(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        old_ts = now - (8 * 86400)  # 8 days ago
        new_ts = now - 60  # 1 minute ago
        storage.save_samples([
            {"target_id": tid, "timestamp": old_ts, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": new_ts, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
        ])
        deleted = storage.cleanup(retention_days=7)
        assert deleted == 1
        result = storage.get_samples(tid)
        assert len(result) == 1
        assert result[0]["latency_ms"] == 20.0

    def test_cleanup_zero_keeps_all(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        old_ts = time.time() - (365 * 86400)
        storage.save_samples([
            {"target_id": tid, "timestamp": old_ts, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        deleted = storage.cleanup(retention_days=0)
        assert deleted == 0
        assert len(storage.get_samples(tid)) == 1


class TestSummary:
    def test_summary_returns_stats(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 30, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 20, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 10, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
        ])
        summary = storage.get_summary(tid, window_seconds=60)
        assert summary["sample_count"] == 3
        assert summary["avg_latency_ms"] == 15.0
        assert abs(summary["packet_loss_pct"] - 33.33) < 1
        assert summary["min_latency_ms"] == 10.0
        assert summary["max_latency_ms"] == 20.0


class TestOutages:
    def test_derive_outages(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        # 5 consecutive timeouts = 1 outage
        samples = [
            {"target_id": tid, "timestamp": now - 50, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ]
        for i in range(5):
            samples.append({
                "target_id": tid, "timestamp": now - 40 + (i * 5),
                "latency_ms": None, "timeout": True, "probe_method": "tcp",
            })
        samples.append(
            {"target_id": tid, "timestamp": now, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        )
        storage.save_samples(samples)
        outages = storage.get_outages(tid, threshold=5)
        assert len(outages) == 1
        assert outages[0]["timeout_count"] == 5

    def test_no_outage_below_threshold(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        samples = [
            {"target_id": tid, "timestamp": now - 20, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 15, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 10, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 5, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ]
        storage.save_samples(samples)
        outages = storage.get_outages(tid, threshold=5)
        assert len(outages) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
SECRET_KEY=test python -m pytest tests/modules/connection_monitor/test_storage.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement ConnectionMonitorStorage**

Create `app/modules/connection_monitor/storage.py`:

```python
"""SQLite storage for Connection Monitor targets and samples."""

import logging
import os
import sqlite3
import time

logger = logging.getLogger(__name__)


class ConnectionMonitorStorage:
    """Manages connection_targets and connection_samples tables."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS connection_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    host TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    poll_interval_ms INTEGER NOT NULL DEFAULT 5000,
                    probe_method TEXT NOT NULL DEFAULT 'auto',
                    tcp_port INTEGER NOT NULL DEFAULT 443,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS connection_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    latency_ms REAL,
                    timeout BOOLEAN NOT NULL DEFAULT 0,
                    probe_method TEXT NOT NULL,
                    FOREIGN KEY (target_id) REFERENCES connection_targets(id)
                        ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_samples_target_ts
                ON connection_samples (target_id, timestamp)
            """)

    # --- Target CRUD ---

    def create_target(
        self,
        label: str,
        host: str,
        enabled: bool = True,
        poll_interval_ms: int = 5000,
        probe_method: str = "auto",
        tcp_port: int = 443,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO connection_targets
                   (label, host, enabled, poll_interval_ms, probe_method, tcp_port, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (label, host, enabled, poll_interval_ms, probe_method, tcp_port, time.time()),
            )
            return cur.lastrowid

    def get_targets(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM connection_targets ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_target(self, target_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM connection_targets WHERE id = ?", (target_id,)
            ).fetchone()
            return dict(row) if row else None

    def update_target(self, target_id: int, **fields) -> bool:
        allowed = {"label", "host", "enabled", "poll_interval_ms", "probe_method", "tcp_port"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [target_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE connection_targets SET {set_clause} WHERE id = ?",
                values,
            )
            return True

    def delete_target(self, target_id: int):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM connection_targets WHERE id = ?", (target_id,)
            )

    # --- Samples ---

    def save_samples(self, samples: list[dict]):
        if not samples:
            return
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO connection_samples
                   (target_id, timestamp, latency_ms, timeout, probe_method)
                   VALUES (:target_id, :timestamp, :latency_ms, :timeout, :probe_method)""",
                samples,
            )

    def get_samples(
        self,
        target_id: int,
        start: float | None = None,
        end: float | None = None,
        limit: int = 10000,
    ) -> list[dict]:
        clauses = ["target_id = ?"]
        params: list = [target_id]
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM connection_samples WHERE {where} ORDER BY timestamp LIMIT ?",
                params + [limit],
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Summary ---

    def get_summary(self, target_id: int, window_seconds: int = 60) -> dict:
        cutoff = time.time() - window_seconds
        with self._connect() as conn:
            row = conn.execute(
                """SELECT
                    COUNT(*) as sample_count,
                    AVG(CASE WHEN timeout = 0 THEN latency_ms END) as avg_latency_ms,
                    MIN(CASE WHEN timeout = 0 THEN latency_ms END) as min_latency_ms,
                    MAX(CASE WHEN timeout = 0 THEN latency_ms END) as max_latency_ms,
                    ROUND(100.0 * SUM(CASE WHEN timeout = 1 THEN 1 ELSE 0 END) / MAX(COUNT(*), 1), 2) as packet_loss_pct
                FROM connection_samples
                WHERE target_id = ? AND timestamp >= ?""",
                (target_id, cutoff),
            ).fetchone()
            return dict(row) if row else {}

    # --- Outages ---

    def get_outages(
        self,
        target_id: int,
        threshold: int = 5,
        start: float | None = None,
        end: float | None = None,
    ) -> list[dict]:
        """Derive outages from consecutive timeout sequences."""
        clauses = ["target_id = ?"]
        params: list = [target_id]
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT timestamp, timeout FROM connection_samples WHERE {where} ORDER BY timestamp",
                params,
            ).fetchall()

        outages = []
        run_start = None
        run_count = 0
        for row in rows:
            if row["timeout"]:
                if run_start is None:
                    run_start = row["timestamp"]
                run_count += 1
            else:
                if run_count >= threshold:
                    outages.append({
                        "start": run_start,
                        "end": row["timestamp"],
                        "duration_seconds": round(row["timestamp"] - run_start, 1),
                        "timeout_count": run_count,
                    })
                run_start = None
                run_count = 0
        # Handle ongoing outage at end of data
        if run_count >= threshold:
            last_ts = rows[-1]["timestamp"] if rows else time.time()
            outages.append({
                "start": run_start,
                "end": None,
                "duration_seconds": round(last_ts - run_start, 1),
                "timeout_count": run_count,
            })
        return outages

    # --- Retention ---

    def cleanup(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = time.time() - (retention_days * 86400)
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM connection_samples WHERE timestamp < ?",
                (cutoff,),
            )
            deleted = cur.rowcount
            if deleted:
                logger.info("Connection Monitor: cleaned up %d old samples", deleted)
            return deleted
```

- [ ] **Step 4: Run tests**

```bash
SECRET_KEY=test python -m pytest tests/modules/connection_monitor/test_storage.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/modules/connection_monitor/storage.py tests/modules/connection_monitor/test_storage.py
git commit -m "feat(connection-monitor): add storage layer for targets and samples"
```

---

## Chunk 2: Event Rules + Collector

### Task 4: Event rules - outage detection and recovery

**Files:**
- Create: `app/modules/connection_monitor/event_rules.py`
- Create: `tests/modules/connection_monitor/test_event_rules.py`

- [ ] **Step 1: Write event rules tests**

Create `tests/modules/connection_monitor/test_event_rules.py`:

```python
"""Tests for Connection Monitor event rules."""

import time
import pytest

from app.modules.connection_monitor.event_rules import ConnectionEventRules


@pytest.fixture
def rules():
    return ConnectionEventRules(outage_threshold=5, loss_warning_pct=2.0)


class TestOutageDetection:
    def test_no_event_below_threshold(self, rules):
        for _ in range(4):
            events = rules.check_probe_result(target_id=1, timeout=True)
        assert events == []

    def test_outage_event_at_threshold(self, rules):
        for _ in range(4):
            rules.check_probe_result(target_id=1, timeout=True)
        events = rules.check_probe_result(target_id=1, timeout=True)
        assert len(events) == 1
        assert events[0]["event_type"] == "cm_target_unreachable"
        assert events[0]["severity"] == "critical"

    def test_no_duplicate_outage_events(self, rules):
        for _ in range(5):
            rules.check_probe_result(target_id=1, timeout=True)
        # Further timeouts should not produce more events
        events = rules.check_probe_result(target_id=1, timeout=True)
        assert events == []

    def test_recovery_event(self, rules):
        for _ in range(5):
            rules.check_probe_result(target_id=1, timeout=True)
        events = rules.check_probe_result(target_id=1, timeout=False)
        assert len(events) == 1
        assert events[0]["event_type"] == "cm_target_recovered"
        assert events[0]["severity"] == "info"

    def test_no_recovery_without_prior_outage(self, rules):
        events = rules.check_probe_result(target_id=1, timeout=False)
        assert events == []

    def test_independent_targets(self, rules):
        for _ in range(5):
            rules.check_probe_result(target_id=1, timeout=True)
        # Target 2 should be independent
        events = rules.check_probe_result(target_id=2, timeout=False)
        assert events == []


class TestPacketLoss:
    def test_loss_warning(self, rules):
        events = rules.check_window_stats(
            target_id=1, packet_loss_pct=5.0, window_seconds=60,
        )
        assert len(events) == 1
        assert events[0]["event_type"] == "cm_packet_loss_warning"
        assert events[0]["severity"] == "warning"

    def test_no_warning_below_threshold(self, rules):
        events = rules.check_window_stats(
            target_id=1, packet_loss_pct=1.0, window_seconds=60,
        )
        assert events == []

    def test_loss_warning_cooldown(self, rules):
        rules.check_window_stats(target_id=1, packet_loss_pct=5.0, window_seconds=60)
        events = rules.check_window_stats(
            target_id=1, packet_loss_pct=5.0, window_seconds=60,
        )
        assert events == []  # Cooldown prevents duplicate
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
SECRET_KEY=test python -m pytest tests/modules/connection_monitor/test_event_rules.py -v
```

- [ ] **Step 3: Implement ConnectionEventRules**

Create `app/modules/connection_monitor/event_rules.py`:

```python
"""Event detection rules for Connection Monitor."""

import time
from app.tz import utc_now


# Cooldown prevents duplicate packet loss warnings within this window
LOSS_COOLDOWN_S = 300


class ConnectionEventRules:
    """Tracks per-target state and emits events for outages, recovery, packet loss."""

    def __init__(self, outage_threshold: int = 5, loss_warning_pct: float = 2.0):
        self._outage_threshold = outage_threshold
        self._loss_warning_pct = loss_warning_pct
        # Per-target state: {target_id: {"consecutive_timeouts": int, "in_outage": bool}}
        self._target_state: dict[int, dict] = {}
        # Per-target loss cooldown: {target_id: last_warning_ts}
        self._loss_cooldown: dict[int, float] = {}

    def _get_state(self, target_id: int) -> dict:
        if target_id not in self._target_state:
            self._target_state[target_id] = {
                "consecutive_timeouts": 0,
                "in_outage": False,
            }
        return self._target_state[target_id]

    def check_probe_result(self, target_id: int, timeout: bool) -> list[dict]:
        """Check a single probe result and return any events to emit."""
        state = self._get_state(target_id)
        events = []

        if timeout:
            state["consecutive_timeouts"] += 1
            if (
                state["consecutive_timeouts"] >= self._outage_threshold
                and not state["in_outage"]
            ):
                state["in_outage"] = True
                events.append({
                    "timestamp": utc_now(),
                    "severity": "critical",
                    "event_type": "cm_target_unreachable",
                    "message": f"Target {target_id} unreachable ({state['consecutive_timeouts']} consecutive timeouts)",
                    "details": {"target_id": target_id, "consecutive_timeouts": state["consecutive_timeouts"]},
                })
        else:
            if state["in_outage"]:
                events.append({
                    "timestamp": utc_now(),
                    "severity": "info",
                    "event_type": "cm_target_recovered",
                    "message": f"Target {target_id} recovered after {state['consecutive_timeouts']} timeouts",
                    "details": {"target_id": target_id, "was_down_for": state["consecutive_timeouts"]},
                })
            state["consecutive_timeouts"] = 0
            state["in_outage"] = False

        return events

    def check_window_stats(
        self, target_id: int, packet_loss_pct: float, window_seconds: int,
    ) -> list[dict]:
        """Check aggregated window stats and return any events."""
        events = []
        now = time.time()

        if packet_loss_pct >= self._loss_warning_pct:
            last_warning = self._loss_cooldown.get(target_id, 0)
            if now - last_warning >= LOSS_COOLDOWN_S:
                self._loss_cooldown[target_id] = now
                events.append({
                    "timestamp": utc_now(),
                    "severity": "warning",
                    "event_type": "cm_packet_loss_warning",
                    "message": f"Target {target_id}: {packet_loss_pct:.1f}% packet loss over {window_seconds}s",
                    "details": {
                        "target_id": target_id,
                        "packet_loss_pct": packet_loss_pct,
                        "window_seconds": window_seconds,
                    },
                })
        return events
```

- [ ] **Step 4: Run tests**

```bash
SECRET_KEY=test python -m pytest tests/modules/connection_monitor/test_event_rules.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/modules/connection_monitor/event_rules.py tests/modules/connection_monitor/test_event_rules.py
git commit -m "feat(connection-monitor): add event rules for outage detection and recovery"
```

---

### Task 5: Collector - orchestrates probing, storage, events

**Files:**
- Create: `app/modules/connection_monitor/collector.py`
- Create: `tests/modules/connection_monitor/test_collector.py`

- [ ] **Step 1: Write collector tests**

Create `tests/modules/connection_monitor/test_collector.py`:

```python
"""Tests for Connection Monitor collector."""

import time
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from app.modules.connection_monitor.collector import ConnectionMonitorCollector
from app.modules.connection_monitor.probe import ProbeResult
from app.collectors.base import CollectorResult


@pytest.fixture
def mock_deps(tmp_path):
    config_mgr = MagicMock()
    config_mgr.get.side_effect = lambda key, default=None: {
        "connection_monitor_enabled": True,
        "connection_monitor_poll_interval_ms": 5000,
        "connection_monitor_probe_method": "tcp",
        "connection_monitor_tcp_port": 443,
        "connection_monitor_retention_days": 0,
        "connection_monitor_outage_threshold": 5,
        "connection_monitor_loss_warning_pct": 2.0,
    }.get(key, default)
    storage = MagicMock()
    web = MagicMock()
    return config_mgr, storage, web


class TestCollectorInit:
    def test_creates_with_1s_base_interval(self, mock_deps):
        config_mgr, storage, web = mock_deps
        with patch("app.modules.connection_monitor.collector.ProbeEngine"):
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            assert collector._poll_interval_seconds == 1

    def test_should_poll_always_true(self, mock_deps):
        config_mgr, storage, web = mock_deps
        with patch("app.modules.connection_monitor.collector.ProbeEngine"):
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            assert collector.should_poll() is True


class TestCollectorEnabled:
    def test_enabled_when_config_true(self, mock_deps):
        config_mgr, storage, web = mock_deps
        with patch("app.modules.connection_monitor.collector.ProbeEngine"):
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            assert collector.is_enabled() is True

    def test_disabled_when_config_false(self, mock_deps):
        config_mgr, storage, web = mock_deps
        config_mgr.get.side_effect = lambda key, default=None: {
            "connection_monitor_enabled": False,
        }.get(key, default)
        with patch("app.modules.connection_monitor.collector.ProbeEngine"):
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            assert collector.is_enabled() is False


class TestCollect:
    def test_always_returns_ok(self, mock_deps):
        config_mgr, storage, web = mock_deps
        with patch("app.modules.connection_monitor.collector.ProbeEngine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.probe.return_value = ProbeResult(
                latency_ms=None, timeout=True, method="tcp"
            )
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            # Force a target to be due
            collector._cm_storage = MagicMock()
            collector._cm_storage.get_targets.return_value = [
                {"id": 1, "host": "1.1.1.1", "enabled": True,
                 "poll_interval_ms": 5000, "probe_method": "tcp", "tcp_port": 443},
            ]
            collector._last_probe = {}
            result = collector.collect()
            assert result.success is True

    def test_skips_targets_not_due(self, mock_deps):
        config_mgr, storage, web = mock_deps
        with patch("app.modules.connection_monitor.collector.ProbeEngine") as MockEngine:
            mock_engine = MockEngine.return_value
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            collector._cm_storage = MagicMock()
            collector._cm_storage.get_targets.return_value = [
                {"id": 1, "host": "1.1.1.1", "enabled": True,
                 "poll_interval_ms": 5000, "probe_method": "tcp", "tcp_port": 443},
            ]
            # Set last probe to now - target is not due
            collector._last_probe = {1: time.time()}
            result = collector.collect()
            mock_engine.probe.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
SECRET_KEY=test python -m pytest tests/modules/connection_monitor/test_collector.py -v
```

- [ ] **Step 3: Implement ConnectionMonitorCollector**

Create `app/modules/connection_monitor/collector.py`:

```python
"""Collector for Connection Monitor - orchestrates probing, storage, and events."""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.collectors.base import Collector, CollectorResult
from app.modules.connection_monitor.event_rules import ConnectionEventRules
from app.modules.connection_monitor.probe import ProbeEngine
from app.modules.connection_monitor.storage import ConnectionMonitorStorage

logger = logging.getLogger(__name__)

# Run retention cleanup every 15 minutes, not every collect cycle
_CLEANUP_INTERVAL_S = 900


class ConnectionMonitorCollector(Collector):
    """Always-on latency collector with per-target timing."""

    name = "connection_monitor"

    def __init__(self, config_mgr, storage, web, **kwargs):
        super().__init__(poll_interval_seconds=1)
        self._config_mgr = config_mgr
        self._core_storage = storage
        self._web = web

        method = config_mgr.get("connection_monitor_probe_method", "auto")
        self._probe = ProbeEngine(method=method)
        self._last_probe: dict[int, float] = {}
        self._last_cleanup = 0.0
        self._event_rules = ConnectionEventRules(
            outage_threshold=int(config_mgr.get("connection_monitor_outage_threshold", 5)),
            loss_warning_pct=float(config_mgr.get("connection_monitor_loss_warning_pct", 2.0)),
        )

        data_dir = os.environ.get("DATA_DIR", "/data")
        db_path = os.path.join(data_dir, "connection_monitor.db")
        self._cm_storage = ConnectionMonitorStorage(db_path)

        self._seeded = False

    def is_enabled(self) -> bool:
        return bool(self._config_mgr.get("connection_monitor_enabled", False))

    def should_poll(self) -> bool:
        """Always return True - per-target timing is managed internally."""
        return True

    def collect(self) -> CollectorResult:
        try:
            self._ensure_default_targets()
            targets = [
                t for t in self._cm_storage.get_targets() if t["enabled"]
            ]
            if not targets:
                return CollectorResult.ok(self.name, None)

            # Determine which targets are due
            now = time.time()
            due = []
            for t in targets:
                interval_s = t["poll_interval_ms"] / 1000.0
                last = self._last_probe.get(t["id"], 0)
                if now - last >= interval_s:
                    due.append(t)

            if not due:
                return CollectorResult.ok(self.name, None)

            # Probe all due targets in parallel
            samples = self._probe_targets(due, now)

            # Save samples
            if samples:
                self._cm_storage.save_samples(samples)

            # Check events
            self._check_events(samples)

            # Periodic retention cleanup
            if now - self._last_cleanup >= _CLEANUP_INTERVAL_S:
                retention = int(
                    self._config_mgr.get("connection_monitor_retention_days", 0)
                )
                self._cm_storage.cleanup(retention)
                self._last_cleanup = now

            # Update web state for dashboard
            self._update_web_state(targets)

            return CollectorResult.ok(self.name, {"probed": len(due)})
        except Exception as exc:
            logger.exception("Connection Monitor collect error")
            return CollectorResult.failure(self.name, str(exc))

    def _probe_targets(self, targets: list[dict], now: float) -> list[dict]:
        """Probe targets in parallel and return sample dicts."""
        samples = []
        tcp_port = int(self._config_mgr.get("connection_monitor_tcp_port", 443))

        with ThreadPoolExecutor(
            max_workers=max(len(targets), 1),
            thread_name_prefix="cm-probe",
        ) as pool:
            futures = {
                pool.submit(self._probe.probe, t["host"], t.get("tcp_port", tcp_port)): t
                for t in targets
            }
            for future in as_completed(futures, timeout=5):
                target = futures[future]
                try:
                    result = future.result()
                except Exception:
                    result = type("R", (), {"latency_ms": None, "timeout": True, "method": "error"})()

                self._last_probe[target["id"]] = now
                samples.append({
                    "target_id": target["id"],
                    "timestamp": now,
                    "latency_ms": result.latency_ms,
                    "timeout": result.timeout,
                    "probe_method": result.method,
                })
        return samples

    def _check_events(self, samples: list[dict]):
        """Run event rules and save any emitted events."""
        all_events = []
        for s in samples:
            events = self._event_rules.check_probe_result(
                target_id=s["target_id"], timeout=s["timeout"]
            )
            all_events.extend(events)

        if all_events and hasattr(self._core_storage, "save_events"):
            self._core_storage.save_events(all_events)

    def _update_web_state(self, targets: list[dict]):
        """Push latest summary to web layer for dashboard card.

        Note: web.update_state() only supports predefined keys. Instead,
        the dashboard card fetches /api/connection-monitor/summary directly.
        This method updates the collector's own state dict that routes can access.
        """
        try:
            summaries = {}
            for t in targets:
                if t["enabled"]:
                    summaries[t["id"]] = {
                        "label": t["label"],
                        "host": t["host"],
                        **self._cm_storage.get_summary(t["id"], window_seconds=60),
                    }
            self._state = {
                "targets": summaries,
                "capability": self._probe.capability_info(),
            }
        except Exception:
            pass  # Non-critical

    def _ensure_default_targets(self):
        """Seed default targets on first enable."""
        if self._seeded:
            return
        self._seeded = True
        if not self._cm_storage.get_targets():
            self._cm_storage.create_target("Cloudflare DNS", "1.1.1.1")
            self._cm_storage.create_target("Google DNS", "8.8.8.8")
            logger.info("Connection Monitor: seeded default targets")

    def get_storage(self) -> ConnectionMonitorStorage:
        """Expose storage for routes."""
        return self._cm_storage

    def get_probe(self) -> ProbeEngine:
        """Expose probe engine for capability endpoint."""
        return self._probe
```

- [ ] **Step 4: Run tests**

```bash
SECRET_KEY=test python -m pytest tests/modules/connection_monitor/test_collector.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/modules/connection_monitor/collector.py tests/modules/connection_monitor/test_collector.py
git commit -m "feat(connection-monitor): add collector with parallel probing and event integration"
```

---

## Chunk 3: API Routes + Docker

### Task 6: API routes

**Files:**
- Create: `app/modules/connection_monitor/routes.py`
- Create: `tests/modules/connection_monitor/test_routes.py`

- [ ] **Step 1: Write route tests**

Create `tests/modules/connection_monitor/test_routes.py`:

```python
"""Tests for Connection Monitor API routes."""

import csv
import io
import json
import time
from unittest.mock import MagicMock, patch
import pytest

from app.modules.connection_monitor.routes import bp
from app.modules.connection_monitor.storage import ConnectionMonitorStorage


@pytest.fixture
def app(tmp_path):
    from flask import Flask
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)

    db_path = str(tmp_path / "test_cm.db")
    storage = ConnectionMonitorStorage(db_path)

    mock_probe = MagicMock()
    mock_probe.capability_info.return_value = {"method": "tcp", "reason": "no ICMP permission"}

    # Patch the get functions
    with patch("app.modules.connection_monitor.routes._get_cm_storage", return_value=storage):
        with patch("app.modules.connection_monitor.routes._get_probe_engine", return_value=mock_probe):
            yield app, storage


@pytest.fixture
def client(app):
    flask_app, storage = app
    return flask_app.test_client(), storage


class TestTargetsAPI:
    def test_get_empty_targets(self, client):
        c, _ = client
        resp = c.get("/api/connection-monitor/targets")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_create_target(self, client):
        c, _ = client
        resp = c.post(
            "/api/connection-monitor/targets",
            json={"label": "Test", "host": "1.1.1.1"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] == 1

    def test_update_target(self, client):
        c, storage = client
        storage.create_target("Test", "1.1.1.1")
        resp = c.put(
            "/api/connection-monitor/targets/1",
            json={"label": "Updated"},
        )
        assert resp.status_code == 200

    def test_delete_target(self, client):
        c, storage = client
        storage.create_target("Test", "1.1.1.1")
        resp = c.delete("/api/connection-monitor/targets/1")
        assert resp.status_code == 200


class TestSamplesAPI:
    def test_get_samples(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        storage.save_samples([
            {"target_id": tid, "timestamp": time.time(), "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/samples/{tid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1

    def test_get_samples_with_time_range(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 200, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 50, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/samples/{tid}?start={now - 100}")
        data = resp.get_json()
        assert len(data) == 1


class TestSummaryAPI:
    def test_get_summary(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 5, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get("/api/connection-monitor/summary")
        assert resp.status_code == 200


class TestOutagesAPI:
    def test_get_outages(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        samples = [{"target_id": tid, "timestamp": now - 10, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"}]
        for i in range(6):
            samples.append({"target_id": tid, "timestamp": now - 9 + i, "latency_ms": None, "timeout": True, "probe_method": "tcp"})
        samples.append({"target_id": tid, "timestamp": now, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"})
        storage.save_samples(samples)
        resp = c.get(f"/api/connection-monitor/outages/{tid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1


class TestExportAPI:
    def test_csv_export(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/export/{tid}")
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type
        content = resp.data.decode()
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 2  # header + 1 data row


class TestCapabilityAPI:
    def test_capability(self, client):
        c, _ = client
        resp = c.get("/api/connection-monitor/capability")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["method"] == "tcp"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
SECRET_KEY=test python -m pytest tests/modules/connection_monitor/test_routes.py -v
```

- [ ] **Step 3: Implement routes**

Create `app/modules/connection_monitor/routes.py`:

```python
"""API routes for Connection Monitor."""

import csv
import io
import logging
import time

from flask import Blueprint, jsonify, request, Response

logger = logging.getLogger(__name__)

from app.web import require_auth

bp = Blueprint("connection_monitor_module", __name__)


def _get_cm_storage():
    """Get ConnectionMonitorStorage. Uses same DATA_DIR as collector.
    Override in tests via patching."""
    import os
    from app.modules.connection_monitor.storage import ConnectionMonitorStorage
    data_dir = os.environ.get("DATA_DIR", "/data")
    db_path = os.path.join(data_dir, "connection_monitor.db")
    return ConnectionMonitorStorage(db_path)


def _get_probe_engine():
    """Get ProbeEngine capability info. Override in tests via patching."""
    from app.modules.connection_monitor.probe import ProbeEngine
    # Return a lightweight probe just for capability info
    return ProbeEngine(method="tcp")


# --- Targets ---

@bp.route("/api/connection-monitor/targets", methods=["GET"])
@require_auth
def api_get_targets():
    storage = _get_cm_storage()
    if not storage:
        return jsonify([])
    targets = storage.get_targets()
    return jsonify(targets)


@bp.route("/api/connection-monitor/targets", methods=["POST"])
def api_create_target():
    storage = _get_cm_storage()
    if not storage:
        return jsonify({"error": "Connection Monitor not available"}), 503
    data = request.get_json()
    if not data or not data.get("label") or not data.get("host"):
        return jsonify({"error": "label and host required"}), 400
    tid = storage.create_target(
        label=data["label"],
        host=data["host"],
        poll_interval_ms=data.get("poll_interval_ms", 5000),
        probe_method=data.get("probe_method", "auto"),
        tcp_port=data.get("tcp_port", 443),
    )
    return jsonify({"id": tid}), 201


@bp.route("/api/connection-monitor/targets/<int:target_id>", methods=["PUT"])
def api_update_target(target_id):
    storage = _get_cm_storage()
    if not storage:
        return jsonify({"error": "Connection Monitor not available"}), 503
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    storage.update_target(target_id, **data)
    return jsonify({"ok": True})


@bp.route("/api/connection-monitor/targets/<int:target_id>", methods=["DELETE"])
def api_delete_target(target_id):
    storage = _get_cm_storage()
    if not storage:
        return jsonify({"error": "Connection Monitor not available"}), 503
    storage.delete_target(target_id)
    return jsonify({"ok": True})


# --- Samples ---

@bp.route("/api/connection-monitor/samples/<int:target_id>")
def api_get_samples(target_id):
    storage = _get_cm_storage()
    if not storage:
        return jsonify([])
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    limit = request.args.get("limit", 10000, type=int)
    samples = storage.get_samples(target_id, start=start, end=end, limit=limit)
    return jsonify(samples)


# --- Summary ---

@bp.route("/api/connection-monitor/summary")
def api_get_summary():
    storage = _get_cm_storage()
    if not storage:
        return jsonify({})
    targets = storage.get_targets()
    summaries = {}
    for t in targets:
        summaries[t["id"]] = {
            "label": t["label"],
            "host": t["host"],
            "enabled": t["enabled"],
            **storage.get_summary(t["id"], window_seconds=60),
        }
    return jsonify(summaries)


# --- Outages ---

@bp.route("/api/connection-monitor/outages/<int:target_id>")
def api_get_outages(target_id):
    storage = _get_cm_storage()
    if not storage:
        return jsonify([])
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    threshold = request.args.get("threshold", 5, type=int)
    outages = storage.get_outages(target_id, threshold=threshold, start=start, end=end)
    return jsonify(outages)


# --- Export ---

@bp.route("/api/connection-monitor/export/<int:target_id>")
def api_export_csv(target_id):
    storage = _get_cm_storage()
    if not storage:
        return jsonify({"error": "No data"}), 404
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    samples = storage.get_samples(target_id, start=start, end=end, limit=0)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "latency_ms", "timeout", "probe_method"])
    for s in samples:
        writer.writerow([s["timestamp"], s["latency_ms"], s["timeout"], s["probe_method"]])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=connection_monitor_{target_id}.csv"},
    )


# --- Capability ---

@bp.route("/api/connection-monitor/capability")
def api_capability():
    probe = _get_probe_engine()
    if not probe:
        return jsonify({"method": "unknown", "reason": "Connection Monitor not running"})
    return jsonify(probe.capability_info())
```

- [ ] **Step 4: Run tests**

```bash
SECRET_KEY=test python -m pytest tests/modules/connection_monitor/test_routes.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/modules/connection_monitor/routes.py tests/modules/connection_monitor/test_routes.py
git commit -m "feat(connection-monitor): add API routes for targets, samples, outages, export, capability"
```

---

### Task 7: Docker compose - add CAP_NET_RAW

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.dev.yml`

- [ ] **Step 1: Add cap_add to docker-compose.yml**

In `docker-compose.yml`, add under the `docsight` service (after `ports` or `volumes`):

```yaml
    cap_add:
      - NET_RAW
```

- [ ] **Step 2: Add cap_add to docker-compose.dev.yml**

In `docker-compose.dev.yml`, add under the `docsight-v2-dev` service:

```yaml
    cap_add:
      - NET_RAW
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml docker-compose.dev.yml
git commit -m "feat(connection-monitor): add NET_RAW capability for ICMP probing"
```

---

## Chunk 4: UI (Settings + Card + Detail View)

### Task 8: i18n translations

**Files:**
- Create: `app/modules/connection_monitor/i18n/en.json`
- Create: `app/modules/connection_monitor/i18n/de.json`
- Create: `app/modules/connection_monitor/i18n/fr.json`
- Create: `app/modules/connection_monitor/i18n/es.json`

- [ ] **Step 1: Create English translations**

Create `app/modules/connection_monitor/i18n/en.json`:

```json
{
  "connection_monitor": "Connection Monitor",
  "connection_monitor_desc": "Always-on latency monitoring for cable troubleshooting",
  "cm_enable": "Enable Connection Monitor",
  "cm_enable_hint": "Continuously probes configured targets and tracks latency, packet loss, and outages.",
  "cm_poll_interval": "Probe interval (ms)",
  "cm_poll_interval_hint": "Time between probes per target. Default: 5000ms (5s). Minimum: 1000ms.",
  "cm_probe_method": "Probe method",
  "cm_probe_method_hint": "Auto tries ICMP first, falls back to TCP if not available. TCP works everywhere.",
  "cm_probe_auto": "Auto (ICMP preferred)",
  "cm_probe_icmp": "ICMP only",
  "cm_probe_tcp": "TCP only",
  "cm_tcp_port": "TCP port",
  "cm_tcp_port_hint": "Port used for TCP probes. Default: 443.",
  "cm_retention": "Keep samples (days)",
  "cm_retention_hint": "0 = keep all data. Otherwise, delete samples older than this many days.",
  "cm_outage_threshold": "Outage threshold",
  "cm_outage_threshold_hint": "Consecutive timeouts before an outage event is triggered.",
  "cm_loss_warning": "Loss warning (%)",
  "cm_loss_warning_hint": "Packet loss percentage that triggers a warning event.",
  "cm_targets": "Targets",
  "cm_targets_hint": "IP addresses or hostnames to monitor.",
  "cm_add_target": "Add target",
  "cm_target_label": "Label",
  "cm_target_host": "Host",
  "cm_remove": "Remove",
  "cm_status_ok": "OK",
  "cm_status_degraded": "Degraded",
  "cm_status_down": "Down",
  "cm_avg_latency": "Avg latency",
  "cm_packet_loss": "Packet loss",
  "cm_method_icmp": "ICMP",
  "cm_method_tcp": "TCP",
  "cm_method_hint_tcp": "Using TCP probing. For more accurate ICMP probing, add cap_add: [NET_RAW] to your Docker Compose.",
  "cm_detail_title": "Connection Monitor",
  "cm_timerange": "Time range",
  "cm_latency_chart": "Latency",
  "cm_loss_chart": "Packet Loss",
  "cm_availability_chart": "Availability",
  "cm_outage_log": "Outage Log",
  "cm_outage_start": "Start",
  "cm_outage_end": "End",
  "cm_outage_duration": "Duration",
  "cm_outage_ongoing": "Ongoing",
  "cm_export_csv": "Export CSV",
  "cm_no_data": "No data yet. Enable the Connection Monitor in settings to start collecting."
}
```

- [ ] **Step 2: Create German translations**

Create `app/modules/connection_monitor/i18n/de.json`:

```json
{
  "connection_monitor": "Verbindungsmonitor",
  "connection_monitor_desc": "Permanente Latenzueberwachung fuer Kabel-Fehlersuche",
  "cm_enable": "Verbindungsmonitor aktivieren",
  "cm_enable_hint": "Ueberwacht konfigurierte Ziele kontinuierlich und zeichnet Latenz, Paketverlust und Ausfaelle auf.",
  "cm_poll_interval": "Abfrageintervall (ms)",
  "cm_poll_interval_hint": "Zeit zwischen Abfragen pro Ziel. Standard: 5000ms (5s). Minimum: 1000ms.",
  "cm_probe_method": "Abfragemethode",
  "cm_probe_method_hint": "Auto versucht zuerst ICMP, faellt auf TCP zurueck falls nicht verfuegbar. TCP funktioniert ueberall.",
  "cm_probe_auto": "Auto (ICMP bevorzugt)",
  "cm_probe_icmp": "Nur ICMP",
  "cm_probe_tcp": "Nur TCP",
  "cm_tcp_port": "TCP-Port",
  "cm_tcp_port_hint": "Port fuer TCP-Abfragen. Standard: 443.",
  "cm_retention": "Daten behalten (Tage)",
  "cm_retention_hint": "0 = alle Daten behalten. Sonst werden aeltere Daten geloescht.",
  "cm_outage_threshold": "Ausfall-Schwelle",
  "cm_outage_threshold_hint": "Aufeinanderfolgende Timeouts bis ein Ausfall-Event ausgeloest wird.",
  "cm_loss_warning": "Verlust-Warnung (%)",
  "cm_loss_warning_hint": "Paketverlust-Prozentsatz der eine Warnung ausloest.",
  "cm_targets": "Ziele",
  "cm_targets_hint": "IP-Adressen oder Hostnamen zur Ueberwachung.",
  "cm_add_target": "Ziel hinzufuegen",
  "cm_target_label": "Bezeichnung",
  "cm_target_host": "Host",
  "cm_remove": "Entfernen",
  "cm_status_ok": "OK",
  "cm_status_degraded": "Beeintraechtigt",
  "cm_status_down": "Ausgefallen",
  "cm_avg_latency": "Durchschn. Latenz",
  "cm_packet_loss": "Paketverlust",
  "cm_method_icmp": "ICMP",
  "cm_method_tcp": "TCP",
  "cm_method_hint_tcp": "TCP-Abfrage aktiv. Fuer genauere ICMP-Abfragen cap_add: [NET_RAW] in Docker Compose hinzufuegen.",
  "cm_detail_title": "Verbindungsmonitor",
  "cm_timerange": "Zeitraum",
  "cm_latency_chart": "Latenz",
  "cm_loss_chart": "Paketverlust",
  "cm_availability_chart": "Verfuegbarkeit",
  "cm_outage_log": "Ausfall-Protokoll",
  "cm_outage_start": "Beginn",
  "cm_outage_end": "Ende",
  "cm_outage_duration": "Dauer",
  "cm_outage_ongoing": "Andauernd",
  "cm_export_csv": "CSV exportieren",
  "cm_no_data": "Noch keine Daten. Aktiviere den Verbindungsmonitor in den Einstellungen."
}
```

- [ ] **Step 3: Create French translations**

Create `app/modules/connection_monitor/i18n/fr.json`:

```json
{
  "connection_monitor": "Moniteur de connexion",
  "connection_monitor_desc": "Surveillance continue de la latence pour le diagnostic cable",
  "cm_enable": "Activer le moniteur de connexion",
  "cm_enable_hint": "Surveille en continu les cibles configurees et enregistre la latence, la perte de paquets et les pannes.",
  "cm_poll_interval": "Intervalle de sondage (ms)",
  "cm_poll_interval_hint": "Temps entre les sondages par cible. Par defaut: 5000ms (5s). Minimum: 1000ms.",
  "cm_probe_method": "Methode de sondage",
  "cm_probe_method_hint": "Auto essaie ICMP d'abord, bascule sur TCP si indisponible. TCP fonctionne partout.",
  "cm_probe_auto": "Auto (ICMP prefere)",
  "cm_probe_icmp": "ICMP uniquement",
  "cm_probe_tcp": "TCP uniquement",
  "cm_tcp_port": "Port TCP",
  "cm_tcp_port_hint": "Port utilise pour les sondes TCP. Par defaut: 443.",
  "cm_retention": "Conserver les donnees (jours)",
  "cm_retention_hint": "0 = conserver toutes les donnees. Sinon, supprimer les donnees plus anciennes.",
  "cm_outage_threshold": "Seuil de panne",
  "cm_outage_threshold_hint": "Timeouts consecutifs avant qu'un evenement de panne soit declenche.",
  "cm_loss_warning": "Alerte de perte (%)",
  "cm_loss_warning_hint": "Pourcentage de perte de paquets declenchant une alerte.",
  "cm_targets": "Cibles",
  "cm_targets_hint": "Adresses IP ou noms d'hotes a surveiller.",
  "cm_add_target": "Ajouter une cible",
  "cm_target_label": "Libelle",
  "cm_target_host": "Hote",
  "cm_remove": "Supprimer",
  "cm_status_ok": "OK",
  "cm_status_degraded": "Degrade",
  "cm_status_down": "Hors ligne",
  "cm_avg_latency": "Latence moy.",
  "cm_packet_loss": "Perte de paquets",
  "cm_method_icmp": "ICMP",
  "cm_method_tcp": "TCP",
  "cm_method_hint_tcp": "Sondage TCP actif. Pour un sondage ICMP plus precis, ajoutez cap_add: [NET_RAW] dans Docker Compose.",
  "cm_detail_title": "Moniteur de connexion",
  "cm_timerange": "Periode",
  "cm_latency_chart": "Latence",
  "cm_loss_chart": "Perte de paquets",
  "cm_availability_chart": "Disponibilite",
  "cm_outage_log": "Journal des pannes",
  "cm_outage_start": "Debut",
  "cm_outage_end": "Fin",
  "cm_outage_duration": "Duree",
  "cm_outage_ongoing": "En cours",
  "cm_export_csv": "Exporter CSV",
  "cm_no_data": "Pas encore de donnees. Activez le moniteur de connexion dans les parametres."
}
```

- [ ] **Step 4: Create Spanish translations**

Create `app/modules/connection_monitor/i18n/es.json`:

```json
{
  "connection_monitor": "Monitor de conexion",
  "connection_monitor_desc": "Monitoreo continuo de latencia para diagnostico de cable",
  "cm_enable": "Activar monitor de conexion",
  "cm_enable_hint": "Monitorea continuamente los objetivos configurados y registra latencia, perdida de paquetes y cortes.",
  "cm_poll_interval": "Intervalo de sondeo (ms)",
  "cm_poll_interval_hint": "Tiempo entre sondeos por objetivo. Por defecto: 5000ms (5s). Minimo: 1000ms.",
  "cm_probe_method": "Metodo de sondeo",
  "cm_probe_method_hint": "Auto intenta ICMP primero, recurre a TCP si no esta disponible. TCP funciona en todas partes.",
  "cm_probe_auto": "Auto (ICMP preferido)",
  "cm_probe_icmp": "Solo ICMP",
  "cm_probe_tcp": "Solo TCP",
  "cm_tcp_port": "Puerto TCP",
  "cm_tcp_port_hint": "Puerto usado para sondeos TCP. Por defecto: 443.",
  "cm_retention": "Conservar datos (dias)",
  "cm_retention_hint": "0 = conservar todos los datos. De lo contrario, eliminar datos mas antiguos.",
  "cm_outage_threshold": "Umbral de corte",
  "cm_outage_threshold_hint": "Timeouts consecutivos antes de que se active un evento de corte.",
  "cm_loss_warning": "Alerta de perdida (%)",
  "cm_loss_warning_hint": "Porcentaje de perdida de paquetes que activa una alerta.",
  "cm_targets": "Objetivos",
  "cm_targets_hint": "Direcciones IP o nombres de host a monitorear.",
  "cm_add_target": "Agregar objetivo",
  "cm_target_label": "Etiqueta",
  "cm_target_host": "Host",
  "cm_remove": "Eliminar",
  "cm_status_ok": "OK",
  "cm_status_degraded": "Degradado",
  "cm_status_down": "Caido",
  "cm_avg_latency": "Latencia prom.",
  "cm_packet_loss": "Perdida de paquetes",
  "cm_method_icmp": "ICMP",
  "cm_method_tcp": "TCP",
  "cm_method_hint_tcp": "Sondeo TCP activo. Para sondeo ICMP mas preciso, agregue cap_add: [NET_RAW] en Docker Compose.",
  "cm_detail_title": "Monitor de conexion",
  "cm_timerange": "Periodo",
  "cm_latency_chart": "Latencia",
  "cm_loss_chart": "Perdida de paquetes",
  "cm_availability_chart": "Disponibilidad",
  "cm_outage_log": "Registro de cortes",
  "cm_outage_start": "Inicio",
  "cm_outage_end": "Fin",
  "cm_outage_duration": "Duracion",
  "cm_outage_ongoing": "En curso",
  "cm_export_csv": "Exportar CSV",
  "cm_no_data": "Sin datos aun. Active el monitor de conexion en la configuracion."
}
```

- [ ] **Step 5: Commit**

```bash
git add app/modules/connection_monitor/i18n/
git commit -m "feat(connection-monitor): add i18n translations (EN/DE/FR/ES)"
```

---

### Task 9: Settings template

**Files:**
- Create: `app/modules/connection_monitor/templates/connection_monitor_settings.html`

- [ ] **Step 1: Create settings template**

Create `app/modules/connection_monitor/templates/connection_monitor_settings.html`.

Follow the existing pattern from weather/speedtest settings:
- `div.settings-panel` with `id="panel-mod-docsight_connection_monitor"`
- Card with `activity` icon
- Toggle row for enable/disable (hidden input + checkbox pattern)
- Form fields for: poll interval, probe method (select), TCP port, retention days, outage threshold, loss warning
- Target management section with add/remove JS

Reference patterns:
- Toggle: `app/modules/weather/templates/weather_settings.html:15-25`
- Form grid: `app/modules/speedtest/templates/speedtest_settings.html:17-37`
- i18n: Use `{{ t['docsight.connection_monitor.cm_enable'] }}` pattern

- [ ] **Step 2: Commit**

```bash
git add app/modules/connection_monitor/templates/connection_monitor_settings.html
git commit -m "feat(connection-monitor): add settings page template"
```

---

### Task 10: Dashboard summary card template

**Files:**
- Create: `app/modules/connection_monitor/templates/connection_monitor_card.html`
- Create: `app/modules/connection_monitor/static/js/connection-monitor-card.js`

- [ ] **Step 1: Create card template**

Create `app/modules/connection_monitor/templates/connection_monitor_card.html`.

Card structure:
- Container `div#connection-monitor-card`
- Title "Connection Monitor" with `activity` icon
- Status line: "X/Y Targets OK" (populated by JS)
- Per-target row: label, latency value, probe method badge, status dot
- Click handler → navigate to detail view tab

- [ ] **Step 2: Create card JS**

Create `app/modules/connection_monitor/static/js/connection-monitor-card.js`.

Responsibilities:
- Fetch `/api/connection-monitor/summary` on load and periodically (every 10s)
- Render status indicators (green/yellow/red based on packet loss and latency)
- Update badge text ("ICMP" / "TCP")
- Click handler to open detail tab

- [ ] **Step 3: Commit**

```bash
git add app/modules/connection_monitor/templates/connection_monitor_card.html app/modules/connection_monitor/static/js/connection-monitor-card.js
git commit -m "feat(connection-monitor): add dashboard summary card"
```

---

### Task 11: Detail view template and charts

**Files:**
- Create: `app/modules/connection_monitor/templates/connection_monitor_detail.html`
- Create: `app/modules/connection_monitor/static/js/connection-monitor-detail.js`
- Create: `app/modules/connection_monitor/static/js/connection-monitor-charts.js`

- [ ] **Step 1: Create detail template**

Create `app/modules/connection_monitor/templates/connection_monitor_detail.html`.

Layout:
- Header: target selector (tabs), timerange picker (1h/6h/24h/7d/custom), capability info
- Chart containers: `canvas#cm-latency-chart`, `canvas#cm-loss-chart`, `div#cm-availability`
- Outage log table: start, end, duration columns
- Export CSV button

- [ ] **Step 2: Create charts JS**

Create `app/modules/connection_monitor/static/js/connection-monitor-charts.js`.

Wraps `chart-engine.js` `renderChart()` function:
- `renderLatencyChart(canvasId, samples)` — line chart with threshold zones (green <30ms, yellow <100ms, red >100ms)
- `renderLossChart(canvasId, samples, windowMs)` — bar chart showing loss % per time window
- `renderAvailabilityBand(containerId, samples)` — simple colored div strip (green=up, red=down)

Reference: `app/static/js/chart-engine.js` — `renderChart(canvasId, labels, datasets, type, zones, opts)`

- [ ] **Step 3: Create detail JS**

Create `app/modules/connection_monitor/static/js/connection-monitor-detail.js`.

Responsibilities:
- Timerange picker: button group for 1h/6h/24h/7d, updates fetch params
- Target selector: tabs per target, switches data source
- Data fetching: `GET /api/connection-monitor/samples/{id}?start=X&end=Y`
- Outage log: `GET /api/connection-monitor/outages/{id}` → render table
- Export button: triggers download of `/api/connection-monitor/export/{id}?start=X&end=Y`
- Auto-refresh every 10s for the current view

- [ ] **Step 4: Verify i18n check passes**

```bash
python scripts/i18n_check.py --validate
```

- [ ] **Step 5: Commit**

```bash
git add app/modules/connection_monitor/templates/connection_monitor_detail.html app/modules/connection_monitor/static/js/
git commit -m "feat(connection-monitor): add detail view with latency, loss, availability charts"
```

---

## Chunk 5: Integration + Final Verification

### Task 12: Run full test suite

- [ ] **Step 1: Run all Connection Monitor tests**

```bash
SECRET_KEY=test python -m pytest tests/modules/connection_monitor/ -v
```

Expected: All tests pass.

- [ ] **Step 2: Run full DOCSight test suite to verify no regressions**

```bash
SECRET_KEY=test python -m pytest tests/ -q --ignore=tests/e2e
```

Expected: All existing tests pass + new CM tests pass.

- [ ] **Step 3: Fix any failures, commit**

If tests fail, fix and commit individually.

---

### Task 13: Manual integration test with dev instance

- [ ] **Step 1: Build and start dev instance**

```bash
docker compose -f docker-compose.dev.yml build --no-cache && docker compose -f docker-compose.dev.yml up -d
```

- [ ] **Step 2: Enable Connection Monitor in settings**

Navigate to `http://localhost:8767`, go to Settings, find Connection Monitor section, enable it.

Verify:
- Default targets (1.1.1.1, 8.8.8.8) appear
- Probe method shows "TCP" or "ICMP" depending on CAP_NET_RAW

- [ ] **Step 3: Verify data collection**

Wait 30 seconds, then check:
- Dashboard card shows target status
- Detail view shows latency chart with data points
- `/api/connection-monitor/summary` returns data
- `/api/connection-monitor/samples/1` returns samples

- [ ] **Step 4: Verify CSV export**

Click Export CSV button in detail view, verify file downloads with correct data.

- [ ] **Step 5: Verify capability endpoint**

```bash
curl http://localhost:8767/api/connection-monitor/capability
```

Expected: JSON with method and reason fields.

- [ ] **Step 6: Stop dev instance**

```bash
docker compose -f docker-compose.dev.yml down
```

---

### Task 14: Create feature branch and final commit

- [ ] **Step 1: Verify all changes are committed**

```bash
git status
```

Expected: Clean working tree on the feature branch.

- [ ] **Step 2: Push feature branch**

```bash
git push -u origin feature/connection-monitor
```
