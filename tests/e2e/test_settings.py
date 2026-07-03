"""E2E tests for the settings page."""

import re

import pytest
from playwright.sync_api import expect


def _login(auth_page, auth_server):
    auth_page.goto(f"{auth_server}/login")
    auth_page.fill('input[name="password"]', "e2e-test-password")
    auth_page.click('button[type="submit"]')
    auth_page.wait_for_load_state("networkidle")


class TestSettingsLoad:
    """Settings page loads correctly."""

    def test_page_title(self, settings_page):
        assert "DOCSight" in settings_page.title()
        assert "Settings" in settings_page.title() or "Einstellungen" in settings_page.title()

    def test_sidebar_visible(self, settings_page):
        sidebar = settings_page.locator("#settings-sidebar")
        assert sidebar.is_visible()

    def test_connection_tab_active(self, settings_page):
        btn = settings_page.locator('button[data-section="connection"]')
        assert "active" in btn.get_attribute("class")


class TestSettingsTabSwitching:
    """Clicking sidebar tabs shows the correct panel."""

    @pytest.mark.parametrize("section", [
        "general",
        "security",
        "appearance",
        "notifications",
        "extensions",
    ])
    def test_switch_to_section(self, settings_page, section):
        btn = settings_page.locator(f'button[data-section="{section}"]')
        btn.click()
        panel = settings_page.locator(f'#panel-{section}, [id="panel-{section}"]')
        assert panel.is_visible()

    def test_switch_back_to_connection(self, settings_page):
        settings_page.locator('button[data-section="general"]').click()
        settings_page.locator('button[data-section="connection"]').click()
        panel = settings_page.locator("#panel-connection")
        assert panel.is_visible()


class TestSettingsFormElements:
    """Form elements exist on settings panels."""

    def test_connection_has_modem_type_select(self, settings_page):
        select = settings_page.locator('select[name="modem_type"], #modem_type, #modem-type')
        assert select.count() > 0

    def test_security_has_password_field(self, settings_page):
        settings_page.locator('button[data-section="security"]').click()
        pw = settings_page.locator('input[type="password"]')
        assert pw.count() > 0

    def test_back_to_dashboard_link(self, settings_page):
        link = settings_page.locator('a[href="/"]')
        assert link.count() > 0

    def test_notifications_panel_has_apprise_fields(self, settings_page):
        settings_page.locator('button[data-section="notifications"]').click()
        expect(settings_page.locator('#notify_apprise_enabled')).to_have_count(1)
        expect(settings_page.locator('#notify_apprise_url')).to_have_count(1)
        expect(settings_page.locator('#notify_apprise_key')).to_have_count(1)
        expect(settings_page.locator('#notify_apprise_token')).to_have_count(1)
        expect(settings_page.locator('#notify_apprise_tag')).to_have_count(1)

    def test_notifications_panel_has_pwa_push_fields(self, settings_page):
        settings_page.locator('button[data-section="notifications"]').click()
        expect(settings_page.locator('#pwa-push-card')).to_have_count(1)
        expect(settings_page.locator('#notify_pwa_push_enabled')).to_have_count(1)
        expect(settings_page.locator('#notify_pwa_push_vapid_public_key')).to_have_count(1)
        expect(settings_page.locator('#notify_pwa_push_vapid_private_key')).to_have_count(1)
        expect(settings_page.locator('#notify_pwa_push_vapid_subject')).to_have_count(1)
        expect(settings_page.locator('#pwa-push-status')).to_have_count(1)

    def test_notifications_panel_has_per_severity_cooldown_rows(self, settings_page):
        settings_page.locator('button[data-section="notifications"]').click()

        for event_type in [
            "health_change",
            "power_change",
            "snr_change",
            "modulation_change",
        ]:
            for severity in ["info", "warning", "critical"]:
                expect(
                    settings_page.locator(
                        f'.notify-event-row[data-event="{event_type}"][data-severity="{severity}"]'
                    )
                ).to_have_count(1)

        expect(
            settings_page.locator(
                '.notify-event-row[data-event="cm_packet_loss_warning"][data-severity="warning"]'
            )
        ).to_have_count(1)
        expect(
            settings_page.locator(
                '.notify-event-row[data-event="error_spike"][data-severity="warning"]'
            )
        ).to_have_count(1)


class TestSettingsDirtyState:
    """Unsaved-change prompts only appear for deliberate settings edits."""

    def test_saved_secret_user_edit_guard_requires_active_field(self, settings_page):
        result = settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#modem_password');
              input.dataset.savedSecret = 'true';
              const inactive = window._shouldTreatSavedSecretEventAsUserEdit({
                target: input,
                isTrusted: true,
              });
              input.focus();
              const active = window._shouldTreatSavedSecretEventAsUserEdit({
                target: input,
                isTrusted: true,
              });
              const untrusted = window._shouldTreatSavedSecretEventAsUserEdit({
                target: input,
                isTrusted: false,
              });
              return {inactive, active, untrusted};
            }
            """
        )

        assert result == {"inactive": False, "active": True, "untrusted": False}

    def test_modem_password_autofill_does_not_show_unsaved_footer(self, settings_page):
        footer = settings_page.locator("#save-footer")
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#modem_password');
              input.dataset.savedSecret = 'true';
              input.setAttribute('placeholder', 'Gespeichert');
              input.value = 'autofilled-password';
              input.dispatchEvent(new Event('input', {bubbles: true}));
              input.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """
        )

        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(footer).to_have_attribute("aria-hidden", "true")
        expect(footer).to_have_attribute("inert", "")
        settings_page.locator('button[data-section="extensions"]').click()
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_autofilled_saved_secret_is_masked_when_unrelated_setting_is_saved(self, settings_page):
        payloads = []

        def capture_config(route):
            payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        settings_page.route("**/api/config", capture_config)
        settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#modem_password');
              input.dataset.savedSecret = 'true';
              input.setAttribute('placeholder', 'Gespeichert');
              input.value = 'autofilled-password';
              input.dispatchEvent(new Event('input', {bubbles: true}));
              input.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """
        )
        settings_page.locator('#modem_url').fill('http://192.168.100.1')

        settings_page.locator('#save-footer button[type="submit"]').click()
        expect(settings_page.locator("#save-footer")).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        assert payloads[-1]["modem_password"] == "••••••••"

    def test_saved_apprise_secret_is_masked_when_unrelated_setting_is_saved(self, settings_page):
        payloads = []

        def capture_config(route):
            payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        settings_page.route("**/api/config", capture_config)
        settings_page.evaluate(
            """
            () => {
              const key = document.querySelector('#notify_apprise_key');
              const token = document.querySelector('#notify_apprise_token');
              for (const input of [key, token]) {
                input.dataset.savedSecret = 'true';
                input.setAttribute('placeholder', 'Saved');
                input.value = 'password-manager-fill';
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new Event('change', {bubbles: true}));
              }
            }
            """
        )
        settings_page.locator('button[data-section="general"]').click()
        settings_page.locator('#poll_interval').fill('901')

        settings_page.locator('#save-footer button[type="submit"]').click()
        expect(settings_page.locator("#save-footer")).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        assert payloads[-1]["notify_apprise_key"] == "••••••••"
        assert payloads[-1]["notify_apprise_token"] == "••••••••"

    def test_saved_pwa_push_private_key_is_masked_when_unrelated_setting_is_saved(self, settings_page):
        payloads = []

        def capture_config(route):
            payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        settings_page.route("**/api/config", capture_config)
        settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#notify_pwa_push_vapid_private_key');
              input.dataset.savedSecret = 'true';
              input.setAttribute('placeholder', 'Saved');
              input.value = 'password-manager-fill';
              input.dispatchEvent(new Event('input', {bubbles: true}));
              input.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """
        )
        settings_page.locator('button[data-section="general"]').click()
        settings_page.locator('#poll_interval').fill('902')

        settings_page.locator('#save-footer button[type="submit"]').click()
        expect(settings_page.locator("#save-footer")).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        assert payloads[-1]["notify_pwa_push_vapid_private_key"] == "••••••••"

    def test_saved_admin_password_is_masked_when_unrelated_setting_is_saved(self, auth_page, auth_server):
        payloads = []

        def capture_config(route):
            payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        _login(auth_page, auth_server)
        auth_page.goto(f"{auth_server}/settings")
        auth_page.wait_for_load_state("networkidle")
        auth_page.route("**/api/config", capture_config)

        admin_password = auth_page.locator('#admin_password')
        expect(admin_password).to_have_attribute("data-saved-secret", "true")
        assert admin_password.input_value() == ""

        auth_page.locator('button[data-section="general"]').click()
        auth_page.locator('#poll_interval').fill('903')
        auth_page.locator('#save-footer button[type="submit"]').click()
        expect(auth_page.locator("#save-footer")).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        assert payloads[-1]["admin_password"] == "••••••••"

    def test_user_edited_admin_password_is_submitted_and_cleared_after_save(self, auth_page, auth_server):
        payloads = []

        def capture_config(route):
            payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        _login(auth_page, auth_server)
        auth_page.goto(f"{auth_server}/settings")
        auth_page.wait_for_load_state("networkidle")
        auth_page.route("**/api/config", capture_config)

        auth_page.locator('button[data-section="security"]').click()
        auth_page.locator('#admin_password').fill('new-admin-secret')
        auth_page.locator('#save-footer button[type="submit"]').click()
        expect(auth_page.locator("#save-footer")).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        assert payloads[-1]["admin_password"] == "new-admin-secret"
        assert auth_page.locator('#admin_password').input_value() == ""

    def test_user_edited_saved_secret_is_submitted_and_cleared_after_save(self, settings_page):
        payloads = []

        def capture_config(route):
            payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        settings_page.route("**/api/config", capture_config)
        settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#modem_password');
              input.dataset.savedSecret = 'true';
              input.setAttribute('placeholder', 'Gespeichert');
            }
            """
        )

        settings_page.locator('#modem_password').fill('new-secret-value')
        settings_page.locator('#save-footer button[type="submit"]').click()
        expect(settings_page.locator("#save-footer")).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        assert payloads[-1]["modem_password"] == "new-secret-value"
        assert settings_page.locator('#modem_password').input_value() == ""

    def test_real_settings_edit_is_saved_when_module_toggle_is_clicked(self, settings_page):
        config_payloads = []
        batch_payloads = []

        def capture_config(route):
            config_payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        def capture_batch(route):
            batch_payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True, "restart_required": False})

        settings_page.route("**/api/config", capture_config)
        settings_page.route("**/api/modules/batch", capture_batch)

        footer = settings_page.locator("#save-footer")
        settings_page.locator('#modem_url').fill('http://192.168.100.1')
        expect(footer).to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(footer).not_to_have_attribute("aria-hidden", "true")
        expect(footer).not_to_have_attribute("inert", "")

        settings_page.locator('button[data-section="extensions"]').click()
        toggle = settings_page.locator('.module-toggle-input').first
        assert toggle.count() == 1
        with settings_page.expect_request("**/api/config"):
            with settings_page.expect_request("**/api/modules/batch"):
                settings_page.locator('.module-toggle .toggle-slider').first.click()

        expect(settings_page.locator('#docsight-confirm-modal')).to_have_count(0)
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        assert config_payloads[-1]["modem_url"] == "http://192.168.100.1"
        assert len(batch_payloads[-1]["modules"]) == 1


class TestSettingsInstantToggleSave:
    """Settings toggles persist immediately without the global save footer."""

    def test_module_toggle_saves_immediately_without_direct_enable_disable_calls(self, settings_page):
        config_payloads = []
        batch_payloads = []
        immediate_calls = []

        def capture_config(route):
            config_payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        def capture_batch(route):
            batch_payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True, "restart_required": True})

        def capture_immediate(route):
            immediate_calls.append(route.request.url)
            route.fulfill(status=500, json={"success": False})

        settings_page.route("**/api/config", capture_config)
        settings_page.route("**/api/modules/batch", capture_batch)
        settings_page.route(re.compile(r".*/api/modules/.+/(enable|disable)$"), capture_immediate)

        settings_page.locator('button[data-section="extensions"]').click()
        toggle_slider = settings_page.locator('.module-toggle-input[data-is-threshold="false"] + .toggle-slider').first
        assert toggle_slider.count() == 1
        with settings_page.expect_request("**/api/config"):
            with settings_page.expect_request("**/api/modules/batch"):
                toggle_slider.click()

        footer = settings_page.locator("#save-footer")
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(settings_page.locator("#module-restart-banner")).to_be_visible()
        assert len(config_payloads) == 1
        assert len(batch_payloads) == 1
        assert len(batch_payloads[0]["modules"]) == 1
        assert immediate_calls == []

    def test_normal_instant_toggle_does_not_flash_manual_save_footer_while_save_is_pending(self, settings_page):
        pending_routes = []

        def hold_config(route):
            pending_routes.append(route)

        settings_page.route("**/api/config", hold_config)
        settings_page.locator('button[data-section="notifications"]').click()
        footer = settings_page.locator("#save-footer")
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#notify_apprise_enabled + .toggle-slider').click()

        assert settings_page.evaluate("() => window._formDirty") is True
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(footer).to_have_attribute("aria-hidden", "true")
        expect(footer).to_have_attribute("inert", "")
        assert len(pending_routes) == 1
        pending_routes[0].fulfill(json={"success": True})
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_normal_instant_toggle_success_does_not_show_settings_saved_toast(self, settings_page):
        settings_page.route("**/api/config", lambda route: route.fulfill(json={"success": True}))
        settings_page.locator('button[data-section="notifications"]').click()

        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#notify_apprise_enabled + .toggle-slider').click()

        toast = settings_page.locator("#toast")
        expect(toast).not_to_be_visible()
        expect(toast).not_to_have_text(re.compile(r"Settings saved", re.I))

    def test_queued_instant_toggles_keep_manual_save_footer_hidden_between_saves(self, settings_page):
        pending_routes = []

        def hold_config(route):
            pending_routes.append(route)

        settings_page.route("**/api/config", hold_config)
        settings_page.locator('button[data-section="notifications"]').click()
        footer = settings_page.locator("#save-footer")

        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#notify_apprise_enabled + .toggle-slider').click()
        settings_page.evaluate(
            """
            () => {
              const toggle = document.querySelector('#notify_pwa_push_enabled');
              toggle.checked = !toggle.checked;
              window._saveSettingsInstantly();
            }
            """
        )
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        with settings_page.expect_request("**/api/config"):
            pending_routes[0].fulfill(json={"success": True})
        settings_page.wait_for_timeout(50)

        assert len(pending_routes) == 2
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        pending_routes[1].fulfill(json={"success": True})
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_notification_cooldown_edit_keeps_dirty_protection_until_change_save_succeeds(self, settings_page):
        settings_page.route("**/api/config", lambda route: route.fulfill(json={"success": True}))
        settings_page.locator('button[data-section="notifications"]').click()
        input_el = settings_page.locator('.notify-event-row[data-event="power_change"][data-severity="warning"] .notify-cooldown-input')
        footer = settings_page.locator("#save-footer")

        input_el.fill('42')
        assert settings_page.evaluate("() => window._formDirty") is True
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        with settings_page.expect_request("**/api/config"):
            input_el.blur()
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        assert settings_page.evaluate("() => window._formDirty") is False

    def test_hidden_companion_instant_toggle_does_not_poison_manual_dirty_baseline(self, settings_page):
        settings_page.route("**/api/config", lambda route: route.fulfill(json={"success": True}))
        settings_page.locator('button[data-section="extensions"]').click()
        footer = settings_page.locator("#save-footer")
        instant_toggle = settings_page.locator('#panel-extensions label.toggle input[type="checkbox"]:not(.module-toggle-input)').first
        expect(instant_toggle).to_have_count(1)

        with settings_page.expect_request("**/api/config"):
            instant_toggle.evaluate("el => { el.checked = !el.checked; el.dispatchEvent(new Event('change', {bubbles: true})); }")
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        settings_page.locator('button[data-section="general"]').click()
        manual_field = settings_page.locator('#poll_interval')
        original_value = manual_field.input_value()
        edited_value = "901" if original_value != "901" else "902"
        manual_field.fill(edited_value)
        expect(footer).to_have_class(re.compile(r".*\bvisible\b.*"))
        manual_field.fill(original_value)
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_notification_event_toggle_saves_cooldowns_immediately(self, settings_page):
        config_payloads = []

        def capture_config(route):
            config_payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        settings_page.route("**/api/config", capture_config)
        settings_page.locator('button[data-section="notifications"]').click()
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('.notify-event-row[data-event="health_change"][data-severity="critical"] .toggle-slider').click()

        footer = settings_page.locator("#save-footer")
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        assert len(config_payloads) == 1
        cooldowns = config_payloads[0]["notify_cooldowns"]
        assert '"health_change:critical":0' in cooldowns.replace(" ", "")

    def test_notification_cooldown_value_saves_immediately(self, settings_page):
        config_payloads = []

        def capture_config(route):
            config_payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        settings_page.route("**/api/config", capture_config)
        settings_page.locator('button[data-section="notifications"]').click()
        settings_page.locator('.notify-event-row[data-event="power_change"][data-severity="warning"] .notify-cooldown-input').fill('42')
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('.notify-event-row[data-event="power_change"][data-severity="warning"] .notify-cooldown-input').blur()

        footer = settings_page.locator("#save-footer")
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        assert len(config_payloads) == 1
        cooldowns = config_payloads[0]["notify_cooldowns"]
        assert '"power_change:warning":42' in cooldowns.replace(" ", "")

    def test_notification_event_toggle_stays_dirty_when_instant_save_fails(self, settings_page):
        def fail_config(route):
            route.fulfill(status=500, json={"success": False, "error": "Save failed"})

        settings_page.route("**/api/config", fail_config)
        settings_page.locator('button[data-section="notifications"]').click()
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('.notify-event-row[data-event="health_change"][data-severity="critical"] .toggle-slider').click()

        footer = settings_page.locator("#save-footer")
        expect(footer).to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(settings_page.locator('#global-error')).to_be_visible()

    def test_edit_made_during_instant_save_remains_dirty(self, settings_page):
        config_payloads = []

        def capture_config(route):
            config_payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        settings_page.route("**/api/config", capture_config)
        settings_page.locator('button[data-section="notifications"]').click()
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('.notify-event-row[data-event="health_change"][data-severity="critical"] .toggle-slider').click()
        settings_page.locator('button[data-section="connection"]').click()
        settings_page.locator('#modem_url').fill('http://192.168.100.1')

        footer = settings_page.locator("#save-footer")
        expect(footer).to_have_class(re.compile(r".*\bvisible\b.*"))
        assert config_payloads[0]["modem_url"] != "http://192.168.100.1"

    def test_saved_secret_clears_when_concurrent_edit_remains_dirty(self, settings_page):
        settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#modem_password');
              input.dataset.savedSecret = 'true';
              input.setAttribute('placeholder', 'Saved');
            }
            """
        )
        settings_page.locator('#modem_password').fill('new-secret-value')
        saved_baseline = settings_page.evaluate(
            "() => _serializeSettingsForm(document.getElementById('settings-form'))"
        )
        settings_page.locator('#modem_url').fill('http://192.168.100.1')

        settings_page.evaluate("baseline => _finishSettingsSave(baseline)", saved_baseline)

        assert settings_page.locator('#modem_password').input_value() == ""
        expect(settings_page.locator("#save-footer")).to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_saved_secret_edited_after_save_snapshot_is_not_cleared(self, settings_page):
        settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#modem_password');
              input.dataset.savedSecret = 'true';
              input.setAttribute('placeholder', 'Saved');
            }
            """
        )
        saved_baseline = settings_page.evaluate(
            "() => _serializeSettingsForm(document.getElementById('settings-form'))"
        )
        settings_page.locator('#modem_password').fill('new-secret-value')

        settings_page.evaluate("baseline => _finishSettingsSave(baseline)", saved_baseline)

        assert settings_page.locator('#modem_password').input_value() == "new-secret-value"
        expect(settings_page.locator("#save-footer")).to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_saved_secret_reedited_after_save_snapshot_is_not_cleared(self, settings_page):
        settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#modem_password');
              input.dataset.savedSecret = 'true';
              input.setAttribute('placeholder', 'Saved');
            }
            """
        )
        settings_page.locator('#modem_password').fill('first-secret-value')
        saved_baseline = settings_page.evaluate(
            "() => _serializeSettingsForm(document.getElementById('settings-form'))"
        )
        settings_page.locator('#modem_password').fill('second-secret-value')

        settings_page.evaluate("baseline => _finishSettingsSave(baseline)", saved_baseline)

        assert settings_page.locator('#modem_password').input_value() == "second-secret-value"
        expect(settings_page.locator("#save-footer")).to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_threshold_profile_toggles_are_exclusive_radios(self, settings_page):
        settings_page.locator('button[data-section="extensions"]').click()
        threshold_toggles = settings_page.locator('.module-toggle-input[data-is-threshold="true"]')
        assert threshold_toggles.count() >= 1
        assert threshold_toggles.first.get_attribute("type") == "radio"
        assert threshold_toggles.first.get_attribute("name") == "threshold_profile_module"
        assert threshold_toggles.first.get_attribute("aria-labelledby")
        assert threshold_toggles.first.get_attribute("aria-describedby")
        expect(settings_page.locator('[role="group"][aria-labelledby="extensions-modules-heading"]')).to_be_visible()


class TestSpeedtestModule:
    """Speedtest module settings interactions."""

    def test_speedtest_section_shows_test_button(self, settings_page):
        settings_page.locator('button[data-section="mod-docsight_speedtest"]').click()

        button = settings_page.get_by_role("button", name="Test Connection")
        assert button.is_visible()

    def test_speedtest_test_connection_sends_insecure_tls_flag(self, settings_page):
        captured = []

        def capture_request(route):
            captured.append(route.request.post_data_json)
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success": true, "results": 0}',
            )

        settings_page.route("**/api/test-speedtest", capture_request)
        settings_page.locator('button[data-section="mod-docsight_speedtest"]').click()
        settings_page.locator("#speedtest_tracker_url").fill("https://speedtest.local:8443")
        settings_page.locator("#speedtest_tracker_token").fill("[REDACTED]")
        settings_page.locator("#panel-mod-docsight_speedtest label.toggle").click()
        expect(settings_page.locator("#speedtest_tls_insecure")).to_be_checked()
        settings_page.get_by_role("button", name="Test Connection").click()

        expect(settings_page.locator("#speedtest-test")).to_contain_text("Connected")
        assert captured
        assert captured[0]["speedtest_tls_insecure"] == "true"

    def test_speedtest_test_connection_success(self, settings_page):
        settings_page.route(
            "**/api/test-speedtest",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
                {
                  "success": true,
                  "results": 1,
                  "latest": {
                    "download": "120.50 Mbps",
                    "upload": "24.10 Mbps",
                    "ping": "11.4 ms"
                  }
                }
                """,
            ),
        )

        settings_page.locator('button[data-section="mod-docsight_speedtest"]').click()
        settings_page.get_by_role("button", name="Test Connection").click()

        result = settings_page.locator("#speedtest-test")
        expect(result).to_be_visible()
        expect(result).to_contain_text("Connected")
        expect(result).to_contain_text("120.50 Mbps")
        expect(result).to_contain_text("24.10 Mbps")
        expect(result).to_contain_text("11.4 ms")

    def test_speedtest_test_connection_error(self, settings_page):
        settings_page.route(
            "**/api/test-speedtest",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success": false, "error": "HTTP 401"}',
            ),
        )

        settings_page.locator('button[data-section="mod-docsight_speedtest"]').click()
        settings_page.get_by_role("button", name="Test Connection").click()

        result = settings_page.locator("#speedtest-test")
        expect(result).to_be_visible()
        expect(result).to_contain_text("Error")
        expect(result).to_contain_text("HTTP 401")


class TestBackupModule:
    """Backup module settings interactions."""

    def test_backup_section_loads_existing_backups(self, settings_page):
        settings_page.route(
            "**/api/backup/list",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
                [
                  {
                    "filename": "docsight_backup_2026-03-14_120000.tar.gz",
                    "size": 3145728,
                    "modified": "2026-03-14T12:00:00"
                  }
                ]
                """,
            ),
        )

        settings_page.locator('button[data-section="mod-docsight_backup"]').click()

        backup_list = settings_page.locator("#backup-list")
        assert backup_list.locator("code").first.text_content() == "docsight_backup_2026-03-14_120000.tar.gz"
        assert backup_list.get_by_text("3.0 MB").count() > 0
