from unittest.mock import Mock, patch

import app.web as web
from app.web import app


class FakeCoreStorage:
    db_path = ":memory:"

    def get_correlation_timeline(self, start_ts, end_ts):
        self.requested_range = (start_ts, end_ts)
        return [
            {"timestamp": end_ts, "source": "modem", "health": "critical"},
            {"timestamp": end_ts, "source": "event", "severity": "critical"},
        ]


class TestEvidenceChecklistApi:
    def test_requires_incident_or_time_range(self):
        from app.modules.evidence import routes

        with app.test_request_context("/api/evidence/checklist"):
            response, status = getattr(routes.api_evidence_checklist, "__wrapped__")()

        assert status == 400
        assert response.get_json()["error"] == "incident_id or from/to required"

    def test_rejects_mixed_incident_and_time_range(self):
        from app.modules.evidence import routes

        with app.test_request_context("/api/evidence/checklist?incident_id=7&from=2026-06-10T18:00:00Z&to=2026-06-10T23:00:00Z"):
            response, status = getattr(routes.api_evidence_checklist, "__wrapped__")()

        assert status == 400
        assert response.get_json()["error"] == "choose incident_id or from/to, not both"

    def test_rejects_partial_time_range_with_specific_error(self):
        from app.modules.evidence import routes

        with app.test_request_context("/api/evidence/checklist?from=2026-06-10T18:00:00"):
            response, status = getattr(routes.api_evidence_checklist, "__wrapped__")()

        assert status == 400
        assert response.get_json()["error"] == "from and to required together"

    def test_endpoint_requires_auth_when_admin_password_is_set(self, monkeypatch):
        config = Mock()
        config.get.side_effect = lambda key, default=None: {"admin_password": "secret"}.get(key, default)
        monkeypatch.setattr(web, "_config_manager", config)
        monkeypatch.setattr(web, "_storage", None)
        app.config["TESTING"] = True

        with app.test_client() as client:
            response = client.get("/api/evidence/checklist?from=2026-06-10T18:00:00Z&to=2026-06-10T23:00:00Z")

        assert response.status_code == 401
        assert response.get_json()["error"] == "Authentication required"

    def test_builds_incident_checklist_from_existing_sources(self):
        from app.modules.evidence import routes

        core = FakeCoreStorage()
        journal = Mock()
        journal.get_incident.return_value = {
            "id": 7,
            "name": "Bad evening",
            "status": "open",
            "start_date": "2026-06-10",
            "end_date": "2026-06-10",
        }
        journal.get_entries.return_value = [{"id": 1, "date": "2026-06-10", "title": "Called support"}]
        config = Mock()
        config.get.side_effect = lambda key, default=None: {"modem_type": "fritzbox"}.get(key, default)
        config.is_speedtest_configured.return_value = True
        config.is_bqm_configured.return_value = False
        config.is_demo_mode.return_value = False

        with app.test_request_context("/api/evidence/checklist?incident_id=7"):
            with patch.object(routes, "get_storage", return_value=core), \
                 patch.object(routes, "get_config_manager", return_value=config), \
                 patch.object(routes, "_get_journal_storage", return_value=journal), \
                 patch.object(routes, "_get_bqm_rows", return_value=[]), \
                 patch.object(routes, "_get_connection_latency_rows", return_value=[]), \
                 patch.object(routes, "_get_tz_name", return_value="UTC"):
                response = getattr(routes.api_evidence_checklist, "__wrapped__")()

        payload = response.get_json()
        assert payload["window"]["kind"] == "incident"
        assert payload["window"]["incident_id"] == 7
        assert payload["window"]["label"] == "Bad evening"
        assert payload["summary"]["present"] >= 2
        items = {item["key"]: item for item in payload["items"]}
        assert items["signal"]["status"] == "present"
        assert items["events"]["status"] == "present"
        assert items["journal"]["status"] == "present"
        assert items["latency"]["status"] == "optional"

    def test_generic_router_marks_docsis_evidence_not_applicable(self):
        from app.modules.evidence import routes

        core = FakeCoreStorage()
        config = Mock()
        config.get.side_effect = lambda key, default=None: {"modem_type": "generic"}.get(key, default)
        config.is_speedtest_configured.return_value = False
        config.is_bqm_configured.return_value = False
        config.is_demo_mode.return_value = False

        with app.test_request_context("/api/evidence/checklist?from=2026-06-10T18:00:00Z&to=2026-06-10T23:00:00Z"):
            with patch.object(routes, "get_storage", return_value=core), \
                 patch.object(routes, "get_config_manager", return_value=config), \
                 patch.object(routes, "_get_journal_entries_for_window", return_value=[]), \
                 patch.object(routes, "_get_bqm_rows", return_value=[]), \
                 patch.object(routes, "_get_connection_latency_rows", return_value=[]):
                response = getattr(routes.api_evidence_checklist, "__wrapped__")()

        items = {item["key"]: item for item in response.get_json()["items"]}
        assert items["signal"]["status"] == "not_applicable"
        assert items["events"]["status"] == "not_applicable"

    def test_manual_range_includes_connection_monitor_latency(self):
        from app.modules.evidence import routes

        core = FakeCoreStorage()
        config = Mock()
        config.get.side_effect = lambda key, default=None: {
            "modem_type": "fritzbox",
            "connection_monitor_enabled": True,
        }.get(key, default)
        config.is_speedtest_configured.return_value = False
        config.is_bqm_configured.return_value = False
        config.is_demo_mode.return_value = False

        with app.test_request_context("/api/evidence/checklist?from=2026-06-10T18:00:00Z&to=2026-06-10T23:00:00Z"):
            with patch.object(routes, "get_storage", return_value=core), \
                 patch.object(routes, "get_config_manager", return_value=config), \
                 patch.object(routes, "_get_journal_entries_for_window", return_value=[]), \
                 patch.object(routes, "_get_bqm_rows", return_value=[]), \
                 patch.object(routes, "_get_connection_latency_rows", return_value=[
                     {"timestamp": "2026-06-10T22:40:00Z", "avg_latency_ms": 18.0}
                 ]):
                response = getattr(routes.api_evidence_checklist, "__wrapped__")()

        items = {item["key"]: item for item in response.get_json()["items"]}
        assert items["latency"]["status"] == "present"
        assert items["latency"]["action"] == {"view": "connection-monitor"}
        assert items["latency"]["sources"][0]["key"] == "connection_monitor"
        assert items["latency"]["sources"][0]["status"] == "present"
        assert items["latency"]["sources"][1]["key"] == "bqm"
        assert items["latency"]["sources"][1]["status"] == "optional"

    def test_connection_monitor_latency_rows_read_connection_monitor_database(self, tmp_path, monkeypatch):
        from app.modules.connection_monitor.storage import ConnectionMonitorStorage
        from app.modules.evidence import routes

        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        storage = ConnectionMonitorStorage(str(tmp_path / "connection_monitor.db"))
        target_id = storage.create_target("Router", "192.0.2.1")
        storage.save_samples([
            {"target_id": target_id, "timestamp": 1781114400.0, "latency_ms": 18.5, "timeout": False, "probe_method": "tcp"},
            {"target_id": target_id, "timestamp": 1781118000.0, "latency_ms": 22.0, "timeout": False, "probe_method": "tcp"},
        ])

        rows = routes._get_connection_latency_rows("2026-06-10T18:00:00Z", "2026-06-10T20:00:00Z")

        assert rows == [{
            "timestamp": "2026-06-10T19:00:00Z",
            "sample_count": 2,
            "latency_count": 2,
            "avg_latency_ms": 20.25,
            "source": "connection_monitor",
            "tier": "raw",
        }]

    def test_manual_range_converts_datetime_local_with_configured_timezone(self):
        from app.modules.evidence import routes

        core = FakeCoreStorage()
        config = Mock()
        config.get.side_effect = lambda key, default=None: {"modem_type": "fritzbox"}.get(key, default)
        config.is_speedtest_configured.return_value = False
        config.is_bqm_configured.return_value = False
        config.is_demo_mode.return_value = False

        with app.test_request_context("/api/evidence/checklist?from=2026-06-10T19:00:00&to=2026-06-10T23:00:00"):
            with patch.object(routes, "get_storage", return_value=core), \
                 patch.object(routes, "get_config_manager", return_value=config), \
                 patch.object(routes, "_get_journal_entries_for_window", return_value=[]), \
                 patch.object(routes, "_get_bqm_rows", return_value=[]), \
                 patch.object(routes, "_get_connection_latency_rows", return_value=[]), \
                 patch.object(routes, "_get_tz_name", return_value="Europe/Berlin"):
                response = getattr(routes.api_evidence_checklist, "__wrapped__")()

        payload = response.get_json()
        assert payload["window"]["from"] == "2026-06-10T17:00:00Z"
        assert payload["window"]["to"] == "2026-06-10T21:00:00Z"
        assert core.requested_range == ("2026-06-10T17:00:00Z", "2026-06-10T21:00:00Z")

    def test_incident_without_start_date_returns_generic_error(self):
        from app.modules.evidence import routes

        core = FakeCoreStorage()
        journal = Mock()
        journal.get_incident.return_value = {"id": 7, "name": "Bad evening"}

        with app.test_request_context("/api/evidence/checklist?incident_id=7"):
            with patch.object(routes, "get_storage", return_value=core), \
                 patch.object(routes, "_get_journal_storage", return_value=journal):
                response, status = getattr(routes.api_evidence_checklist, "__wrapped__")()

        assert status == 400
        assert response.get_json()["error"] == "incident has no usable date range"
