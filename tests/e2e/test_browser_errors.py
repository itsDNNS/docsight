"""The browser error collector catches what it should and lets handled failures pass."""

import pytest

from tests.e2e.support.browser_errors import BrowserErrors


@pytest.mark.allow_browser_errors("the test plants errors to see them collected")
def test_a_planted_error_and_console_error_are_collected(browser, live_server):
    collector = BrowserErrors()
    context = collector.watch_context(browser.new_context())
    page = context.new_page()
    page.goto(f"{live_server}/?lang=en", wait_until="networkidle")
    page.evaluate("setTimeout(() => { throw new Error('planted failure'); })")
    page.evaluate("console.error('planted console error')")
    page.evaluate("fetch('/api/does-not-exist').catch(() => {})")
    page.wait_for_timeout(500)
    context.close()

    assert any("planted failure" in error for error in collector.errors)
    assert any("planted console error" in error for error in collector.errors)
    # A 404 response is logged by the browser, but it is not a JavaScript fault.
    assert not any("does-not-exist" in error for error in collector.errors)


@pytest.mark.allow_browser_errors("the test checks what the collector records")
def test_a_request_aborted_by_leaving_the_page_is_not_an_error(browser, live_server):
    collector = BrowserErrors()
    context = collector.watch_context(browser.new_context())
    page = context.new_page()
    page.goto(f"{live_server}/?lang=en", wait_until="networkidle")
    # A reload aborts the page's open requests, and a view logs the rejected fetch
    # while the old page goes away.
    page.evaluate("addEventListener('pagehide', () => console.error('view fetch error: TypeError: Failed to fetch'))")
    page.reload(wait_until="networkidle")
    page.evaluate("console.error('later fetch error: TypeError: Failed to fetch')")
    context.close()

    # The same message on a page that is not being left still counts.
    assert collector.errors == [e for e in collector.errors if "later fetch error" in e]
    assert len(collector.errors) == 1
