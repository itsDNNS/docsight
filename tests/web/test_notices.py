import pytest

from app import maintainer_notices
from app.web import reset_modem_state


@pytest.fixture
def local_notices(monkeypatch):
    notices = (
        {
            "id": "docsight-test-notice",
            "severity": "info",
            "title": "Bundled maintainer notice",
            "body": "This notice is evaluated locally.",
            "locations": ("dashboard", "settings"),
            "link_label": "Release notes",
            "link_url": "https://github.com/itsDNNS/docsight/releases",
        },
    )
    monkeypatch.setattr(maintainer_notices, "LOCAL_NOTICES", notices)
    yield notices


def test_notices_api_returns_local_notices(client, local_notices):
    response = client.get("/api/notices?location=dashboard")

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["notices"][0]["id"] == "docsight-test-notice"
    assert data["notices"][0]["title"] == "Bundled maintainer notice"


def test_notice_dismissal_persists_and_hides_notice(client, config_mgr, local_notices):
    response = client.post("/api/notices/docsight-test-notice/dismiss")

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert config_mgr.get("dismissed_notice_ids") == ["docsight-test-notice"]

    response = client.get("/api/notices?location=dashboard")
    assert response.get_json()["notices"] == []


def test_notice_dismissal_preserves_order_and_keeps_new_id_at_cap(client, config_mgr, local_notices):
    existing = [f"notice-{idx}" for idx in range(200)]
    config_mgr.save({"dismissed_notice_ids": existing})

    response = client.post("/api/notices/docsight-test-notice/dismiss")

    assert response.status_code == 200
    persisted = response.get_json()["dismissed_notice_ids"]
    assert len(persisted) == 200
    assert persisted[-1] == "docsight-test-notice"
    assert "notice-0" not in persisted
    assert config_mgr.get("dismissed_notice_ids") == persisted


def test_notice_api_rejects_invalid_location_and_id(client, local_notices):
    assert client.get("/api/notices?location=remote").status_code == 400
    assert client.post("/api/notices/<script>/dismiss").status_code == 400


def test_dashboard_renders_notice_until_dismissed(client, config_mgr, local_notices):
    reset_modem_state()

    response = client.get("/")
    assert response.status_code == 200
    assert b"Bundled maintainer notice" in response.data
    assert b"data-notice-id=\"docsight-test-notice\"" in response.data

    config_mgr.save({"dismissed_notice_ids": ["docsight-test-notice"]})
    response = client.get("/")
    assert b"Bundled maintainer notice" not in response.data


def test_settings_about_panel_renders_notices_and_privacy_copy(client, local_notices):
    response = client.get("/settings")

    assert response.status_code == 200
    assert b"About Project" in response.data
    assert b"Bundled maintainer notice" in response.data
    assert b"DOCSight does not fetch a remote notices feed" in response.data
