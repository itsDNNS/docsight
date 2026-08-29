"""E2E tests for the in-app glossary view."""

import re

from playwright.sync_api import expect


def _assert_visible_boxes_do_not_overlap(page, selector):
    boxes = page.locator(selector).evaluate_all(
        """nodes => nodes
            .filter(node => {
              const style = window.getComputedStyle(node);
              const rect = node.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            })
            .map((node, index) => {
              const rect = node.getBoundingClientRect();
              return { index, left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom };
            })"""
    )
    for i, first in enumerate(boxes):
        for second in boxes[i + 1:]:
            overlaps = not (
                first["right"] <= second["left"]
                or second["right"] <= first["left"]
                or first["bottom"] <= second["top"]
                or second["bottom"] <= first["top"]
            )
            assert not overlaps, f"{selector} boxes overlap: {first} vs {second}"


def _active_article(page):
    return page.locator("#view-glossary .glossary-term-article:not([hidden])")


def _assert_no_horizontal_overflow(page):
    overflow = page.evaluate(
        """() => ({
          document: document.documentElement.scrollWidth > document.documentElement.clientWidth,
          media: [...document.querySelectorAll(
            '#view-glossary .glossary-term-article:not([hidden]) .glossary-media-card'
          )].some(node => node.scrollWidth > node.clientWidth)
        })"""
    )
    assert overflow == {"document": False, "media": False}


def _assert_shared_medium_image_loaded(page, expected_alt, expected_caption):
    article = _active_article(page)
    image = article.locator('.glossary-media-card img[src="/static/glossary/shared-medium.svg"]')
    image.scroll_into_view_if_needed()
    expect(image).to_have_attribute("alt", expected_alt)
    caption = article.locator(".glossary-media-card figcaption")
    expect(caption).to_have_text(expected_caption)
    contrast_ratio = caption.evaluate(
        r"""node => {
          const parseRgb = value => value.match(/\d+(?:\.\d+)?/g).slice(0, 3).map(Number);
          const luminance = rgb => {
            const channels = rgb.map(value => {
              const normalized = value / 255;
              return normalized <= 0.04045
                ? normalized / 12.92
                : Math.pow((normalized + 0.055) / 1.055, 2.4);
            });
            return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
          };
          const foreground = luminance(parseRgb(getComputedStyle(node).color));
          const background = luminance(
            parseRgb(getComputedStyle(node.closest('.glossary-card')).backgroundColor)
          );
          return (Math.max(foreground, background) + 0.05)
            / (Math.min(foreground, background) + 0.05);
        }"""
    )
    assert contrast_ratio >= 4.5
    expect(image).to_be_visible()
    assert image.evaluate(
        """node => node.complete
          ? node.naturalWidth > 0 && node.naturalHeight > 0
          : new Promise(resolve => {
              node.addEventListener(
                'load',
                () => resolve(node.naturalWidth > 0 && node.naturalHeight > 0),
                { once: true }
              );
              node.addEventListener('error', () => resolve(false), { once: true });
            })"""
    )
    _assert_visible_boxes_do_not_overlap(
        page, "#view-glossary .glossary-term-article:not([hidden]) > .glossary-card"
    )
    _assert_no_horizontal_overflow(page)


def test_glossary_app_view_renders_inside_shell(page, live_server):
    page.goto(f"{live_server}/?lang=en&term=docsis#glossary?term=docsis")
    page.wait_for_selector("#view-glossary.active", state="visible")

    expect(page.locator(".sidebar")).to_be_visible()
    expect(page.locator('.nav-item[data-view="glossary"]')).to_have_class(re.compile(r"active"))
    expect(page.locator("#view-glossary .view-page-title", has_text="Glossary")).to_be_visible()
    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="DOCSIS")).to_be_visible()
    expect(_active_article(page).locator(".glossary-summary-card", has_text="Quick summary")).to_be_visible()
    expect(_active_article(page).locator(".glossary-explanation-card", has_text="Explanation")).to_be_visible()
    expect(page.locator(".glossary-index-desktop .glossary-term-link").first).to_have_text("Before/After Comparison")
    desktop_terms = page.locator(".glossary-index-desktop .glossary-term-link").evaluate_all(
        "nodes => nodes.map(node => node.textContent.trim())"
    )
    assert desktop_terms == sorted(desktop_terms, key=str.casefold)
    _assert_visible_boxes_do_not_overlap(page, "#view-glossary .glossary-term-article:not([hidden]) > .glossary-card")


def test_glossary_term_list_navigation_updates_hash_and_article(page, live_server):
    page.goto(f"{live_server}/?lang=en&term=sc_qam#glossary?term=sc_qam")
    page.wait_for_selector("#view-glossary.active", state="visible")

    expect(_active_article(page).locator(".glossary-explanation-card", has_text="DOCSIS 3.0-style channels")).to_be_visible()

    page.locator(".glossary-index-desktop [data-glossary-term]", has_text="Gaming Index").click()
    expect(page).to_have_url(re.compile(r"#glossary\?term=gaming_index"))
    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="Gaming Index")).to_be_visible()


def test_glossary_legacy_level_deep_link_opens_article_without_detail_ui(page, live_server):
    page.goto(f"{live_server}/?lang=en#glossary?term=docsis&level=technician")
    page.wait_for_selector("#view-glossary.active", state="visible")

    article = _active_article(page)
    expect(article.locator(".glossary-term-header-card h3", has_text="DOCSIS")).to_be_visible()
    expect(article.locator(".glossary-summary-card", has_text="Quick summary")).to_be_visible()
    expect(article.locator(".glossary-explanation-card", has_text="Explanation")).to_be_visible()
    expect(article.locator('[data-glossary-detail-level]')).to_have_count(0)


def test_glossary_invalid_deep_link_shows_searchable_empty_state(page, live_server):
    page.goto(f"{live_server}/?lang=en#glossary?term=not_a_real_term")
    page.wait_for_selector("#view-glossary.active", state="visible")

    expect(page.locator("#view-glossary [data-glossary-missing]")).to_be_visible()
    expect(page.locator("#glossary-search")).to_have_value("not_a_real_term")
    expect(page.locator("#view-glossary .glossary-term-article:not([hidden])")).to_have_count(0)


def test_glossary_mobile_layout_has_no_horizontal_overflow(page, live_server):
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{live_server}/?lang=en&term=gaming_index#glossary?term=gaming_index")
    page.wait_for_selector("#view-glossary.active", state="visible")

    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="Gaming Index")).to_be_visible()
    has_overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    assert has_overflow is False
    _assert_visible_boxes_do_not_overlap(page, "#view-glossary .glossary-term-article:not([hidden]) > .glossary-card")


def test_tkg_law_appendix_expands_by_keyboard_without_mobile_overflow(page, live_server):
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{live_server}/?lang=en&term=tkg_rights_de#glossary?term=tkg_rights_de")
    page.wait_for_selector("#view-glossary.active", state="visible")

    article = _active_article(page)
    details = article.locator(".glossary-law-details")
    summary = details.locator("summary")
    expect(details).not_to_have_attribute("open", "")
    summary.focus()
    expect(summary).to_be_focused()
    page.keyboard.press("Enter")
    expect(details).to_have_attribute("open", "")
    expect(article.locator('.glossary-law-verbatim[lang="de"]')).to_have_count(2)
    expect(article).to_contain_text("Der Verbraucher kann von einem Anbieter")
    _assert_no_horizontal_overflow(page)
    _assert_visible_boxes_do_not_overlap(
        page, "#view-glossary .glossary-term-article:not([hidden]) > .glossary-card"
    )


def test_glossary_shared_medium_media_desktop(page, live_server):
    page.set_viewport_size({"width": 1440, "height": 950})
    page.goto(f"{live_server}/?lang=de&term=shared_medium#glossary?term=shared_medium")
    page.wait_for_selector("#view-glossary.active", state="visible")

    _assert_shared_medium_image_loaded(
        page,
        "Mehrere Haushalte sind mit demselben gemeinsam genutzten Kabelsegment im Viertel verbunden",
        (
            "Haushalte im selben Kabelsegment teilen sich einen Teil des Zugangsnetzes. "
            "Ein einzelnes Modem kann die Gesamtauslastung des Segments nicht messen."
        ),
    )


def test_glossary_shared_medium_media_mobile(page, live_server):
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{live_server}/?lang=fr&term=shared_medium#glossary?term=shared_medium")
    page.wait_for_selector("#view-glossary.active", state="visible")

    _assert_shared_medium_image_loaded(
        page,
        "Plusieurs foyers reliés à un même segment de câble partagé dans le quartier",
        (
            "Les foyers d’un même segment de câble partagent une partie du réseau d’accès. "
            "Un seul modem ne peut pas mesurer l’utilisation totale du segment."
        ),
    )


def test_glossary_search_filters_alphabetical_terms(page, live_server):
    page.goto(f"{live_server}/?lang=en&term=docsis#glossary?term=docsis")
    page.wait_for_selector("#view-glossary.active", state="visible")

    search = page.locator("#glossary-search")
    search.fill("Cable Modem")
    expect(page.locator(".glossary-index-desktop [data-term-id='cmts']")).to_be_visible()
    expect(page.locator(".glossary-index-desktop [data-search^='Speedtest ']")).to_be_hidden()
    expect(page.locator("#glossary-result-count")).to_contain_text("1 term shown")

    search.fill("SNR")
    first_visible = page.locator(".glossary-index-desktop [data-glossary-term]:visible").first
    expect(first_visible).to_have_attribute("data-term-id", "snr_mer")
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"#glossary\?term=snr_mer"))
    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="SNR/MER")).to_be_visible()

    search.fill("")
    restored_terms = page.locator(".glossary-index-desktop .glossary-term-link").evaluate_all(
        "nodes => nodes.slice(0, 3).map(node => node.textContent.trim())"
    )
    assert restored_terms == ["Before/After Comparison", "BNetzA measurement", "BQM"]


def test_glossary_alias_deep_link_resolves_to_canonical_term(page, live_server):
    page.goto(f"{live_server}/?lang=en#glossary?term=Signal-to-noise%20ratio")
    page.wait_for_selector("#view-glossary.active", state="visible")

    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="SNR/MER")).to_be_visible()
    expect(page.locator("#view-glossary [data-glossary-missing]")).to_be_hidden()


def test_glossary_desktop_click_does_not_refocus_closed_mobile_picker(page, live_server):
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{live_server}/?lang=en&term=docsis#glossary?term=docsis")
    page.wait_for_selector("#view-glossary.active", state="visible")

    page.locator(".glossary-mobile-picker-trigger").click()
    page.keyboard.press("Escape")
    expect(page.locator("#glossary-mobile-picker")).to_be_hidden()

    page.set_viewport_size({"width": 1440, "height": 950})
    page.locator(".glossary-index-desktop [data-term-id='cmts']").click()

    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="CMTS")).to_be_visible()
    trigger_has_focus = page.evaluate(
        "document.activeElement === document.querySelector('.glossary-mobile-picker-trigger')"
    )
    assert trigger_has_focus is False


def test_glossary_mobile_uses_picker_instead_of_inline_long_list(page, live_server):
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{live_server}/?lang=en&term=docsis#glossary?term=docsis")
    page.wait_for_selector("#view-glossary.active", state="visible")

    expect(page.locator(".glossary-index-desktop")).to_be_hidden()
    expect(page.locator(".glossary-mobile-picker-trigger", has_text="Search or change term")).to_be_visible()
    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="DOCSIS")).to_be_visible()

    page.locator(".glossary-mobile-picker-trigger").click()
    expect(page.locator("#glossary-mobile-picker")).to_be_visible()
    mobile_search = page.locator("#glossary-mobile-search")
    expect(mobile_search).to_be_focused()
    mobile_search.fill("Cable Modem")
    expect(page.locator("#glossary-mobile-picker [data-term-id='cmts']")).to_be_visible()
    expect(page.locator("#glossary-mobile-picker [data-search^='Speedtest ']")).to_be_hidden()

    page.keyboard.press("Shift+Tab")
    expect(page.locator(".glossary-mobile-picker-close")).to_be_focused()
    for _ in range(8):
        page.keyboard.press("Tab")
        focus_inside_picker = page.evaluate(
            "document.querySelector('#glossary-mobile-picker').contains(document.activeElement)"
        )
        assert focus_inside_picker is True

    page.keyboard.press("Escape")
    expect(page.locator("#glossary-mobile-picker")).to_be_hidden()
    expect(page.locator(".glossary-mobile-picker-trigger")).to_be_focused()


def test_dashboard_contextual_help_links_to_matching_in_app_glossary_term(page, live_server):
    page.goto(f"{live_server}/?lang=en")
    page.wait_for_load_state("networkidle")

    page.locator(".hero-meta-item.glossary-hint", has_text="DOCSIS basics").click()
    link = page.locator("#glossary-popover-overlay .glossary-popover-link")
    expect(link).to_be_visible()
    expect(link).to_have_attribute("href", re.compile(r"/\?lang=en#glossary\?term=docsis$"))


def test_dashboard_contextual_glossary_link_is_keyboard_reachable(page, live_server):
    page.goto(f"{live_server}/?lang=en")
    page.wait_for_load_state("networkidle")

    hint = page.locator(".hero-meta-item.glossary-hint", has_text="DOCSIS basics")
    hint.focus()
    page.keyboard.press("Enter")

    link = page.locator("#glossary-popover-overlay .glossary-popover-link")
    expect(link).to_be_visible()
    expect(link).to_be_focused()

    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"/\?lang=en#glossary\?term=docsis"))
    page.wait_for_selector("#view-glossary.active", state="visible")
    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="DOCSIS")).to_be_visible()
