"""Regression checks for accessibility findings across the dashboard views."""

import pytest
from playwright.sync_api import expect

# Contrast of an element's text against the background it sits on: the element's
# and its ancestors' backgrounds are composited down to the first opaque one.
CONTRAST = r"""node => {
  const parse = value => {
    const srgb = value.match(/color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)/);
    if (srgb) return [srgb[1] * 255, srgb[2] * 255, srgb[3] * 255, srgb[4] === undefined ? 1 : +srgb[4]];
    const rgb = value.match(/rgba?\(([\d.]+),? ([\d.]+),? ([\d.]+)(?:,? \/? ?([\d.]+))?\)/);
    return [+rgb[1], +rgb[2], +rgb[3], rgb[4] === undefined ? 1 : +rgb[4]];
  };
  const layers = [];
  for (let el = node; el; el = el.parentElement) {
    const bg = parse(getComputedStyle(el).backgroundColor);
    if (bg[3] > 0) layers.push(bg);
    if (bg[3] >= 1) break;
  }
  let base = [255, 255, 255];
  for (const [r, g, b, a] of layers.reverse()) base = [r * a + base[0] * (1 - a), g * a + base[1] * (1 - a), b * a + base[2] * (1 - a)];
  const fg = parse(getComputedStyle(node).color);
  const text = [0, 1, 2].map(i => fg[i] * fg[3] + base[i] * (1 - fg[3]));
  const lum = c => {
    const ch = c.map(v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  };
  const [hi, lo] = [lum(text), lum(base)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
}"""


def _open(page, view, scheme="light"):
    page.emulate_media(color_scheme=scheme)
    page.evaluate("view => switchView(view)", view)


def _assert_readable(locator, label):
    assert locator.count(), f"{label}: nothing to check"
    ratios = [round(item.evaluate(CONTRAST), 2) for item in locator.all()]
    assert min(ratios) >= 4.5, f"{label}: {ratios}"


def test_overview_headings_do_not_skip_levels(demo_page):
    levels = demo_page.locator("#view-dashboard h1, #view-dashboard h2, #view-dashboard h3, #view-dashboard h4, h1").evaluate_all(
        "nodes => nodes.filter(n => n.offsetParent || n.closest('h1')).map(n => +n.tagName[1])"
    )
    assert levels[0] == 1
    assert all(level <= previous + 1 for previous, level in zip(levels, levels[1:])), levels
    expect(demo_page.locator("#home-findings-title")).to_have_js_property("tagName", "H2")


def test_glossary_hints_with_text_keep_it_as_their_name(demo_page):
    hint = demo_page.locator("#view-dashboard .hero-meta-item.glossary-hint").first
    expect(hint).not_to_have_attribute("aria-label", "x")
    assert hint.get_attribute("aria-label") is None
    described = hint.get_attribute("aria-describedby")
    assert described and demo_page.locator(f"#{described}").text_content().strip()
    # Icon-only hints still carry the explanation as their name.
    icon_hint = demo_page.locator(".home-kpi-label .glossary-hint").first
    assert icon_hint.get_attribute("aria-label")


def test_channel_status_rows_read_their_visible_text(demo_page):
    _open(demo_page, "channels")
    rows = demo_page.locator("#view-channels .cs-row:not(.cs-aggregate):visible")
    expect(rows.first).to_be_visible()
    assert demo_page.locator("#view-channels .cs-row[aria-label]").count() == 0
    first = rows.first
    label = first.locator(".cs-label").inner_text().splitlines()[0]
    assert label in first.text_content()
    assert first.locator(".sr-only").count() >= 1


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_correlation_legend_stays_readable_on_and_off(demo_page, scheme):
    _open(demo_page, "correlation", scheme)
    chips = demo_page.locator("#correlation-legend span[data-metric]")
    expect(chips.first).to_be_visible()
    _assert_readable(chips, "legend on")
    chips.first.click()
    expect(chips.first).to_have_attribute("aria-pressed", "false")
    _assert_readable(chips.first, "legend off")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_status_badges_stay_readable(demo_page, scheme):
    _open(demo_page, "live", scheme)
    # The demo modem has no segment utilization view; render both direction badges on the overview.
    demo_page.evaluate("""() => document.querySelector('#view-dashboard').insertAdjacentHTML('beforeend',
        '<div class="fritz-cable-event" id="a11y-probe"><div class="fritz-cable-event-header">'
        + '<span class="fritz-cable-event-direction is-downstream">Downstream</span>'
        + '<span class="fritz-cable-event-direction is-upstream">Upstream</span></div></div>')""")
    _assert_readable(demo_page.locator("#a11y-probe .fritz-cable-event-direction"), "segment directions")

    _open(demo_page, "evidence", scheme)
    badges = demo_page.locator("#view-evidence .evidence-badge")
    expect(badges.first).to_be_visible()
    _assert_readable(badges, "evidence badges")

    _open(demo_page, "journal", scheme)
    new_entry = demo_page.locator('#view-journal button[data-action="openEntryModal"]').first
    expect(new_entry).to_be_visible()
    _assert_readable(new_entry, "new entry button")


def test_table_headers_are_never_empty(demo_page):
    for view, header in (("speedtest", "th.st-sc-col"), ("journal", "th.journal-col-select")):
        _open(demo_page, view)
        cell = demo_page.locator(f"#view-{view} {header}")
        expect(cell).to_be_attached()
        assert cell.text_content().strip(), header


def test_bqm_days_keep_the_visible_day_in_their_name(demo_page):
    _open(demo_page, "bqm")
    day = demo_page.locator(".bqm-day[data-date]:not([disabled])").first
    expect(day).to_be_visible()
    assert day.get_attribute("aria-label") is None
    date = day.get_attribute("data-date")
    visible = day.evaluate("node => [...node.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim()")
    assert visible == str(int(date[-2:]))
    assert visible in day.text_content() and date[:4] in day.text_content()
