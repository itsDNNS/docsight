"""Tests for enriched speedtest storage schema (18 new columns)."""

import sqlite3
import pytest

from app.modules.speedtest.storage import SpeedtestStorage


ENRICHED_COLUMNS = [
    "isp", "server_host", "server_location", "server_country", "server_ip",
    "ping_low", "ping_high", "dl_latency_iqm", "dl_latency_jitter",
    "ul_latency_iqm", "ul_latency_jitter", "dl_bytes", "ul_bytes",
    "dl_elapsed_ms", "ul_elapsed_ms", "external_ip", "is_vpn", "result_url",
]


def _get_columns(db_path):
    with sqlite3.connect(db_path) as conn:
        return [r[1] for r in conn.execute("PRAGMA table_info(speedtest_results)").fetchall()]


def test_ensure_table_creates_enriched_columns(tmp_path):
    """All 18 enriched columns must exist after SpeedtestStorage init."""
    db_path = str(tmp_path / "speedtest.db")
    SpeedtestStorage(db_path)
    cols = _get_columns(db_path)
    for col in ENRICHED_COLUMNS:
        assert col in cols, f"Missing enriched column: {col}"


def test_save_upserts_enriched_fields(tmp_path):
    """Saving a result twice should update enriched fields on the second insert."""
    db_path = str(tmp_path / "speedtest.db")
    storage = SpeedtestStorage(db_path)

    base_result = {
        "id": 42,
        "timestamp": "2026-01-01T12:00:00Z",
        "download_mbps": 500.0,
        "upload_mbps": 50.0,
        "download_human": "500 Mbps",
        "upload_human": "50 Mbps",
        "ping_ms": 10.0,
        "jitter_ms": 1.0,
        "packet_loss_pct": 0.0,
        "server_id": 1,
        "server_name": "Test Server",
        # enriched fields absent on first save
    }

    # First insert - no enriched data
    storage.save_speedtest_results([base_result])

    # Verify enriched fields are NULL after first insert
    row = storage.get_speedtest_by_id(42)
    assert row is not None
    assert row["isp"] is None
    assert row["result_url"] is None
    assert row["is_vpn"] is None

    # Second insert with enriched data
    enriched_result = {
        **base_result,
        "isp": "Deutsche Telekom",
        "server_host": "speedtest.telekom.de",
        "server_location": "Frankfurt",
        "server_country": "Germany",
        "server_ip": "1.2.3.4",
        "ping_low": 8.5,
        "ping_high": 14.2,
        "dl_latency_iqm": 11.1,
        "dl_latency_jitter": 0.9,
        "ul_latency_iqm": 12.3,
        "ul_latency_jitter": 1.2,
        "dl_bytes": 654321,
        "ul_bytes": 123456,
        "dl_elapsed_ms": 9000,
        "ul_elapsed_ms": 8500,
        "external_ip": "5.6.7.8",
        "is_vpn": False,
        "result_url": "https://www.speedtest.net/result/c/abc123",
    }
    storage.save_speedtest_results([enriched_result])

    # Verify enriched fields are updated
    row = storage.get_speedtest_by_id(42)
    assert row is not None
    assert row["isp"] == "Deutsche Telekom"
    assert row["server_host"] == "speedtest.telekom.de"
    assert row["server_location"] == "Frankfurt"
    assert row["server_country"] == "Germany"
    assert row["server_ip"] == "1.2.3.4"
    assert row["ping_low"] == pytest.approx(8.5)
    assert row["ping_high"] == pytest.approx(14.2)
    assert row["dl_latency_iqm"] == pytest.approx(11.1)
    assert row["dl_latency_jitter"] == pytest.approx(0.9)
    assert row["ul_latency_iqm"] == pytest.approx(12.3)
    assert row["ul_latency_jitter"] == pytest.approx(1.2)
    assert row["dl_bytes"] == 654321
    assert row["ul_bytes"] == 123456
    assert row["dl_elapsed_ms"] == 9000
    assert row["ul_elapsed_ms"] == 8500
    assert row["external_ip"] == "5.6.7.8"
    assert row["is_vpn"] == 0  # False -> 0 in SQLite
    assert row["result_url"] == "https://www.speedtest.net/result/c/abc123"

    # Original fields must not change on upsert
    assert row["download_mbps"] == pytest.approx(500.0)
    assert row["ping_ms"] == pytest.approx(10.0)
    assert row["server_name"] == "Test Server"


# ---------------------------------------------------------------------------
# Client parsing tests
# ---------------------------------------------------------------------------

from app.modules.speedtest.client import SpeedtestClient  # noqa: E402

FULL_API_RESPONSE = {
    "id": 1444, "ping": 23.3,
    "download_bits": 1095383784, "upload_bits": 54018392,
    "download_bits_human": "1.10 Gbps", "upload_bits_human": "54.02 Mbps",
    "data": {
        "timestamp": "2026-04-03T14:10:20Z",
        "ping": {"jitter": 3.771, "latency": 23.299, "low": 16.135, "high": 24.368},
        "download": {
            "bandwidth": 136922973, "bytes": 1316377479, "elapsed": 9903,
            "latency": {"iqm": 39.149, "low": 14.115, "high": 115.655, "jitter": 6.651},
        },
        "upload": {
            "bandwidth": 6752299, "bytes": 41127544, "elapsed": 6102,
            "latency": {"iqm": 80.022, "low": 11.653, "high": 1547.885, "jitter": 41.352},
        },
        "packetLoss": 0,
        "isp": "ExampleNet Germany",
        "interface": {"internalIp": "192.0.2.27", "externalIp": "203.0.113.86", "isVpn": False},
        "server": {"id": 44081, "host": "speedtest.example.net", "port": 8080,
                   "name": "ExampleNet Test Server", "location": "Frankfurt am Main",
                   "country": "Germany", "ip": "212.83.32.10"},
        "result": {"id": "abc-uuid", "url": "https://www.speedtest.net/result/c/abc-uuid", "persisted": True},
    },
}


def test_parse_result_extracts_enriched_fields():
    """_parse_result() must extract all 18 enriched fields with correct values and rounding."""
    client = SpeedtestClient.__new__(SpeedtestClient)
    result = client._parse_result(FULL_API_RESPONSE)

    assert result["isp"] == "ExampleNet Germany"
    assert result["server_host"] == "speedtest.example.net"
    assert result["server_location"] == "Frankfurt am Main"
    assert result["server_country"] == "Germany"
    assert result["server_ip"] == "212.83.32.10"
    assert result["ping_low"] == 16.14   # round(16.135, 2)
    assert result["ping_high"] == 24.37  # round(24.368, 2)
    assert result["dl_latency_iqm"] == 39.15   # round(39.149, 2)
    assert result["dl_latency_jitter"] == 6.65  # round(6.651, 2)
    assert result["ul_latency_iqm"] == 80.02    # round(80.022, 2)
    assert result["ul_latency_jitter"] == 41.35  # round(41.352, 2)
    assert result["dl_bytes"] == 1316377479
    assert result["ul_bytes"] == 41127544
    assert result["dl_elapsed_ms"] == 9903
    assert result["ul_elapsed_ms"] == 6102
    assert result["external_ip"] == "203.0.113.86"
    assert result["is_vpn"] is False
    assert result["result_url"] == "https://www.speedtest.net/result/c/abc-uuid"


def test_parse_result_handles_missing_enriched_fields():
    """_parse_result() must return None for all enriched fields when data is minimal."""
    client = SpeedtestClient.__new__(SpeedtestClient)
    minimal_item = {"data": {"timestamp": "2026-04-03T14:10:20Z"}}
    result = client._parse_result(minimal_item)

    for field in ENRICHED_COLUMNS:
        assert result[field] is None, f"Expected None for {field}, got {result[field]!r}"
