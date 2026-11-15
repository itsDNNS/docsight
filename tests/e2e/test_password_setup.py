"""A fresh install stays locked until the first visitor after start sets the admin password."""

import re

from playwright.sync_api import expect


def test_the_first_visit_sets_the_admin_password(page, password_setup_server):
    page.goto(password_setup_server)
    expect(page).to_have_url(re.compile(r"/password-setup$"))
    page.get_by_label("New admin password").fill("correct horse")
    page.get_by_label("Repeat password").fill("correct hose")
    page.get_by_role("button", name="Set password and continue").click()
    expect(page.get_by_role("alert")).to_contain_text("do not match")

    page.get_by_label("New admin password").fill("correct horse")
    page.get_by_label("Repeat password").fill("correct horse")
    page.get_by_role("button", name="Set password and continue").click()

    # Signed in, the fresh install continues with the first-run setup.
    expect(page).to_have_url(re.compile(r"/setup$"))
