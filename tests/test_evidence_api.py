import builtins
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

    def test_endpoint_requires_auth_when_admin_password_is_set(self, monkeypatch, tmp_path):
        config = Mock()
        config.get.side_effect = lambda key, default=None: {"admin_password": "secret"}.get(key, default)
        config.data_dir = str(tmp_path)
        monkeypatch.setattr(web, "_config_manager", config)
        monkeypatch.setattr(web, "_storage", None)
        web._init_auth_state()
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

    def test_manual_range_accepts_explicit_offset_timestamps(self):
        from app.modules.evidence import routes

        core = FakeCoreStorage()
        config = Mock()
        config.get.side_effect = lambda key, default=None: {"modem_type": "fritzbox"}.get(key, default)
        config.is_speedtest_configured.return_value = False
        config.is_bqm_configured.return_value = False
        config.is_demo_mode.return_value = False

        with app.test_request_context("/api/evidence/checklist?from=2026-06-10T19:00:00%2B02:00&to=2026-06-10T23:00:00%2B02:00"):
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

    def test_invalid_incident_id_returns_specific_client_error(self):
        from app.modules.evidence import routes

        for value in ("abc", "0", "-1"):
            with app.test_request_context(f"/api/evidence/checklist?incident_id={value}"):
                response, status = getattr(routes.api_evidence_checklist, "__wrapped__")()

            assert status == 400
            assert response.get_json()["error"] == "incident_id must be a positive integer"

    def test_journal_window_uses_configured_local_dates_from_normalized_window(self, tmp_path):
        from app.modules.journal.storage import JournalStorage
        from app.modules.evidence import routes

        db_path = str(tmp_path / "docsight.db")
        journal = JournalStorage(db_path)
        journal.save_entry("2026-06-10", "Previous local day", "outside")
        journal.save_entry("2026-06-11", "Selected local day", "inside")

        with patch.object(routes, "_get_tz_name", return_value="Europe/Berlin"):
            rows = routes._get_journal_entries_for_window(
                db_path,
                "2026-06-10T23:30:00Z",
                "2026-06-11T00:30:00Z",
            )

        assert [row["title"] for row in rows] == ["Selected local day"]

    def test_journal_window_falls_back_to_utc_when_configured_timezone_is_invalid(self, tmp_path):
        from app.modules.journal.storage import JournalStorage
        from app.modules.evidence import routes

        db_path = str(tmp_path / "docsight.db")
        journal = JournalStorage(db_path)
        journal.save_entry("2026-06-10", "UTC day", "inside")

        with patch.object(routes, "_get_tz_name", return_value="Invalid/Timezone"):
            rows = routes._get_journal_entries_for_window(
                db_path,
                "2026-06-10T22:30:00Z",
                "2026-06-10T23:00:00Z",
            )

        assert [row["title"] for row in rows] == ["UTC day"]

    def test_bqm_rows_filter_to_exact_utc_window_after_local_date_fetch(self, tmp_path):
        from app.modules.bqm.storage import BqmStorage
        from app.modules.evidence import routes

        db_path = str(tmp_path / "docsight.db")
        storage = BqmStorage(db_path, "Europe/Berlin")
        storage.store_csv_data([
            {"timestamp": "2026-06-10T21:30:00Z", "date": "2026-06-10", "sent_polls": 10, "lost_polls": 0, "latency_min_ms": 10, "latency_avg_ms": 20, "latency_max_ms": 30, "score": 100},
            {"timestamp": "2026-06-10T22:30:00Z", "date": "2026-06-11", "sent_polls": 10, "lost_polls": 0, "latency_min_ms": 11, "latency_avg_ms": 21, "latency_max_ms": 31, "score": 100},
            {"timestamp": "2026-06-10T23:30:00Z", "date": "2026-06-11", "sent_polls": 10, "lost_polls": 0, "latency_min_ms": 12, "latency_avg_ms": 22, "latency_max_ms": 32, "score": 100},
        ])

        with patch.object(routes, "_get_tz_name", return_value="Europe/Berlin"):
            rows = routes._get_bqm_rows(
                db_path,
                "2026-06-10T22:00:00Z",
                "2026-06-10T23:00:00Z",
            )

        assert [row["timestamp"] for row in rows] == ["2026-06-10T22:30:00Z"]

    def test_bqm_rows_skip_malformed_timestamps_without_marking_source_unavailable(self, tmp_path):
        from app.modules.bqm.storage import BqmStorage
        from app.modules.evidence import routes

        def fake_rows(self, start_date, end_date):
            return [
                {"timestamp": "not-a-timestamp", "sent_polls": 10},
                {"timestamp": "2026-06-10T22:30:00Z", "sent_polls": 10},
                {"timestamp": "2026-06-10T23:30:00Z", "sent_polls": 10},
            ]

        with patch.object(routes, "_get_tz_name", return_value="Europe/Berlin"), \
             patch.object(BqmStorage, "get_data_for_range", fake_rows):
            rows = routes._get_bqm_rows(
                str(tmp_path / "docsight.db"),
                "2026-06-10T22:00:00Z",
                "2026-06-10T23:00:00Z",
            )

        assert rows == [{"timestamp": "2026-06-10T22:30:00Z", "sent_polls": 10}]

    def test_bqm_rows_return_unavailable_sentinel_on_storage_error(self, tmp_path):
        from app.modules.evidence import routes

        with patch.object(routes, "_get_tz_name", return_value="Europe/Berlin"):
            rows = routes._get_bqm_rows(
                str(tmp_path / "missing" / "docsight.db"),
                "2026-06-10T22:00:00Z",
                "2026-06-10T23:00:00Z",
            )

        assert rows is None

    def test_bqm_rows_return_unavailable_sentinel_when_bqm_module_is_missing(self, tmp_path):
        from app.modules.evidence import routes

        real_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "app.modules.bqm.storage":
                raise ImportError("BQM module unavailable")
            return real_import(name, globals, locals, fromlist, level)

        with patch.object(builtins, "__import__", side_effect=guarded_import):
            rows = routes._get_bqm_rows(
                str(tmp_path / "docsight.db"),
                "2026-06-10T22:00:00Z",
                "2026-06-10T23:00:00Z",
            )

        assert rows is None

    def test_manual_range_rejects_malformed_timestamp_with_specific_error(self):
        from app.modules.evidence import routes

        core = FakeCoreStorage()
        config = Mock()
        config.get.side_effect = lambda key, default=None: {"modem_type": "fritzbox"}.get(key, default)
        config.is_speedtest_configured.return_value = False
        config.is_bqm_configured.return_value = False
        config.is_demo_mode.return_value = False

        with app.test_request_context("/api/evidence/checklist?from=not-a-date&to=2026-06-10T23:00:00Z"):
            with patch.object(routes, "get_storage", return_value=core), \
                 patch.object(routes, "get_config_manager", return_value=config), \
                 patch.object(routes, "_get_tz_name", return_value="Europe/Berlin"):
                response, status = getattr(routes.api_evidence_checklist, "__wrapped__")()

        assert status == 400
        assert response.get_json()["error"] == "from/to must be valid ISO timestamps"

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
