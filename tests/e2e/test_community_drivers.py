"""Real settings and connection-test workflow for an inert community driver."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.support.lifecycle import (
    ProcessSpec, artifact_log_path, reserve_local_port, running_processes,
)
from tests.test_community_drivers import DRIVER_ID, make_app, write_driver


def serve_community_driver(data_path, *, listener_socket):
    from waitress.server import create_server

    os.environ.clear()
    os.environ["TZ"] = "UTC"
    root = Path(data_path)
    write_driver(root / "modules")
    application, runtime = make_app(root)
    runtime.config_manager.save({"modem_type": "generic"})
    create_server(application, sockets=[listener_socket], threads=2).run()


@pytest.fixture
def community_driver_server(tmp_path):
    reservation = reserve_local_port()
    identity = f"community-driver-{reservation.port}"
    spec = ProcessSpec(
        identity=identity, reservation=reservation,
        process_target=serve_community_driver, args=(str(tmp_path),),
        readiness_path="", log_path=artifact_log_path(identity),
        data_path=str(tmp_path),
    )
    base_url = f"http://127.0.0.1:{reservation.port}"
    with running_processes([spec]):
        yield base_url


def test_community_driver_settings_and_connection(page, community_driver_server):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    # Catalog browsing is unrelated to this locally installed module.
    page.route("**/api/modules/registry", lambda route: route.fulfill(json=[]))
    page.goto(community_driver_server + "/settings")
    page.locator('[data-section="extensions"]').click()
    row = page.locator(f'.toggle-row[data-module-id="{DRIVER_ID}"]')
    expect(row).to_be_visible()
    expect(page.locator("#panel-extensions")).to_have_css("opacity", "1")
    expect(row).to_contain_text("Example Driver")
    expect(row.locator(".module-badge")).to_have_text(["Community", "Driver"])
    screenshot = os.environ.get("DOCSIGHT_DRIVER_SCREENSHOT")
    if screenshot:
        row.scroll_into_view_if_needed()
        page.screenshot(path=screenshot, full_page=True, animations="disabled")
    page.locator('[data-section="connection"]').click()
    page.locator("#modem_type").select_option(DRIVER_ID)
    page.locator("#modem_user").fill("tester")
    page.locator("#modem_password").fill("test-password")
    with page.expect_response("**/api/test-modem") as response:
        page.locator('[onclick="testModem()"]').click()
    assert response.value.json() == {"success": True, "model": "Community Test Modem"}
    with page.expect_response("**/api/config") as saved:
        page.locator('#save-footer button[type="submit"]').click()
    assert saved.value.json()["success"] is True
    page.reload()
    expect(page.locator("#modem_type")).to_have_value(DRIVER_ID)
    with page.expect_response("**/api/test-modem") as masked_response:
        page.locator('[onclick="testModem()"]').click()
    assert masked_response.value.json()["model"] == "Community Test Modem"
    assert errors == []
