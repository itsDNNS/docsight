"""The overview's "Get more out of DOCSight" checklist after setup."""

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import _new_target
from tests.e2e.support.lifecycle import running_processes
from tests.e2e.support.profiles import ServerProfile
from tests.e2e.support.vodafone import seed_vodafone_tg_data

# A configured instance with real channel data and nothing optional set up yet.
ONBOARDING_PROFILE = ServerProfile(
    "onboarding-checklist", configured=True, demo_mode=False,
    modem_type="vodafone_station", seed_callback=seed_vodafone_tg_data,
)


@pytest.fixture
def onboarding_server(tmp_path_factory):
    """Own process: dismissing the checklist must not leak into other tests."""
    target, spec = _new_target("onboarding-checklist", tmp_path_factory.mktemp("onboarding"), ONBOARDING_PROFILE)
    with running_processes([spec]):
        yield target.base_url


def test_checklist_links_open_items_and_stays_dismissed(page, onboarding_server):
    page.goto(f"{onboarding_server}/?lang=en", wait_until="networkidle")

    checklist = page.locator(".onboarding-checklist")
    expect(checklist).to_be_visible()
    expect(checklist.locator("h2")).to_have_text("Get more out of DOCSight")
    expect(checklist).to_contain_text("0 of 4 done")
    expect(checklist.locator('[data-onboarding-item="notifications"] a')).to_have_attribute(
        "href", "/settings#notifications")
    expect(checklist.locator('[data-onboarding-item="backup"] a')).to_have_attribute("href", "/settings#data")

    checklist.get_by_role("button", name="Hide checklist").click()
    expect(checklist).to_have_count(0)
    page.reload(wait_until="networkidle")
    expect(page.locator(".onboarding-checklist")).to_have_count(0)
    expect(page.locator(".home-kpis")).to_be_visible()
