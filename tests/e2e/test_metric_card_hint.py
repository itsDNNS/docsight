"""The help icon of a metric card sits next to the card title, not on top of it."""

import pytest


@pytest.mark.parametrize("width", [390, 1440])
def test_the_help_icon_does_not_cover_the_card_title(browser, live_server, width):
    context = browser.new_context(viewport={"width": width, "height": 900}, has_touch=width < 500)
    page = context.new_page()
    page.goto(f"{live_server}/?lang=en#channels?mode=status", wait_until="networkidle")
    # Open the family readings and measure once their cards are laid out.
    overlaps = page.wait_for_function("""() => {
        const families = document.getElementById('channel-families');
        if (!families) return null;
        families.open = true;
        const cards = Array.from(families.querySelectorAll('.metric-card')).filter(card => card.querySelector('.glossary-hint'));
        if (!cards.length || cards[0].getBoundingClientRect().height === 0) return null;
        return cards.flatMap(card => {
            const hint = card.querySelector('.glossary-hint svg, .glossary-hint i').getBoundingClientRect();
            const label = card.querySelector('.metric-label').getBoundingClientRect();
            const apart = hint.left >= label.right || hint.right <= label.left || hint.top >= label.bottom || hint.bottom <= label.top;
            return apart ? [] : [card.querySelector('.metric-label').textContent.trim()];
        });
    }""").json_value()
    assert overlaps == []
    context.close()
