"""Tests for settings and setup pages."""

import re

from app.web import init_config, app
from app.config import ConfigManager

class TestSettingsRoute:
    def test_settings_contains_comcast_xfinity_isp_option(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        assert b"Comcast/Xfinity" in resp.data

    def test_settings_modules_lists_builtin_features(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        assert b"Built-in Features" in resp.data
        assert b"Gaming Quality Index" in resp.data
        assert b"Segment Utilization" in resp.data
        assert b"Requires FRITZ!OS 8.20 or newer" in resp.data

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

