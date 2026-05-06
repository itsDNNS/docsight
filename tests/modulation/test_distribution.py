"""Tests for modulation distribution and intraday/distribution outputs."""

from datetime import datetime, timezone

from app.modules.modulation.engine import DISCLAIMER, compute_distribution, compute_distribution_v2, compute_intraday


def _make_snapshot(timestamp, us_channels=None, ds_channels=None):
    return {
        "timestamp": timestamp,
        "us_channels": us_channels or [],
        "ds_channels": ds_channels or [],
        "summary": {},
    }


def _make_channels(modulations, docsis_version="3.0"):
    return [
        {"modulation": m, "channel_id": i, "docsis_version": docsis_version}
        for i, m in enumerate(modulations)
    ]

# ── _parse_qam_order ──

class TestComputeDistributionV2:
    def test_empty_snapshots(self):
        result = compute_distribution_v2([], "us", "UTC")
        assert result["sample_count"] == 0
        assert result["protocol_groups"] == []
        assert result["aggregate"]["health_index"] is None
        assert result["disclaimer"] == DISCLAIMER

    def test_single_protocol_group(self):
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                us_channels=_make_channels(["64QAM", "64QAM", "64QAM", "64QAM"]),
            )
        ]
        result = compute_distribution_v2(snaps, "us", "UTC")
        assert len(result["protocol_groups"]) == 1
        pg = result["protocol_groups"][0]
        assert pg["docsis_version"] == "3.0"
        assert pg["max_qam"] == "64QAM"
        assert pg["health_index"] == 100.0  # US 3.0 at 64QAM = max
        assert pg["channel_count"] == 4

    def test_mixed_protocol_groups(self):
        us_channels = (
            _make_channels(["64QAM", "64QAM"], docsis_version="3.0") +
            _make_channels(["1024QAM"], docsis_version="3.1")
        )
        # Fix channel_ids to be unique
        for i, ch in enumerate(us_channels):
            ch["channel_id"] = i
        snaps = [_make_snapshot("2026-03-01T10:00:00Z", us_channels=us_channels)]
        result = compute_distribution_v2(snaps, "us", "UTC")
        assert len(result["protocol_groups"]) == 2
        versions = [pg["docsis_version"] for pg in result["protocol_groups"]]
        assert "3.0" in versions
        assert "3.1" in versions

    def test_us31_128qam_does_not_count_as_low_qam(self):
        us_channels = [
            {"channel_id": 41, "modulation": "128QAM", "docsis_version": "3.1"},
        ]
        snaps = [_make_snapshot("2026-03-01T10:00:00Z", us_channels=us_channels)]
        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["docsis_version"] == "3.1"
        assert pg["degraded_channel_count"] == 0
        assert pg["low_qam_pct"] == 0.0

    def test_us31_512qam_not_counted_as_degraded(self):
        us_channels = [
            {"channel_id": 41, "modulation": "512QAM", "docsis_version": "3.1"},
        ]
        snaps = [_make_snapshot("2026-03-01T10:00:00Z", us_channels=us_channels)]
        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["docsis_version"] == "3.1"
        assert pg["degraded_channel_count"] == 0

    def test_us31_low_qam_pct_counts_64qam_but_excludes_128qam(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z",
                           us_channels=[{"channel_id": 41, "modulation": "1024QAM", "docsis_version": "3.1"}]),
            _make_snapshot("2026-03-01T14:00:00Z",
                           us_channels=[{"channel_id": 41, "modulation": "128QAM", "docsis_version": "3.1"}]),
            _make_snapshot("2026-03-01T18:00:00Z",
                           us_channels=[{"channel_id": 41, "modulation": "64QAM", "docsis_version": "3.1"}]),
        ]
        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["low_qam_pct"] == 33.3
        assert pg["days"][0]["low_qam_pct"] == 33.3

    def test_us31_low_qam_pct_keeps_unknown_in_visible_denominator(self):
        snaps = [
            _make_snapshot(
                f"2026-05-01T{hour:02d}:00:00Z",
                us_channels=[{
                    "channel_id": 41,
                    "modulation": "Unknown",
                    "docsis_version": "3.1",
                }],
            )
            for hour in range(19)
        ]
        snaps.append(_make_snapshot(
            "2026-05-01T20:00:00Z",
            us_channels=[{
                "channel_id": 41,
                "modulation": "64QAM",
                "docsis_version": "3.1",
            }],
        ))

        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        day = pg["days"][0]

        assert day["distribution"] == {"64QAM": 5.0, "Unknown": 95.0}
        assert day["sample_count"] == 20
        assert day["numeric_sample_count"] == 1
        assert day["low_qam_sample_count"] == 1
        assert day["low_qam_pct"] == 5.0
        assert pg["low_qam_pct"] == 5.0
        assert result["aggregate"]["low_qam_pct"] == 5.0

    def test_us31_low_qam_pct_counts_64qam_excludes_128qam_and_keeps_unknown_denominator(self):
        snaps = []
        for hour in range(10):
            snaps.append(_make_snapshot(
                f"2026-05-06T{hour:02d}:00:00Z",
                us_channels=[{"channel_id": 41, "modulation": "Unknown", "docsis_version": "3.1"}],
            ))
        for hour in range(10, 15):
            snaps.append(_make_snapshot(
                f"2026-05-06T{hour:02d}:00:00Z",
                us_channels=[{"channel_id": 41, "modulation": "128QAM", "docsis_version": "3.1"}],
            ))
        for hour in range(15, 20):
            snaps.append(_make_snapshot(
                f"2026-05-06T{hour:02d}:00:00Z",
                us_channels=[{"channel_id": 41, "modulation": "64QAM", "docsis_version": "3.1"}],
            ))

        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        day = pg["days"][0]

        assert day["distribution"] == {"128QAM": 25.0, "64QAM": 25.0, "Unknown": 50.0}
        assert day["low_qam_pct"] == 25.0
        assert pg["low_qam_pct"] == 25.0
        assert result["aggregate"]["low_qam_pct"] == 25.0

    def test_low_qam_pct_unknown_denominator_weighted_across_days_and_protocols(self):
        snaps = []
        # Day 1 / DOCSIS 3.1: 1 low sample, 19 Unknown => 5% for that day/group.
        for hour in range(19):
            snaps.append(_make_snapshot(
                f"2026-05-01T{hour:02d}:00:00Z",
                us_channels=[{"channel_id": 41, "modulation": "Unknown", "docsis_version": "3.1"}],
            ))
        snaps.append(_make_snapshot(
            "2026-05-01T20:00:00Z",
            us_channels=[{"channel_id": 41, "modulation": "64QAM", "docsis_version": "3.1"}],
        ))
        # Day 2 / DOCSIS 3.0: 1 low sample, 99 non-low samples. This guards the
        # global aggregate against protocol averaging and numeric-only denominators.
        snaps.append(_make_snapshot(
            "2026-05-02T00:00:00Z",
            us_channels=[{"channel_id": 1, "modulation": "16QAM", "docsis_version": "3.0"}],
        ))
        for minute in range(99):
            snaps.append(_make_snapshot(
                f"2026-05-02T01:{minute % 60:02d}:00Z",
                us_channels=[{"channel_id": 1, "modulation": "64QAM", "docsis_version": "3.0"}],
            ))

        result = compute_distribution_v2(snaps, "us", "UTC")
        groups = {pg["docsis_version"]: pg for pg in result["protocol_groups"]}

        assert groups["3.1"]["low_qam_pct"] == 5.0
        assert groups["3.0"]["low_qam_pct"] == 1.0
        assert result["aggregate"]["low_qam_pct"] == 1.7
        assert result["aggregate"]["low_qam_pct"] != 3.0
        assert result["aggregate"]["low_qam_pct"] != 100.0


    def test_prefers_profile_modulation_for_ofdma_distribution(self):
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                us_channels=[{
                    "channel_id": 41,
                    "modulation": "OFDMA",
                    "profile_modulation": "128QAM",
                    "docsis_version": "3.1",
                }],
            )
        ]
        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["docsis_version"] == "3.1"
        assert pg["dominant_modulation"] == "128QAM"
        assert pg["degraded_channel_count"] == 0
        assert pg["low_qam_pct"] == 0.0
        assert pg["distribution"]["128QAM"] == 100.0

    def test_per_day_data(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["64QAM"])),
            _make_snapshot("2026-03-02T10:00:00Z", us_channels=_make_channels(["64QAM"])),
        ]
        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        assert len(pg["days"]) == 2
        assert pg["days"][0]["date"] == "2026-03-01"
        assert pg["days"][1]["date"] == "2026-03-02"

    def test_health_index_us30_correct(self):
        """US 3.0 at 64QAM should be 100, not the old 40."""
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                us_channels=_make_channels(["64QAM", "64QAM", "64QAM", "64QAM"]),
            )
        ]
        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["health_index"] == 100.0

    def test_health_index_ds30_correct(self):
        """DS 3.0 at 256QAM should be 100."""
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                ds_channels=_make_channels(["256QAM", "256QAM"]),
            )
        ]
        result = compute_distribution_v2(snaps, "ds", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["health_index"] == 100.0

    def test_health_index_ds30_fixed_64qam_channels_stay_healthy(self):
        """Fixed 64QAM DS channels should not lower the v2 health index."""
        ds_channels = [
            {"channel_id": 1, "modulation": "256QAM", "docsis_version": "3.0"},
            {"channel_id": 2, "modulation": "64QAM", "docsis_version": "3.0"},
            {"channel_id": 3, "modulation": "64QAM", "docsis_version": "3.0"},
        ]
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z", ds_channels=ds_channels),
            _make_snapshot("2026-03-01T14:00:00Z", ds_channels=ds_channels),
        ]
        result = compute_distribution_v2(snaps, "ds", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["health_index"] == 100.0
        assert pg["days"][0]["health_index"] == 100.0

    def test_health_index_ds30_still_drops_when_channel_falls_below_its_baseline(self):
        """A DS channel that drops from 256QAM to 64QAM should still lower health."""
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                ds_channels=[{"channel_id": 1, "modulation": "256QAM", "docsis_version": "3.0"}],
            ),
            _make_snapshot(
                "2026-03-01T14:00:00Z",
                ds_channels=[{"channel_id": 1, "modulation": "64QAM", "docsis_version": "3.0"}],
            ),
        ]
        result = compute_distribution_v2(snaps, "ds", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["health_index"] == 83.3

    def test_degraded_channel_count(self):
        us_channels = [
            {"channel_id": 1, "modulation": "64QAM", "docsis_version": "3.0"},
            {"channel_id": 2, "modulation": "64QAM", "docsis_version": "3.0"},
            {"channel_id": 3, "modulation": "16QAM", "docsis_version": "3.0"},
        ]
        snaps = [_make_snapshot("2026-03-01T10:00:00Z", us_channels=us_channels)]
        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["degraded_channel_count"] == 1  # Ch 3 at 16QAM <= threshold(16)

    def test_ds_64qam_not_degraded(self):
        """DS 3.0 channels at 64QAM must NOT be counted as degraded (issue fix)."""
        ds_channels = [
            {"channel_id": 1, "modulation": "256QAM", "docsis_version": "3.0"},
            {"channel_id": 2, "modulation": "64QAM", "docsis_version": "3.0"},
            {"channel_id": 3, "modulation": "64QAM", "docsis_version": "3.0"},
        ]
        snaps = [_make_snapshot("2026-03-01T10:00:00Z", ds_channels=ds_channels)]
        result = compute_distribution_v2(snaps, "ds", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["degraded_channel_count"] == 0  # 64QAM > threshold(16)

    def test_dominant_modulation(self):
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                us_channels=_make_channels(["64QAM", "64QAM", "16QAM"]),
            )
        ]
        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["dominant_modulation"] == "64QAM"

    def test_sample_density(self):
        snaps = [_make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["64QAM"]))]
        result = compute_distribution_v2(snaps, "us", "UTC")
        # Single day with 1 snapshot: expected = 1 * 1 = 1
        assert result["expected_samples"] == 1
        assert result["sample_count"] == 1
        assert result["sample_density"] == 1.0

    def test_sample_density_multi_day(self):
        # 3 days, 10 snapshots each — expected uses median (10)
        snaps = []
        for day in range(1, 4):
            for hour in range(10):
                ts = f"2026-03-0{day}T{hour:02d}:00:00Z"
                snaps.append(_make_snapshot(ts, us_channels=_make_channels(["64QAM"])))
        result = compute_distribution_v2(snaps, "us", "UTC")
        assert result["sample_count"] == 30
        assert result["expected_samples"] == 30  # 3 days * median(10) = 30
        assert result["sample_density"] == 1.0

    def test_disclaimer_present(self):
        result = compute_distribution_v2([], "us", "UTC")
        assert "disclaimer" in result
        assert len(result["disclaimer"]) > 0


class TestComputeIntraday:
    def test_empty(self):
        result = compute_intraday([], "us", "UTC", "2026-03-01")
        assert result["protocol_groups"] == []
        assert result["date"] == "2026-03-01"
        assert result["disclaimer"] == DISCLAIMER

    def test_single_channel_timeline(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z",
                           us_channels=[{"channel_id": 1, "modulation": "64QAM",
                                         "docsis_version": "3.0", "frequency": "51.000"}]),
            _make_snapshot("2026-03-01T14:00:00Z",
                           us_channels=[{"channel_id": 1, "modulation": "16QAM",
                                         "docsis_version": "3.0", "frequency": "51.000"}]),
            _make_snapshot("2026-03-01T18:00:00Z",
                           us_channels=[{"channel_id": 1, "modulation": "64QAM",
                                         "docsis_version": "3.0", "frequency": "51.000"}]),
        ]
        result = compute_intraday(snaps, "us", "UTC", "2026-03-01")
        assert len(result["protocol_groups"]) == 1
        pg = result["protocol_groups"][0]
        assert pg["docsis_version"] == "3.0"
        ch = pg["channels"][0]
        assert ch["channel_id"] == 1
        assert ch["degraded"] is True
        assert len(ch["timeline"]) == 3  # 3 transitions: 64→16→64
        assert ch["summary"] != ""  # Should mention 16QAM degradation

    def test_filters_by_date(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z",
                           us_channels=[{"channel_id": 1, "modulation": "64QAM",
                                         "docsis_version": "3.0", "frequency": "51.000"}]),
            _make_snapshot("2026-03-02T10:00:00Z",
                           us_channels=[{"channel_id": 1, "modulation": "64QAM",
                                         "docsis_version": "3.0", "frequency": "51.000"}]),
        ]
        result = compute_intraday(snaps, "us", "UTC", "2026-03-01")
        pg = result["protocol_groups"][0]
        ch = pg["channels"][0]
        assert len(ch["timeline"]) == 1  # Only 1 snapshot on March 1

    def test_not_degraded_channel(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z",
                           us_channels=[{"channel_id": 1, "modulation": "64QAM",
                                         "docsis_version": "3.0", "frequency": "51.000"}]),
        ]
        result = compute_intraday(snaps, "us", "UTC", "2026-03-01")
        ch = result["protocol_groups"][0]["channels"][0]
        assert ch["degraded"] is False
        assert ch["health_index"] == 100.0
        assert ch["summary"] == ""

    def test_ds_64qam_not_degraded_intraday(self):
        """DS 3.0 channel at 64QAM must not be flagged degraded in intraday."""
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z",
                           ds_channels=[{"channel_id": 1, "modulation": "64QAM",
                                         "docsis_version": "3.0", "frequency": "500.000"}]),
        ]
        result = compute_intraday(snaps, "ds", "UTC", "2026-03-01")
        ch = result["protocol_groups"][0]["channels"][0]
        assert ch["degraded"] is False
        assert ch["health_index"] == 100.0
        assert ch["summary"] == ""

    def test_multi_protocol_groups(self):
        us_channels = [
            {"channel_id": 1, "modulation": "64QAM", "docsis_version": "3.0", "frequency": "51.000"},
            {"channel_id": 10, "modulation": "1024QAM", "docsis_version": "3.1", "frequency": "100.000"},
        ]
        snaps = [_make_snapshot("2026-03-01T10:00:00Z", us_channels=us_channels)]
        result = compute_intraday(snaps, "us", "UTC", "2026-03-01")
        assert len(result["protocol_groups"]) == 2

    def test_us31_intraday_treats_64qam_as_degraded_event(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z",
                           us_channels=[{"channel_id": 41, "modulation": "1024QAM",
                                         "docsis_version": "3.1", "frequency": "29.775 - 64.775"}]),
            _make_snapshot("2026-03-01T14:00:00Z",
                           us_channels=[{"channel_id": 41, "modulation": "64QAM",
                                         "docsis_version": "3.1", "frequency": "29.775 - 64.775"}]),
            _make_snapshot("2026-03-01T18:00:00Z",
                           us_channels=[{"channel_id": 41, "modulation": "1024QAM",
                                         "docsis_version": "3.1", "frequency": "29.775 - 64.775"}]),
        ]

        result = compute_intraday(snaps, "us", "UTC", "2026-03-01")
        pg = next(pg for pg in result["protocol_groups"] if pg["docsis_version"] == "3.1")
        ch = pg["channels"][0]

        assert ch["degraded"] is True
        assert ch["worst_modulation"] == "64QAM"
        assert ch["degraded_sample_pct"] == 33
        assert ch["degraded_events"][0]["label"] == "64QAM"
        assert "64QAM" in ch["summary"]

    def test_us31_channel_summary_does_not_treat_128qam_as_low_qam(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z",
                           us_channels=[{"channel_id": 41, "modulation": "1024QAM",
                                         "docsis_version": "3.1", "frequency": "29.775 - 64.775"}]),
            _make_snapshot("2026-03-01T14:00:00Z",
                           us_channels=[{"channel_id": 41, "modulation": "128QAM",
                                         "docsis_version": "3.1", "frequency": "29.775 - 64.775"}]),
            _make_snapshot("2026-03-01T18:00:00Z",
                           us_channels=[{"channel_id": 41, "modulation": "512QAM",
                                         "docsis_version": "3.1", "frequency": "29.775 - 64.775"}]),
        ]
        result = compute_intraday(snaps, "us", "UTC", "2026-03-01")
        pg = next(pg for pg in result["protocol_groups"] if pg["docsis_version"] == "3.1")
        ch = pg["channels"][0]
        assert ch["degraded"] is False
        assert ch["summary"] == ""
        assert ch["worst_modulation"] == ""
        assert ch["degraded_sample_pct"] == 0
        assert ch["degraded_events"] == []

    def test_intraday_prefers_profile_modulation_for_ofdma(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z",
                           us_channels=[{"channel_id": 41, "modulation": "OFDMA", "profile_modulation": "1024QAM",
                                         "docsis_version": "3.1", "frequency": "29.775 - 64.775"}]),
            _make_snapshot("2026-03-01T14:00:00Z",
                           us_channels=[{"channel_id": 41, "modulation": "OFDMA", "profile_modulation": "128QAM",
                                         "docsis_version": "3.1", "frequency": "29.775 - 64.775"}]),
            _make_snapshot("2026-03-01T18:00:00Z",
                           us_channels=[{"channel_id": 41, "modulation": "OFDMA", "profile_modulation": "512QAM",
                                         "docsis_version": "3.1", "frequency": "29.775 - 64.775"}]),
        ]
        result = compute_intraday(snaps, "us", "UTC", "2026-03-01")
        pg = next(pg for pg in result["protocol_groups"] if pg["docsis_version"] == "3.1")
        ch = pg["channels"][0]
        assert ch["degraded"] is False
        assert ch["worst_modulation"] == ""
        assert ch["degraded_events"] == []
        assert ch["timeline"] == [
            {"time": "10:00", "modulation": "1024QAM"},
            {"time": "14:00", "modulation": "128QAM"},
            {"time": "18:00", "modulation": "512QAM"},
        ]


# ── Legacy compute_distribution (v1 compat) ──

class TestComputeDistribution:
    def test_empty_snapshots(self):
        result = compute_distribution([], "us", "UTC")
        assert result["sample_count"] == 0
        assert result["days"] == []
        assert result["aggregate"]["health_index"] is None
        assert result["aggregate"]["distribution"] == {}

    def test_single_day_single_snapshot(self):
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                us_channels=_make_channels(["64QAM", "64QAM", "4QAM", "64QAM"]),
            )
        ]
        result = compute_distribution(snaps, "us", "UTC")
        assert len(result["days"]) == 1
        day = result["days"][0]
        assert day["date"] == "2026-03-01"

    def test_multi_day_grouping(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["64QAM"])),
            _make_snapshot("2026-03-01T14:00:00Z", us_channels=_make_channels(["64QAM"])),
            _make_snapshot("2026-03-02T10:00:00Z", us_channels=_make_channels(["4QAM"])),
        ]
        result = compute_distribution(snaps, "us", "UTC")
        assert len(result["days"]) == 2
        assert result["days"][0]["date"] == "2026-03-01"
        assert result["days"][1]["date"] == "2026-03-02"

    def test_downstream_channels(self):
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                ds_channels=_make_channels(["256QAM", "256QAM"]),
                us_channels=_make_channels(["4QAM"]),
            )
        ]
        result = compute_distribution(snaps, "ds", "UTC")
        assert "256QAM" in result["aggregate"]["distribution"]
        assert "4QAM" not in result["aggregate"]["distribution"]

    def test_direction_field_in_result(self):
        result = compute_distribution([], "ds", "UTC")
        assert result["direction"] == "ds"

    def test_low_qam_threshold_in_result(self):
        result = compute_distribution([], "us", "UTC", low_qam_threshold=32)
        assert result["low_qam_threshold"] == 32

    def test_date_range_correct(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["64QAM"])),
            _make_snapshot("2026-03-05T10:00:00Z", us_channels=_make_channels(["64QAM"])),
        ]
        result = compute_distribution(snaps, "us", "UTC")
        assert result["date_range"]["start"] == "2026-03-01"
        assert result["date_range"]["end"] == "2026-03-05"

    def test_density_capped_at_1(self):
        snaps = [
            _make_snapshot(f"2026-03-01T{i:02d}:00:00Z", us_channels=_make_channels(["64QAM"]))
            for i in range(24)
        ] * 5
        result = compute_distribution(snaps, "us", "UTC")
        assert result["sample_density"] == 1.0


# ── compute_trend ──
