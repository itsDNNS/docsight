"""Helpers for the top navigation: views inside a group need their panel open."""


def nav_item(page, view):
    return page.locator(f'#topnav .nav-item[data-view="{view}"]')


def open_nav_group_for(page, view):
    """Open the dropdown panel that contains ``view`` (no-op for top-level entries)."""
    panel = nav_item(page, view).locator('xpath=ancestor::div[contains(@class, "topnav-panel")]')
    if panel.count() and panel.is_hidden():
        page.locator(f'#{panel.get_attribute("aria-labelledby")}').click()
    return nav_item(page, view)


def open_view(page, view):
    """Navigate like a user: open the containing group if needed, then pick the view."""
    open_nav_group_for(page, view).click()
