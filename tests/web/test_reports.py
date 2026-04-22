"""Tests for report/comparison helpers exposed through web routes."""

from unittest.mock import patch
from app.web import app

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
