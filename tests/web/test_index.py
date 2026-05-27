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


def _element_by_id(html, element_id):
    marker = f'id="{element_id}"'
    marker_idx = html.index(marker)
    start = html.rfind('<div class="metric-card', 0, marker_idx)
    end = html.find('<div class="metric-card', marker_idx + len(marker))
    return html[start:end if end != -1 else len(html)]


def _family_metric(health, avg, minimum=None, maximum=None, available=True):
    return {
        "available": available,
        "avg": avg,
        "min": minimum if minimum is not None else avg,
        "max": maximum if maximum is not None else avg,
        "health": health,
    }


def _family_modulation(value, health="good"):
    return {
        "available": value is not None,
        "value": value,
        "secondary": None,
        "distinct": [value] if value is not None else [],
        "health": health,
    }


def _add_mixed_signal_families(analysis):
    analysis["summary"].update({
        "ds_scqam_power_avg": 1.0,
        "ds_scqam_snr_avg": 36.0,
        "ds_ofdm_power_avg": 0.5,
        "ds_ofdm_mer_avg": 37.0,
        "us_scqam_power_avg": 43.0,
        "us_ofdma_power_avg": None,
        "signal_families": {
            "downstream": {
                "health": "warning",
                "families": {
                    "sc_qam": {
                        "family": "sc_qam",
                        "count": 1,
                        "health": "good",
                        "power": _family_metric("good", 1.0),
                        "snr": _family_metric("good", 36.0),
                        "modulation": _family_modulation("256QAM"),
                    },
                    "ofdm": {
                        "family": "ofdm",
                        "count": 1,
                        "health": "warning",
                        "power": _family_metric("good", 0.5),
                        "mer": _family_metric("warning", 37.0),
                        "modulation": _family_modulation("4096QAM"),
                    },
                },
            },
            "upstream": {
                "health": "warning",
                "families": {
                    "sc_qam": {
                        "family": "sc_qam",
                        "count": 1,
                        "health": "good",
                        "power": _family_metric("good", 43.0),
                        "modulation": _family_modulation("64QAM"),
                    },
                    "ofdma": {
                        "family": "ofdma",
                        "count": 1,
                        "health": "warning",
                        "power": _family_metric("missing", None, available=False),
                        "modulation": _family_modulation("64QAM", "warning"),
                    },
                },
            },
        },
    })
    return analysis


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

    def test_home_renders_downstream_signal_family_cards_without_mixed_average(self, client, sample_analysis):
        _add_mixed_signal_families(sample_analysis)
        sample_analysis["summary"].update({"ds_snr_avg": 38.5})
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        scqam_power_card = _element_by_id(html, "metric-ds-sc-qam-power-card")
        ofdm_power_card = _element_by_id(html, "metric-ds-ofdm-power-card")
        scqam_snr_card = _element_by_id(html, "metric-ds-sc-qam-snr-card")
        ofdm_mer_card = _element_by_id(html, "metric-ds-ofdm-mer-card")
        assert "DS POWER (SC-QAM)" in scqam_power_card
        assert "1.0<span class=\"unit\">dBmV</span>" in scqam_power_card
        assert "256QAM" in scqam_power_card
        status_row_start = scqam_power_card.index('<div class="metric-sub metric-status-row">')
        status_row_end = scqam_power_card.index('</div>', status_row_start)
        status_row = scqam_power_card[status_row_start:status_row_end]
        assert "256QAM" not in status_row
        assert '<div class="metric-sub metric-modulation-row">' in scqam_power_card
        assert "DS POWER (OFDM)" in ofdm_power_card
        assert "0.5<span class=\"unit\">dBmV</span>" in ofdm_power_card
        assert "4096QAM" in ofdm_power_card
        assert "DS SNR (SC-QAM)" in scqam_snr_card
        assert "36.0<span class=\"unit\">dB</span>" in scqam_snr_card
        assert "DS MER (OFDM)" in ofdm_mer_card
        assert "37.0<span class=\"unit\">dB</span>" in ofdm_mer_card
        assert "38.5<span class=\"unit\">dB</span>" not in scqam_snr_card + ofdm_mer_card
        assert '<span class="metric-label">DS SC-QAM</span>' not in html

    def test_home_signal_family_cards_follow_ds_us_order(self, client, sample_analysis):
        _add_mixed_signal_families(sample_analysis)
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        labels = [
            "DS POWER (SC-QAM)",
            "DS POWER (OFDM)",
            "DS SNR (SC-QAM)",
            "DS MER (OFDM)",
            "US POWER (SC-QAM)",
            "US POWER (OFDMA)",
        ]
        positions = [html.index(f'<span class="metric-label">{label}</span>') for label in labels]
        assert positions == sorted(positions)

    def test_home_signal_family_card_status_uses_displayed_average_health(self, client, sample_analysis):
        _add_mixed_signal_families(sample_analysis)
        ofdm_power = sample_analysis["summary"]["signal_families"]["downstream"]["families"]["ofdm"]["power"]
        ofdm_power.update({"avg": 0.6, "min": -7.8, "max": 9.0, "health": "critical"})
        sample_analysis["summary"]["ds_ofdm_power_avg"] = 0.6
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        card = _element_by_id(resp.get_data(as_text=True), "metric-ds-ofdm-power-card")
        assert "0.6<span class=\"unit\">dBmV</span>" in card
        assert "badge badge-good" in card
        assert "badge badge-critical" not in card
        assert "--metric-range-accent: var(--good);" in card

    def test_home_signal_family_cards_show_metric_health_bars(self, client, sample_analysis):
        _add_mixed_signal_families(sample_analysis)
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        for element_id, caption in [
            ("metric-ds-sc-qam-power-card", "Channel min-max"),
            ("metric-ds-ofdm-power-card", "Channel min-max"),
            ("metric-ds-sc-qam-snr-card", "Channel min-max"),
            ("metric-ds-ofdm-mer-card", "Channel min-max"),
            ("metric-us-sc-qam-card", "Channel min-max"),
        ]:
            card = _element_by_id(html, element_id)
            assert 'class="metric-range-viz"' in card
            assert caption in card
        ofdma_card = _element_by_id(html, "metric-us-ofdma-card")
        assert 'class="metric-range-viz"' not in ofdma_card

    def test_home_signal_family_health_bar_falls_back_to_value_for_missing_min_max(self, client, sample_analysis):
        _add_mixed_signal_families(sample_analysis)
        family_metric = sample_analysis["summary"]["signal_families"]["downstream"]["families"]["sc_qam"]["snr"]
        family_metric.pop("min")
        family_metric.pop("max")
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        card = _element_by_id(resp.get_data(as_text=True), "metric-ds-sc-qam-snr-card")
        assert 'class="metric-range-viz"' in card
        assert "Channel min-max" in card
        assert "36.0 — 36.0" in card
        assert "None — None" not in card

    def test_home_renders_upstream_signal_family_cards_separately(self, client, sample_analysis):
        _add_mixed_signal_families(sample_analysis)
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        scqam_card = _element_by_id(html, "metric-us-sc-qam-card")
        ofdma_card = _element_by_id(html, "metric-us-ofdma-card")
        assert "US POWER (SC-QAM)" in scqam_card
        assert "43.0<span class=\"unit\">dBmV</span>" in scqam_card
        assert "64QAM" in scqam_card
        assert "US POWER (OFDMA)" in ofdma_card
        assert "Unavailable<span class=\"unit\">dBmV</span>" in ofdma_card
        assert "badge badge-missing" in ofdma_card

    def test_home_family_cards_expose_family_sparkline_keys(self, client, sample_analysis):
        _add_mixed_signal_families(sample_analysis)
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-spark-key="ds_scqam_power_avg"' in _element_by_id(html, "metric-ds-sc-qam-power-card")
        assert 'data-spark-key="ds_ofdm_power_avg"' in _element_by_id(html, "metric-ds-ofdm-power-card")
        assert 'data-spark-key="ds_scqam_snr_avg"' in _element_by_id(html, "metric-ds-sc-qam-snr-card")
        assert 'data-spark-key="ds_ofdm_mer_avg"' in _element_by_id(html, "metric-ds-ofdm-mer-card")
        assert 'data-spark-key="us_scqam_power_avg"' in _element_by_id(html, "metric-us-sc-qam-card")
        assert 'data-spark-key="us_ofdma_power_avg"' in _element_by_id(html, "metric-us-ofdma-card")

    def test_home_family_cards_use_direction_icons_and_spark_colors(self, client, sample_analysis):
        _add_mixed_signal_families(sample_analysis)
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        for element_id in [
            "metric-ds-sc-qam-power-card",
            "metric-ds-ofdm-power-card",
            "metric-ds-sc-qam-snr-card",
            "metric-ds-ofdm-mer-card",
        ]:
            card = _element_by_id(html, element_id)
            assert 'metric-icon ds-signal"><i data-lucide="arrow-down"' in card
            assert 'data-spark-color="#8b5cf6"' in card
        for element_id in ["metric-us-sc-qam-card", "metric-us-ofdma-card"]:
            card = _element_by_id(html, element_id)
            assert 'metric-icon us-signal"><i data-lucide="arrow-up"' in card
            assert 'data-spark-color="#38bdf8"' in card

    def test_home_removes_modulation_context_when_family_cards_include_ranges(self, client, sample_analysis):
        _add_mixed_signal_families(sample_analysis)
        update_state(analysis=sample_analysis)

        resp = client.get("/?lang=en")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'class="hero-modulation-context"' not in html

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
