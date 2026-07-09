"""Tests for settings and setup pages."""

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from app.web import init_config, app
from app.config import ConfigManager


def _rendered_panel(html: str, panel_id: str):
    soup = BeautifulSoup(html, "html.parser")
    panel = soup.find(id=panel_id)
    assert panel is not None
    return panel

class TestSettingsRoute:
    def test_settings_contains_comcast_xfinity_isp_option(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        assert b"Comcast/Xfinity" in resp.data

    def test_settings_extensions_panel_lists_rendered_feature_toggles(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        panel = _rendered_panel(resp.data.decode("utf-8"), "panel-extensions")

        headings = [
            heading.get_text(" ", strip=True)
            for heading in panel.select(".toggle-section-divider")
        ]
        assert headings
        assert panel.select_one("#module-registry-refresh") is not None
        assert "Community Modules" in panel.get_text(" ", strip=True)

        rendered_rows = {
            row.select_one(".toggle-title").get_text(" ", strip=True): row
            for row in panel.select(".toggle-row")
            if row.select_one(".toggle-title")
        }
        assert "Gaming Quality Index" in rendered_rows
        assert "Segment Utilization" in rendered_rows
        assert (
            rendered_rows["Gaming Quality Index"].select_one(
                'input[name="gaming_quality_enabled"]'
            )
            is not None
        )
        assert (
            rendered_rows["Segment Utilization"].select_one(
                'input[name="segment_utilization_enabled"]'
            )
            is not None
        )
        assert "Requires FRITZ!OS 8.20 or newer" in rendered_rows[
            "Segment Utilization"
        ].get_text(" ", strip=True)

    def test_settings_bnetz_labels_distinguish_dashboard_and_file_watcher(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        assert "BNetzA measurement dashboard" in html
        assert "Shows manual BNetzA uploads and evidence on the dashboard" in html
        assert "use BNetzA File Watcher for automatic imports" in html

        manifest_path = Path("app/modules/bnetz/manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["name"] == "BNetzA File Watcher Module"
        assert "Automatic import module for BNetzA PDFs/CSVs" in manifest["description"]

    def test_settings_connection_includes_segment_toggle_for_fritzbox(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        assert b"Collect segment utilization" in resp.data
        assert b'name="segment_utilization_enabled"' in resp.data

    def test_settings_modules_shows_segment_disabled_status(self, client, config_mgr):
        config_mgr.save({"segment_utilization_enabled": False})
        init_config(config_mgr)
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        assert b"Segment Utilization" in resp.data
        assert b"Disabled" in resp.data

    def test_settings_sidebar_groups_core_and_module_navigation(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        assert 'aria-labelledby="settings-nav-core-label"' in html
        assert 'id="settings-nav-core-label"' in html
        assert re.search(
            r'id="settings-nav-core-label"[^>]*>\s*Settings\s*</div>', html
        )
        assert html.index('id="settings-nav-core-label"') < html.index('data-section="connection"')

    def test_settings_icon_only_controls_have_accessible_names(self, client, config_mgr):
        config_mgr.save({"admin_password": "admin-secret-value"})
        init_config(config_mgr)
        with client.session_transaction() as session:
            session["authenticated"] = True

        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        assert re.search(r'<button[^>]+id="mobile-menu-button"[^>]+aria-label="Open settings navigation"', html)
        assert 'aria-controls="settings-sidebar"' in html
        assert 'aria-expanded="false"' in html
        assert re.search(r'<button[^>]+data-section="connection"[^>]+aria-current="page"', html)
        assert re.search(r'<button[^>]+onclick="copyToken\(\)"[^>]+aria-label="Copy to Clipboard"', html)
        assert re.search(r'<button[^>]+id="module-registry-refresh"[^>]+aria-label="Refresh"', html)

    def test_settings_notifications_channel_cards_render_compact_status_headers(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        for card_id in ["notification-webhook-card", "notification-apprise-card", "pwa-push-card"]:
            match = re.search(rf'<div class="[^"]*notification-channel-card[^"]*collapsed[^"]*" id="{card_id}"', html)
            assert match is not None
        assert 'data-channel-badge="webhook">Not configured</span>' in html
        assert 'data-channel-badge="apprise">Disabled</span>' in html
        assert 'data-channel-badge="pwa">Disabled</span>' in html
        assert 'aria-controls="notification-webhook-body"' in html
        assert 'id="notification-webhook-body" aria-hidden="true" inert' in html

    def test_settings_modem_status_indicator_starts_hidden_and_live(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        match = re.search(r'<div class="status-indicator" id="modem-status"[^>]*>', html)
        assert match is not None
        status_tag = match.group(0)
        assert "hidden" in status_tag
        assert 'role="status"' in status_tag
        assert 'aria-live="polite"' in status_tag
        assert 'id="dot-notifications"' not in html

    def test_settings_mqtt_status_indicator_starts_hidden_and_live(self):
        template = Path("app/modules/mqtt/templates/mqtt_settings.html").read_text(
            encoding="utf-8"
        )
        status = BeautifulSoup(template, "html.parser").select_one("#mqtt-status")

        assert status is not None
        assert "hidden" in status.attrs
        assert status.get("role") == "status"
        assert status.get("aria-live") == "polite"
        assert status.select_one("#mqtt-status-text") is not None

    def test_settings_smart_capture_uses_shared_form_classes(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        smart_capture = html[html.index('id="panel-smart_capture"'):html.index('id="sc-dependent-content"')]
        guardrails = html[html.index('id="sc-dependent-content"'):html.index('id="sc-history-container"')]
        scoped_html = smart_capture + guardrails

        assert 'class="form-group"' not in scoped_html
        for control_id in [
            "sc_trigger_modulation_direction",
            "sc_trigger_modulation_min_qam",
            "sc_trigger_health_level",
        ]:
            assert re.search(rf'<select[^>]+class="form-input form-select"[^>]+id="{control_id}"', scoped_html)
            assert re.search(rf'<label[^>]+class="form-label"[^>]+for="{control_id}"', scoped_html)
        for control_id in [
            "sc_trigger_error_spike_min_delta",
            "sc_trigger_packet_loss_min_pct",
            "sc_global_cooldown",
            "sc_trigger_cooldown",
            "sc_max_actions_per_hour",
            "sc_speedtest_min_interval",
            "sc_speedtest_max_actions_per_day",
            "sc_speedtest_match_window",
        ]:
            assert re.search(rf'<input[^>]+class="form-input"[^>]+id="{control_id}"', scoped_html)
            assert re.search(rf'<label[^>]+class="form-label"[^>]+for="{control_id}"', scoped_html)

    def test_settings_admin_password_field_uses_saved_secret_placeholder(self, client, config_mgr):
        config_mgr.save({"admin_password": "admin-secret-value"})
        init_config(config_mgr)
        with client.session_transaction() as session:
            session["authenticated"] = True

        resp = client.get("/settings?lang=en")

        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        admin_match = re.search(r'<input[^>]+id="admin_password"[^>]*>', html)
        assert admin_match is not None
        admin_input = admin_match.group(0)
        assert "admin-secret-value" not in html
        assert "••••••••" not in admin_input
        assert 'value=""' in admin_input
        assert 'data-saved-secret="true"' in admin_input


class TestSetupRoute:
    def test_setup_redirects_when_configured(self, client):
        resp = client.get("/setup")
        assert resp.status_code == 302
        assert "/" == resp.headers["Location"]

    def test_setup_renders_when_unconfigured(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data3"))
        init_config(mgr)
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/setup")
            assert resp.status_code == 200
            assert b"DOCSight" in resp.data


class TestSettingsRender:
    def test_settings_renders(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200

