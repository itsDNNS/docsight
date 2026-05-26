"""Tests for demo history signal-family trend fields."""

from app.collectors.demo import DemoCollector


def test_demo_historical_analysis_populates_signal_family_trend_keys():
    collector = object.__new__(DemoCollector)

    analysis = collector._generate_historical_analysis(
        index=1,
        diurnal=0.0,
        seasonal=0.0,
        bad_period=False,
        hour=12,
        day_of_year=120,
    )

    summary = analysis["summary"]
    families = summary["signal_families"]

    assert set(families["downstream"]["families"]) == {"sc_qam", "ofdm"}
    assert set(families["upstream"]["families"]) == {"sc_qam", "ofdma"}
    assert summary["ds_scqam_snr_avg"] is not None
    assert summary["ds_ofdm_mer_avg"] is not None
    assert summary["us_scqam_power_avg"] is not None
    assert summary["us_ofdma_power_avg"] is not None
