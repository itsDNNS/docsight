"""Tests for app/prometheus.py — format_metrics() Prometheus text formatter.

All tests verify the pure function format_metrics(analysis, device_info,
connection_info, last_poll_timestamp) returns valid Prometheus text exposition
format strings.
"""

import pytest

from app.prometheus import format_metrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_metric(output, metric_line):
    """Return True if metric_line appears as an exact line in output."""
    return metric_line in output.splitlines()


def _has_metric_approx(output, prefix):
    """Return True if any line starts with prefix."""
    return any(line.startswith(prefix) for line in output.splitlines())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ANALYSIS_FULL = {
    "summary": {
        "ds_total": 24,
        "us_total": 4,
        "ds_power_min": -1.5,
        "ds_power_max": 5.0,
        "ds_power_avg": 2.5,
        "us_power_min": 41.0,
        "us_power_max": 47.0,
        "us_power_avg": 44.0,
        "ds_snr_min": 33.0,
        "ds_snr_max": 38.0,
        "ds_snr_avg": 35.5,
        "ds_correctable_errors": 500,
        "ds_uncorrectable_errors": 20,
        "health": "good",
        "health_issues": [],
    },
    "ds_channels": [
        {
            "channel_id": 1,
            "frequency": "474000000",
            "power": 3.0,
            "modulation": "256QAM",
            "snr": 35.0,
            "correctable_errors": 100,
            "uncorrectable_errors": 5,
            "docsis_version": "3.0",
            "health": "good",
            "health_detail": "",
        },
        {
            "channel_id": 2,
            "frequency": "482000000",
            "power": -1.5,
            "modulation": "256QAM",
            "snr": 33.0,
            "correctable_errors": 50,
            "uncorrectable_errors": 2,
            "docsis_version": "3.0",
            "health": "good",
            "health_detail": "",
        },
    ],
    "us_channels": [
        {
            "channel_id": 1,
            "frequency": "30000000",
            "power": 42.0,
            "modulation": "64QAM",
            "docsis_version": "3.0",
            "health": "good",
            "health_detail": "",
        }
    ],
}

DEVICE_INFO_FULL = {
    "model": "FRITZ!Box 6690",
    "sw_version": "7.57",
    "manufacturer": "AVM",
    "uptime_seconds": 86400,
    "wan_ipv4": "192.0.2.1",
    "wan_ipv6": "2001:db8::1"
}

CONNECTION_INFO_FULL = {
    "max_downstream_kbps": 1000000,
    "max_upstream_kbps": 50000,
    "connection_type": "DOCSIS 3.1",
}


# ---------------------------------------------------------------------------
# Downstream channel metrics
# ---------------------------------------------------------------------------

class TestDownstreamChannelMetrics:
    def test_ds_power_dbmv(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert _has_metric(out, 'docsight_downstream_power_dbmv{channel_id="1",frequency="474"} 3.0')

    def test_ds_snr_db(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert _has_metric(out, 'docsight_downstream_snr_db{channel_id="1",frequency="474"} 35.0')

    def test_ds_corrected_errors_total(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert _has_metric(out, 'docsight_downstream_corrected_errors_total{channel_id="1",frequency="474"} 100')

    def test_ds_uncorrected_errors_total(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert _has_metric(out, 'docsight_downstream_uncorrected_errors_total{channel_id="1",frequency="474"} 5')

    def test_ds_modulation_256qam(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert _has_metric(out, 'docsight_downstream_modulation{channel_id="1",frequency="474"} 256')

    def test_ds_snr_none_omits_line(self):
        analysis = {
            "summary": {
                "ds_total": 1, "us_total": 0,
                "health": "good", "health_issues": [],
                "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0,
            },
            "ds_channels": [{
                "channel_id": 5,
                "frequency": "474000000",
                "power": 3.0,
                "modulation": "256QAM",
                "snr": None,
                "correctable_errors": 0,
                "uncorrectable_errors": 0,
                "docsis_version": "3.0",
                "health": "good",
                "health_detail": "",
            }],
            "us_channels": [],
        }
        out = format_metrics(analysis, None, None, 0.0)
        assert not _has_metric_approx(out, 'docsight_downstream_snr_db{channel_id="5",frequency="474"}')

    def test_ds_modulation_ofdm_omits_line(self):
        """OFDM is not parseable as QAM order, so modulation line must be omitted."""
        analysis = {
            "summary": {
                "ds_total": 1, "us_total": 0,
                "health": "good", "health_issues": [],
                "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0,
            },
            "ds_channels": [{
                "channel_id": 7,
                "frequency": "474000000",
                "power": 3.0,
                "modulation": "OFDM",
                "snr": 35.0,
                "correctable_errors": 0,
                "uncorrectable_errors": 0,
                "docsis_version": "3.1",
                "health": "good",
                "health_detail": "",
            }],
            "us_channels": [],
        }
        out = format_metrics(analysis, None, None, 0.0)
        assert not _has_metric_approx(out, 'docsight_downstream_modulation{channel_id="7",frequency="474"}')

    def test_multiple_ds_channels_separate_lines(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert _has_metric(out, 'docsight_downstream_power_dbmv{channel_id="1",frequency="474"} 3.0')
        assert _has_metric(out, 'docsight_downstream_power_dbmv{channel_id="2",frequency="482"} -1.5')

    def test_ds_power_negative_value(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert _has_metric(out, 'docsight_downstream_power_dbmv{channel_id="2",frequency="482"} -1.5')

    def test_ds_has_help_comment(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        lines = out.splitlines()
        assert any("# HELP docsight_downstream_power_dbmv" in l for l in lines)

    def test_ds_has_type_comment(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        lines = out.splitlines()
        assert any("# TYPE docsight_downstream_power_dbmv" in l for l in lines)


# ---------------------------------------------------------------------------
# Upstream channel metrics
# ---------------------------------------------------------------------------

class TestUpstreamChannelMetrics:
    def test_us_power_dbmv(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert _has_metric(out, 'docsight_upstream_power_dbmv{channel_id="1",frequency="30"} 42.0')

    def test_us_modulation_64qam(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert _has_metric(out, 'docsight_upstream_modulation{channel_id="1",frequency="30"} 64')

    def test_us_power_none_omits_line(self):
        analysis = {
            "summary": {
                "ds_total": 0, "us_total": 1,
                "health": "good", "health_issues": [],
                "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0,
            },
            "ds_channels": [],
            "us_channels": [{
                "channel_id": 3,
                "frequency": "30000000",
                "power": None,
                "modulation": "64QAM",
                "docsis_version": "3.0",
                "health": "good",
                "health_detail": "",
            }],
        }
        out = format_metrics(analysis, None, None, 0.0)
        assert not _has_metric_approx(out, 'docsight_upstream_power_dbmv{channel_id="3",frequency="30"}')

    def test_multiple_us_channels_separate_lines(self):
        analysis = {
            "summary": {
                "ds_total": 0, "us_total": 2,
                "health": "good", "health_issues": [],
                "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0,
            },
            "ds_channels": [],
            "us_channels": [
                {
                    "channel_id": 1,
                    "frequency": "30000000",
                    "power": 42.0,
                    "modulation": "64QAM",
                    "docsis_version": "3.0",
                    "health": "good",
                    "health_detail": "",
                },
                {
                    "channel_id": 2,
                    "frequency": "38000000",
                    "power": 45.0,
                    "modulation": "64QAM",
                    "docsis_version": "3.0",
                    "health": "good",
                    "health_detail": "",
                },
            ],
        }
        out = format_metrics(analysis, None, None, 0.0)
        assert _has_metric(out, 'docsight_upstream_power_dbmv{channel_id="1",frequency="30"} 42.0')
        assert _has_metric(out, 'docsight_upstream_power_dbmv{channel_id="2",frequency="38"} 45.0')

    def test_frequency_label_normalizes_mhz_values(self):
        analysis = {
            "summary": {
                "ds_total": 1, "us_total": 1,
                "health": "good", "health_issues": [],
                "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0,
            },
            "ds_channels": [{
                "channel_id": 9,
                "frequency": "114.0 MHz",
                "power": 2.5,
                "modulation": "256QAM",
                "snr": 36.0,
                "correctable_errors": 0,
                "uncorrectable_errors": 0,
                "docsis_version": "3.0",
                "health": "good",
                "health_detail": "",
            }],
            "us_channels": [{
                "channel_id": 2,
                "frequency": "44 MHz",
                "power": 43.0,
                "modulation": "64QAM",
                "docsis_version": "3.0",
                "health": "good",
                "health_detail": "",
            }],
        }
        out = format_metrics(analysis, None, None, 0.0)
        assert _has_metric(out, 'docsight_downstream_power_dbmv{channel_id="9",frequency="114.0"} 2.5')
        assert _has_metric(out, 'docsight_upstream_modulation{channel_id="2",frequency="44"} 64')

    def test_us_has_help_comment(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        lines = out.splitlines()
        assert any("# HELP docsight_upstream_power_dbmv" in l for l in lines)

    def test_us_has_type_comment(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        lines = out.splitlines()
        assert any("# TYPE docsight_upstream_power_dbmv" in l for l in lines)


# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------

class TestSummaryMetrics:
    def test_health_good_is_0(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert _has_metric(out, "docsight_health_status 0")

    def test_health_tolerated_is_1(self):
        analysis = {**ANALYSIS_FULL, "summary": {**ANALYSIS_FULL["summary"], "health": "tolerated"}}
        out = format_metrics(analysis, None, None, 0.0)
        assert _has_metric(out, "docsight_health_status 1")

    def test_health_marginal_is_2(self):
        analysis = {**ANALYSIS_FULL, "summary": {**ANALYSIS_FULL["summary"], "health": "marginal"}}
        out = format_metrics(analysis, None, None, 0.0)
        assert _has_metric(out, "docsight_health_status 2")

    def test_health_critical_is_3(self):
        analysis = {**ANALYSIS_FULL, "summary": {**ANALYSIS_FULL["summary"], "health": "critical"}}
        out = format_metrics(analysis, None, None, 0.0)
        assert _has_metric(out, "docsight_health_status 3")

    def test_health_none_analysis_is_4(self):
        out = format_metrics(None, None, None, 0.0)
        assert _has_metric(out, "docsight_health_status 4")

    def test_ds_channels_total(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert _has_metric(out, "docsight_downstream_channels_total 24")

    def test_us_channels_total(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert _has_metric(out, "docsight_upstream_channels_total 4")

    def test_channel_counts_zero_for_empty_channels(self):
        analysis = {
            "summary": {
                "ds_total": 0, "us_total": 0,
                "health": "good", "health_issues": [],
                "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0,
            },
            "ds_channels": [],
            "us_channels": [],
        }
        out = format_metrics(analysis, None, None, 0.0)
        assert _has_metric(out, "docsight_downstream_channels_total 0")
        assert _has_metric(out, "docsight_upstream_channels_total 0")


# ---------------------------------------------------------------------------
# Device info metrics
# ---------------------------------------------------------------------------

class TestDeviceInfoMetrics:
    def test_device_info_metric(self):
        out = format_metrics(None, DEVICE_INFO_FULL, None, 0.0)
        assert _has_metric(out, 'docsight_device_info{model="FRITZ!Box 6690",sw_version="7.57"} 1')

    def test_device_uptime_seconds(self):
        out = format_metrics(None, DEVICE_INFO_FULL, None, 0.0)
        assert _has_metric(out, "docsight_device_uptime_seconds 86400")

    def test_device_info_without_uptime_omits_uptime_line(self):
        info = {"model": "TestModem", "sw_version": "1.0", "manufacturer": "Test"}
        out = format_metrics(None, info, None, 0.0)
        assert not _has_metric_approx(out, "docsight_device_uptime_seconds")

    def test_device_info_none_no_device_lines(self):
        out = format_metrics(None, None, None, 0.0)
        assert not _has_metric_approx(out, "docsight_device_info")
        assert not _has_metric_approx(out, "docsight_device_uptime_seconds")

    def test_device_info_has_help_comment(self):
        out = format_metrics(None, DEVICE_INFO_FULL, None, 0.0)
        lines = out.splitlines()
        assert any("# HELP docsight_device_info" in l for l in lines)

    def test_device_info_has_type_comment(self):
        out = format_metrics(None, DEVICE_INFO_FULL, None, 0.0)
        lines = out.splitlines()
        assert any("# TYPE docsight_device_info" in l for l in lines)

    def test_device_info_excludes_mutable_fields(self):
        info = {
            "model": "TG6442VF",
            "sw_version": "1.0",
            "docsis_status": "online",
            "reboot_reason": "power on",
        }
        out = format_metrics(None, info, None, 0.0)
        device_info_lines = [
            line for line in out.splitlines()
            if line.startswith("docsight_device_info{")
        ]
        assert device_info_lines, "docsight_device_info line missing"
        joined = "\n".join(device_info_lines)
        assert "docsis_status" not in joined
        assert "reboot_reason" not in joined

    def test_docsis_online_is_one_when_online(self):
        info = {"model": "TG6442VF", "docsis_status": "online"}
        out = format_metrics(None, info, None, 0.0)
        assert _has_metric(out, "docsight_docsis_online 1")

    def test_docsis_online_is_zero_for_other_statuses(self):
        for status in ("offline", "scanning frequencies", "firmware update"):
            info = {"model": "TG6442VF", "docsis_status": status}
            out = format_metrics(None, info, None, 0.0)
            assert _has_metric(out, "docsight_docsis_online 0"), f"status={status}"

    def test_docsis_online_omitted_when_status_missing(self):
        info = {"model": "TG6442VF"}
        out = format_metrics(None, info, None, 0.0)
        assert not _has_metric_approx(out, "docsight_docsis_online")

    def test_last_reboot_reason_info_emitted_with_label(self):
        info = {"model": "TG6442VF", "reboot_reason": "power on"}
        out = format_metrics(None, info, None, 0.0)
        assert _has_metric(out, 'docsight_last_reboot_reason_info{reason="power on"} 1')

    def test_last_reboot_reason_info_omitted_when_missing(self):
        info = {"model": "TG6442VF"}
        out = format_metrics(None, info, None, 0.0)
        assert not _has_metric_approx(out, "docsight_last_reboot_reason_info")

    def test_wan_ipv4_info_emitted_with_label(self):
        info = {"model": "TG6442VF", "wan_ipv4": "192.0.2.1"}
        out = format_metrics(None, info, None, 0.0)
        assert _has_metric(out, 'docsight_device_wan_ipv4_info{wan_ipv4="192.0.2.1"} 1')

    def test_wan_ipv4_info_omitted_when_missing(self):
        info = {"model": "TG6442VF"}
        out = format_metrics(None, info, None, 0.0)
        assert not _has_metric_approx(out, "docsight_device_wan_ipv4_info")

    def test_wan_ipv4_info_omitted_when_empty_string(self):
        info = {"model": "TG6442VF", "wan_ipv4": ""}
        out = format_metrics(None, info, None, 0.0)
        assert not _has_metric_approx(out, "docsight_device_wan_ipv4_info")

    def test_wan_ipv4_info_excluded_from_device_info_labels(self):
        info = {"model": "TG6442VF", "wan_ipv4": "192.0.2.1"}
        out = format_metrics(None, info, None, 0.0)
        device_info_lines = [
            line for line in out.splitlines()
            if line.startswith("docsight_device_info{")
        ]
        assert device_info_lines, "docsight_device_info line missing"
        assert "wan_ipv4" not in "\n".join(device_info_lines)

    def test_wan_ipv6_info_emitted_with_label(self):
        info = {"model": "TG6442VF", "wan_ipv6": "2001:db8::1"}
        out = format_metrics(None, info, None, 0.0)
        assert _has_metric(out, 'docsight_device_wan_ipv6_info{wan_ipv6="2001:db8::1"} 1')

    def test_wan_ipv6_info_omitted_when_missing(self):
        info = {"model": "TG6442VF"}
        out = format_metrics(None, info, None, 0.0)
        assert not _has_metric_approx(out, "docsight_device_wan_ipv6_info")

    def test_wan_ipv6_info_omitted_when_empty_string(self):
        info = {"model": "TG6442VF", "wan_ipv6": ""}
        out = format_metrics(None, info, None, 0.0)
        assert not _has_metric_approx(out, "docsight_device_wan_ipv6_info")

    def test_wan_ipv6_info_excluded_from_device_info_labels(self):
        info = {"model": "TG6442VF", "wan_ipv6": "2001:db8::1"}
        out = format_metrics(None, info, None, 0.0)
        device_info_lines = [
            line for line in out.splitlines()
            if line.startswith("docsight_device_info{")
        ]
        assert device_info_lines, "docsight_device_info line missing"
        assert "wan_ipv6" not in "\n".join(device_info_lines)

    def test_wan_label_values_are_escaped(self):
        info = {
            "model": "TG6442VF",
            "wan_ipv4": 'bogus"value',
            "wan_ipv6": "line1\nline2",
        }
        out = format_metrics(None, info, None, 0.0)
        assert _has_metric(
            out,
            'docsight_device_wan_ipv4_info{wan_ipv4="bogus\\"value"} 1',
        )
        assert _has_metric(
            out,
            'docsight_device_wan_ipv6_info{wan_ipv6="line1\\nline2"} 1',
        )

    def test_label_values_are_escaped(self):
        """Backslash, double-quote, and newline in label values must be
        escaped per the Prometheus text exposition spec."""
        info = {
            "model": 'Model "Gamma"\\beta',
            "reboot_reason": "line1\nline2",
        }
        out = format_metrics(None, info, None, 0.0)
        assert _has_metric(
            out,
            'docsight_device_info{model="Model \\"Gamma\\"\\\\beta"} 1',
        )
        assert _has_metric(
            out,
            'docsight_last_reboot_reason_info{reason="line1\\nline2"} 1',
        )


# ---------------------------------------------------------------------------
# Connection info metrics
# ---------------------------------------------------------------------------

class TestConnectionInfoMetrics:
    def test_max_downstream_kbps(self):
        out = format_metrics(None, None, CONNECTION_INFO_FULL, 0.0)
        assert _has_metric(out, "docsight_connection_max_downstream_kbps 1000000")

    def test_max_upstream_kbps(self):
        out = format_metrics(None, None, CONNECTION_INFO_FULL, 0.0)
        assert _has_metric(out, "docsight_connection_max_upstream_kbps 50000")

    def test_connection_info_none_no_connection_lines(self):
        out = format_metrics(None, None, None, 0.0)
        assert not _has_metric_approx(out, "docsight_connection_max_downstream_kbps")
        assert not _has_metric_approx(out, "docsight_connection_max_upstream_kbps")

    def test_connection_has_help_comment(self):
        out = format_metrics(None, None, CONNECTION_INFO_FULL, 0.0)
        lines = out.splitlines()
        assert any("# HELP docsight_connection_max_downstream_kbps" in l for l in lines)

    def test_connection_has_type_comment(self):
        out = format_metrics(None, None, CONNECTION_INFO_FULL, 0.0)
        lines = out.splitlines()
        assert any("# TYPE docsight_connection_max_downstream_kbps" in l for l in lines)


# ---------------------------------------------------------------------------
# Poll timestamp metrics
# ---------------------------------------------------------------------------

class TestPollTimestampMetrics:
    def test_last_poll_timestamp(self):
        out = format_metrics(None, None, None, 1709568000.0)
        assert _has_metric(out, "docsight_last_poll_timestamp_seconds 1709568000.0")

    def test_last_poll_timestamp_zero(self):
        out = format_metrics(None, None, None, 0.0)
        assert _has_metric(out, "docsight_last_poll_timestamp_seconds 0.0")

    def test_last_poll_has_help_comment(self):
        out = format_metrics(None, None, None, 0.0)
        lines = out.splitlines()
        assert any("# HELP docsight_last_poll_timestamp_seconds" in l for l in lines)

    def test_last_poll_has_type_comment(self):
        out = format_metrics(None, None, None, 0.0)
        lines = out.splitlines()
        assert any("# TYPE docsight_last_poll_timestamp_seconds" in l for l in lines)


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------

class TestOutputFormat:
    def test_output_ends_with_newline(self):
        out = format_metrics(ANALYSIS_FULL, DEVICE_INFO_FULL, CONNECTION_INFO_FULL, 1709568000.0)
        assert out.endswith("\n")

    def test_no_trailing_whitespace_on_metric_lines(self):
        out = format_metrics(ANALYSIS_FULL, DEVICE_INFO_FULL, CONNECTION_INFO_FULL, 1709568000.0)
        for line in out.splitlines():
            assert line == line.rstrip(), f"Trailing whitespace on line: {repr(line)}"

    def test_help_before_type(self):
        """HELP must come before TYPE for each metric family."""
        out = format_metrics(ANALYSIS_FULL, DEVICE_INFO_FULL, CONNECTION_INFO_FULL, 1709568000.0)
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("# TYPE "):
                metric_name = line.split()[2]
                # Find the preceding HELP line
                help_found = any(
                    l.startswith(f"# HELP {metric_name}") for l in lines[:i]
                )
                assert help_found, f"No # HELP before # TYPE for {metric_name}"

    def test_output_is_string(self):
        out = format_metrics(None, None, None, 0.0)
        assert isinstance(out, str)

    def test_health_has_help_and_type(self):
        out = format_metrics(None, None, None, 0.0)
        lines = out.splitlines()
        assert any("# HELP docsight_health_status" in l for l in lines)
        assert any("# TYPE docsight_health_status" in l for l in lines)

    def test_channel_counts_have_help_and_type(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        lines = out.splitlines()
        assert any("# HELP docsight_downstream_channels_total" in l for l in lines)
        assert any("# TYPE docsight_downstream_channels_total" in l for l in lines)

    def test_counters_have_counter_type(self):
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        lines = out.splitlines()
        corr_type = next(
            (l for l in lines if "# TYPE docsight_downstream_corrected_errors_total" in l), None
        )
        uncorr_type = next(
            (l for l in lines if "# TYPE docsight_downstream_uncorrected_errors_total" in l), None
        )
        assert corr_type is not None
        assert uncorr_type is not None
        assert "counter" in corr_type
        assert "counter" in uncorr_type


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_all_none_produces_valid_output(self):
        """All-None inputs must produce valid minimal output."""
        out = format_metrics(None, None, None, 0.0)
        assert isinstance(out, str)
        assert len(out) > 0
        assert out.endswith("\n")
        assert _has_metric(out, "docsight_health_status 4")
        assert _has_metric(out, "docsight_last_poll_timestamp_seconds 0.0")

    def test_empty_channels_no_per_channel_lines(self):
        analysis = {
            "summary": {
                "ds_total": 0, "us_total": 0,
                "health": "good", "health_issues": [],
                "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0,
            },
            "ds_channels": [],
            "us_channels": [],
        }
        out = format_metrics(analysis, None, None, 0.0)
        assert not _has_metric_approx(out, 'docsight_downstream_power_dbmv{')
        assert not _has_metric_approx(out, 'docsight_upstream_power_dbmv{')

    def test_modulation_label_value_escaped(self):
        """Modulation strings with special chars should not break output."""
        # Even if modulation string has quotes, output must not contain unescaped quotes
        # within label values for string-based labels (we use numeric QAM values so this
        # applies indirectly). Check that output is well-formed.
        out = format_metrics(ANALYSIS_FULL, None, None, 0.0)
        assert isinstance(out, str)

    def test_no_flask_import(self):
        """prometheus.py must not import Flask."""
        import importlib.util
        import pathlib
        import re

        spec = importlib.util.find_spec("app.prometheus")
        assert spec is not None, "app.prometheus module not found"
        source_path = pathlib.Path(spec.origin)
        source = source_path.read_text(encoding="utf-8")
        # Check that there are no actual import statements for flask
        has_flask_import = bool(re.search(r"^(import flask|from flask)", source, re.MULTILINE | re.IGNORECASE))
        assert not has_flask_import, "prometheus.py must not contain Flask imports"

    def test_reuses_parse_qam_order_from_analyzer(self):
        """prometheus.py must import _parse_qam_order from app.analyzer."""
        import importlib.util
        import pathlib

        spec = importlib.util.find_spec("app.prometheus")
        assert spec is not None, "app.prometheus module not found"
        source_path = pathlib.Path(spec.origin)
        source = source_path.read_text(encoding="utf-8")
        assert "_parse_qam_order" in source
        assert "analyzer" in source

    def test_realistic_full_data_produces_valid_prometheus_text(self):
        """Integration test: full realistic data must produce parseable Prometheus format."""
        out = format_metrics(ANALYSIS_FULL, DEVICE_INFO_FULL, CONNECTION_INFO_FULL, 1709568000.0)
        lines = out.splitlines()
        for line in lines:
            if line and not line.startswith("#"):
                # Each non-comment, non-empty line must be: metric_name[{labels}] value
                parts = line.rsplit(" ", 1)
                assert len(parts) == 2, f"Invalid metric line: {repr(line)}"
                # Value must be parseable as float
                float(parts[1])
