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


def test_integration_setup_modals_are_guided_and_actionable(demo_page):
    """Integration setup modals should use scannable steps, settings links, copy actions, and validation states."""
    cases = [
        ("openSpeedtestSetupModal()", "#speedtest-setup-modal", "Speedtest Tracker setup", "Open Speedtest settings", "/settings#mod-docsight_speedtest", "Copy Docker command", "Review validation path", "Speedtest can be tested"),
        ("openBqmSetupModal()", "#bqm-setup-modal", "ThinkBroadband BQM setup", "Open BQM settings", "/settings#mod-docsight_bqm", "Copy example URL format", "Review validation path", "BQM can be validated"),
        ("openSmokepingSetupModal()", "#smokeping-setup-modal", "SmokePing setup", "Open SmokePing settings", "/settings#mod-docsight_smokeping", "Copy SmokePing target", "Review validation path", "SmokePing validation depends"),
    ]
    for opener, selector, title, settings_label, settings_href, copy_label, validate_label, status_text in cases:
        demo_page.evaluate(opener)
        modal = demo_page.locator(selector)
        expect(modal).to_be_visible()
        expect(modal.get_by_role("heading", name=title)).to_be_visible()
        expect(modal).to_contain_text("Why connect it")
        expect(modal).to_contain_text("Requirements")
        expect(modal).to_contain_text("Configure")
        expect(modal).to_contain_text("Validate")
        expect(modal.get_by_role("link", name=settings_label)).to_have_attribute("href", settings_href)
        expect(modal.get_by_role("button", name=copy_label)).to_be_visible()
        modal.get_by_role("button", name=validate_label).click()
        expect(modal.locator(".setup-validation-status")).to_contain_text(status_text)
        demo_page.keyboard.press("Escape")
        expect(modal).not_to_be_visible()


def test_guided_setup_modal_footers_do_not_cover_mobile_content(demo_page):
    """Mobile setup modals should scroll their final content fully above footer actions."""
    demo_page.set_viewport_size({"width": 393, "height": 852})
    cases = [
        ("openSpeedtestSetupModal()", "#speedtest-setup-modal"),
        ("openBqmSetupModal()", "#bqm-setup-modal"),
        ("openSmokepingSetupModal()", "#smokeping-setup-modal"),
    ]

    for opener, selector in cases:
        demo_page.evaluate(opener)
        modal = demo_page.locator(selector)
        expect(modal).to_be_visible()
        modal.locator(".modal-body").evaluate("el => { el.scrollTop = el.scrollHeight; }")
        geometry = modal.evaluate(
            """
            (el) => {
                const footer = el.querySelector('.modal-footer');
                const body = el.querySelector('.modal-body');
                const lastCard = body.querySelector('.setup-guide-card:last-child');
                const footerRect = footer.getBoundingClientRect();
                const bodyRect = body.getBoundingClientRect();
                const lastRect = lastCard.getBoundingClientRect();
                const footerStyle = getComputedStyle(footer);
                const overflowingCards = Array.from(body.querySelectorAll('.setup-guide-card')).filter((card) => {
                    const rect = card.getBoundingClientRect();
                    return rect.left < -1 || rect.right > window.innerWidth + 1;
                }).map((card) => card.querySelector('h3')?.textContent?.trim() || card.textContent.trim().slice(0, 40));
                return {
                    lastCardBottom: lastRect.bottom,
                    footerTop: footerRect.top,
                    bodyBottom: bodyRect.bottom,
                    bodyHeight: bodyRect.height,
                    bodyOverflow: body.scrollWidth - body.clientWidth,
                    overflowingCards,
                    footerBottom: footerRect.bottom,
                    footerWraps: footerRect.height >= 44,
                    footerFlexWrap: footerStyle.flexWrap,
                    viewportHeight: window.innerHeight,
                };
            }
            """
        )

        assert geometry["bodyHeight"] >= 96
        assert geometry["bodyOverflow"] <= 1
        assert geometry["overflowingCards"] == []
        assert geometry["lastCardBottom"] <= geometry["footerTop"] - 8
        assert geometry["bodyBottom"] <= geometry["footerTop"] - 8
        assert geometry["footerBottom"] <= geometry["viewportHeight"]
        assert geometry["footerWraps"] is True
        assert geometry["footerFlexWrap"] == "wrap"

        demo_page.keyboard.press("Escape")
        expect(modal).not_to_be_visible()


def test_integration_setup_copy_actions_provide_feedback(demo_page):
    """Copy actions in guided setup modals provide accessible feedback without native dialogs."""
    demo_page.evaluate("""
        window.__copiedSetupText = '';
        Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: {
                writeText: async function(text) {
                    window.__copiedSetupText = text;
                }
            }
        });
    """)

    demo_page.evaluate("openSpeedtestSetupModal()")
    modal = demo_page.locator("#speedtest-setup-modal")
    expect(modal).to_be_visible()
    modal.get_by_role("button", name="Copy Docker command").click()
    expect(modal.locator(".setup-validation-status")).to_contain_text("Copied")
    copied = demo_page.evaluate("window.__copiedSetupText")
    assert "speedtest" in copied.lower()

    demo_page.keyboard.press("Escape")
    expect(modal).not_to_be_visible()


def test_journal_import_modal_shows_preview_and_validation_states(demo_page):
    """Journal import exposes accepted formats, inline validation, preview counts, and selection state."""
    _open_journal(demo_page)
    demo_page.evaluate("openImportModal()")
    modal = demo_page.locator("#import-modal")

    expect(modal).to_be_visible()
    expect(modal.get_by_role("button", name="Browse CSV or Excel file")).to_be_visible()
    expect(modal.locator("#import-validation-state")).to_contain_text("Choose a CSV or Excel file")

    demo_page.evaluate(
        """
        () => {
            const file = new File(['not supported'], 'notes.txt', { type: 'text/plain' });
            handleImportFile({ files: [file] });
        }
        """
    )
    expect(modal.locator("#import-validation-state")).to_contain_text("Unsupported file type")

    demo_page.evaluate(
        """
        () => renderImportPreview({
            total: 3,
            skipped: 1,
            duplicates: 1,
            rows: [
                { date: '2026-05-01', title: 'Outage window', description: 'Cable modem offline', skipped: false, duplicate: false },
                { date: '2026-05-02', title: 'Existing packet loss', description: 'Already imported earlier', skipped: false, duplicate: true },
                { date: '', raw_date: 'May 3', title: 'Needs date review', description: 'No parseable date', skipped: true, duplicate: false }
            ]
        })
        """
    )
    expect(modal.locator("#import-validation-state")).to_contain_text("1 ready")
    expect(modal.locator("#import-validation-state")).to_contain_text("1 duplicate")
    expect(modal.locator("#import-validation-state")).to_contain_text("1 needs a date")
    expect(modal.locator("#import-confirm-btn")).to_contain_text("Import 1 selected entry")
    expect(modal.locator("#import-confirm-btn")).to_be_enabled()

    modal.locator(".import-row-cb").first.uncheck()
    expect(modal.locator("#import-validation-state")).to_contain_text("No valid rows selected")
    expect(modal.locator("#import-confirm-btn")).to_be_disabled()

    modal.locator(".import-row-skipped .import-row-cb").check()
    expect(modal.locator("#import-validation-state")).to_contain_text("No valid rows selected")
    expect(modal.locator("#import-confirm-btn")).to_be_disabled()


def test_bqm_import_modal_shows_preview_and_validation_states(demo_page):
    """BQM image import explains accepted files, validates dates, and summarizes readiness in the modal."""
    demo_page.evaluate("openBqmImportModal()")
    modal = demo_page.locator("#bqm-import-modal")

    expect(modal).to_be_visible()
    expect(modal.get_by_role("button", name="Browse BQM images")).to_be_visible()
    expect(modal.locator("#bqm-import-validation-state")).to_contain_text("Choose PNG or JPEG BQM graph images")

    demo_page.evaluate(
        """
        () => {
            const bad = new File(['bad'], 'notes.txt', { type: 'text/plain' });
            handleBqmImportFiles([bad]);
        }
        """
    )
    expect(modal.locator("#bqm-import-validation-state")).to_contain_text("Unsupported file type")

    demo_page.evaluate(
        """
        () => {
            window._bqmImportFiles = [
                { file: new File(['png'], 'bqm-2026-05-01.png', { type: 'image/png' }), date: '2026-05-01', originalDate: '2026-05-01', thumbUrl: '' },
                { file: new File(['png'], 'bqm-no-date.png', { type: 'image/png' }), date: '', originalDate: '', thumbUrl: '' }
            ];
            renderBqmImportPreview();
        }
        """
    )
    expect(modal.locator("#bqm-import-validation-state")).to_contain_text("1 ready")
    expect(modal.locator("#bqm-import-validation-state")).to_contain_text("1 needs a date")
    expect(modal.locator("#bqm-import-confirm-btn")).to_be_disabled()

    modal.locator(".bqm-import-date-missing").fill("2026-05-02")
    expect(modal.locator("#bqm-import-validation-state")).to_contain_text("2 ready")
    expect(modal.locator("#bqm-import-confirm-btn")).to_be_enabled()


def test_ai_export_modal_previews_privacy_scope_and_size(demo_page):
    """AI export modal explains local scope, included/excluded data, and output size before copying."""
    demo_page.route(
        "**/api/export?**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"text":"# DOCSight Export\\nISP: Vodafone\\nPublic IP: 203.0.113.45\\nRouter hostname: fritzbox.local\\nCustomer ref: K-123456\\nDOCSIS health: warning"}',
        ),
    )

    demo_page.locator("#export-link").click()
    modal = demo_page.locator("#export-modal")

    expect(modal).to_be_visible()
    expect(modal.get_by_role("heading", name="Export for AI Analysis")).to_be_visible()
    expect(modal).to_contain_text("Generated locally")
    expect(modal).to_contain_text("You decide where to paste or upload it")
    expect(modal).to_contain_text("Included in this export")
    expect(modal).to_contain_text("Excluded by default")
    expect(modal).to_contain_text("DOCSIS signal summary")
    expect(modal).to_contain_text("Remote upload to AI services")
    expect(modal.locator("#export-size-indicator")).to_contain_text("characters")
    expect(modal.get_by_role("button", name="Download Markdown")).to_be_visible()


def test_ai_export_redaction_copy_and_download_states(demo_page):
    """AI export redaction controls update the preview and expose copy/download status states."""
    demo_page.route(
        "**/api/export?**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"text":"# DOCSight Export\\nPublic IP: 203.0.113.45\\nIPv6 prefix: 2001:db8::42\\nRouter hostname: fritzbox.local\\nCustomer ref: K-123456\\nContact: dennis@example.net\\nDOCSIS health: warning"}',
        ),
    )
    demo_page.evaluate("""
        window.__copiedExportText = '';
        Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: {
                writeText: async function(text) {
                    window.__copiedExportText = text;
                }
            }
        });
    """)

    demo_page.locator("#export-link").click()
    modal = demo_page.locator("#export-modal")
    expect(modal).to_be_visible()

    preview = modal.locator("#export-text")
    expect(preview).to_have_value("# DOCSight Export\nPublic IP: 203.0.113.45\nIPv6 prefix: 2001:db8::42\nRouter hostname: fritzbox.local\nCustomer ref: K-123456\nContact: dennis@example.net\nDOCSIS health: warning")

    modal.get_by_label("Redact IP addresses").check()
    modal.get_by_label("Redact hostnames").check()
    modal.get_by_label("Redact account or customer details").check()

    redacted_text = preview.input_value()
    assert "203.0.113.45" not in redacted_text
    assert "2001:db8::42" not in redacted_text
    assert "fritzbox.local" not in redacted_text
    assert "K-123456" not in redacted_text
    assert "dennis@example.net" not in redacted_text
    assert "[redacted-ip]" in redacted_text
    assert "[redacted-hostname]" in redacted_text
    assert "[redacted-customer]" in redacted_text

    modal.get_by_role("button", name="Copy export").click()
    expect(modal.locator("#export-status")).to_contain_text("Export copied")
    copied = demo_page.evaluate("window.__copiedExportText")
    assert "203.0.113.45" not in copied
    assert "2001:db8::42" not in copied
    assert "[redacted-ip]" in copied

    with demo_page.expect_download() as download_info:
        modal.get_by_role("button", name="Download Markdown").click()
    download = download_info.value
    assert download.suggested_filename == "docsight-ai-export.md"
    expect(modal.locator("#export-status")).to_contain_text("Download ready")


def test_ai_export_ignores_pending_response_after_keyboard_dismissal(demo_page):
    """Dismissed export modals must not keep sensitive pending export text in hidden DOM."""
    demo_page.evaluate("""
        window.__resolveExportResponse = null;
        window.__originalExportFetch = window.fetch;
        window.fetch = function(url, options) {
            if (String(url || '').includes('/api/export')) {
                return new Promise(function(resolve) {
                    window.__resolveExportResponse = function() {
                        resolve(new Response(JSON.stringify({
                            text: '# DOCSight Export\\nPublic IP: 203.0.113.45\\nRouter hostname: fritzbox.local'
                        }), {status: 200, headers: {'Content-Type': 'application/json'}}));
                    };
                });
            }
            return window.__originalExportFetch(url, options);
        };
    """)

    demo_page.locator("#export-link").click()
    modal = demo_page.locator("#export-modal")
    expect(modal).to_be_visible()
    demo_page.keyboard.press("Escape")
    expect(modal).not_to_be_visible()

    demo_page.evaluate("window.__resolveExportResponse()")
    demo_page.wait_for_timeout(100)

    expect(modal.locator("#export-text")).to_have_value("")
    expect(modal.locator("#export-status")).to_have_text("")
    demo_page.evaluate("window.fetch = window.__originalExportFetch")
