"""The notice center in the top bar and the overview's notice line."""

import re

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import _new_target
from tests.e2e.support.lifecycle import running_processes
from tests.e2e.support.profiles import ServerProfile

NOTICE_ID = "docsight-local-notices-2026-05"


@pytest.fixture
def notice_server(tmp_path_factory):
    """Own process: marking the notice read must not leak into other tests."""
    profile = ServerProfile("notice-center", configured=True, demo_mode=True)
    target, spec = _new_target("notice-center", tmp_path_factory.mktemp("notice-center"), profile)
    with running_processes([spec]):
        yield target.base_url


def test_notice_line_opens_the_center_and_read_notices_stay_listed(page, notice_server):
    page.goto(f"{notice_server}/?lang=en", wait_until="networkidle")

    line = page.locator(".notice-line")
    expect(line).to_have_count(1)
    expect(line).to_contain_text("Maintainer notices are now local-first")
    expect(page.locator(".maintainer-notice")).to_have_count(0)
    badge = page.locator("[data-notice-unread-count]")
    expect(badge).to_have_text("1")
    expect(page.locator("#nav-toggle-notices")).to_have_attribute("aria-label", "Notices, 1 unread")

    line.get_by_role("button", name="Open notices").click()
    panel = page.locator("#nav-panel-notices")
    expect(panel).to_be_visible()
    item = panel.locator(f'[data-notice-center-item="{NOTICE_ID}"]')
    item.get_by_role("button", name="Mark as read").click()

    expect(item).to_have_class(re.compile(r"\bread\b"))
    expect(badge).to_be_hidden()
    expect(page.locator(".notice-line")).to_have_count(0)
    expect(page.locator("#nav-toggle-notices")).to_have_attribute("aria-label", "Notices")

    page.reload(wait_until="networkidle")
    expect(page.locator(".notice-line")).to_have_count(0)
    page.locator("#nav-toggle-notices").click()
    expect(panel.locator(f'.notice-center-item.read[data-notice-center-item="{NOTICE_ID}"]')).to_be_visible()
