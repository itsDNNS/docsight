"""Claim persistence, API, privacy, and capability integration tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from app.storage import SnapshotStorage


@pytest.fixture
def core_storage(tmp_path):
    return SnapshotStorage(str(tmp_path / "docsis_history.db"), max_days=7)


def _claim_payload(**overrides):
    payload = {
        "status": "draft",
        "origin": "manual",
        "window_from": "2026-01-01T00:00:00Z",
        "window_to": "2026-05-01T00:00:00Z",
        "fault_report_received_date": "2026-01-01",
        "fault_report_channel": "provider portal",
        "ticket_ref": "SYNTHETIC-42",
        "restored_date": "2026-01-06",
        "monthly_fee_cents": 4_000,
        "confirmed_days": ["2026-01-04", "2026-01-05", "2026-01-06"],
        "eligibility": {
            "complete_outage": True,
            "replacement_solution_days": [],
            "missed_appointments": 1,
        },
        "prior_credit": {"amount_cents": 1_169, "classification": "unclear"},
    }
    payload.update(overrides)
    return payload


def test_manual_core_flow_works_with_all_supporting_modules_disabled(
    make_app, make_config, builtin_module_loader_factory, core_storage, monkeypatch
):
    disabled = ",".join([
        "docsight.reports", "docsight.evidence", "docsight.journal",
        "docsight.connection_monitor", "docsight.bnetz",
    ])
    config = make_config({"disabled_modules": disabled})
    application = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    )
    client = application.test_client()

    import app.modules.de_tkg_compensation.routes as routes

    monkeypatch.setattr(
        routes, "load_connection_monitor_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("disabled data read")),
    )
    monkeypatch.setattr(
        routes, "load_incident_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("disabled data read")),
    )

    candidates = client.get("/api/de-tkg/candidates")
    assert candidates.status_code == 200
    assert candidates.get_json()["candidates"] == []
    assert not any(
        candidates.get_json()["capabilities"][name]
        for name in ("reports", "evidence", "journal", "connection_monitor", "bnetz")
    )

    created = client.post("/api/de-tkg/claims", json=_claim_payload())
    assert created.status_code == 201
    claim_id = created.get_json()["id"]

    calculated = client.post(f"/api/de-tkg/claims/{claim_id}/calculate")
    assert calculated.status_code == 200
    result = calculated.get_json()
    assert result["total_cents"] == 2_000
    assert result["missed_appointments_total_cents"] == 1_000
    assert result["prior_credit_automatically_deducted"] is False
    assert result["report_chunks"] == []

    generated = client.post(f"/api/de-tkg/claims/{claim_id}/letter", json={})
    assert generated.status_code == 200
    assert "keine Rechtsberatung" in generated.get_json()["letter_text"]

    downloaded = client.get(f"/api/de-tkg/claims/{claim_id}/letter?download=1")
    assert downloaded.status_code == 200
    disposition = downloaded.headers["Content-Disposition"]
    assert "docsight_tkg_entschaedigung_" in disposition
    assert "SYNTHETIC-42" not in disposition


def test_route_counts_report_receipt_as_day_zero(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()
    claim = client.post(
        "/api/de-tkg/claims",
        json=_claim_payload(
            window_from="2026-01-05T00:00:00Z",
            window_to="2026-01-08T23:59:00Z",
            fault_report_received_date="2026-01-05",
            restored_date="2026-01-08",
            confirmed_days=["2026-01-07", "2026-01-08"],
            eligibility={
                "complete_outage": True,
                "replacement_solution_days": [],
                "missed_appointments": 0,
            },
        ),
    ).get_json()

    response = client.post(f"/api/de-tkg/claims/{claim['id']}/calculate")

    assert response.status_code == 200
    result = response.get_json()
    assert [(item["date"], item["day_index"]) for item in result["exclusions"]] == [
        ("2026-01-07", 2)
    ]
    assert [(item["date"], item["day_index"]) for item in result["days"]] == [
        ("2026-01-08", 3)
    ]


def test_known_validation_error_uses_public_stable_code_and_message(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    response = client.post(
        "/api/de-tkg/claims", json=_claim_payload(status="not-a-status")
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "code": "technical_status_invalid",
        "error": "Status must be draft or completed",
    }


@pytest.mark.parametrize(
    ("sink", "expected_status"),
    [
        ("create", 400),
        ("update", 400),
        ("calculate", 422),
        ("letter_rules", 409),
        ("letter_calculate", 422),
    ],
)
def test_unknown_validation_errors_never_expose_exception_data(
    sink,
    expected_status,
    make_app,
    make_config,
    builtin_module_loader_factory,
    core_storage,
    monkeypatch,
):
    import app.modules.de_tkg_compensation.routes as routes

    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()
    claim = client.post("/api/de-tkg/claims", json=_claim_payload()).get_json()
    secret_code = "technical_secret_code_DO_NOT_EXPOSE"
    secret_message = "secret-message-DO_NOT_EXPOSE"

    def fail_with_secret(*_args, **_kwargs):
        raise routes.RuleValidationError(secret_code, secret_message)

    if sink in {"create", "update"}:
        monkeypatch.setattr(routes, "_normalise_claim_payload", fail_with_secret)
        response = (
            client.post("/api/de-tkg/claims", json={})
            if sink == "create"
            else client.put(f"/api/de-tkg/claims/{claim['id']}", json={})
        )
    elif sink == "calculate":
        monkeypatch.setattr(routes, "_calculate_claim", fail_with_secret)
        response = client.post(f"/api/de-tkg/claims/{claim['id']}/calculate")
    elif sink == "letter_rules":
        monkeypatch.setattr(routes, "resolve_ruleset", fail_with_secret)
        response = client.get(f"/api/de-tkg/claims/{claim['id']}/letter")
    else:
        monkeypatch.setattr(routes, "_calculate_claim", fail_with_secret)
        response = client.post(f"/api/de-tkg/claims/{claim['id']}/letter", json={})

    assert response.status_code == expected_status
    assert response.get_json() == {
        "code": "technical_validation_failed",
        "error": "The request could not be validated",
    }
    serialized = response.get_data(as_text=True)
    assert secret_code not in serialized
    assert secret_message not in serialized


def test_is_demo_is_server_owned_and_demo_claim_is_marked(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config({"demo_mode": True})
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    rejected = client.post(
        "/api/de-tkg/claims", json={**_claim_payload(), "is_demo": False}
    )
    assert rejected.status_code == 400
    assert rejected.get_json()["code"] == "technical_unknown_field"

    created = client.post("/api/de-tkg/claims", json=_claim_payload())
    assert created.status_code == 201
    assert created.get_json()["is_demo"] is True


def test_calculation_and_letter_require_explicit_per_day_confirmation(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()
    created = client.post(
        "/api/de-tkg/claims", json=_claim_payload(confirmed_days=[])
    ).get_json()

    calculated = client.post(f"/api/de-tkg/claims/{created['id']}/calculate")
    generated = client.post(f"/api/de-tkg/claims/{created['id']}/letter", json={})

    assert calculated.status_code == 422
    assert generated.status_code == 422
    assert calculated.get_json()["code"] == "eligibility_confirmed_days_required"


def test_reports_capability_returns_deterministic_90_day_chunks(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()
    created = client.post("/api/de-tkg/claims", json=_claim_payload()).get_json()

    result = client.post(f"/api/de-tkg/claims/{created['id']}/calculate").get_json()

    assert len(result["report_chunks"]) == 2
    assert result["report_chunks"][0]["from"] == "2026-01-01T00:00:00Z"
    assert result["report_chunks"][0]["to"] == "2026-04-01T00:00:00Z"
    assert "technical 90-day" in result["report_chunk_note"]


def test_only_connection_monitor_active_produces_unconfirmed_proposals(
    make_app, make_config, builtin_module_loader_factory, core_storage, tmp_path, monkeypatch
):
    connection_db = tmp_path / "connection_monitor.db"
    with sqlite3.connect(connection_db) as conn:
        conn.execute("CREATE TABLE connection_targets (id INTEGER PRIMARY KEY, enabled INTEGER)")
        conn.execute("CREATE TABLE connection_samples (target_id INTEGER, timestamp REAL, timeout INTEGER)")
        conn.execute("INSERT INTO connection_targets VALUES (1, 1)")
        conn.executemany(
            "INSERT INTO connection_samples VALUES (1, ?, ?)",
            [(1_767_225_600 + offset, 1) for offset in range(5)] + [(1_767_312_000, 0)],
        )
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    disabled = ",".join([
        "docsight.reports", "docsight.evidence", "docsight.journal", "docsight.bnetz",
    ])
    config = make_config({"disabled_modules": disabled})
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    payload = client.get("/api/de-tkg/candidates").get_json()

    assert payload["capabilities"]["connection_monitor"] is True
    assert payload["capabilities"]["connection_monitor_source"] is True
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["origin"] == "telemetry"
    assert payload["candidates"][0]["derived"] is True


def test_enabled_connection_monitor_with_missing_source_is_graceful(
    make_app, make_config, builtin_module_loader_factory, core_storage, tmp_path, monkeypatch
):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    disabled = ",".join([
        "docsight.reports", "docsight.evidence", "docsight.journal", "docsight.bnetz",
    ])
    config = make_config({"disabled_modules": disabled})
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    payload = client.get("/api/de-tkg/candidates").get_json()

    assert payload["capabilities"]["connection_monitor"] is True
    assert payload["capabilities"]["connection_monitor_source"] is False
    assert payload["candidates"] == []


def test_only_reports_active_returns_chunks_without_reading_other_sources(
    make_app, make_config, builtin_module_loader_factory, core_storage, monkeypatch
):
    disabled = ",".join([
        "docsight.evidence", "docsight.journal", "docsight.connection_monitor", "docsight.bnetz",
    ])
    config = make_config({"disabled_modules": disabled})
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()
    import app.modules.de_tkg_compensation.routes as routes
    monkeypatch.setattr(
        routes, "load_incident_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("disabled data read")),
    )
    created = client.post("/api/de-tkg/claims", json=_claim_payload()).get_json()

    result = client.post(f"/api/de-tkg/claims/{created['id']}/calculate").get_json()

    assert result["capabilities"]["reports"] is True
    assert result["capabilities"]["journal"] is False
    assert len(result["report_chunks"]) == 2
    assert result["journal_export_url"] is None


def test_claim_timestamps_are_normalized_to_utc_z(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()
    payload = _claim_payload(
        window_from="2026-01-01T01:30:00+02:00",
        window_to="2026-05-01T01:30:00+02:00",
    )

    claim = client.post("/api/de-tkg/claims", json=payload).get_json()

    assert claim["window_from"] == "2025-12-31T23:30:00Z"
    assert claim["window_to"] == "2026-04-30T23:30:00Z"
    datetime.fromisoformat(claim["created_at"].replace("Z", "+00:00")).astimezone(timezone.utc)


def test_nested_claim_fields_are_strictly_validated(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    response = client.post(
        "/api/de-tkg/claims",
        json=_claim_payload(eligibility={"complete_outage": "yes"}),
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "technical_complete_outage_invalid"


def test_module_itself_can_be_disabled_with_routes_and_assets_absent(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config({
        "disabled_modules": "docsight.de_tkg_compensation",
        "modem_type": "demo",
        "demo_mode": True,
    })
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    assert client.get("/api/de-tkg/candidates").status_code == 404
    assert client.get("/modules/docsight.de_tkg_compensation/static/main.js").status_code == 404
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert b"tkg-compensation-root" not in dashboard.data


def test_glossary_link_uses_script_name_prefix(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config({"modem_type": "demo", "demo_mode": True})
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    response = client.get(
        "/?lang=en", environ_overrides={"SCRIPT_NAME": "/docsight"}
    )

    assert response.status_code == 200
    assert (
        b'id="tkg-glossary-link" '
        b'href="/docsight/?lang=en#glossary?term=tkg_rights_de"'
        in response.data
    )


def test_existing_module_apis_toggle_tkg_module_state(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    disabled = client.post(
        "/api/modules/batch",
        json={"modules": [{"id": "docsight.de_tkg_compensation", "enabled": False}]},
    )
    enabled = client.post("/api/modules/docsight.de_tkg_compensation/enable")

    assert disabled.status_code == 200
    assert disabled.get_json()["restart_required"] is True
    assert enabled.status_code == 200
    assert "docsight.de_tkg_compensation" not in config.get("disabled_modules", "")


def test_demo_purge_removes_only_demo_claims(core_storage):
    from app.modules.de_tkg_compensation.storage import ClaimStorage

    claims = ClaimStorage(core_storage.db_path)
    demo = claims.create(_claim_payload(), is_demo=True)
    real = claims.create(_claim_payload(ticket_ref="REAL-SYNTHETIC"), is_demo=False)

    assert core_storage.purge_demo_data() == 1
    assert claims.get(demo["id"]) is None
    assert claims.get(real["id"])["ticket_ref"] == "REAL-SYNTHETIC"

    with sqlite3.connect(core_storage.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM de_tkg_claim_drafts WHERE is_demo = 1"
        ).fetchone()[0] == 0


@pytest.mark.parametrize(("fee", "expected"), [(4_000, 1_000), (6_000, 1_200)])
def test_appointment_only_claim_calculates_and_generates_outage_free_letter(
    fee, expected, make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config({"timezone": "Europe/Berlin"})
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()
    payload = _claim_payload(
        window_from=None,
        window_to=None,
        fault_report_received_date=None,
        fault_report_channel="",
        ticket_ref="",
        restored_date=None,
        monthly_fee_cents=fee,
        confirmed_days=[],
        eligibility={"complete_outage": False, "missed_appointments": 1},
    )

    claim = client.post("/api/de-tkg/claims", json=payload).get_json()
    calculated = client.post(f"/api/de-tkg/claims/{claim['id']}/calculate")
    generated = client.post(f"/api/de-tkg/claims/{claim['id']}/letter", json={})

    assert calculated.status_code == 200
    assert calculated.get_json()["total_cents"] == 0
    assert calculated.get_json()["missed_appointments_total_cents"] == expected
    assert generated.status_code == 200
    text = generated.get_json()["letter_text"]
    assert "TKG §58 Abs.4" in text
    assert "vollständigen Dienstausfall" not in text
    assert "Störungsmeldung" not in text


def test_absurd_missed_appointment_count_is_rejected_before_persistence(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    response = client.post(
        "/api/de-tkg/claims",
        json=_claim_payload(eligibility={"missed_appointments": 1_000_000_000}),
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "technical_missed_appointments_limit"
    assert client.get("/api/de-tkg/claims").get_json() == []


@pytest.mark.parametrize(
    "changed",
    [
        {"window_to": "2026-01-06T00:00:00Z"},
        {"origin": "incident"},
        {"fault_report_received_date": "2026-01-02"},
        {"fault_report_channel": "telephone"},
        {"ticket_ref": "CHANGED"},
        {"restored_date": "2026-01-05"},
        {"monthly_fee_cents": 6_000},
        {"confirmed_days": ["2026-01-04"]},
        {"eligibility": {"complete_outage": True, "missed_appointments": 2}},
        {"prior_credit": {"amount_cents": 200, "classification": "goodwill"}},
    ],
)
def test_claim_fact_changes_atomically_invalidate_persisted_letter(
    changed, make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()
    claim = client.post("/api/de-tkg/claims", json=_claim_payload()).get_json()
    assert client.post(f"/api/de-tkg/claims/{claim['id']}/letter", json={}).status_code == 200

    updated = client.put(f"/api/de-tkg/claims/{claim['id']}", json=changed)

    assert updated.status_code == 200
    assert updated.get_json()["letter_text"] is None
    assert client.get(f"/api/de-tkg/claims/{claim['id']}/letter").status_code == 409
    assert client.get(
        f"/api/de-tkg/claims/{claim['id']}/letter?download=1"
    ).status_code == 409
    completed = client.put(
        f"/api/de-tkg/claims/{claim['id']}", json={"status": "completed"}
    )
    assert completed.status_code == 409
    assert completed.get_json()["code"] == "technical_letter_not_generated"


def test_letter_only_and_safe_status_edits_preserve_generated_text(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()
    claim = client.post("/api/de-tkg/claims", json=_claim_payload()).get_json()
    client.post(f"/api/de-tkg/claims/{claim['id']}/letter", json={})

    edited = client.put(
        f"/api/de-tkg/claims/{claim['id']}", json={"letter_text": "Eigener Text"}
    )
    completed = client.put(
        f"/api/de-tkg/claims/{claim['id']}", json={"status": "completed"}
    )

    assert edited.get_json()["letter_text"] == "Eigener Text"
    assert completed.status_code == 200
    assert client.get(f"/api/de-tkg/claims/{claim['id']}/letter").get_json()["letter_text"] == "Eigener Text"

    changed = client.put(
        f"/api/de-tkg/claims/{claim['id']}", json={"monthly_fee_cents": 6_000}
    )
    assert changed.get_json()["status"] == "draft"
    assert changed.get_json()["letter_text"] is None


def test_raw_letter_text_cannot_bypass_calculation_and_generation(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    created_with_letter = client.post(
        "/api/de-tkg/claims", json=_claim_payload(letter_text="stale")
    )
    claim = client.post("/api/de-tkg/claims", json=_claim_payload()).get_json()
    edited_before_generation = client.put(
        f"/api/de-tkg/claims/{claim['id']}", json={"letter_text": "stale"}
    )

    assert created_with_letter.status_code == 409
    assert edited_before_generation.status_code == 409
    assert created_with_letter.get_json()["code"] == "technical_letter_not_generated"
    assert edited_before_generation.get_json()["code"] == "technical_letter_not_generated"


def test_naive_manual_windows_use_configured_timezone_in_winter_and_summer(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config({"timezone": "Europe/Berlin"})
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    winter = client.post(
        "/api/de-tkg/claims",
        json=_claim_payload(window_from="2026-01-15T00:30", window_to="2026-01-15T23:30"),
    ).get_json()
    summer = client.post(
        "/api/de-tkg/claims",
        json=_claim_payload(window_from="2026-07-15T00:30", window_to="2026-07-15T23:30"),
    ).get_json()

    assert winter["window_from"] == "2026-01-14T23:30:00Z"
    assert winter["window_to"] == "2026-01-15T22:30:00Z"
    assert summer["window_from"] == "2026-07-14T22:30:00Z"
    assert summer["window_to"] == "2026-07-15T21:30:00Z"


def test_confirmed_day_outside_configured_local_claim_window_is_rejected_at_boundary(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config({"timezone": "Europe/Berlin"})
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()
    claim = client.post(
        "/api/de-tkg/claims",
        json=_claim_payload(
            window_from="2026-01-03T00:00",
            window_to="2026-01-03T23:59",
            fault_report_received_date="2026-01-01",
            restored_date="2026-01-03",
            confirmed_days=["2026-01-02"],
        ),
    ).get_json()

    response = client.post(f"/api/de-tkg/claims/{claim['id']}/calculate")

    assert claim["window_from"] == "2026-01-02T23:00:00Z"
    assert response.status_code == 422
    assert response.get_json()["code"] == "technical_confirmed_day_outside_claim_window"


def test_unknown_stored_rules_version_blocks_calculation_and_stale_letter(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config()
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()
    claim = client.post("/api/de-tkg/claims", json=_claim_payload()).get_json()
    client.post(f"/api/de-tkg/claims/{claim['id']}/letter", json={})
    with sqlite3.connect(core_storage.db_path) as conn:
        conn.execute(
            "UPDATE de_tkg_claim_drafts SET rules_version = ? WHERE id = ?",
            ("de-tkg58-legacy-unknown", claim["id"]),
        )

    calculated = client.post(f"/api/de-tkg/claims/{claim['id']}/calculate")
    letter = client.get(f"/api/de-tkg/claims/{claim['id']}/letter")

    assert calculated.status_code == 422
    assert calculated.get_json()["code"] == "technical_rules_version_unsupported"
    assert letter.status_code == 409
    assert letter.get_json()["code"] == "technical_rules_version_unsupported"


def test_upgrade_migrates_old_rules_version_and_clears_derived_letter(core_storage):
    from app.modules.de_tkg_compensation.storage import ClaimStorage

    storage = ClaimStorage(core_storage.db_path)
    claim = storage.create({**_claim_payload(), "letter_text": "stale"}, is_demo=False)
    with sqlite3.connect(core_storage.db_path) as conn:
        conn.execute(
            "UPDATE de_tkg_claim_drafts SET rules_version = ? WHERE id = ?",
            ("de-tkg58-pre-registry", claim["id"]),
        )
        conn.execute(
            "DELETE FROM _docsight_migrations WHERE id = ?",
            ("de-tkg-compensation-0002-rules-version",),
        )

    migrated = ClaimStorage(core_storage.db_path).get(claim["id"])

    assert migrated["rules_version"] == "de-tkg58-2026.1"
    assert migrated["letter_text"] is None


def test_ongoing_connection_candidate_api_marks_latest_evidence_without_restoration(
    make_app, make_config, builtin_module_loader_factory, core_storage, tmp_path, monkeypatch
):
    connection_db = tmp_path / "connection_monitor.db"
    with sqlite3.connect(connection_db) as conn:
        conn.execute("CREATE TABLE connection_targets (id INTEGER PRIMARY KEY, enabled INTEGER)")
        conn.execute("CREATE TABLE connection_samples (target_id INTEGER, timestamp REAL, timeout INTEGER)")
        conn.execute("CREATE INDEX idx_samples_target_ts ON connection_samples(target_id, timestamp)")
        conn.execute("INSERT INTO connection_targets VALUES (1, 1)")
        conn.executemany(
            "INSERT INTO connection_samples VALUES (1, ?, 1)",
            [(1_783_201_540 + offset * 60,) for offset in range(6)],
        )
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    config = make_config({
        "timezone": "Europe/Berlin",
        "disabled_modules": ",".join([
            "docsight.reports", "docsight.evidence", "docsight.journal", "docsight.bnetz",
        ]),
    })
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    payload = client.get("/api/de-tkg/candidates").get_json()
    candidate = payload["candidates"][0]

    assert candidate["ongoing"] is True
    assert candidate["restoration_suggested"] is False
    assert candidate["window_from_local"].startswith("2026-07-")
    assert payload["timezone"] == "Europe/Berlin"
    assert "never cap a manual legal claim" in payload["proposal_limits_note"]
    assert payload["proposal_limits"] == {
        "connection_lookback_days": 30,
        "connection_max_results": 64,
        "connection_max_samples_per_target": 2_000,
        "connection_max_targets": 16,
        "incident_max_results": 64,
    }


def test_open_journal_candidate_api_extends_to_configured_local_today(
    make_app, make_config, builtin_module_loader_factory, core_storage, monkeypatch
):
    from app.modules.journal.storage import JournalStorage

    JournalStorage(core_storage.db_path)
    with sqlite3.connect(core_storage.db_path) as conn:
        conn.execute(
            "INSERT INTO incidents (name, description, start_date, end_date, status, "
            "created_at, updated_at, is_demo) VALUES (?, ?, ?, NULL, 'open', ?, ?, 0)",
            ("Open incident", "", "2026-03-27", "2026-03-27T00:00:00Z", "2026-03-27T00:00:00Z"),
        )
    import app.modules.de_tkg_compensation.routes as routes

    monkeypatch.setattr(routes, "local_today", lambda _tz: "2026-03-30")
    config = make_config({
        "timezone": "Europe/Berlin",
        "disabled_modules": ",".join([
            "docsight.reports", "docsight.evidence", "docsight.connection_monitor", "docsight.bnetz",
        ]),
    })
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    payload = client.get("/api/de-tkg/candidates").get_json()
    candidate = next(item for item in payload["candidates"] if item["origin"] == "incident")

    assert candidate["ongoing"] is True
    assert candidate["restoration_suggested"] is False
    assert candidate["suggested_days"] == [
        "2026-03-27", "2026-03-28", "2026-03-29", "2026-03-30"
    ]


def test_all_tkg_claim_and_candidate_routes_require_authentication(
    make_app, make_config, builtin_module_loader_factory, core_storage
):
    config = make_config({"admin_password": "secret123"})
    client = make_app(
        config_manager=config,
        storage=core_storage,
        module_loader_factory=builtin_module_loader_factory(config),
    ).test_client()

    requests = (
        client.get("/api/de-tkg/candidates"),
        client.get("/api/de-tkg/claims"),
        client.post("/api/de-tkg/claims", json=_claim_payload()),
        client.get("/api/de-tkg/claims/1"),
        client.put("/api/de-tkg/claims/1", json={"status": "draft"}),
        client.delete("/api/de-tkg/claims/1"),
        client.post("/api/de-tkg/claims/1/calculate"),
        client.get("/api/de-tkg/claims/1/letter"),
        client.post("/api/de-tkg/claims/1/letter", json={}),
    )

    assert all(response.status_code == 401 for response in requests)
