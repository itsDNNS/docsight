"""E2E tests for the command palette and the keyboard shortcuts."""

import re

from playwright.sync_api import expect


def _palette(page):
    return page.locator("#command-palette")


def _open_with_keyboard(page):
    page.keyboard.press("Control+k")
    expect(_palette(page)).to_be_visible()
    expect(page.locator("#command-palette-input")).to_be_focused()


def _active_option(page):
    active_id = page.locator("#command-palette-input").get_attribute("aria-activedescendant")
    assert active_id, "no active option"
    return page.locator(f"#{active_id}")


def test_ctrl_k_finds_a_view_and_opens_it(demo_page):
    _open_with_keyboard(demo_page)
    combobox = demo_page.locator("#command-palette-input")
    expect(combobox).to_have_attribute("role", "combobox")
    expect(combobox).to_have_attribute("aria-controls", "command-palette-list")

    combobox.fill("channels")
    active = _active_option(demo_page)
    expect(active).to_have_attribute("aria-selected", "true")
    expect(active).to_contain_text("Channels")

    demo_page.keyboard.press("Enter")
    expect(_palette(demo_page)).to_be_hidden()
    expect(demo_page).to_have_url(re.compile(r"#channels"))
    expect(demo_page.locator("#view-channels")).to_be_visible()


def test_arrow_keys_move_through_the_results_and_wrap(demo_page):
    _open_with_keyboard(demo_page)
    options = demo_page.locator("#command-palette-list [role='option']")
    count = options.count()
    assert count > 2
    first_id = options.nth(0).get_attribute("id")
    expect(demo_page.locator("#command-palette-input")).to_have_attribute("aria-activedescendant", first_id)

    demo_page.keyboard.press("ArrowDown")
    expect(options.nth(1)).to_have_attribute("aria-selected", "true")
    expect(options.nth(0)).to_have_attribute("aria-selected", "false")

    demo_page.keyboard.press("ArrowUp")
    demo_page.keyboard.press("ArrowUp")
    expect(options.nth(count - 1)).to_have_attribute("aria-selected", "true")
    expect(demo_page.locator("[role='option'][aria-selected='true']")).to_have_count(1)


def test_escape_closes_and_returns_focus_to_the_trigger(demo_page):
    trigger = demo_page.locator("#command-palette-open")
    trigger.click()
    expect(_palette(demo_page)).to_be_visible()
    demo_page.keyboard.press("Escape")
    expect(_palette(demo_page)).to_be_hidden()
    expect(trigger).to_be_focused()


def test_channel_results_open_the_channel_timeline(demo_page):
    _open_with_keyboard(demo_page)
    demo_page.locator("#command-palette-input").fill("ds 13")
    active = _active_option(demo_page)
    expect(active).to_contain_text("DS channel 13")
    expect(active).to_contain_text("MHz")

    demo_page.keyboard.press("Enter")
    expect(demo_page).to_have_url(re.compile(r"#channels\?mode=timeline&dir=ds&channel=13"))
    expect(demo_page.locator("#channel-select")).to_have_value("ds-13")


def test_settings_sections_open_from_the_dashboard(demo_page):
    _open_with_keyboard(demo_page)
    demo_page.locator("#command-palette-input").fill("backups")
    expect(_active_option(demo_page)).to_contain_text("Data and storage")
    demo_page.keyboard.press("Enter")
    expect(demo_page).to_have_url(re.compile(r"/settings#data$"))
    expect(demo_page.locator("#settings-section-title")).to_have_text("Data and storage")


def test_settings_page_switches_sections_in_place(settings_page):
    _open_with_keyboard(settings_page)
    settings_page.locator("#command-palette-input").fill("appearance")
    settings_page.keyboard.press("Enter")
    expect(settings_page).to_have_url(re.compile(r"/settings#appearance$"))
    expect(settings_page.locator("#panel-appearance")).to_be_visible()


def test_glossary_terms_open_in_the_glossary(demo_page):
    _open_with_keyboard(demo_page)
    demo_page.locator("#command-palette-input").fill("snr")
    active = _active_option(demo_page)
    expect(active).to_contain_text("SNR")
    expect(active.locator("mark")).to_have_text("SNR")
    demo_page.keyboard.press("Enter")
    expect(demo_page).to_have_url(re.compile(r"#glossary\?term="))
    expect(demo_page.locator("#view-glossary")).to_be_visible()


def test_no_results_are_announced(demo_page):
    _open_with_keyboard(demo_page)
    demo_page.locator("#command-palette-input").fill("zzqx")
    expect(demo_page.locator("#command-palette-empty")).to_be_visible()
    expect(demo_page.locator("#command-palette-empty")).to_contain_text("zzqx")
    expect(demo_page.locator("#command-palette-status")).to_contain_text("zzqx")
    expect(demo_page.locator("#command-palette-input")).not_to_have_attribute("aria-activedescendant", re.compile(".+"))


def test_g_shortcuts_jump_to_destinations(demo_page):
    demo_page.keyboard.press("g")
    demo_page.keyboard.press("e")
    expect(demo_page).to_have_url(re.compile(r"#events"))
    expect(demo_page.locator("#view-events")).to_be_visible()

    demo_page.keyboard.press("g")
    demo_page.keyboard.press("s")
    expect(demo_page).to_have_url(re.compile(r"#trends"))

    demo_page.keyboard.press("g")
    demo_page.keyboard.press("o")
    expect(demo_page.locator("#view-dashboard")).to_be_visible()


def test_letter_shortcuts_leave_text_fields_alone(settings_page):
    search = settings_page.locator("#settings-search")
    search.click()
    settings_page.keyboard.type("ge?")
    expect(search).to_have_value("ge?")
    expect(_palette(settings_page)).to_be_hidden()
    expect(settings_page).to_have_url(re.compile(r"/settings"))


def test_question_mark_lists_the_shortcuts(demo_page):
    demo_page.keyboard.press("?")
    expect(_palette(demo_page)).to_be_visible()
    help_panel = demo_page.locator("#command-palette-help")
    expect(help_panel).to_be_visible()
    expect(demo_page.locator("#command-palette-help-toggle")).to_have_attribute("aria-expanded", "true")
    expect(help_panel.locator("[data-palette-shortcut='events'] dd")).to_have_text("Events")
    expect(help_panel.locator("[data-palette-shortcut='signal'] dd")).to_have_text("Signal")

    demo_page.keyboard.type("ev")
    expect(help_panel).to_be_hidden()
    expect(_active_option(demo_page)).to_be_visible()
