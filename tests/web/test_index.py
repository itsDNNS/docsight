"""Tests for index/dashboard rendering paths."""

import json
from app.web import app, update_state, init_config, init_storage
from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.modules.bnetz.storage import BnetzStorage

class TestIndexRoute:
    def test_redirect_to_setup_when_unconfigured(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data2"))
        init_config(mgr)
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/")
            assert resp.status_code == 302
            assert "/setup" in resp.headers["Location"]

    def test_index_renders(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"DOCSight" in resp.data

    def test_index_with_lang(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        resp = client.get("/?lang=de")
        assert resp.status_code == 200

    def test_index_hides_error_card_when_unsupported(self, client, sample_analysis):
        sample_analysis["summary"]["errors_supported"] = False
        sample_analysis["summary"]["ds_correctable_errors"] = 0
        sample_analysis["summary"]["ds_uncorrectable_errors"] = 0
        sample_analysis["ds_channels"][0]["correctable_errors"] = None
        sample_analysis["ds_channels"][0]["uncorrectable_errors"] = None
        update_state(analysis=sample_analysis)

        resp = client.get("/")

        assert resp.status_code == 200
        assert b'id="metric-errors-card"' not in resp.data
        assert b"N/A</div>" not in resp.data

    def test_index_with_incomplete_bnetz(self, tmp_path, sample_analysis):
        """Dashboard hides BNetzA card when entry has NULL fields (#148)."""
        mgr = ConfigManager(str(tmp_path / "data_bnetz"))
        mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
        init_config(mgr)
        storage = SnapshotStorage(str(tmp_path / "data_bnetz" / "docsight.db"))
        init_storage(storage)
        app.config["TESTING"] = True
        # Save a BNetzA measurement with all numeric fields as None
        bs = BnetzStorage(storage.db_path)
        bs.save_bnetz_measurement({
            "date": "2025-06-01",
            "measurements_download": [],
            "measurements_upload": [],
        })
        update_state(analysis=sample_analysis)
        with app.test_client() as c:
            resp = c.get("/")
        assert resp.status_code == 200
        assert b"bnetz_has_deviation" not in resp.data  # card should not render

    def test_no_docsis_shows_placeholder(self, client):
        """Generic router with empty channels shows no-DOCSIS placeholder."""
        analysis = {
            "summary": {
                "ds_total": 0, "us_total": 0,
                "ds_power_min": 0, "ds_power_max": 0, "ds_power_avg": 0,
                "us_power_min": 0, "us_power_max": 0, "us_power_avg": 0,
                "ds_snr_min": 0, "ds_snr_avg": 0, "ds_snr_max": 0,
                "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0,
                "ds_uncorr_pct": 0,
                "health": "good", "health_issues": [],
                "us_capacity_mbps": 0,
            },
            "ds_channels": [],
            "us_channels": [],
        }
        update_state(analysis=analysis)
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"no-docsis-placeholder" in resp.data
        # DOCSIS-specific sections should NOT appear
        assert b"hero-card" not in resp.data
        assert b"channel-table" not in resp.data

    def test_no_docsis_shows_speedtest_card(self, tmp_path):
        """When has_docsis=false but speedtest is configured, speed card appears."""
        mgr = ConfigManager(str(tmp_path / "data_speed"))
        mgr.save({
            "modem_type": "generic",
            "speedtest_tracker_url": "http://speedtest.local",
            "speedtest_tracker_token": "testtoken123",
        })
        init_config(mgr)
        init_storage(None)
        app.config["TESTING"] = True

        analysis = {
            "summary": {
                "ds_total": 0, "us_total": 0,
                "ds_power_min": 0, "ds_power_max": 0, "ds_power_avg": 0,
                "us_power_min": 0, "us_power_max": 0, "us_power_avg": 0,
                "ds_snr_min": 0, "ds_snr_avg": 0, "ds_snr_max": 0,
                "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0,
                "ds_uncorr_pct": 0,
                "health": "good", "health_issues": [],
                "us_capacity_mbps": 0,
            },
            "ds_channels": [],
            "us_channels": [],
        }
        update_state(
            analysis=analysis,
            speedtest_latest={
                "download_mbps": 230.5,
                "upload_mbps": 41.2,
                "ping_ms": 12.0,
                "jitter_ms": 1.5,
                "packet_loss_pct": 0,
            },
        )
        with app.test_client() as c:
            resp = c.get("/")
        assert resp.status_code == 200
        html = resp.data
        # No-DOCSIS placeholder should still appear
        assert b"no-docsis-placeholder" in html
        # Speed card should appear in the non-DOCSIS section
        assert b"230" in html  # download speed value
        assert b"41" in html   # upload speed value
        assert b"12 ms Ping" in html

class TestIndexSegmentUtilizationVisibility:
    def test_index_hides_segment_tab_when_disabled(self, client, config_mgr, sample_analysis):
        config_mgr.save({"segment_utilization_enabled": False})
        init_config(config_mgr)
        update_state(analysis=sample_analysis)
        resp = client.get("/?lang=en")
        assert resp.status_code == 200
        assert b'data-view="segment-utilization"' not in resp.data
