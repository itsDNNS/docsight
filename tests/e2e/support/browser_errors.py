"""Collect JavaScript errors from every page a test opens, so none goes unnoticed."""

import re

# Console errors that are not JavaScript faults. Each needs a reason.
ALLOWED_CONSOLE_ERRORS = (
    # The browser logs every non-2xx response; tests mock 4xx/5xx answers on purpose,
    # and the page handles them. A missing asset still fails the test that needs it.
    re.compile(r"^Failed to load resource: the server responded with a status of \d{3}"),
    # Network failures: tests abort requests or stop their server while the page still
    # loads. The page's handling of a failed request is tested where it matters.
    re.compile(r"^Failed to load resource: net::ERR_"),
)


class BrowserErrors:
    def __init__(self):
        self.errors = []
        self._leaving = set()

    def watch_context(self, context):
        context.on("page", self.watch_page)
        for page in context.pages:
            self.watch_page(page)
        return context

    def watch_page(self, page):
        page.on("pageerror", lambda error: self.errors.append(f"uncaught error on {page.url}: {error}"))
        page.on("console", lambda message: self._console(page, message))
        # Leaving a page (reload, navigation) aborts its open requests; the page may log that.
        page.on("request", lambda request: self._leaving.add(id(page))
                if request.is_navigation_request() and request.frame == page.main_frame else None)
        page.on("load", lambda: self._leaving.discard(id(page)))

    def _console(self, page, message):
        if message.type != "error":
            return
        if any(pattern.search(message.text) for pattern in ALLOWED_CONSOLE_ERRORS):
            return
        if id(page) in self._leaving and "Failed to fetch" in message.text:
            return
        source = (message.location or {}).get("url") or ""
        self.errors.append(f"console.error on {page.url}: {message.text}" + (f" ({source})" if source else ""))
