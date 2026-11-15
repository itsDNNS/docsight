"""A fresh install stays locked until the setup code from the log sets the first admin password."""

import re
from pathlib import Path

from playwright.sync_api import expect


def _setup_code(log_path):
    match = re.search(r"\b[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}\b", Path(log_path).read_text())
    assert match, "the setup code is missing from the DOCSight log"
    return match.group(0)


def test_the_setup_code_from_the_log_sets_the_first_password(page, password_setup_server):
    base_url, log_path = password_setup_server

    page.goto(base_url)
    expect(page).to_have_url(re.compile(r"/password-setup$"))
    page.get_by_label("Setup code").fill("AAAA-BBBB-CCCC")
    page.get_by_label("New admin password").fill("correct horse")
    page.get_by_label("Repeat password").fill("correct horse")
    page.get_by_role("button", name="Set password and continue").click()
    expect(page.get_by_role("alert")).to_contain_text("setup code does not match")

    page.get_by_label("Setup code").fill(_setup_code(log_path))
    page.get_by_label("New admin password").fill("correct horse")
    page.get_by_label("Repeat password").fill("correct horse")
    page.get_by_role("button", name="Set password and continue").click()

    # Signed in, the fresh install continues with the first-run setup.
    expect(page).to_have_url(re.compile(r"/setup$"))
