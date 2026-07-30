"""Desktop runtime endpoint mode, loopback, and token policy."""

from __future__ import annotations

TOKEN = "A" * 43
RUNTIME_ENV = {
    "DOCSIGHT_DESKTOP_MODE": "1",
    "DOCSIGHT_DESKTOP_INSTANCE_TOKEN": TOKEN,
    "DOCSIGHT_DESKTOP_INSTANCE_PID": "4242",
    "DOCSIGHT_DESKTOP_PROCESS_START_TIME": "133700000",
    "DOCSIGHT_DESKTOP_APP_VERSION": "v1.2.3",
    "WEB_PORT": "8765",
}


def set_runtime_environment(monkeypatch):
    for key, value in RUNTIME_ENV.items():
        monkeypatch.setenv(key, value)


def test_desktop_runtime_endpoint_is_unavailable_outside_desktop_mode(
    client,
    monkeypatch,
):
    for key in RUNTIME_ENV:
        monkeypatch.delenv(key, raising=False)

    response = client.get(
        "/desktop-runtime",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 404


def test_desktop_runtime_endpoint_rejects_non_loopback_client(client, monkeypatch):
    set_runtime_environment(monkeypatch)

    response = client.get(
        "/desktop-runtime",
        headers={"Authorization": f"Bearer {TOKEN}"},
        environ_base={"REMOTE_ADDR": "192.0.2.10"},
    )

    assert response.status_code == 403


def test_desktop_runtime_endpoint_rejects_missing_or_wrong_token(
    client,
    monkeypatch,
):
    set_runtime_environment(monkeypatch)

    assert client.get("/desktop-runtime").status_code == 404
    assert client.get(
        "/desktop-runtime",
        headers={"Authorization": f"Bearer {'B' * 43}"},
    ).status_code == 404


def test_desktop_runtime_endpoint_rejects_non_ascii_authorization(
    client,
    monkeypatch,
):
    set_runtime_environment(monkeypatch)

    response = client.get(
        "/desktop-runtime",
        headers={"Authorization": "Bearer \N{SNOWMAN}"},
    )

    assert response.status_code == 404


def test_desktop_runtime_endpoint_returns_exact_identity_on_loopback(
    client,
    monkeypatch,
):
    set_runtime_environment(monkeypatch)

    response = client.get(
        "/desktop-runtime",
        headers={"Authorization": f"Bearer {TOKEN}"},
        environ_base={"REMOTE_ADDR": "::1"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "schema_version": 1,
        "pid": 4242,
        "port": 8765,
        "application_version": "v1.2.3",
        "process_start_time": 133700000,
        "instance_token": TOKEN,
    }


def test_desktop_runtime_endpoint_rejects_malformed_process_contract(
    client,
    monkeypatch,
):
    set_runtime_environment(monkeypatch)
    monkeypatch.setenv("DOCSIGHT_DESKTOP_INSTANCE_PID", "true")

    response = client.get(
        "/desktop-runtime",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 404


def test_ordinary_health_does_not_expose_desktop_token(client, monkeypatch):
    set_runtime_environment(monkeypatch)

    response = client.get("/health")

    assert response.status_code == 200
    assert "instance_token" not in response.get_json()
