"""Tests for report/comparison helpers exposed through web routes."""

from unittest.mock import patch
from app.web import app


class TestReportHelpers:
    def test_compute_worst_values_preserves_unsupported_error_counters(self):
        from app.modules.reports.report import _compute_worst_values

        snapshots = [
            {"summary": {
                "errors_supported": False,
                "ds_correctable_errors": None,
                "ds_uncorrectable_errors": None,
                "health": "good",
            }},
        ]

        worst = _compute_worst_values(snapshots)

        assert worst["ds_correctable_max"] is None
        assert worst["ds_uncorrectable_max"] is None

    def test_compute_worst_values_treats_legacy_unsupported_zeroes_as_unavailable(self):
        from app.modules.reports.report import _compute_worst_values

        snapshots = [
            {"summary": {
                "errors_supported": False,
                "ds_correctable_errors": 0,
                "ds_uncorrectable_errors": 0,
                "health": "good",
            }},
        ]

        worst = _compute_worst_values(snapshots)

        assert worst["ds_correctable_max"] is None
        assert worst["ds_uncorrectable_max"] is None

    def test_compute_worst_values_keeps_supported_zero_error_counters(self):
        from app.modules.reports.report import _compute_worst_values

        snapshots = [
            {"summary": {
                "errors_supported": False,
                "ds_correctable_errors": None,
                "ds_uncorrectable_errors": None,
                "health": "good",
            }},
            {"summary": {
                "errors_supported": True,
                "ds_correctable_errors": 0,
                "ds_uncorrectable_errors": 0,
                "health": "good",
            }},
        ]

        worst = _compute_worst_values(snapshots)

        assert worst["ds_correctable_max"] == 0
        assert worst["ds_uncorrectable_max"] == 0

    def test_report_count_formatter_preserves_unsupported_values(self):
        from app.modules.reports.report import _format_optional_count

        assert _format_optional_count(None) == "N/A"
        assert _format_optional_count(0) == "0"
        assert _format_optional_count(1234) == "1,234"


class TestComplaintRoutes:
    def test_get_comparison_data_helper(self):
        from app.modules.reports.routes import _get_comparison_data

        comparison_data = {
            "period_a": {"from": "2026-03-01T00:00:00Z", "to": "2026-03-01T23:59:00Z"},
            "period_b": {"from": "2026-03-08T00:00:00Z", "to": "2026-03-08T23:59:00Z"},
            "delta": {"verdict": "degraded"},
        }

        with app.test_request_context(
            "/api/complaint"
            "?comparison_from_a=2026-03-01T00:00:00Z"
            "&comparison_to_a=2026-03-01T23:59:00Z"
            "&comparison_from_b=2026-03-08T00:00:00Z"
            "&comparison_to_b=2026-03-08T23:59:00Z"
        ):
            with patch("app.modules.comparison.routes.compare_periods", return_value=comparison_data):
                result = _get_comparison_data(object())

        assert result == comparison_data
