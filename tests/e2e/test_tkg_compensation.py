"""Behavior-driven browser contracts for the German TKG compensation wizard."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from app.theme_registry import BUILTIN_THEMES


def _open_tkg(page):
    page.evaluate("switchView('mod-docsight-de_tkg_compensation')")
    root = page.locator("#tkg-compensation-root")
    expect(root).to_be_visible()
    return root


def _apply_builtin_theme(page, name, mode):
    theme = next(item for item in BUILTIN_THEMES if item["name"] == name)
    page.locator("html").evaluate(
        """
        (element, config) => {
            element.setAttribute('data-theme', config.mode);
            for (const [key, value] of Object.entries(config.values)) {
                element.style.setProperty(key, value);
            }
        }
        """,
        {"mode": mode, "values": theme["theme_data"][mode]},
    )


def _enter_outage_and_calculate(page, *, fee="40.00"):
    page.locator("#tkg-window-from").fill("2026-01-01T00:00")
    page.locator("#tkg-window-to").fill("2026-01-06T23:59")
    page.locator("#tkg-next").click()
    facts = page.locator('[data-tkg-step="2"]')
    expect(facts).to_be_visible()
    expect(facts).to_be_focused()
    page.locator("#tkg-report-date").fill("2026-01-01")
    page.locator("#tkg-restored-date").fill("2026-01-06")
    page.locator("#tkg-complete-outage").check()
    page.locator("#tkg-monthly-fee").fill(fee)
    for day in ("2026-01-04", "2026-01-05", "2026-01-06"):
        page.locator(f'.tkg-day[data-date="{day}"] [data-kind="complete"]').check()
    page.locator("#tkg-calculate").click()
    expect(page.locator('[data-tkg-step="3"]')).to_be_visible()


def _enter_appointment_only_and_calculate(page, *, fee, expected):
    page.locator("#tkg-next").click()
    expect(page.locator('[data-tkg-step="2"]')).to_be_visible()
    expect(page.locator("#tkg-report-date")).to_have_value("")
    expect(page.locator("#tkg-restored-date")).to_have_value("")
    page.locator("#tkg-monthly-fee").fill(fee)
    page.locator("#tkg-missed-appointments").fill("1")
    page.locator("#tkg-calculate").click()
    expect(page.locator('[data-tkg-step="3"]')).to_be_visible()
    expect(page.locator("#tkg-calculation")).to_contain_text(expected)
    expect(page.locator("#tkg-calculation")).to_contain_text("TKG §58 Abs.4")
    expect(page.locator("#tkg-calculation table")).to_have_count(0)


def _generate_letter(page):
    page.locator("#tkg-next").click()
    page.locator("#tkg-generate-letter").click()
    letter = page.locator("#tkg-letter")
    expect(letter).not_to_have_value("")
    return letter.input_value()


def _assert_download(page, expected_text):
    page.locator("#tkg-next").click()
    with page.expect_download() as download_info:
        page.locator("#tkg-download").click()
    download = download_info.value
    assert download.suggested_filename.endswith(".txt")
    assert download.path().read_bytes().decode("utf-8") == expected_text


@pytest.mark.parametrize(
    "viewport",
    [{"width": 1280, "height": 900}, {"width": 393, "height": 852}],
    ids=["desktop", "mobile"],
)
def test_manual_claim_calculation_copy_download_and_focus_flow(tkg_core_page, viewport):
    tkg_core_page.set_viewport_size(viewport)
    root = _open_tkg(tkg_core_page)
    expect(root).to_contain_text("Germany-specific")
    _enter_outage_and_calculate(tkg_core_page)

    calculation = tkg_core_page.locator("#tkg-calculation")
    expect(calculation).to_contain_text("20,00 €")
    expect(calculation).to_contain_text("max(5,00 €; 10% = 4,00 €)")
    expect(calculation).to_contain_text("de-tkg58-2026.1")
    first_day_row = calculation.locator("tbody tr").first
    expect(first_day_row.locator("td").nth(0)).to_have_text("2026-01-04")
    expect(first_day_row.locator("td").nth(1)).to_have_text("3")
    expected_text = _generate_letter(tkg_core_page)
    assert "max(5,00 €; 10 % = 4,00 €) = 5,00 €" in expected_text

    parsed = urlsplit(tkg_core_page.url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    tkg_core_page.context.grant_permissions(
        ["clipboard-read", "clipboard-write"], origin=origin
    )
    tkg_core_page.locator("#tkg-next").click()
    tkg_core_page.locator("#tkg-copy").click()
    expect(tkg_core_page.locator("#tkg-status")).to_contain_text("copied")
    assert tkg_core_page.evaluate("navigator.clipboard.readText()") == expected_text
    tkg_core_page.locator("#tkg-previous").click()
    _assert_download(tkg_core_page, expected_text)

    overflow = root.evaluate(
        "el => ({root: el.scrollWidth - el.clientWidth, document: document.documentElement.scrollWidth - window.innerWidth})"
    )
    assert overflow["root"] <= 1
    assert overflow["document"] <= 1


@pytest.mark.parametrize(
    ("theme_name", "mode"),
    [("Tribu", "dark"), ("Tribu", "light"), ("Amber Terminal", "dark")],
)
def test_tkg_controls_follow_builtin_theme_tokens(tkg_core_page, theme_name, mode):
    _apply_builtin_theme(tkg_core_page, theme_name, mode)
    root = _open_tkg(tkg_core_page)

    styles = root.evaluate(
        """
        (root) => {
            const resolveBackground = (token) => {
                const probe = document.createElement('span');
                probe.style.backgroundColor = `var(${token})`;
                document.body.appendChild(probe);
                const value = getComputedStyle(probe).backgroundColor;
                probe.remove();
                return value;
            };
            const panel = root.querySelector('[data-tkg-step="1"]');
            const primary = root.querySelector('#tkg-next');
            const secondary = root.querySelector('#tkg-load-candidates');
            const input = root.querySelector('#tkg-window-from');
            return {
                expectedAccent: resolveBackground('--accent'),
                expectedCard: resolveBackground('--card'),
                expectedCardBorder: resolveBackground('--card-border'),
                expectedControl: resolveBackground('--elevated'),
                panelBackground: getComputedStyle(panel).backgroundColor,
                panelBorder: getComputedStyle(panel).borderColor,
                panelOutlineColor: getComputedStyle(panel).outlineColor,
                panelOutline: getComputedStyle(panel).outlineStyle,
                primaryBackground: getComputedStyle(primary).backgroundColor,
                secondaryBackground: getComputedStyle(secondary).backgroundColor,
                inputBackground: getComputedStyle(input).backgroundColor,
                inputColorScheme: getComputedStyle(input).colorScheme,
            };
        }
        """
    )

    assert styles["panelBackground"] == styles["expectedCard"]
    assert styles["panelBorder"] == styles["expectedCardBorder"]
    assert styles["panelOutline"] == "solid"
    assert styles["panelOutlineColor"] == styles["expectedAccent"]
    assert styles["primaryBackground"] == styles["expectedAccent"]
    assert styles["secondaryBackground"] == styles["expectedControl"]
    assert styles["inputBackground"] == styles["expectedControl"]
    assert styles["inputColorScheme"] == mode


def test_candidate_application_is_keyboard_accessible_and_keeps_legal_facts_blank(demo_page):
    candidate_payload = {
        "candidates": [{
            "id": "incident-7",
            "label": "Ongoing incident",
            "origin": "incident",
            "derived": True,
            "ongoing": True,
            "restoration_suggested": False,
            "window_from": "2026-03-26T23:00:00Z",
            "window_to": "2026-03-30T21:59:59Z",
            "window_from_local": "2026-03-27T00:00",
            "window_to_local": "2026-03-30T23:59",
            "suggested_days": ["2026-03-27", "2026-03-28", "2026-03-29", "2026-03-30"],
        }],
        "capabilities": {"bnetz": False},
        "customer_defaults": {},
        "local_today": "2026-03-30",
        "rules_version": "de-tkg58-2026.1",
        "jurisdiction": "DE",
    }
    demo_page.route(
        re.compile(r".*/api/de-tkg/candidates$"),
        lambda route: route.fulfill(json=candidate_payload),
    )
    _open_tkg(demo_page)

    action = demo_page.get_by_role("button", name="Use proposal: Ongoing incident")
    expect(action).to_be_visible()
    action.focus()
    demo_page.keyboard.press("Enter")

    expect(demo_page.locator('[data-tkg-step="2"]')).to_be_focused()
    expect(demo_page.locator("#tkg-window-from")).to_have_value("2026-03-27T00:00")
    expect(demo_page.locator("#tkg-window-to")).to_have_value("2026-03-30T23:59")
    expect(demo_page.locator("#tkg-report-date")).to_have_value("")
    expect(demo_page.locator("#tkg-restored-date")).to_have_value("")
    day_boxes = demo_page.locator('#tkg-days [data-kind="complete"]')
    assert day_boxes.count() == 4
    assert day_boxes.evaluate_all("nodes => nodes.every(node => !node.checked)")
    expect(demo_page.locator("#tkg-status")).to_contain_text("no restoration is inferred")


def test_candidate_reload_keeps_result_visible_and_exposes_busy_state(demo_page):
    responses = {"candidates": [], "fails": False}

    def fulfill_candidates(route):
        if responses["fails"]:
            route.fulfill(status=503, json={})
            return
        route.fulfill(
            json={
                "candidates": responses["candidates"],
                "capabilities": {"bnetz": False},
                "customer_defaults": {},
                "local_today": "2026-03-30",
                "rules_version": "de-tkg58-2026.1",
                "jurisdiction": "DE",
            }
        )

    demo_page.route(re.compile(r".*/api/de-tkg/candidates$"), fulfill_candidates)
    _open_tkg(demo_page)
    load = demo_page.locator("#tkg-load-candidates")
    status = demo_page.locator("#tkg-status")
    expect(status).to_have_text("Proposals loaded: 0.")

    demo_page.evaluate(
        """
        window.__tkgOriginalFetch = window.fetch;
        window.fetch = function(input, init) {
            if (String(input).endsWith('/api/de-tkg/candidates')) {
                return new Promise(function(resolve) {
                    window.__tkgFinishCandidateFetch = function() {
                        resolve(window.__tkgOriginalFetch(input, init));
                    };
                });
            }
            return window.__tkgOriginalFetch(input, init);
        };
        """
    )
    load.click()
    expect(load).to_be_disabled()
    expect(load).to_have_attribute("aria-busy", "true")
    expect(status).to_have_text("Loading…")
    demo_page.evaluate("window.__tkgFinishCandidateFetch()")

    expect(load).to_be_enabled()
    expect(load).to_have_attribute("aria-busy", "false")
    expect(status).to_have_text("Proposals loaded: 0.")

    responses["candidates"] = [
        {
            "id": "incident-8",
            "label": "Resolved incident",
            "origin": "incident",
            "derived": True,
            "ongoing": False,
            "restoration_suggested": True,
            "window_from": "2026-03-27T23:00:00Z",
            "window_to": "2026-03-29T21:59:59Z",
            "window_from_local": "2026-03-28T00:00",
            "window_to_local": "2026-03-29T23:59",
            "suggested_days": ["2026-03-28", "2026-03-29"],
        },
    ]
    demo_page.evaluate("window.fetch = window.__tkgOriginalFetch")
    load.click()

    expect(status).to_have_text("Proposals loaded: 1.")
    expect(
        demo_page.get_by_role("button", name="Use proposal: Resolved incident")
    ).to_be_enabled()

    responses["fails"] = True
    load.click()

    expect(load).to_be_enabled()
    expect(load).to_have_attribute("aria-busy", "false")
    expect(status).to_have_text("The request could not be completed.")


def test_fact_edit_invalidates_calculation_links_and_letter_until_regenerated(tkg_core_page):
    _open_tkg(tkg_core_page)
    _enter_outage_and_calculate(tkg_core_page)
    original = _generate_letter(tkg_core_page)
    assert original

    tkg_core_page.locator("#tkg-previous").click()
    tkg_core_page.locator("#tkg-previous").click()
    expect(tkg_core_page.locator('[data-tkg-step="2"]')).to_be_visible()
    tkg_core_page.locator("#tkg-monthly-fee").fill("60.00")

    expect(tkg_core_page.locator("#tkg-letter")).to_have_value("")
    expect(tkg_core_page.locator("#tkg-calculation")).to_contain_text(
        "Confirm and calculate the facts first"
    )
    assert tkg_core_page.locator("#tkg-report-links a").count() == 0
    tkg_core_page.locator("#tkg-next").click()
    expect(tkg_core_page.locator('[data-tkg-step="2"]')).to_be_visible()

    tkg_core_page.locator("#tkg-calculate").click()
    expect(tkg_core_page.locator('[data-tkg-step="3"]')).to_be_visible()
    regenerated = _generate_letter(tkg_core_page)
    assert regenerated != original
    assert "10 % = 6,00 €" in regenerated


def test_clipboard_fallback_copies_exact_text_without_clipboard_api(tkg_core_page):
    _open_tkg(tkg_core_page)
    _enter_appointment_only_and_calculate(tkg_core_page, fee="40.00", expected="10,00 €")
    expected_text = _generate_letter(tkg_core_page)
    tkg_core_page.locator("#tkg-next").click()
    tkg_core_page.evaluate(
        """
        Object.defineProperty(navigator, 'clipboard', {value: undefined, configurable: true});
        window.__fallbackCopied = null;
        document.execCommand = function(command) {
            if (command !== 'copy') return false;
            var node = document.activeElement;
            window.__fallbackCopied = node.value.slice(node.selectionStart, node.selectionEnd);
            return true;
        };
        """
    )

    tkg_core_page.locator("#tkg-copy").click()

    assert tkg_core_page.evaluate("window.__fallbackCopied") == expected_text
    expect(tkg_core_page.locator("#tkg-status")).to_contain_text("copied")


def test_disabled_module_has_no_tab_route_or_static_asset(page, tkg_disabled_server):
    page.goto(tkg_disabled_server)
    page.wait_for_load_state("networkidle")

    assert page.locator("#tkg-compensation-root").count() == 0
    assert page.locator('[data-view="mod-docsight-de_tkg_compensation"]').count() == 0
    assert page.request.get(f"{tkg_disabled_server}/api/de-tkg/candidates").status == 404
    assert page.request.get(
        f"{tkg_disabled_server}/modules/docsight.de_tkg_compensation/static/main.js"
    ).status == 404


def test_full_appointment_only_api_copy_and_export_flow_at_root_and_prefix(
    page, path_prefix_servers
):
    app_url = path_prefix_servers["app_url"]
    page.goto(f"{app_url}/login")
    page.fill('input[name="password"]', path_prefix_servers["password"])
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    _open_tkg(page)

    is_prefix = path_prefix_servers["mount_path"] == "/docsight"
    fee, expected = ("60.00", "12,00 €") if is_prefix else ("40.00", "10,00 €")
    _enter_appointment_only_and_calculate(page, fee=fee, expected=expected)
    text = _generate_letter(page)
    assert "TKG §58 Abs.4" in text
    assert "vollständigen Dienstausfall" not in text
    assert "Störungsmeldung" not in text
    parsed = urlsplit(page.url)
    page.context.grant_permissions(
        ["clipboard-read", "clipboard-write"],
        origin=f"{parsed.scheme}://{parsed.netloc}",
    )
    page.locator("#tkg-next").click()
    page.locator("#tkg-copy").click()
    assert page.evaluate("navigator.clipboard.readText()") == text
    page.locator("#tkg-previous").click()
    _assert_download(page, text)

    response = page.request.get(f"{app_url}/api/de-tkg/candidates")
    assert response.status == 200
    assert page.evaluate("docsightUrl('/api/de-tkg/candidates')") == (
        f"{path_prefix_servers['mount_path']}/api/de-tkg/candidates"
    )
