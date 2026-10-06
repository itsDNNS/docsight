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

    def test_settings_render_in_the_app_shell(self, settings_page):
        expect(settings_page.locator("#topnav")).to_be_visible()
        expect(settings_page.locator("#settings-index")).to_be_visible()
        gear = settings_page.locator(".topnav-settings")
        expect(gear).to_have_attribute("aria-current", "page")
        expect(gear).to_have_attribute("aria-label", "Settings")
        expect(settings_page.locator("#settings-section-title")).to_have_text("Connection")

    def test_topnav_destinations_lead_back_to_the_dashboard(self, settings_page):
        settings_page.locator("#nav-toggle-signal").click()
        with settings_page.expect_navigation():
            settings_page.locator('#nav-panel-signal [data-view="trends"]').click()
        expect(settings_page).to_have_url(re.compile(r"/#trends$"))
        expect(settings_page.locator("#view-trends")).to_have_class(re.compile(r".*\bactive\b.*"))

    def test_connection_tab_active(self, settings_page):
        btn = settings_page.locator('button[data-section="connection"]')
        assert "active" in btn.get_attribute("class")

    def test_built_in_module_settings_sit_in_their_topic_sections(self, settings_page):
        index = settings_page.locator("#settings-index")
        expect(index).to_have_attribute("aria-label", "Settings sections")
        expect(index.locator('[data-section^="mod-"]')).to_have_count(0)
        for section, module in [("sources", "speedtest"), ("evidence", "reports"), ("data", "backup"), ("access", "mqtt")]:
            expect(settings_page.locator(f"#panel-{section} #block-mod-docsight_{module}")).to_have_count(1)

    def test_old_module_addresses_open_the_topic_section_at_the_module(self, page, live_server):
        page.goto(f"{live_server}/settings#mod-docsight_backup")
        page.wait_for_load_state("networkidle")
        expect(page.locator("#panel-data")).to_be_visible()
        expect(page.locator('button[data-section="data"]')).to_have_attribute("aria-current", "page")
        expect(page).to_have_url(re.compile(r"#data$"))
        expect(page.locator("#block-mod-docsight_backup")).to_be_in_viewport()

    @pytest.mark.parametrize("width", [1280, 390])
    def test_bnetz_extension_labels_distinguish_dashboard_and_file_watcher(self, settings_page, width):
        settings_page.set_viewport_size({"width": width, "height": 844})
        settings_page.reload(wait_until="networkidle")
        settings_page.evaluate("() => window.switchSection('extensions')")

        panel = settings_page.locator("#panel-extensions")
        expect(panel.get_by_text("BNetzA measurement dashboard")).to_be_visible()
        expect(panel.get_by_text("Shows manual BNetzA uploads and evidence on the dashboard")).to_be_visible()
        expect(panel.get_by_text("BNetzA File Watcher Module")).to_be_visible()
        expect(panel.get_by_text("Automatic import module for BNetzA PDFs/CSVs")).to_be_visible()
        settings_page.evaluate("() => window.switchSection('evidence')")
        expect(settings_page.locator("#block-mod-docsight_bnetz .card-title").first).to_have_text(re.compile("BNetzA File Watcher"))
        settings_page.evaluate("() => window.switchSection('extensions')")

        assert panel.evaluate("el => el.scrollWidth <= document.documentElement.clientWidth")


class TestSettingsSearch:
    """The search finds settings by their label and opens the section at the match."""

    def test_result_opens_the_section_and_focuses_the_field(self, settings_page):
        settings_page.locator('button[data-section="appearance"]').click()
        settings_page.locator("#settings-search").fill("history")
        results = settings_page.locator(".settings-search-result")
        expect(results.first.locator(".settings-search-label")).to_have_text("History and snapshots")
        result = results.filter(has_text="History (days)")
        expect(result.locator(".settings-search-where")).to_contain_text("Data and storage")
        result.click()
        expect(settings_page.locator("#panel-data")).to_be_visible()
        expect(settings_page.locator("#history_days")).to_be_focused()
        expect(settings_page.locator("#settings-search-results")).to_be_hidden()

    def test_keyboard_moves_through_results_and_escape_clears(self, settings_page):
        search = settings_page.locator("#settings-search")
        search.fill("mqtt")
        search.press("ArrowDown")
        expect(settings_page.locator(".settings-search-result").first).to_be_focused()
        settings_page.keyboard.press("Escape")
        expect(search).to_be_focused()
        expect(search).to_have_value("")
        expect(settings_page.locator("#settings-search-results")).to_be_hidden()
        search.fill("time zone")
        search.press("Enter")
        expect(settings_page.locator("#panel-appearance")).to_be_visible()

    def test_no_match_says_so(self, settings_page):
        settings_page.locator("#settings-search").fill("zzz-no-such-setting")
        expect(settings_page.locator(".settings-search-empty")).to_have_text("No setting matches")

    def test_phone_search_opens_the_section_view(self, settings_page):
        settings_page.set_viewport_size({"width": 390, "height": 844})
        settings_page.goto(settings_page.url.split("#")[0], wait_until="networkidle")
        settings_page.locator("#settings-search").fill("poll")
        settings_page.locator(".settings-search-result").first.click()
        expect(settings_page.locator("#panel-connection")).to_be_visible()
        expect(settings_page.locator("#settings-index")).to_be_hidden()


class TestSettingsCompactLayout:
    """Below 768px the section index is a list and each section opens as its own view."""

    def test_phone_opens_on_the_section_list_with_every_section_reachable(self, settings_page):
        settings_page.set_viewport_size({"width": 390, "height": 844})
        settings_page.goto(settings_page.url.split("#")[0], wait_until="networkidle")

        expect(settings_page.locator("#settings-index")).to_be_visible()
        expect(settings_page.locator(".settings-content")).to_be_hidden()
        about = settings_page.locator('button[data-section="about"]')
        about.scroll_into_view_if_needed()
        expect(about).to_be_visible()
        assert settings_page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")

    def test_section_opens_as_detail_and_back_returns_to_the_list(self, settings_page):
        settings_page.set_viewport_size({"width": 390, "height": 844})
        settings_page.goto(settings_page.url.split("#")[0], wait_until="networkidle")

        settings_page.locator('button[data-section="notifications"]').click()
        expect(settings_page.locator("#panel-notifications")).to_be_visible()
        expect(settings_page.locator("#settings-index")).to_be_hidden()
        expect(settings_page.locator("#settings-section-title")).to_be_focused()
        expect(settings_page).to_have_url(re.compile(r"#notifications$"))
        expect(settings_page.locator('button[data-section="notifications"]')).to_have_attribute("aria-current", "page")

        settings_page.locator("#settings-back").click()
        expect(settings_page.locator("#settings-index")).to_be_visible()
        expect(settings_page.locator("#panel-notifications")).to_be_hidden()
        expect(settings_page.locator('button[data-section="notifications"]')).to_be_focused()
        expect(settings_page).not_to_have_url(re.compile(r"#"))

    def test_browser_back_from_a_section_returns_to_the_list(self, settings_page):
        settings_page.set_viewport_size({"width": 390, "height": 844})
        settings_page.goto(settings_page.url.split("#")[0], wait_until="networkidle")

        settings_page.locator('button[data-section="data"]').click()
        expect(settings_page.locator("#panel-data")).to_be_visible()
        settings_page.go_back()
        expect(settings_page.locator("#settings-index")).to_be_visible()
        expect(settings_page.locator("#panel-data")).to_be_hidden()

    def test_deep_link_opens_the_section_and_back_shows_the_list(self, settings_page):
        settings_page.set_viewport_size({"width": 390, "height": 844})
        settings_page.goto(settings_page.url.split("#")[0] + "#security", wait_until="networkidle")

        expect(settings_page.locator("#panel-access")).to_be_visible()
        expect(settings_page.locator("#settings-index")).to_be_hidden()
        settings_page.locator("#settings-back").click()
        expect(settings_page.locator("#settings-index")).to_be_visible()

    def test_active_settings_navigation_item_is_announced(self, settings_page):
        connection = settings_page.locator('button[data-section="connection"]')
        notifications = settings_page.locator('button[data-section="notifications"]')
        expect(connection).to_have_attribute("aria-current", "page")
        expect(notifications).not_to_have_attribute("aria-current", "page")

        notifications.click()
        expect(notifications).to_have_attribute("aria-current", "page")
        expect(connection).not_to_have_attribute("aria-current", "page")

    def test_icon_only_settings_controls_have_accessible_names(self, settings_page):
        settings_page.route(
            "**/api/backup/list",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='[{"filename":"docsight_backup_2026-03-14_120000.tar.gz","size":3145728,"modified":"2026-03-14T12:00:00"}]',
            ),
        )

        expect(settings_page.locator("#nav-toggle-more")).to_have_attribute("aria-label", "More")

        settings_page.locator('button[data-section="extensions"]').click()
        refresh = settings_page.locator("#module-registry-refresh")
        expect(refresh).to_have_attribute("aria-label", "Refresh")
        expect(refresh).to_have_attribute("title", "Refresh")

        settings_page.locator('button[data-section="data"]').click()
        expect(settings_page.locator('#backup_enabled')).to_have_attribute("aria-labelledby", "backup-enabled-label")
        expect(settings_page.locator('label[for="backup_path"]')).to_have_text("Backup Path")
        delete_button = settings_page.locator('#backup-list button[aria-label^="Delete"]')
        expect(delete_button).to_have_count(1)
        expect(delete_button).to_have_attribute("aria-label", re.compile(r"Delete .*docsight_backup_2026-03-14_120000\.tar\.gz"))
        expect(delete_button.locator('svg[aria-hidden="true"], i[aria-hidden="true"]')).to_have_count(1)

    @pytest.mark.parametrize("width, compact", [(700, True), (850, False)])
    @pytest.mark.parametrize("section, setup", [
        ("connection", None),
        ("notifications", "expand-webhook"),
    ])
    def test_tablet_widths_use_comfortable_single_column_settings_forms(self, settings_page, width, compact, section, setup):
        settings_page.set_viewport_size({"width": width, "height": 844})
        settings_page.reload(wait_until="networkidle")
        settings_page.evaluate("section => window.switchSection(section)", section)
        if setup == "expand-webhook":
            settings_page.locator('#notification-webhook-card .notification-collapse-button').click()

        metrics = settings_page.evaluate(
            """
            (section) => {
              const panel = document.querySelector(`#panel-${section}`);
              const grids = Array.from(panel.querySelectorAll('.form-grid.cols-2'))
                .filter((grid) => grid.getClientRects().length > 0 && !grid.closest('[inert]'));
              const fieldWidths = grids.flatMap((grid) => Array.from(grid.querySelectorAll('.form-field'))
                .filter((field) => field.getClientRects().length > 0)
                .map((field) => field.getBoundingClientRect().width));
              return {
                gridColumns: grids.map((grid) => getComputedStyle(grid).gridTemplateColumns.trim().split(' ').filter(Boolean).length),
                minFieldWidth: Math.min(...fieldWidths),
                indexVisible: document.querySelector('#settings-index').getClientRects().length > 0,
                docWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth,
              };
            }
            """,
            section,
        )
        assert metrics["gridColumns"]
        assert all(count == 1 for count in metrics["gridColumns"])
        assert metrics["minFieldWidth"] >= 280
        assert metrics["docWidth"] <= metrics["viewportWidth"]
        assert metrics["indexVisible"] is not compact


class TestSettingsTabSwitching:
    """Clicking sidebar tabs shows the correct panel."""

    @pytest.mark.parametrize("section", [
        "sources",
        "evidence",
        "data",
        "access",
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
        settings_page.locator('button[data-section="data"]').click()
        settings_page.locator('button[data-section="connection"]').click()
        panel = settings_page.locator("#panel-connection")
        assert panel.is_visible()

    def test_initial_hash_deep_link_restores_section_on_load(self, page, live_server):
        page.goto(f"{live_server}/settings#notifications")
        page.wait_for_load_state("networkidle")

        expect(page.locator("#panel-notifications")).to_be_visible()
        expect(page.locator('button[data-section="notifications"]')).to_have_attribute(
            "aria-current", "page"
        )
        assert page.url.endswith("#notifications")

        page.locator('button[data-section="data"]').click()
        expect(page.locator("#panel-data")).to_be_visible()
        assert page.url.endswith("#data")

        page.go_back()
        expect(page.locator("#panel-notifications")).to_be_visible()
        assert page.url.endswith("#notifications")

    def test_section_changes_create_browser_history(self, settings_page):
        settings_page.locator('button[data-section="data"]').click()
        settings_page.locator('button[data-section="notifications"]').click()
        expect(settings_page.locator("#panel-notifications")).to_be_visible()

        settings_page.go_back()
        expect(settings_page.locator("#panel-data")).to_be_visible()
        assert settings_page.url.endswith("#data")

        settings_page.go_forward()
        expect(settings_page.locator("#panel-notifications")).to_be_visible()
        assert settings_page.url.endswith("#notifications")


class TestSettingsFormElements:
    """Form elements exist on settings panels."""

    def test_connection_has_modem_type_select(self, settings_page):
        select = settings_page.locator('select[name="modem_type"], #modem_type, #modem-type')
        assert select.count() > 0

    def test_modem_status_updates_after_successful_connection_test(self, settings_page):
        settings_page.route("**/api/test-modem", lambda route: route.fulfill(json={"success": True, "model": "Demo CM"}))

        status = settings_page.locator("#modem-status")
        expect(status).to_have_attribute("hidden", "")

        settings_page.locator('button[data-action="testModem"]').click()

        expect(status).to_have_class(re.compile(r".*\bconnected\b.*"))
        expect(status).not_to_have_class(re.compile(r".*\bdisconnected\b.*"))
        expect(status).not_to_have_attribute("hidden", "")
        expect(status.locator("#modem-status-text")).to_have_text("Connected: Demo CM")

    def test_modem_status_updates_after_failed_connection_test(self, settings_page):
        settings_page.route("**/api/test-modem", lambda route: route.fulfill(json={"success": False, "error": "Auth failed"}))

        status = settings_page.locator("#modem-status")
        expect(status).to_have_attribute("hidden", "")

        settings_page.locator('button[data-action="testModem"]').click()

        expect(status).to_have_class(re.compile(r".*\bdisconnected\b.*"))
        expect(status).not_to_have_class(re.compile(r".*\bconnected\b.*"))
        expect(status).not_to_have_attribute("hidden", "")
        expect(status.locator("#modem-status-text")).to_have_text("Error: Auth failed")

    def test_mqtt_status_updates_while_testing_and_after_success(self, settings_page):
        pending_routes = []

        def hold_mqtt(route):
            pending_routes.append(route)

        settings_page.route("**/api/test-mqtt", hold_mqtt)
        settings_page.locator('button[data-section="access"]').click()
        status = settings_page.locator("#mqtt-status")
        expect(status).to_have_attribute("hidden", "")

        with settings_page.expect_request("**/api/test-mqtt"):
            settings_page.locator('#block-mod-docsight_mqtt button[data-action="testMqtt"]').click()

        expect(status).to_have_class(re.compile(r".*\btesting\b.*"))
        expect(status).not_to_have_attribute("hidden", "")
        expect(status.locator("#mqtt-status-text")).to_have_text(re.compile("Testing", re.I))
        assert len(pending_routes) == 1

        pending_routes[0].fulfill(json={"success": True})

        expect(status).to_have_class(re.compile(r".*\bconnected\b.*"))
        expect(status).not_to_have_class(re.compile(r".*\bdisconnected\b.*"))
        expect(status.locator("#mqtt-status-text")).to_have_text("Connected")

    def test_mqtt_status_updates_after_failed_connection_test(self, settings_page):
        settings_page.route(
            "**/api/test-mqtt",
            lambda route: route.fulfill(json={"success": False, "error": "MQTT auth failed"}),
        )
        settings_page.locator('button[data-section="access"]').click()
        status = settings_page.locator("#mqtt-status")
        expect(status).to_have_attribute("hidden", "")

        settings_page.locator('#block-mod-docsight_mqtt button[data-action="testMqtt"]').click()

        expect(status).to_have_class(re.compile(r".*\bdisconnected\b.*"))
        expect(status).not_to_have_class(re.compile(r".*\bconnected\b.*"))
        expect(status).not_to_have_attribute("hidden", "")
        expect(status.locator("#mqtt-status-text")).to_have_text("Error: MQTT auth failed")

    def test_mqtt_status_updates_after_network_error(self, settings_page):
        settings_page.route("**/api/test-mqtt", lambda route: route.abort())
        settings_page.locator('button[data-section="access"]').click()
        status = settings_page.locator("#mqtt-status")
        expect(status).to_have_attribute("hidden", "")

        settings_page.locator('#block-mod-docsight_mqtt button[data-action="testMqtt"]').click()

        expect(status).to_have_class(re.compile(r".*\bdisconnected\b.*"))
        expect(status).not_to_have_attribute("hidden", "")
        expect(status.locator("#mqtt-status-text")).to_have_text("Network error")

    def test_mqtt_status_wraps_without_mobile_overflow(self, settings_page):
        settings_page.set_viewport_size({"width": 390, "height": 844})
        settings_page.reload(wait_until="networkidle")
        settings_page.route(
            "**/api/test-mqtt",
            lambda route: route.fulfill(
                json={
                    "success": False,
                    "error": "Connection refused by broker at mqtt.example.invalid:1883",
                }
            ),
        )
        settings_page.evaluate("() => window.switchSection('access')")
        settings_page.locator('#block-mod-docsight_mqtt button[data-action="testMqtt"]').click()

        expect(settings_page.locator("#mqtt-status")).to_have_class(
            re.compile(r".*\bdisconnected\b.*")
        )
        metrics = settings_page.evaluate(
            """
            () => ({
              docWidth: document.documentElement.scrollWidth,
              viewportWidth: window.innerWidth,
            })
            """
        )
        assert metrics["docWidth"] <= metrics["viewportWidth"]

    def test_security_has_password_field(self, settings_page):
        settings_page.locator('button[data-section="access"]').click()
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

    def test_notifications_channel_cards_are_collapsed_with_live_status_summaries(self, settings_page):
        settings_page.locator('button[data-section="notifications"]').click()

        for card_id in ["notification-webhook-card", "notification-apprise-card", "pwa-push-card"]:
            card = settings_page.locator(f"#{card_id}")
            expect(card).to_have_class(re.compile(r".*\bcollapsed\b.*"))
            expect(card.locator('.card-collapse-body')).to_have_attribute("aria-hidden", "true")
            expect(card.locator('.card-collapse-body')).to_have_attribute("inert", "")

        expect(settings_page.locator('[data-channel-badge="webhook"]')).to_have_text("Not configured")
        expect(settings_page.locator('[data-channel-badge="apprise"]')).to_have_text("Disabled")
        expect(settings_page.locator('[data-channel-badge="pwa"]')).to_have_text("Disabled")

        settings_page.locator('#notification-webhook-card .notification-collapse-button').click()
        expect(settings_page.locator('#notification-webhook-card')).not_to_have_class(re.compile(r".*\bcollapsed\b.*"))
        expect(settings_page.locator('#notification-webhook-card .notification-collapse-button')).to_have_attribute("aria-expanded", "true")
        expect(settings_page.locator('#notification-webhook-body')).to_have_attribute("aria-hidden", "false")
        expect(settings_page.locator('#notification-webhook-body')).not_to_have_attribute("inert", "")

    def test_notifications_channel_badges_update_when_toggles_or_url_change(self, settings_page):
        settings_page.route("**/api/config", lambda route: route.fulfill(json={"success": True}))
        settings_page.locator('button[data-section="notifications"]').click()

        settings_page.locator('#notify_webhook_url').evaluate("el => { el.value = 'https://ntfy.sh/docsight'; el.dispatchEvent(new Event('input', {bubbles: true})); }")
        expect(settings_page.locator('[data-channel-badge="webhook"]')).to_have_text("Enabled")

        settings_page.locator('#notify_apprise_enabled + .toggle-slider').click()
        expect(settings_page.locator('[data-channel-badge="apprise"]')).to_have_text("Enabled")
        expect(settings_page.locator('#notification-apprise-card')).not_to_have_class(re.compile(r".*\bcollapsed\b.*"))

        settings_page.locator('#notify_pwa_push_enabled + .toggle-slider').click()
        expect(settings_page.locator('[data-channel-badge="pwa"]')).to_have_text("Enabled")
        expect(settings_page.locator('#pwa-push-card')).not_to_have_class(re.compile(r".*\bcollapsed\b.*"))
        expect(settings_page.locator("#save-bar-count")).to_have_text("Unsaved changes (3)")

    def test_notifications_mobile_scroll_is_reduced_by_collapsed_channel_cards(self, settings_page):
        settings_page.set_viewport_size({"width": 390, "height": 844})
        settings_page.reload(wait_until="networkidle")
        settings_page.evaluate("() => window.switchSection('notifications')")

        metrics = settings_page.evaluate(
            """
            () => {
              const panel = document.querySelector('#panel-notifications');
              return {
                panelScrollHeight: panel.scrollHeight,
                collapsedChannels: panel.querySelectorAll('.notification-channel-card.collapsed').length,
              };
            }
            """
        )
        assert metrics["collapsedChannels"] == 3
        assert metrics["panelScrollHeight"] < 2000

    def test_smart_capture_form_controls_use_shared_visual_contract(self, settings_page):
        settings_page.locator('button[data-section="evidence"]').click()
        controls = [
            "sc_trigger_modulation_direction",
            "sc_trigger_modulation_min_qam",
            "sc_trigger_error_spike_min_delta",
            "sc_trigger_health_level",
            "sc_trigger_packet_loss_min_pct",
            "sc_global_cooldown",
            "sc_trigger_cooldown",
            "sc_max_actions_per_hour",
            "sc_speedtest_min_interval",
            "sc_speedtest_max_actions_per_day",
            "sc_speedtest_match_window",
        ]

        for control_id in controls:
            control = settings_page.locator(f"#{control_id}")
            expect(control).to_have_class(re.compile(r".*\bform-input\b.*"))
            expect(settings_page.locator(f'label[for="{control_id}"]')).to_have_class(re.compile(r".*\bform-label\b.*"))

        for control_id in [
            "sc_trigger_modulation_direction",
            "sc_trigger_modulation_min_qam",
            "sc_trigger_health_level",
        ]:
            expect(settings_page.locator(f"#{control_id}")).to_have_class(re.compile(r".*\bform-select\b.*"))

        metrics = settings_page.evaluate(
            """
            (ids) => ids.map((id) => {
              const el = document.getElementById(id);
              const styles = getComputedStyle(el);
              return {
                id,
                height: el.getBoundingClientRect().height,
                bg: styles.backgroundColor,
                color: styles.color,
              };
            })
            """,
            controls,
        )
        # One shared control height (40px on desktop, 44px on touch and phone-width screens).
        assert len({round(item["height"]) for item in metrics}) == 1, metrics
        assert all(item["height"] >= 40 for item in metrics)
        assert all(item["bg"] != "rgb(255, 255, 255)" for item in metrics)

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


def _assert_toast_state(page, ok):
    toast = page.locator("#toast")
    expect(toast).to_be_visible()
    expected = "toast-ok" if ok else "toast-fail"
    unexpected = "toast-fail" if ok else "toast-ok"
    expect(toast).to_have_class(re.compile(rf".*\b{expected}\b.*"))
    expect(toast).not_to_have_class(re.compile(rf".*\b{unexpected}\b.*"))


def _theme_registry_payload():
    return [
        {
            "id": "docsight.theme_test_registry",
            "name": "Registry Test Theme",
            "description": "Test theme from registry",
            "version": "1.0.0",
            "author": "DOCSight Tests",
            "download_url": "https://example.invalid/theme.zip",
        }
    ]


def _module_registry_payload(status="not_installed"):
    return [
        {
            "id": "docsight.test_module",
            "name": "Registry Test Module",
            "description": "Test module from registry",
            "author": "DOCSight Tests",
            "version": "1.0.0",
            "status": status,
            "download_url": "https://example.invalid/module.zip",
            "verified": True,
        }
    ]


class TestSettingsThemeRegistry:
    """The Appearance panel loads available themes without manual refresh."""

    def test_appearance_panel_loads_theme_registry_once_when_opened(self, settings_page):
        registry_requests = []

        def capture_registry(route):
            registry_requests.append(route.request.url)
            route.fulfill(json=_theme_registry_payload())

        settings_page.route("**/api/themes/registry", capture_registry)

        settings_page.locator('button[data-section="appearance"]').click()
        expect(settings_page.locator('#registry-gallery .theme-card')).to_have_count(1)
        expect(settings_page.locator('#registry-gallery')).to_contain_text("Registry Test Theme")
        assert len(registry_requests) == 1

        settings_page.locator('button[data-section="data"]').click()
        settings_page.locator('button[data-section="appearance"]').click()
        expect(settings_page.locator('#registry-gallery .theme-card')).to_have_count(1)
        assert len(registry_requests) == 1


class TestSettingsToastStates:
    """Theme and module registry operations report the correct toast polarity."""

    @pytest.mark.parametrize("ok, expected, unexpected", [
        (True, "toast-ok", "toast-fail"),
        (False, "toast-fail", "toast-ok"),
    ])
    def test_toast_helper_applies_explicit_polarity_classes(
        self, settings_page, ok, expected, unexpected
    ):
        settings_page.evaluate(
            "({ok}) => window.showToast(ok ? 'Saved' : 'Failed', ok)",
            {"ok": ok},
        )

        toast = settings_page.locator("#toast")
        expect(toast).to_be_visible()
        expect(toast).to_have_class(re.compile(rf".*\b{expected}\b.*"))
        expect(toast).not_to_have_class(re.compile(rf".*\b{unexpected}\b.*"))

    @pytest.mark.parametrize("success", [True, False])
    def test_theme_install_toast_state_matches_result(self, settings_page, success):
        settings_page.route("**/api/themes/registry", lambda route: route.fulfill(json=_theme_registry_payload()))
        settings_page.route(
            "**/api/themes/install",
            lambda route: route.fulfill(json={"success": success} if success else {"success": False, "error": "Theme failed"}),
        )

        settings_page.locator('button[data-section="appearance"]').click()
        settings_page.locator('#panel-appearance button[data-action="refreshRegistry"]').click()
        install_button = settings_page.locator('#registry-gallery .theme-card button', has_text=re.compile("Install", re.I))
        expect(install_button).to_have_count(1)
        install_button.click()

        _assert_toast_state(settings_page, success)

    @pytest.mark.parametrize("success", [True, False])
    def test_module_install_toast_state_matches_result(self, settings_page, success):
        settings_page.route("**/api/modules/registry", lambda route: route.fulfill(json=_module_registry_payload()))
        settings_page.route(
            "**/api/modules/install",
            lambda route: route.fulfill(json={"success": success} if success else {"success": False, "error": "Module failed"}),
        )

        settings_page.locator('button[data-section="extensions"]').click()
        install_button = settings_page.locator('#module-registry-gallery button').first
        expect(install_button).to_have_text(re.compile("Install", re.I))
        install_button.click()
        expect(install_button).to_have_text(re.compile("Confirm", re.I))
        install_button.click()

        _assert_toast_state(settings_page, success)

    @pytest.mark.parametrize("success", [True, False])
    def test_module_uninstall_toast_state_matches_result(self, settings_page, success):
        settings_page.route(
            "**/api/modules/registry",
            lambda route: route.fulfill(json=_module_registry_payload(status="installed_enabled")),
        )
        settings_page.route(
            "**/api/modules/uninstall",
            lambda route: route.fulfill(json={"success": success} if success else {"success": False, "error": "Uninstall failed"}),
        )

        settings_page.locator('button[data-section="extensions"]').click()
        uninstall_button = settings_page.locator('#module-registry-gallery button').first
        expect(uninstall_button).to_have_text(re.compile("Uninstall", re.I))
        uninstall_button.click()
        expect(uninstall_button).to_have_text(re.compile("Confirm", re.I))
        uninstall_button.click()

        _assert_toast_state(settings_page, success)


class TestSettingsModuleRegistry:
    """The Extensions panel loads community modules without manual refresh."""

    def test_extensions_panel_auto_loads_module_registry_when_opened(self, settings_page):
        registry_requests = []

        def capture_registry(route):
            registry_requests.append(route.request.url)
            route.fulfill(json=_module_registry_payload())

        settings_page.route("**/api/modules/registry", capture_registry)

        settings_page.locator('button[data-section="extensions"]').click()
        expect(
            settings_page.locator("#module-registry-gallery .module-registry-card")
        ).to_have_count(1)
        expect(settings_page.locator("#module-registry-gallery")).to_contain_text(
            "Registry Test Module"
        )
        assert len(registry_requests) == 1


class TestSettingsDirtyState:
    """Unsaved-change prompts only appear for deliberate settings edits."""

    def test_saved_secret_user_edit_guard_requires_active_field(self, settings_page):
        settings_page.locator('#modem_password').evaluate("el => { el.dataset.savedSecret = 'true'; }")
        settings_page.locator('#modem_url').focus()
        settings_page.locator('#modem_password').evaluate("""el => {
            el.value = 'autofill';
            el.dispatchEvent(new Event('input', {bubbles: true}));
        }""")
        expect(settings_page.locator('#save-footer')).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        settings_page.locator('#modem_password').focus()
        settings_page.locator('#modem_password').evaluate("el => el.dispatchEvent(new Event('input', {bubbles: true}))")
        expect(settings_page.locator('#save-footer')).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        settings_page.locator('#modem_password').fill('deliberate-edit')
        expect(settings_page.locator('#save-footer')).to_have_class(re.compile(r".*\bvisible\b.*"))

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
        settings_page.locator('button[data-section="connection"]').click()
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
        settings_page.locator('button[data-section="connection"]').click()
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

        auth_page.locator('button[data-section="connection"]').click()
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

        auth_page.locator('button[data-section="access"]').click()
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

    def test_module_switch_saves_only_the_module_and_leaves_manual_edits_pending(self, settings_page):
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

        settings_page.locator('button[data-section="extensions"]').click()
        with settings_page.expect_request("**/api/modules/batch"):
            settings_page.locator('.module-toggle .toggle-slider').first.click()

        expect(settings_page.locator('#docsight-confirm-modal')).to_have_count(0)
        expect(footer).to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(settings_page.locator("#save-bar-count")).to_have_text("Unsaved changes (1)")
        assert config_payloads == []
        assert len(batch_payloads[0]["modules"]) == 1
        assert len(batch_payloads[-1]["modules"]) == 1


class TestSettingsInstantToggleSave:
    """Only theme, mode, font and module or feature switches save at once; the rest waits for Save."""

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
        with settings_page.expect_request("**/api/modules/batch"):
            toggle_slider.click()

        footer = settings_page.locator("#save-footer")
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(settings_page.locator("#module-restart-banner")).to_be_visible()
        assert config_payloads == []
        assert len(batch_payloads) == 1
        assert len(batch_payloads[0]["modules"]) == 1
        assert immediate_calls == []

    def test_instant_feature_switch_does_not_flash_the_save_bar_while_its_save_is_pending(self, settings_page):
        pending_routes = []
        settings_page.route("**/api/config", lambda route: pending_routes.append(route))
        settings_page.locator('button[data-section="extensions"]').click()
        footer = settings_page.locator("#save-footer")

        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#gaming_quality_enabled + .toggle-slider').click()

        assert settings_page.evaluate("""() => {
            const event = new Event('beforeunload', {cancelable: true});
            window.dispatchEvent(event);
            return event.defaultPrevented;
        }""") is True
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(footer).to_have_attribute("aria-hidden", "true")
        assert set(pending_routes[0].request.post_data_json) == {"gaming_quality_enabled"}
        pending_routes[0].fulfill(json={"success": True})
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(settings_page.locator("#toast")).not_to_be_visible()

    def test_each_section_says_how_it_saves(self, settings_page):
        hint = settings_page.locator("#settings-save-hint")
        expect(hint).to_have_text("Changes here are saved with Save in the bar at the bottom.")
        settings_page.locator('button[data-section="appearance"]').click()
        expect(hint).to_contain_text("Theme, mode and font apply immediately.")
        settings_page.locator('button[data-section="extensions"]').click()
        expect(hint).to_have_text("Changes here apply immediately.")

    def test_mode_switch_saves_only_the_theme(self, settings_page):
        payloads = []
        settings_page.route("**/api/config", lambda route: (payloads.append(route.request.post_data_json), route.fulfill(json={"success": True})))
        settings_page.locator('button[data-section="appearance"]').click()
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('label[for="theme-toggle-appearance"]').click()
        assert payloads == [{"theme": "light"}]
        expect(settings_page.locator("#save-footer")).not_to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_queued_instant_switches_keep_the_save_bar_hidden_between_saves(self, settings_page):
        pending_routes = []
        settings_page.route("**/api/config", lambda route: pending_routes.append(route))
        settings_page.locator('button[data-section="extensions"]').click()
        footer = settings_page.locator("#save-footer")

        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#gaming_quality_enabled + .toggle-slider').click()
        settings_page.locator('#bnetz_enabled + .toggle-slider').click()
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        with settings_page.expect_request("**/api/config"):
            pending_routes[0].fulfill(json={"success": True})
        for _ in range(40):  # the route handler records the request just after the request event
            if len(pending_routes) > 1:
                break
            settings_page.wait_for_timeout(25)
        assert set(pending_routes[1].request.post_data_json) == {"bnetz_enabled"}
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        pending_routes[1].fulfill(json={"success": True})
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_notification_switches_and_rules_wait_for_save(self, settings_page):
        requests = []
        settings_page.on("request", lambda request: requests.append(request.url) if "/api/config" in request.url else None)
        settings_page.locator('button[data-section="notifications"]').click()
        footer = settings_page.locator("#save-footer")
        settings_page.locator('#notify_apprise_enabled + .toggle-slider').click()
        settings_page.locator('#per-event-cooldowns .card-header').click()
        settings_page.locator('.notify-event-row[data-event="health_change"][data-severity="critical"] .toggle-slider').click()
        settings_page.locator('.notify-event-row[data-event="power_change"][data-severity="warning"] .notify-cooldown-input').fill('42')
        expect(footer).to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(settings_page.locator("#save-bar-count")).to_have_text("Unsaved changes (3)")
        settings_page.wait_for_timeout(300)
        assert requests == []

    def test_hidden_companion_instant_toggle_does_not_poison_manual_dirty_baseline(self, settings_page):
        settings_page.route("**/api/config", lambda route: route.fulfill(json={"success": True}))
        settings_page.locator('button[data-section="extensions"]').click()
        footer = settings_page.locator("#save-footer")
        instant_toggle = settings_page.locator('#panel-extensions label.toggle input[type="checkbox"]:not(.module-toggle-input)').first
        expect(instant_toggle).to_have_count(1)

        with settings_page.expect_request("**/api/config"):
            instant_toggle.evaluate("el => { el.checked = !el.checked; el.dispatchEvent(new Event('change', {bubbles: true})); }")
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        settings_page.locator('button[data-section="connection"]').click()
        manual_field = settings_page.locator('#poll_interval')
        original_value = manual_field.input_value()
        edited_value = "901" if original_value != "901" else "902"
        manual_field.fill(edited_value)
        expect(footer).to_have_class(re.compile(r".*\bvisible\b.*"))
        manual_field.fill(original_value)
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_collapsed_per_event_rules_hide_their_table_until_opened(self, settings_page):
        settings_page.locator('button[data-section="notifications"]').click()
        card = settings_page.locator("#per-event-cooldowns")
        header = card.locator(".card-header")
        expect(card).to_have_class(re.compile(r".*\bcollapsed\b.*"))
        expect(card.locator(".cooldown-table")).not_to_be_in_viewport()
        assert card.evaluate("el => el.querySelector('.card-collapse-body').getBoundingClientRect().height") == 0
        header.click()
        expect(header).to_have_attribute("aria-expanded", "true")
        expect(card.locator(".cooldown-table")).to_be_visible()

    def test_per_event_rules_are_sent_with_save(self, settings_page):
        payloads = []
        settings_page.route("**/api/config", lambda route: (payloads.append(route.request.post_data_json), route.fulfill(json={"success": True})))
        settings_page.locator('button[data-section="notifications"]').click()
        settings_page.locator('#per-event-cooldowns .card-header').click()
        settings_page.locator('.notify-event-row[data-event="health_change"][data-severity="critical"] .toggle-slider').click()
        settings_page.locator('.notify-event-row[data-event="power_change"][data-severity="warning"] .notify-cooldown-input').fill('42')
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#save-footer button[type="submit"]').click()
        cooldowns = payloads[0]["notify_cooldowns"].replace(" ", "")
        assert '"health_change:critical":0' in cooldowns
        assert '"power_change:warning":42' in cooldowns
        expect(settings_page.locator("#save-footer")).not_to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_rules_stay_unsaved_when_save_fails(self, settings_page):
        settings_page.route("**/api/config", lambda route: route.fulfill(status=500, json={"success": False, "error": "Save failed"}))
        settings_page.locator('button[data-section="notifications"]').click()
        settings_page.locator('#per-event-cooldowns .card-header').click()
        settings_page.locator('.notify-event-row[data-event="health_change"][data-severity="critical"] .toggle-slider').click()
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#save-footer button[type="submit"]').click()
        expect(settings_page.locator("#save-footer")).to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(settings_page.locator('#global-error')).to_be_visible()

    def test_edit_made_during_an_instant_save_stays_unsaved(self, settings_page):
        held = []
        settings_page.route("**/api/config", lambda route: held.append(route))
        settings_page.locator('button[data-section="extensions"]').click()
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#gaming_quality_enabled + .toggle-slider').click()
        settings_page.locator('button[data-section="connection"]').click()
        settings_page.locator('#modem_url').fill('http://192.168.100.1')

        held[0].fulfill(json={"success": True})
        expect(settings_page.locator("#save-footer")).to_have_class(re.compile(r".*\bvisible\b.*"))
        assert "modem_url" not in held[0].request.post_data_json

    def test_saved_secret_clears_when_concurrent_edit_remains_dirty(self, settings_page):
        held = []
        settings_page.route("**/api/config", lambda route: held.append(route))
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
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#settings-form').evaluate("form => form.requestSubmit()")
        settings_page.locator('#modem_url').fill('http://192.168.100.1')

        assert held[0].request.post_data_json["modem_password"] == "new-secret-value"
        held[0].fulfill(json={"success": True})
        expect(settings_page.locator('#toast')).to_be_visible()

        assert settings_page.locator('#modem_password').input_value() == ""
        expect(settings_page.locator("#save-footer")).to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_saved_secret_edited_after_save_snapshot_is_not_cleared(self, settings_page):
        held = []
        settings_page.route("**/api/config", lambda route: held.append(route))
        settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#modem_password');
              input.dataset.savedSecret = 'true';
              input.setAttribute('placeholder', 'Saved');
            }
            """
        )
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#settings-form').evaluate("form => form.requestSubmit()")
        settings_page.locator('#modem_password').fill('new-secret-value')

        assert held[0].request.post_data_json["modem_password"] == "••••••••"
        held[0].fulfill(json={"success": True})
        expect(settings_page.locator('#toast')).to_be_visible()

        assert settings_page.locator('#modem_password').input_value() == "new-secret-value"
        expect(settings_page.locator("#save-footer")).to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_saved_secret_reedited_after_save_snapshot_is_not_cleared(self, settings_page):
        held = []
        settings_page.route("**/api/config", lambda route: held.append(route))
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
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#settings-form').evaluate("form => form.requestSubmit()")
        settings_page.locator('#modem_password').fill('second-secret-value')

        assert held[0].request.post_data_json["modem_password"] == "first-secret-value"
        held[0].fulfill(json={"success": True})
        expect(settings_page.locator('#toast')).to_be_visible()

        assert settings_page.locator('#modem_password').input_value() == "second-secret-value"
        expect(settings_page.locator("#save-footer")).to_have_class(re.compile(r".*\bvisible\b.*"))

    @pytest.mark.parametrize("first_success", [True, False])
    def test_queued_saves_read_edits_when_they_run(self, settings_page, first_success):
        held = []
        settings_page.route("**/api/config", lambda route: held.append(route))
        settings_page.locator('#modem_url').fill('http://first.example')
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#save-footer button[type="submit"]').click()
        settings_page.locator('#modem_url').fill('http://queued.example')
        settings_page.locator('#settings-form').evaluate("form => form.requestSubmit()")
        assert len(held) == 1
        with settings_page.expect_request("**/api/config"):
            held[0].fulfill(status=200 if first_success else 500, json={"success": first_success})
        settings_page.locator('#modem_url').fill('http://later.example')
        assert held[1].request.post_data_json['modem_url'] == 'http://queued.example'
        held[1].fulfill(json={"success": True})
        expect(settings_page.locator('#save-footer')).to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_failed_module_switch_is_retried_with_save(self, settings_page):
        configs, batches = [], []
        settings_page.route("**/api/config", lambda route: configs.append(route))
        def respond_batch(route):
            batches.append(route.request.post_data_json)
            success = len(batches) > 1
            route.fulfill(status=200 if success else 500, json={"success": success})
        settings_page.route("**/api/modules/batch", respond_batch)
        settings_page.locator('#modem_password').fill('submitted-secret')
        settings_page.locator('#modem_url').fill('http://confirmed.example')
        settings_page.locator('button[data-section="extensions"]').click()
        with settings_page.expect_request("**/api/modules/batch"):
            settings_page.locator('.module-toggle-input[data-is-threshold="false"] + .toggle-slider').first.click()
        expect(settings_page.locator('#global-error')).to_be_visible()
        assert configs == []
        expect(settings_page.locator('#save-footer')).to_have_class(re.compile(r".*\bvisible\b.*"))
        with settings_page.expect_request("**/api/config"):
            settings_page.locator('#save-footer button[type="submit"]').click()
        assert configs[0].request.post_data_json['modem_password'] == 'submitted-secret'
        assert configs[0].request.post_data_json['modem_url'] == 'http://confirmed.example'
        with settings_page.expect_request("**/api/modules/batch"):
            configs[0].fulfill(json={"success": True})
        expect(settings_page.locator('#save-footer')).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        assert batches[1] == batches[0]
        expect(settings_page.locator('#modem_password')).to_have_value('')
        expect(settings_page.locator('#global-error')).not_to_be_visible()

    def test_save_bar_counts_changes_by_section_and_discard_restores_saved_values(self, settings_page):
        footer = settings_page.locator("#save-footer")
        url = settings_page.locator("#modem_url").input_value()
        settings_page.locator("#modem_url").fill("http://discarded.example")
        settings_page.locator("#isp_select").select_option("__other__")
        expect(settings_page.locator("#isp-other-row")).to_be_visible()
        settings_page.locator('button[data-section="data"]').click()
        history = settings_page.locator("#history_days").input_value()
        settings_page.locator("#history_days").fill("123")
        expect(footer).to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(settings_page.locator("#save-bar-count")).to_have_text("Unsaved changes (3)")
        expect(settings_page.locator("#save-bar-sections")).to_have_text("Connection, Data and storage")
        settings_page.locator("#save-bar-discard").click()
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(settings_page.locator("#history_days")).to_have_value(history)
        settings_page.locator('button[data-section="connection"]').click()
        expect(settings_page.locator("#modem_url")).to_have_value(url)
        expect(settings_page.locator("#isp-other-row")).to_be_hidden()

    def test_automatic_backup_card_names_the_newest_backup(self, settings_page):
        settings_page.route(
            "**/api/backup/list",
            lambda route: route.fulfill(json=[
                {"filename": "docsight_backup_2026-03-13_120000.tar.gz", "size": 1048576, "modified": "2026-03-13T12:00:00"},
                {"filename": "docsight_backup_2026-03-14_120000.tar.gz", "size": 1048576, "modified": "2026-03-14T12:00:00"},
            ]),
        )
        settings_page.locator('button[data-section="data"]').click()
        line = settings_page.locator("#backup-last-run")
        expect(line).to_be_visible()
        expect(line).to_contain_text("Last backup")
        expect(line).to_contain_text("14")

    def test_automatic_backup_fields_are_inert_while_backups_are_off(self, settings_page):
        settings_page.locator('button[data-section="data"]').click()
        block = settings_page.locator("#backup-auto-settings")
        toggle = settings_page.locator("#backup_enabled")
        if toggle.is_checked():
            settings_page.locator("#backup_enabled + .toggle-slider").click()
        expect(block).to_have_attribute("inert", "")
        settings_page.locator("#backup_enabled + .toggle-slider").click()
        expect(block).not_to_have_attribute("inert", "")
        expect(settings_page.locator("#backup_path")).to_be_enabled()

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
        settings_page.locator('button[data-section="sources"]').click()

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
        settings_page.locator('button[data-section="sources"]').click()
        settings_page.locator("#speedtest_tracker_url").fill("https://speedtest.local:8443")
        settings_page.locator("#speedtest_tracker_token").fill("[REDACTED]")
        settings_page.locator("#block-mod-docsight_speedtest label.toggle").click()
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

        settings_page.locator('button[data-section="sources"]').click()
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

        settings_page.locator('button[data-section="sources"]').click()
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

        settings_page.locator('button[data-section="data"]').click()

        backup_list = settings_page.locator("#backup-list")
        assert backup_list.locator("code").first.text_content() == "docsight_backup_2026-03-14_120000.tar.gz"
        assert backup_list.get_by_text("3.0 MB").count() > 0
