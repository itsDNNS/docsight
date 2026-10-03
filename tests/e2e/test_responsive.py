"""E2E tests for responsive / mobile layout."""

import re

import pytest
from playwright.sync_api import expect


@pytest.fixture()
def mobile_page(page, live_server):
    """Page with a mobile viewport (375x667, iPhone SE)."""
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto(live_server)
    page.wait_for_load_state("networkidle")
    return page


class TestMobileLayout:
    """Mobile viewport behavior."""

    def test_bottom_navigation_visible_on_mobile(self, mobile_page):
        nav = mobile_page.locator("#main-nav")
        expect(nav).to_be_visible()
        box = nav.bounding_box()
        viewport = mobile_page.viewport_size
        assert box is not None
        assert abs(box["y"] + box["height"] - viewport["height"]) <= 1
        assert box["x"] <= 0.5 and box["width"] >= viewport["width"] - 1

    def test_top_bar_keeps_brand_refresh_and_more(self, mobile_page):
        expect(mobile_page.locator(".topnav-brand")).to_be_visible()
        expect(mobile_page.locator("#refresh-btn")).to_be_visible()
        expect(mobile_page.locator("#nav-toggle-more")).to_be_visible()

    def test_destinations_are_touch_friendly(self, mobile_page):
        boxes = mobile_page.locator("#main-nav .topnav-dest").evaluate_all(
            "els => els.map((el) => { const r = el.getBoundingClientRect(); return [r.width, r.height]; })"
        )
        assert len(boxes) >= 4
        assert all(width >= 44 and height >= 44 for width, height in boxes)

    def test_closed_sheets_are_not_in_the_tab_order(self, mobile_page):
        """Closed panels are hidden, so none of their controls can take focus."""
        focusable_in_closed_panels = mobile_page.evaluate(
            """
            () => Array.from(document.querySelectorAll('.topnav-panel'))
                .filter((panel) => panel.hidden)
                .flatMap((panel) => Array.from(panel.querySelectorAll('a[href], button, input')))
                .filter((el) => el.offsetParent !== null)
                .map((el) => el.textContent.trim() || el.id)
            """
        )
        assert focusable_in_closed_panels == []

    def test_sheet_opens_above_the_bottom_bar_and_closes_on_escape(self, mobile_page):
        toggle = mobile_page.locator("#nav-toggle-signal")
        panel = mobile_page.locator("#nav-panel-signal")
        toggle.focus()
        toggle.press("ArrowDown")

        expect(panel).to_be_visible()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        assert mobile_page.evaluate("document.activeElement.getAttribute('data-view')") == "trends"
        panel_box = panel.bounding_box()
        nav_box = mobile_page.locator("#main-nav").bounding_box()
        assert panel_box["y"] + panel_box["height"] <= nav_box["y"]
        expect(mobile_page.locator("#topnav-backdrop")).to_be_visible()

        mobile_page.keyboard.press("Escape")
        expect(panel).to_be_hidden()
        expect(mobile_page.locator("#topnav-backdrop")).to_be_hidden()
        assert mobile_page.evaluate("document.activeElement && document.activeElement.id") == "nav-toggle-signal"

    def test_sheet_labels_stay_inside_the_sheet(self, mobile_page):
        mobile_page.locator("#nav-toggle-cases").click()
        geometry = mobile_page.locator("#nav-panel-cases").evaluate(
            """
            (panel) => {
                const rect = panel.getBoundingClientRect();
                const items = Array.from(panel.querySelectorAll('.nav-item'));
                return {
                    background: getComputedStyle(panel).backgroundColor,
                    overflowing: items.filter((item) => item.scrollWidth - item.clientWidth > 1).map((item) => item.textContent.trim()),
                    outside: items.filter((item) => {
                        const box = item.getBoundingClientRect();
                        return box.left < rect.left - 1 || box.right > rect.right + 1;
                    }).map((item) => item.textContent.trim()),
                };
            }
            """
        )
        assert geometry["overflowing"] == []
        assert geometry["outside"] == []
        assert "rgba" not in geometry["background"]

    def test_backdrop_tap_closes_the_sheet(self, mobile_page):
        mobile_page.locator("#nav-toggle-cases").click()
        expect(mobile_page.locator("#nav-panel-cases")).to_be_visible()
        mobile_page.mouse.click(20, 140)
        expect(mobile_page.locator("#nav-panel-cases")).to_be_hidden()

    def test_views_are_grouped_by_task(self, mobile_page):
        groups = mobile_page.evaluate(
            """
            () => Object.fromEntries(Array.from(document.querySelectorAll('#topnav .topnav-group')).map((group) => [
                group.dataset.navGroup,
                Array.from(group.querySelectorAll('.nav-item[data-view]')).map((item) => item.dataset.view),
            ]))
            """
        )
        assert {"trends", "channels"} <= set(groups["signal"])
        assert "evidence" in groups["cases"] and "journal" in groups["cases"]
        assert "glossary" in groups["more"]
        top_level = mobile_page.locator("#main-nav .topnav-list > .topnav-entry > .nav-item[data-view]").evaluate_all(
            "els => els.map((el) => el.dataset.view)"
        )
        assert top_level == ["live", "events"]

    def test_evidence_journey_opens_from_the_cases_sheet(self, mobile_page):
        mobile_page.locator("#nav-toggle-cases").click()
        mobile_page.locator('#nav-panel-cases [data-view="evidence"]').click()
        mobile_page.wait_for_selector('#view-evidence.active')
        assert mobile_page.locator('#evidence-placeholder').is_visible()
        expect(mobile_page.locator("#nav-panel-cases")).to_be_hidden()
        expect(mobile_page.locator("#nav-toggle-cases")).to_have_class(re.compile(r"\bactive\b"))

    def test_bnetz_measurements_are_readable_and_actionable_on_mobile(self, mobile_page):
        """BNetzA evidence rows should not hide values or actions off-screen."""
        mobile_page.evaluate("switchView('bnetz')")
        mobile_page.wait_for_selector("#bnetz-table-card", state="visible")
        mobile_page.wait_for_selector("#bnetz-tbody tr[data-bnetz-idx]")

        overflow = mobile_page.locator("#bnetz-table-card").evaluate(
            "el => el.scrollWidth - el.clientWidth"
        )
        assert overflow <= 1

        # Collapsed rows show date, measured values, and verdict; the rest on expand.
        first = mobile_page.locator("#bnetz-tbody tr[data-bnetz-idx]").first
        toggle = first.locator(".bnetz-expand-btn")
        expect(first.locator(".bnetz-actions-cell")).to_be_hidden()
        expect(first.locator(".bnetz-verdict")).to_be_visible()
        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(first.locator(".bnetz-actions-cell")).to_be_visible()
        mobile_page.locator("#bnetz-tbody tr[data-bnetz-idx]").evaluate_all(
            "rows => rows.forEach((row) => { if (!row.classList.contains('bnetz-row-open')) row.click(); })"
        )

        action_rects = mobile_page.locator(
            "#bnetz-tbody tr[data-bnetz-idx] .bnetz-action-btn:not(.bnetz-action-placeholder)"
        ).evaluate_all(
            """
            buttons => buttons.map((btn) => {
                const rect = btn.getBoundingClientRect();
                return {left: rect.left, right: rect.right, width: rect.width, visible: rect.width > 0 && rect.height > 0};
            })
            """
        )
        assert action_rects, "expected BNetzA row actions to be rendered"
        viewport_width = mobile_page.evaluate("window.innerWidth")
        assert all(rect["visible"] for rect in action_rects)
        assert all(rect["left"] >= 0 and rect["right"] <= viewport_width for rect in action_rects)

    def test_speedtest_history_stacks_rows_without_horizontal_scrolling(self, mobile_page):
        mobile_page.evaluate("switchView('speedtest')")
        mobile_page.wait_for_selector("#speedtest-tbody tr .st-col-dl")
        wrap = mobile_page.locator("#speedtest-table-wrap")
        assert wrap.evaluate("el => el.scrollWidth - el.clientWidth") <= 1
        first = mobile_page.locator("#speedtest-tbody tr").first
        for column in ("time", "dl", "ul", "ping", "jitter", "loss", "server"):
            expect(first.locator(f".st-col-{column}")).to_be_visible()
        assert "Upload" in first.locator(".st-col-ul").evaluate(
            "el => getComputedStyle(el, '::before').content"
        )

    def test_correlation_timeline_wraps_mobile_evidence_rows(self, mobile_page):
        """Correlation timeline rows should expose details without hidden horizontal scrolling."""
        mobile_page.evaluate("switchView('correlation')")
        mobile_page.wait_for_selector("#correlation-table-card", state="visible")
        mobile_page.wait_for_selector("#correlation-tbody tr[data-ts]")

        overflow = mobile_page.locator("#correlation-table-wrap").evaluate(
            "el => el.scrollWidth - el.clientWidth"
        )
        assert overflow <= 1

        row_geometry = mobile_page.locator("#correlation-tbody tr[data-ts]").first.evaluate(
            """
            (row) => {
                const rowRect = row.getBoundingClientRect();
                const details = row.querySelector('td:last-child').getBoundingClientRect();
                return {
                    rowLeft: rowRect.left,
                    rowRight: rowRect.right,
                    detailsLeft: details.left,
                    detailsRight: details.right,
                    viewportWidth: window.innerWidth,
                };
            }
            """
        )
        assert row_geometry["rowLeft"] >= 0
        assert row_geometry["rowRight"] <= row_geometry["viewportWidth"]
        assert row_geometry["detailsLeft"] >= 0
        assert row_geometry["detailsRight"] <= row_geometry["viewportWidth"]

    def test_incident_journal_mobile_actions_chips_and_rows_are_scannable(self, mobile_page):
        """Incident Journal should use mobile-first actions, wrapping chips, and card rows."""
        mobile_page.evaluate("switchView('journal')")
        mobile_page.wait_for_selector("#journal-table-card", state="visible")
        mobile_page.wait_for_selector("#journal-tbody tr[data-id]")
        mobile_page.evaluate(
            """
            () => {
                window._incidentsData = [
                    {id: 501, name: 'Upstream Noise Issue with very long mobile label', status: 'open', entry_count: 3},
                    {id: 502, name: 'Firmware Update Issues and repeated support calls', status: 'escalated', entry_count: 1}
                ];
                window.renderIncidentBar(window._incidentsData);
            }
            """
        )

        geometry = mobile_page.evaluate(
            """
            () => {
                const viewportWidth = window.innerWidth;
                const visibleRows = Array.from(document.querySelectorAll('#journal-tbody tr[data-id]'));
                const firstRow = visibleRows[0];
                const titleCell = firstRow.querySelector('td:nth-child(3)');
                const clipCell = firstRow.querySelector('.journal-clip');
                const actionRects = Array.from(document.querySelectorAll('.journal-header-actions > button, .journal-export-wrapper > button')).map((button) => {
                    const rect = button.getBoundingClientRect();
                    return {left: rect.left, right: rect.right, height: rect.height, width: rect.width};
                });
                const chipRects = Array.from(document.querySelectorAll('#incident-filter-bar .incident-pill')).map((pill) => {
                    const rect = pill.getBoundingClientRect();
                    return {left: rect.left, right: rect.right, width: rect.width};
                });
                return {
                    viewportWidth,
                    viewOverflow: document.querySelector('#view-journal').scrollWidth - document.querySelector('#view-journal').clientWidth,
                    actionsOverflow: document.querySelector('.journal-header-actions').scrollWidth - document.querySelector('.journal-header-actions').clientWidth,
                    tableOverflow: document.querySelector('#journal-table-card').scrollWidth - document.querySelector('#journal-table-card').clientWidth,
                    chipWrap: getComputedStyle(document.querySelector('#incident-filter-bar')).flexWrap,
                    rowDisplay: getComputedStyle(firstRow).display,
                    titleWidth: titleCell.getBoundingClientRect().width,
                    clipDisplay: getComputedStyle(clipCell).display,
                    actionRects,
                    chipRects,
                };
            }
            """
        )

        assert geometry["viewOverflow"] <= 1
        assert geometry["actionsOverflow"] <= 1
        assert geometry["tableOverflow"] <= 1
        assert geometry["chipWrap"] == "wrap"
        assert geometry["rowDisplay"] in {"block", "grid"}
        assert geometry["titleWidth"] >= 220
        assert geometry["clipDisplay"] == "none"
        assert all(rect["height"] >= 44 for rect in geometry["actionRects"])
        assert all(rect["left"] >= 0 and rect["right"] <= geometry["viewportWidth"] for rect in geometry["actionRects"])
        assert all(rect["left"] >= 0 and rect["right"] <= geometry["viewportWidth"] for rect in geometry["chipRects"])

    def test_incident_journal_mobile_bulk_selection_remains_accessible(self, mobile_page):
        """Bulk mode controls should remain reachable in mobile card rows."""
        mobile_page.evaluate("switchView('journal')")
        mobile_page.wait_for_selector("#journal-table-card", state="visible")
        mobile_page.wait_for_selector("#journal-tbody tr[data-id]")
        mobile_page.locator("#btn-bulk-toggle").click()
        mobile_page.wait_for_selector(".journal-row-check")

        checkbox_geometry = mobile_page.locator("#journal-tbody tr[data-id] .journal-check-cell").first.evaluate(
            """
            (cell) => {
                const rect = cell.getBoundingClientRect();
                const inputRect = cell.querySelector('input').getBoundingClientRect();
                return {
                    cellLeft: rect.left,
                    cellRight: rect.right,
                    cellHeight: rect.height,
                    inputLeft: inputRect.left,
                    inputRight: inputRect.right,
                    viewportWidth: window.innerWidth,
                };
            }
            """
        )

        assert checkbox_geometry["cellLeft"] >= 0
        assert checkbox_geometry["cellRight"] <= checkbox_geometry["viewportWidth"]
        assert checkbox_geometry["cellHeight"] >= 44
        assert checkbox_geometry["inputLeft"] >= 0
        assert checkbox_geometry["inputRight"] <= checkbox_geometry["viewportWidth"]

    def test_incident_journal_mobile_export_and_attachment_badges_fit_viewport(self, mobile_page):
        """Export choices and attachment badges should remain usable in the mobile layout."""
        mobile_page.evaluate("switchView('journal')")
        mobile_page.wait_for_selector("#journal-table-card", state="visible")
        mobile_page.evaluate(
            """
            () => {
                window._journalSortCol = 'date';
                window._journalSortAsc = false;
                window.T = Object.assign({}, window.T, {
                    attachments: 'Attachments "screenshots"',
                    incident_date: 'Date "local"'
                });
                window.renderJournalTable([{
                    id: 9001,
                    date: '2026-05-02',
                    title: 'Mobile evidence entry with attached screenshots and modem exports',
                    description: 'Includes screenshots and diagnostics for the support case.',
                    attachment_count: 2,
                    icon: 'documentation'
                }]);
            }
            """
        )
        mobile_page.locator(".journal-export-wrapper > button").click()

        geometry = mobile_page.evaluate(
            """
            () => {
                const viewportWidth = window.innerWidth;
                const dropdown = document.querySelector('#journal-export-dropdown');
                const dropdownRect = dropdown.getBoundingClientRect();
                const optionRects = Array.from(dropdown.querySelectorAll('button')).map((button) => {
                    const rect = button.getBoundingClientRect();
                    return {left: rect.left, right: rect.right, height: rect.height};
                });
                const clip = document.querySelector('#journal-tbody tr[data-id] .journal-clip');
                const clipRect = clip.getBoundingClientRect();
                return {
                    viewportWidth,
                    dropdownLeft: dropdownRect.left,
                    dropdownRight: dropdownRect.right,
                    optionRects,
                    clipDisplay: getComputedStyle(clip).display,
                    clipText: clip.textContent.trim(),
                    clipLeft: clipRect.left,
                    clipRight: clipRect.right,
                    clipLabel: clip.getAttribute('data-label'),
                    dateLabel: document.querySelector('#journal-tbody tr[data-id] .journal-date-cell').getAttribute('data-label'),
                };
            }
            """
        )

        assert geometry["dropdownLeft"] >= 0
        assert geometry["dropdownRight"] <= geometry["viewportWidth"]
        assert all(rect["left"] >= 0 and rect["right"] <= geometry["viewportWidth"] for rect in geometry["optionRects"])
        assert all(rect["height"] >= 40 for rect in geometry["optionRects"])
        assert geometry["clipDisplay"] == "inline-flex"
        assert geometry["clipText"] == "📎 2"
        assert geometry["clipLabel"] == 'Attachments "screenshots"'
        assert geometry["dateLabel"] == 'Date "local"'
        assert geometry["clipLeft"] >= 0
        assert geometry["clipRight"] <= geometry["viewportWidth"]

    def test_mobile_chart_tabs_help_and_close_targets_are_comfortable(self, mobile_page):
        """Chart controls, tabs, help hints, and modal close buttons should meet mobile hit targets."""
        mobile_page.evaluate("switchView('trends')")
        mobile_page.wait_for_selector("#view-trends.active .chart-expand-btn", state="attached")
        mobile_page.evaluate(
            """
            () => document.querySelectorAll(
                '#view-trends.active .chart-card, #view-trends.active .chart-card canvas, #view-trends.active .chart-expand-btn'
            ).forEach((el) => { el.style.display = el.matches('.chart-expand-btn') ? 'inline-flex' : 'block'; })
            """
        )

        mobile_page.evaluate(
            """
            () => {
                const fixture = document.createElement('div');
                fixture.id = '__touch-target-fixture';
                fixture.style.position = 'fixed';
                fixture.style.left = '8px';
                fixture.style.top = '80px';
                fixture.style.zIndex = '9999';
                fixture.innerHTML = '<button class="chart-expand-btn" type="button" aria-label="Expand chart">⛶</button><span class="glossary-hint" tabindex="0" aria-label="Help"><i>?</i></span>';
                document.body.appendChild(fixture);
            }
            """
        )

        trends_targets = mobile_page.evaluate(
            """
            () => {
                const viewportWidth = window.innerWidth;
                const groups = {
                    expand: '#__touch-target-fixture .chart-expand-btn',
                    tabs: '#view-trends.active #trend-tabs .trend-tab',
                    glossary: '#__touch-target-fixture .glossary-hint'
                };
                return Object.fromEntries(Object.entries(groups).map(([group, selector]) => [
                    group,
                    Array.from(document.querySelectorAll(selector)).map((el) => {
                        const rect = el.getBoundingClientRect();
                        const style = getComputedStyle(el);
                        return {
                            width: rect.width,
                            height: rect.height,
                            left: rect.left,
                            right: rect.right,
                            viewportWidth,
                            opacity: Number(style.opacity),
                            visibility: style.visibility,
                            pointerEvents: style.pointerEvents,
                        };
                    }).filter((rect) => rect.width > 0 && rect.height > 0)
                ]));
            }
            """
        )

        mobile_page.evaluate("switchView('speedtest')")
        mobile_page.wait_for_selector("#view-speedtest.active #speedtest-tabs .trend-tab")
        speedtest_tabs = mobile_page.locator("#view-speedtest.active #speedtest-tabs .trend-tab").evaluate_all(
            """
            tabs => tabs.map((tab) => {
                const rect = tab.getBoundingClientRect();
                return {width: rect.width, height: rect.height, left: rect.left, right: rect.right, viewportWidth: window.innerWidth};
            })
            """
        )

        mobile_page.evaluate("switchView('correlation')")
        mobile_page.wait_for_selector("#view-correlation.active #correlation-tabs .trend-tab")
        mobile_page.evaluate("document.querySelector('#correlation-chart-container').style.display = 'block'")
        correlation_controls = mobile_page.evaluate(
            """
            () => Array.from(document.querySelectorAll(
                '#view-correlation.active #correlation-tabs .trend-tab, #view-correlation.active .chart-export-btn'
            )).map((el) => {
                const rect = el.getBoundingClientRect();
                return {width: rect.width, height: rect.height, left: rect.left, right: rect.right, viewportWidth: window.innerWidth};
            })
            """
        )

        mobile_page.locator("#view-correlation.active .chart-export-btn").first.click()
        mobile_page.evaluate("window.DOCSightModal.open('bqm-import-modal')")
        mobile_page.wait_for_selector("#bqm-import-modal.open .modal-header .modal-close")
        modal_close_rect = mobile_page.locator("#bqm-import-modal.open .modal-header .modal-close").evaluate(
            """
            (button) => {
                const rect = button.getBoundingClientRect();
                return {width: rect.width, height: rect.height, left: rect.left, right: rect.right, viewportWidth: window.innerWidth};
            }
            """
        )

        assert trends_targets["expand"], "expected visible trend chart expand buttons"
        assert trends_targets["tabs"], "expected visible trend tabs"
        assert trends_targets["glossary"], "expected visible trend glossary hints"
        assert speedtest_tabs, "expected visible speedtest tabs"
        assert correlation_controls, "expected visible correlation tabs/export controls"
        assert modal_close_rect, "expected visible modal close button"

        all_targets = (
            trends_targets["expand"]
            + trends_targets["tabs"]
            + trends_targets["glossary"]
            + speedtest_tabs
            + correlation_controls
            + [modal_close_rect]
        )
        too_small = [rect for rect in all_targets if rect["width"] < 44 or rect["height"] < 44]
        assert too_small == []
        assert all(rect["left"] >= 0 and rect["right"] <= rect["viewportWidth"] for rect in all_targets)
        assert all(rect["opacity"] > 0 for rect in trends_targets["glossary"])
        assert all(rect["visibility"] == "visible" for rect in trends_targets["glossary"])
        assert all(rect["pointerEvents"] != "none" for rect in trends_targets["glossary"])

class TestDesktopCorrelationLayout:
    """Desktop correlation timeline layout behavior."""

    def test_correlation_timeline_sticky_header_uses_opaque_backdrop(self, page, live_server):
        """Sticky Unified Timeline headers should mask rows while scrolling."""
        page.set_viewport_size({"width": 1366, "height": 768})
        page.goto(live_server)
        page.wait_for_load_state("networkidle")
        page.evaluate("switchView('correlation')")
        page.wait_for_selector("#correlation-table-card", state="visible")
        page.wait_for_selector("#correlation-tbody tr[data-ts]")
        page.locator("#correlation-table-wrap").evaluate("wrap => { wrap.style.maxHeight = '96px'; }")

        header_state = page.locator("#correlation-table thead th").first.evaluate(
            r"""
            (th) => {
                const wrap = document.querySelector('#correlation-table-wrap');
                const canScroll = wrap.scrollHeight > wrap.clientHeight;
                wrap.scrollTop = 80;
                const style = getComputedStyle(th);
                const bg = style.backgroundColor;
                const match = bg.match(/rgba?\(([^)]+)\)/);
                let alpha = 1;
                if (match) {
                    const parts = match[1].split(',').map((part) => part.trim());
                    if (parts.length === 4) alpha = Number(parts[3]);
                }
                const rect = th.getBoundingClientRect();
                const topElement = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
                return {
                    backgroundColor: bg,
                    alpha,
                    canScroll,
                    position: style.position,
                    scrollTop: wrap.scrollTop,
                    zIndex: Number(style.zIndex) || 0,
                    topElementTag: topElement ? topElement.tagName : null,
                };
            }
            """
        )

        assert header_state["canScroll"] is True
        assert header_state["scrollTop"] > 0
        assert header_state["position"] == "sticky"
        assert header_state["topElementTag"] == "TH"
        assert header_state["alpha"] >= 0.98, header_state["backgroundColor"]


def test_bnetz_table_aligns_actions_and_names_each_verdict_on_desktop(demo_page):
    demo_page.evaluate("switchView('bnetz')")
    demo_page.wait_for_selector("#bnetz-tbody tr[data-bnetz-idx]")
    geometry = demo_page.evaluate(
        """
        () => {
            const rows = [...document.querySelectorAll('#bnetz-tbody tr[data-bnetz-idx]')];
            const firstCell = rows[0].querySelector('td');
            return {
                deleteLefts: [...new Set(rows.map((row) =>
                    Math.round(row.querySelector('.bnetz-action-delete').getBoundingClientRect().left)))],
                verdictTexts: rows.map((row) => row.querySelector('.bnetz-verdict-text').innerText.trim()),
                cellPadding: parseFloat(getComputedStyle(firstCell).paddingLeft),
                unnamedActions: [...document.querySelectorAll('#bnetz-tbody .bnetz-action-btn:not(.bnetz-action-placeholder)')]
                    .filter((el) => !el.getAttribute('aria-label')).length,
            };
        }
        """
    )
    assert len(geometry["deleteLefts"]) == 1
    assert all(geometry["verdictTexts"])
    assert geometry["cellPadding"] >= 12
    assert geometry["unnamedActions"] == 0
