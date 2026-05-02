"""E2E coverage for DOCSight modal behavior."""

from playwright.sync_api import expect


def _open_journal(demo_page):
    demo_page.locator('.nav-item[data-view="journal"]').click()
    expect(demo_page.locator("#view-journal")).to_be_visible()


def test_modal_focus_trap_escape_and_return_focus(demo_page):
    """Dashboard modals move focus inside, trap Tab, close on Escape, and restore focus."""
    _open_journal(demo_page)
    opener = demo_page.get_by_role("button", name="New Entry")
    opener.click()

    modal = demo_page.locator("#entry-modal")
    expect(modal).to_be_visible()
    expect(modal).to_have_attribute("role", "dialog")
    expect(modal).to_have_attribute("aria-modal", "true")

    focused_inside = demo_page.evaluate(
        """
        () => {
            const modal = document.querySelector('#entry-modal');
            return modal && modal.contains(document.activeElement);
        }
        """
    )
    assert focused_inside

    for _ in range(12):
        demo_page.keyboard.press("Tab")
        assert demo_page.evaluate(
            """
            () => {
                const modal = document.querySelector('#entry-modal');
                return modal && modal.contains(document.activeElement);
            }
            """
        )

    demo_page.keyboard.press("Escape")
    expect(modal).not_to_be_visible()
    expect(opener).to_be_focused()


def test_settings_backup_browser_uses_accessible_modal_contract(settings_page):
    """Backup directory browser follows the shared modal semantics and safety contract."""
    settings_page.locator('button[data-section="mod-docsight_backup"]').click()
    backup_enabled = settings_page.locator("#backup_enabled")
    if not backup_enabled.is_checked():
        backup_enabled.evaluate("el => { el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); }")
    opener = settings_page.get_by_role("button", name="Browse")
    settings_page.locator("#backup_path").evaluate("el => { el.value = '/'; }")
    opener.click()

    modal = settings_page.locator("#browse-modal")
    expect(modal).to_be_visible()
    expect(modal).to_have_attribute("role", "dialog")
    expect(modal).to_have_attribute("aria-modal", "true")
    expect(modal).to_have_attribute("aria-labelledby", "browse-modal-title")
    expect(modal.locator("#browse-selected-path")).to_be_visible()
    expect(modal.locator("#browse-status")).to_be_visible()

    assert settings_page.evaluate(
        """
        () => {
            const modal = document.querySelector('#browse-modal');
            return modal && modal.contains(document.activeElement);
        }
        """
    )

    settings_page.evaluate(
        """
        () => {
            const dirs = document.querySelector('#browse-dirs');
            dirs.textContent = '';
            dirs.appendChild(_createBrowseItem('tmp', '/tmp', 'folder', false));
        }
        """
    )
    first_dir = modal.locator(".browse-item").first
    expect(first_dir).to_be_visible()
    expect(first_dir).to_have_attribute("role", "button")
    expect(first_dir).to_have_attribute("tabindex", "0")
    first_dir.focus()
    assert first_dir.evaluate("el => el === document.activeElement")
    first_dir.press("Enter")
    expect(modal.locator("#browse-status")).not_to_have_text("Loading...")

    settings_page.keyboard.press("Escape")
    expect(modal).not_to_be_visible()
    settings_page.wait_for_function("el => el === document.activeElement", arg=opener.element_handle())


def test_styled_confirm_dialog_replaces_native_confirm_for_speedtest_cache(settings_page):
    """Important settings actions use DOCSight confirmation UI instead of native dialogs."""
    native_dialogs = []
    settings_page.on("dialog", lambda dialog: (native_dialogs.append(dialog.message), dialog.dismiss()))
    settings_page.locator('button[data-section="mod-docsight_speedtest"]').click()
    settings_page.locator("#speedtest_clear_cache").click()

    confirm_modal = settings_page.locator("#docsight-confirm-modal")
    expect(confirm_modal).to_be_visible()
    expect(confirm_modal).to_have_attribute("role", "dialog")
    expect(confirm_modal).to_contain_text("Clear")
    expect(confirm_modal.get_by_role("button", name="Cancel")).to_be_visible()
    assert native_dialogs == []

    settings_page.keyboard.press("Escape")
    expect(confirm_modal).not_to_be_visible()


def test_journal_entry_modal_guides_evidence_capture(demo_page):
    """Journal entries guide evidence-first capture with clear actions and icon labels."""
    _open_journal(demo_page)
    demo_page.get_by_role("button", name="New Entry").click()

    modal = demo_page.locator("#entry-modal")
    expect(modal).to_be_visible()
    expect(modal).to_contain_text("Capture what happened")
    expect(modal).to_contain_text("outage, packet loss, speed degradation")
    expect(modal).to_contain_text("Evidence")
    expect(modal.get_by_role("button", name="Create entry")).to_be_visible()
    expect(modal.get_by_role("button", name="Outage")).to_be_visible()
    expect(modal.get_by_role("button", name="Measurement")).to_be_visible()
    assert modal.get_by_text("Incident Container").count() == 0


def test_incident_modal_and_summary_offer_report_path(demo_page):
    """Incidents use user-facing copy, show linked evidence counts, and offer report entry points."""
    _open_journal(demo_page)
    demo_page.evaluate("openIncidentModal()")

    modal = demo_page.locator("#incident-container-modal")
    expect(modal).to_be_visible()
    expect(modal).to_contain_text("Group related entries and evidence")
    expect(modal).to_contain_text("Linked evidence")
    expect(modal.get_by_role("button", name="Create incident")).to_be_visible()
    assert modal.get_by_text("Incident Container").count() == 0

    demo_page.keyboard.press("Escape")
    expect(modal).not_to_be_visible()

    demo_page.evaluate(
        """
        () => {
            window._incidentsData = [{
                id: 381,
                name: 'Packet loss evening window',
                description: 'Repeated evening packet loss with attached modem evidence.',
                status: 'open',
                start_date: '2026-05-01',
                end_date: null,
                entry_count: 3
            }];
            renderIncidentSummary(381);
        }
        """
    )
    summary = demo_page.locator("#incident-summary")
    expect(summary).to_be_visible()
    expect(summary).to_contain_text("3 Entries")
    expect(summary).to_contain_text("Linked evidence")
    expect(summary.get_by_role("button", name="Build report")).to_be_visible()


def test_report_modal_frames_isp_ready_evidence_builder(demo_page):
    """The report modal previews evidence contents, privacy expectations, and output actions before generation."""
    demo_page.locator("#report-link").click()

    modal = demo_page.locator("#report-modal")
    expect(modal).to_be_visible()
    expect(modal.get_by_role("heading", name="ISP-ready evidence package")).to_be_visible()
    expect(modal).to_contain_text("Build a local evidence package for ISP support or complaint escalation.")
    expect(modal).to_contain_text("Signal summary")
    expect(modal).to_contain_text("Incident timeline and journal notes")
    expect(modal).to_contain_text("BQM, SmokePing, and Speedtest evidence when available")
    expect(modal).to_contain_text("Generated locally")
    expect(modal.get_by_role("button", name="Build evidence package")).to_be_visible()


def test_report_modal_shows_generation_success_and_error_states(demo_page):
    """Report generation exposes progress, success, and actionable error states in the modal."""
    request_urls = []
    demo_page.route(
        "**/api/complaint?**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"text":"Subject: DOCSIS Signal Quality Issues\\n\\nEvidence summary ready."}',
        ),
    )
    demo_page.locator("#report-link").click()
    modal = demo_page.locator("#report-modal")
    modal.get_by_role("button", name="Build evidence package").click()

    expect(modal.locator("#report-builder-status")).to_contain_text("Evidence package ready")
    expect(modal.locator("#report-complaint-text")).to_have_value("Subject: DOCSIS Signal Quality Issues\n\nEvidence summary ready.")
    expect(modal.get_by_role("button", name="Copy letter text")).to_be_visible()
    expect(modal.get_by_role("button", name="Download PDF package")).to_be_visible()

    demo_page.keyboard.press("Escape")
    expect(modal).not_to_be_visible()
    demo_page.locator("#report-link").click()
    expect(modal.locator("#report-step1")).to_be_visible()
    expect(modal.locator("#report-step2")).not_to_be_visible()
    expect(modal.locator("#report-builder-status")).to_have_text("")
    expect(modal.locator("#report-complaint-text")).to_have_value("")
    expect(modal.get_by_role("button", name="Build evidence package")).to_be_visible()
    expect(modal.get_by_role("button", name="Copy letter text")).not_to_be_visible()
    modal.locator(".modal-footer").get_by_role("button", name="Close").click()

    demo_page.unroute("**/api/complaint?**")
    demo_page.route(
        "**/api/complaint?**",
        lambda route: route.fulfill(
            status=500,
            content_type="application/json",
            body='{"error":"No report data is available for this period."}',
        ),
    )
    demo_page.locator("#report-link").click()
    modal.get_by_role("button", name="Build evidence package").click()

    expect(modal.locator("#report-builder-status")).to_contain_text("No report data is available for this period")
    expect(modal.locator("#report-step1")).to_be_visible()



def test_report_modal_preserves_bnetz_source_and_ignores_stale_generation(demo_page):
    """Report modal keeps selected BNetzA source and ignores stale async results after dismissal."""
    demo_page.evaluate("""
        window.__reportTestRequests = [];
        window.__resolveReportTestFetch = null;
        window.__originalReportFetch = window.fetch;
        window.fetch = function(url, options) {
            if (String(url).startsWith('/api/complaint?')) {
                window.__reportTestRequests.push(String(url));
                return new Promise(function(resolve) {
                    window.__resolveReportTestFetch = function() {
                        resolve(new Response(JSON.stringify({ text: 'Stale evidence package should not reopen.' }), {
                            status: 200,
                            headers: { 'Content-Type': 'application/json' }
                        }));
                    };
                });
            }
            return window.__originalReportFetch(url, options);
        };
    """)
    demo_page.evaluate("generateBnetzComplaint('measurement-42')")
    modal = demo_page.locator("#report-modal")
    expect(modal).to_be_visible()
    expect(modal.locator("#report-bnetz-id")).to_have_value("measurement-42")
    modal.get_by_role("button", name="Build evidence package").click()
    expect(modal.locator("#report-builder-status")).to_contain_text("Building evidence package")
    demo_page.keyboard.press("Escape")
    expect(modal).not_to_be_visible()

    demo_page.locator("#report-link").click()
    expect(modal.locator("#report-step1")).to_be_visible()
    expect(modal.locator("#report-step2")).not_to_be_visible()
    expect(modal.locator("#report-builder-status")).to_have_text("")
    demo_page.evaluate("window.__resolveReportTestFetch()")
    demo_page.wait_for_timeout(250)
    expect(modal.locator("#report-step1")).to_be_visible()
    expect(modal.locator("#report-step2")).not_to_be_visible()
    expect(modal.locator("#report-complaint-text")).to_have_value("")
    request_urls = demo_page.evaluate("window.__reportTestRequests")
    assert any("bnetz_id=measurement-42" in url for url in request_urls)

    demo_page.evaluate("window.fetch = window.__originalReportFetch")
