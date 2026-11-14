"""Forms validate before saving, label their fields and stay usable with touch and input methods."""

from playwright.sync_api import expect


def test_settings_point_at_an_out_of_range_field_instead_of_saving(settings_page):
    page = settings_page
    posts = []
    page.on("request", lambda request: posts.append(request.url) if request.method == "POST" and "/api/config" in request.url else None)
    field = page.locator("#poll_interval")
    field.fill("1")
    page.locator('.settings-index-item[data-section="appearance"]').click()
    expect(page.locator("#panel-appearance")).to_be_visible()

    page.locator('#save-footer button[type="submit"]').click()
    # The section that holds the field opens and the field explains what is wrong.
    expect(field).to_be_visible()
    expect(field).to_have_attribute("aria-invalid", "true")
    error = page.locator("#poll_interval-error")
    expect(error).not_to_be_empty()
    assert "poll_interval-error" in field.get_attribute("aria-describedby")
    assert posts == []

    field.fill(field.get_attribute("min"))
    expect(field).not_to_have_attribute("aria-invalid", "true")
    expect(error).to_be_empty()


def test_settings_errors_are_announced(settings_page):
    expect(settings_page.locator("#global-error")).to_have_attribute("role", "alert")


def test_admin_password_is_offered_as_a_new_password(settings_page):
    expect(settings_page.locator("#admin_password")).to_have_attribute("autocomplete", "new-password")


def test_report_customer_fields_have_labels_and_autofill(demo_page):
    page = demo_page
    expect(page.locator("#report-name")).to_have_attribute("autocomplete", "name")
    expect(page.locator("#report-address")).to_have_attribute("autocomplete", "street-address")
    for field in ("#report-name", "#report-number", "#report-address"):
        assert page.locator(field).evaluate("el => el.labels.length === 1 && el.labels[0].textContent.trim().length > 0")


def test_fields_are_large_enough_that_phones_do_not_zoom(browser, live_server):
    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    page = context.new_page()
    page.goto(f"{live_server}/settings", wait_until="networkidle")
    sizes = page.evaluate("""() => Array.from(document.querySelectorAll('.form-input, .form-select'))
        .filter(el => el.getClientRects().length)
        .map(el => parseFloat(getComputedStyle(el).fontSize))""")
    assert sizes and min(sizes) >= 16
    context.close()


def test_enter_that_confirms_an_input_method_does_not_run_the_command(demo_page):
    page = demo_page
    page.keyboard.press("Control+k")
    combobox = page.locator("#command-palette-input")
    expect(combobox).to_be_focused()
    combobox.fill("channels")
    combobox.evaluate("""el => el.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', isComposing: true, bubbles: true, cancelable: true}))""")
    expect(page.locator("#command-palette")).to_be_visible()
    page.keyboard.press("Enter")
    expect(page.locator("#view-channels")).to_be_visible()
