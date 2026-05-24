"""Tests for index/dashboard rendering paths."""

import json

import pytest

from app.web import app, update_state, init_config, init_storage, _snr_channel_family
from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.modules.bnetz.storage import BnetzStorage


def _metric_card(html, label):
    label_markup = f'<span class="metric-label">{label}</span>'
    label_idx = html.index(label_markup)
    start = html.rfind('<div class="metric-card', 0, label_idx)
    end = html.find('<div class="metric-card', label_idx)
    return html[start:end if end != -1 else len(html)]


class TestIndexRoute:
    @pytest.mark.parametrize(
        ("channel", "family"),
        [
            ({"modulation": "256QAM", "docsis_version": "3.1"}, "sc_qam"),
            ({"type": "256QAM", "docsis_version": "3.1"}, "sc_qam"),
            ({"modulation": "4096QAM", "docsis_version": "3.1"}, "ofdm"),
            ({"type": "OFDM", "modulation": "4096QAM", "docsis_version": "3.1"}, "ofdm"),
        ],
    )
    def test_snr_channel_family_preserves_explicit_basis(self, channel, family):
        assert _snr_channel_family(channel) == family

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

    def test_index_accepts_unsupported_none_error_counter(self, client, sample_analysis):
        sample_analysis["summary"]["errors_supported"] = False
        sample_analysis["summary"]["ds_correctable_errors"] = None
        sample_analysis["summary"]["ds_uncorrectable_errors"] = None
        update_state(analysis=sample_analysis)

        resp = client.get("/")

        assert resp.status_code == 200
        assert b'id="metric-errors-card"' not in resp.data

    def test_index_partial_error_support_hides_uncomputable_error_card(self, client, sample_analysis):
        sample_analysis["summary"]["errors_supported"] = True
        sample_analysis["summary"]["ds_correctable_errors"] = None
        sample_analysis["summary"]["ds_uncorrectable_errors"] = 1000
        sample_analysis["summary"]["ds_uncorr_pct"] = None
        update_state(analysis=sample_analysis)

        resp = client.get("/")

        assert resp.status_code == 200
        assert b'id="metric-errors-card"' not in resp.data
        assert b">None<" not in resp.data
        assert b"None Corr" not in resp.data

    def test_average_kpi_cards_do_not_use_worst_channel_status(self, client, sample_analysis):
        """Average Home KPI cards keep value, marker, color, and badge aligned."""
        summary = sample_analysis["summary"]
        summary.update({
            "ds_power_min": -6.9,
            "ds_power_max": 9.3,
            "ds_power_avg": 0.9,
            "ds_snr_min": 34.0,
            "ds_snr_max": 42.0,
            "ds_snr_avg": 37.1,
            "health": "critical",
            "health_issues": ["ds_power_critical", "snr_critical"],
        })
        sample_analysis["ds_channels"] = [
            {
                "channel_id": 1,
                "frequency": "602 MHz",
                "power": 0.9,
                "snr": 37.1,
                "modulation": "256QAM",
                "docsis_version": "3.1",
                "correctable_errors": 0,
                "uncorrectable_errors": 0,
                "health": "critical",
                "health_detail": "power critical; snr critical",
            }
        ]
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        ds_card = _metric_card(html, "DS Power")
        snr_card = _metric_card(html, "DS SNR (SC-QAM)")
        assert "0.9<span class=\"unit\">dBmV</span>" in ds_card
        assert "badge badge-good" in ds_card
        assert "--metric-range-accent: var(--good);" in ds_card
        assert "37.1<span class=\"unit\">dB</span>" in snr_card
        assert "badge badge-good" in snr_card
        assert "--metric-range-accent: var(--good);" in snr_card
        assert "Critical" in html

    def test_snr_card_uses_sc_qam_basis_for_sc_qam_channels(self, client, sample_analysis):
        sample_analysis["summary"].update({
            "ds_total": 2,
            "ds_snr_min": 35.0,
            "ds_snr_avg": 36.0,
            "ds_snr_max": 37.0,
        })
        sample_analysis["ds_channels"] = [
            {
                "channel_id": 1,
                "frequency": "602 MHz",
                "power": 3.0,
                "snr": 35.0,
                "modulation": "256QAM",
                "docsis_version": "3.1",
                "correctable_errors": 0,
                "uncorrectable_errors": 0,
                "health": "good",
                "health_detail": "",
            },
            {
                "channel_id": 2,
                "frequency": "610 MHz",
                "power": 3.1,
                "snr": 37.0,
                "modulation": "256QAM",
                "docsis_version": "3.1",
                "correctable_errors": 0,
                "uncorrectable_errors": 0,
                "health": "good",
                "health_detail": "",
            },
        ]
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        snr_card = _metric_card(resp.get_data(as_text=True), "DS SNR (SC-QAM)")
        assert "36.0<span class=\"unit\">dB</span>" in snr_card
        assert "Channel min-max" in snr_card
        assert "Avg across all DS channels" not in snr_card
        assert "OFDM/MER only" not in snr_card

    def test_snr_card_uses_ofdm_mer_basis_when_only_ofdm_available(self, client, sample_analysis):
        sample_analysis["summary"].update({
            "ds_total": 1,
            "ds_snr_min": 41.0,
            "ds_snr_avg": 41.0,
            "ds_snr_max": 41.0,
        })
        sample_analysis["ds_channels"] = [
            {
                "channel_id": 33,
                "frequency": "774 MHz",
                "power": 1.0,
                "snr": 41.0,
                "modulation": "OFDM",
                "docsis_version": "3.1",
                "correctable_errors": 0,
                "uncorrectable_errors": 0,
                "health": "good",
                "health_detail": "",
            },
        ]
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        snr_card = _metric_card(resp.get_data(as_text=True), "DS MER (OFDM)")
        assert "41.0<span class=\"unit\">dB</span>" in snr_card
        assert "Avg across all DS channels" not in snr_card
        assert "SC-QAM only" not in snr_card

    def test_snr_card_prefers_sc_qam_basis_when_mixed_with_ofdm(self, client, sample_analysis):
        sample_analysis["summary"].update({
            "ds_total": 2,
            "ds_snr_min": 36.0,
            "ds_snr_avg": 38.5,
            "ds_snr_max": 41.0,
        })
        sample_analysis["ds_channels"] = [
            {
                "channel_id": 1,
                "frequency": "602 MHz",
                "power": 3.0,
                "snr": 36.0,
                "modulation": "256QAM",
                "docsis_version": "3.1",
                "correctable_errors": 0,
                "uncorrectable_errors": 0,
                "health": "good",
                "health_detail": "",
            },
            {
                "channel_id": 33,
                "frequency": "774 MHz",
                "power": 1.0,
                "snr": 41.0,
                "modulation": "OFDM",
                "docsis_version": "3.1",
                "correctable_errors": 0,
                "uncorrectable_errors": 0,
                "health": "good",
                "health_detail": "",
            },
        ]
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        snr_card = _metric_card(resp.get_data(as_text=True), "DS SNR (SC-QAM)")
        assert "36.0<span class=\"unit\">dB</span>" in snr_card
        assert "38.5<span class=\"unit\">dB</span>" not in snr_card
        assert "Avg across all DS channels" not in snr_card

    def test_snr_card_treats_docsis31_high_qam_profile_as_ofdm_mer(self, client, sample_analysis):
        sample_analysis["summary"].update({
            "ds_total": 1,
            "ds_snr_min": 42.0,
            "ds_snr_avg": 42.0,
            "ds_snr_max": 42.0,
        })
        sample_analysis["ds_channels"] = [
            {
                "channel_id": 33,
                "frequency": "774 MHz",
                "power": 1.0,
                "snr": 42.0,
                "modulation": "4096QAM",
                "docsis_version": "3.1",
                "correctable_errors": 0,
                "uncorrectable_errors": 0,
                "health": "good",
                "health_detail": "",
            },
        ]
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        snr_card = _metric_card(resp.get_data(as_text=True), "DS MER (OFDM)")
        assert "42.0<span class=\"unit\">dB</span>" in snr_card
        assert "DS SNR (SC-QAM)" not in snr_card

    def test_snr_card_uses_fallback_label_for_unknown_family(self, client, sample_analysis):
        sample_analysis["summary"].update({
            "ds_total": 1,
            "ds_snr_min": 39.0,
            "ds_snr_avg": 39.0,
            "ds_snr_max": 39.0,
        })
        sample_analysis["ds_channels"] = [
            {
                "channel_id": 1,
                "frequency": "602 MHz",
                "power": 1.0,
                "snr": 39.0,
                "modulation": "",
                "docsis_version": "",
                "correctable_errors": 0,
                "uncorrectable_errors": 0,
                "health": "good",
                "health_detail": "",
            },
        ]
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        snr_card = _metric_card(resp.get_data(as_text=True), "SNR/MER")
        assert "39.0<span class=\"unit\">dB</span>" in snr_card
        assert "Avg across all DS channels" not in snr_card

    def test_home_surfaces_normal_modulation_context(self, client, sample_analysis):
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'class="hero-modulation-context"' in html
        assert 'data-modulation-dir="ds"' in html
        assert 'data-modulation-dir="us"' in html
        assert "256QAM" in html
        assert "64QAM" in html
        assert 'href="#modulation"' in html
        assert "Modulation Performance" in html

    def test_home_marks_reduced_upstream_modulation_as_explicit_cause(self, client, sample_analysis):
        sample_analysis["summary"].update({
            "health": "warning",
            "health_issues": ["us_modulation_marginal"],
        })
        sample_analysis["us_channels"][0].update({
            "modulation": "32QAM",
            "health": "warning",
            "health_detail": "modulation marginal",
        })
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-modulation-dir="us"' in html
        assert "32QAM" in html
        assert "Upstream modulation degraded" in html
        assert "Reduced modulation contributes to this state" in html
        assert 'class="hero-modulation-card hero-modulation-warn"' in html
        assert 'href="#modulation"' in html

    @pytest.mark.parametrize(
        ("issue", "detail", "expected_label"),
        [
            ("ds_modulation_critical", "modulation critical", "Modulation kritisch degradiert"),
            ("ds_modulation_marginal", "modulation warning", "Modulation degradiert"),
            ("ds_modulation_tolerated", "modulation tolerated", "Modulation degradiert"),
        ],
    )
    def test_home_translates_downstream_modulation_issues_in_german_dashboard(
        self, client, sample_analysis, issue, detail, expected_label
    ):
        sample_analysis["summary"].update({
            "health": "critical" if issue == "ds_modulation_critical" else "marginal",
            "health_issues": [issue],
        })
        sample_analysis["ds_channels"][0].update({
            "modulation": "64QAM",
            "health": "critical" if issue == "ds_modulation_critical" else "warning",
            "health_detail": detail,
        })
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=de")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert issue not in html
        assert expected_label in html
        assert "Downstream-Details bleiben in der Modulationsansicht" in html

    def test_home_marks_critical_upstream_modulation(self, client, sample_analysis):
        sample_analysis["summary"].update({
            "health": "critical",
            "health_issues": ["us_modulation_critical"],
        })
        sample_analysis["us_channels"][0].update({
            "modulation": "8QAM",
            "health": "critical",
            "health_detail": "modulation critical",
        })
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "8QAM" in html
        assert "Upstream modulation critically degraded" in html
        assert 'class="hero-modulation-card hero-modulation-crit"' in html

    def test_home_modulation_context_handles_missing_modulation_without_false_alarm(self, client, sample_analysis):
        for channel in sample_analysis["ds_channels"] + sample_analysis["us_channels"]:
            channel["modulation"] = None
            channel["health"] = "good"
            channel["health_detail"] = ""
        sample_analysis["summary"].update({"health": "good", "health_issues": []})
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'class="hero-modulation-context"' in html
        modulation_context = html[
            html.index('class="hero-modulation-context"'):html.index('class="hero-chart-wrap"')
        ]
        assert ">N/A<" in modulation_context
        assert "Modulation data unavailable" not in modulation_context
        assert "No current QAM value reported by the modem" in modulation_context
        assert "None" not in modulation_context
        assert 'class="hero-modulation-card hero-modulation-warn"' not in modulation_context
        assert 'class="hero-modulation-card hero-modulation-crit"' not in modulation_context

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
