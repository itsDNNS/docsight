"""Tests for report/comparison helpers exposed through web routes."""

from unittest.mock import Mock, patch
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

    def test_diagnostic_notes_trust_analyzer_metric_health(self):
        from app.modules.reports.report import _build_diagnostic_notes

        analysis = {
            "ds_channels": [
                {
                    "channel_id": 1,
                    "docsis_version": "3.0",
                    "modulation": "256QAM",
                    "power": 30.0,
                    "snr": 20.0,
                    "power_health": "good",
                    "snr_health": "good",
                }
            ],
            "us_channels": [
                {
                    "channel_id": 2,
                    "docsis_version": "3.1",
                    "type": "OFDMA",
                    "profile_modulation": "64QAM",
                    "power": 55.0,
                    "power_health": "critical",
                }
            ],
        }

        notes = _build_diagnostic_notes(analysis)

        assert [note["type"] for note in notes] == ["us_power_high"]
        assert notes[0]["channel_type"] == "OFDMA"


class TestComplaintRoutes:
    def test_api_report_passes_customer_details_to_pdf_generator(self):
        from app.modules.reports import routes

        storage = Mock()
        storage.get_range_data.return_value = [{"timestamp": "2026-05-01T00:00:00Z", "summary": {}}]
        config_manager = Mock()
        config_manager.get.side_effect = lambda key, default="": {
            "isp_name": "Example ISP",
            "modem_type": "Example Modem",
        }.get(key, default)
        analysis = {"summary": {"health": "critical"}, "ds_channels": [], "us_channels": []}
        pdf_bytes = b"%PDF-1.4\ncustomer-data\n"

        with app.test_request_context(
            "/api/report?days=7&lang=de"
            "&name=Max%20Mustermann"
            "&number=KD-123456"
            "&address=Musterstra%C3%9Fe%201%0A12345%20Musterstadt"
        ):
            with patch.object(routes, "get_storage", return_value=storage), \
                 patch.object(routes, "get_config_manager", return_value=config_manager), \
                 patch.object(routes, "get_state", return_value={"analysis": analysis, "connection_info": {}}), \
                 patch.object(routes, "generate_report", return_value=pdf_bytes) as generate_report:
                response = getattr(routes.api_report, "__wrapped__")()

        assert response.status_code == 200
        assert response.data == pdf_bytes
        generate_report.assert_called_once()
        assert generate_report.call_args.kwargs["customer_name"] == "Max Mustermann"
        assert generate_report.call_args.kwargs["customer_number"] == "KD-123456"
        assert generate_report.call_args.kwargs["customer_address"] == "Musterstraße 1\n12345 Musterstadt"

    def test_api_incident_report_passes_customer_details_to_pdf_generator(self):
        from app.modules.journal import routes

        storage = Mock()
        storage.get_incident.return_value = {
            "id": 7,
            "name": "Repeated outages",
            "status": "open",
            "description": "Recurring signal loss.",
        }
        storage.get_entries.return_value = []
        storage.get_attachment.return_value = None
        config_manager = Mock()
        config_manager.get.side_effect = lambda key, default="": {
            "isp_name": "Example ISP",
            "modem_type": "Example Modem",
        }.get(key, default)
        pdf_bytes = b"%PDF-1.4\nincident-customer-data\n"

        with app.test_request_context(
            "/api/incidents/7/report?lang=de"
            "&name=Max%20Mustermann"
            "&number=KD-123456"
            "&address=Musterstra%C3%9Fe%201%0A12345%20Musterstadt"
        ):
            with patch.object(routes, "_get_journal_storage", return_value=storage), \
                 patch.object(routes, "get_config_manager", return_value=config_manager), \
                 patch.object(routes, "get_state", return_value={"connection_info": {}}), \
                 patch("app.modules.reports.report.generate_incident_report", return_value=pdf_bytes) as generate_incident_report:
                response = getattr(routes.api_incident_report, "__wrapped__")(7)

        assert response.status_code == 200
        assert response.data == pdf_bytes
        generate_incident_report.assert_called_once()
        assert generate_incident_report.call_args.kwargs["customer_name"] == "Max Mustermann"
        assert generate_incident_report.call_args.kwargs["customer_number"] == "KD-123456"
        assert generate_incident_report.call_args.kwargs["customer_address"] == "Musterstraße 1\n12345 Musterstadt"

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
