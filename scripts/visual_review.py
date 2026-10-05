#!/usr/bin/env python3
"""Render DOCSight views for a visual review and compare two renderings.

``capture`` opens every navigation view and every settings section of a running
DOCSight instance in dark and light mode at desktop and phone size, and saves a
full-page screenshot plus the computed style of every visible element. With
``--password`` it also captures the login page and signs in with it.

``compare`` reports pixel and style differences between two captures (for
example ``main`` and a pull request) as diff images and a Markdown summary.

Both builds should run in demo mode with the same ``DOCSIGHT_DEMO_SEED`` and
``DOCSIGHT_DEMO_NOW``, so their demo data match, and be captured with ``--now``
set to that same time, so the browser clocks agree with the seeded history.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 393, "height": 852}}
THEMES = ("dark", "light")
STYLE_PROPERTIES = (
    "display", "position", "width", "height", "color", "background-color", "background-image",
    "border-top-color", "border-top-width", "border-top-style", "border-radius", "box-shadow",
    "font-family", "font-size", "font-weight", "line-height", "letter-spacing", "text-transform",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
    "margin-top", "margin-right", "margin-bottom", "margin-left", "gap", "opacity",
)
# Text that follows the server clock (times relative to "now"). Both captures
# replace it with the same placeholder, so text width and wrapping stay equal.
CLOCK_TEXT_SELECTORS = (
    ".cs-axis-ticks > span",  # status track time axis
    ".evidence-item-meta .evidence-muted",  # evidence timestamps
)
# Timestamps of live polls: each server polls at its own second after the seeded
# history (which ends at the pinned DOCSIGHT_DEMO_NOW, equal to --now).
LIVE_TIMESTAMP_SELECTORS = (".correlation-cell-timestamp",)
# A pixel counts as changed when any channel differs by more than this (0-255).
PIXEL_TOLERANCE = 24
STILL_CSS = """
*, *::before, *::after {
    animation: none !important;
    transition: none !important;
    caret-color: transparent !important;
}
"""

# Each kind of page: the element that holds the captured content, and its persistent chrome.
DASHBOARD = {"root": ".view.active", "shell": ".topnav"}
# The section index; older builds used a sidebar, and a comparison may capture either.
SETTINGS = {"root": ".settings-panel.active", "shell": "#settings-index, #settings-sidebar"}
LOGIN = {"root": "body", "shell": None}

READY_JS = """root => {
    const el = document.querySelector(root);
    if (!el) return false;
    const empty = [...el.querySelectorAll('.view-empty')].some(node => node.getClientRects().length);
    return empty || el.innerText.trim().length > 40;
}"""

STYLE_JS = """([props, root, shell]) => {
    const keyOf = el => {
        if (el.id) return '#' + el.id;
        const parent = el.parentElement;
        if (!parent) return el.tagName.toLowerCase();
        const index = Array.prototype.indexOf.call(parent.children, el) + 1;
        return keyOf(parent) + '>' + el.tagName.toLowerCase() + ':' + index;
    };
    const collect = root => {
        const out = {};
        if (!root) return out;
        for (const el of [root, ...root.querySelectorAll('*')]) {
            if (!el.getClientRects().length) continue;
            const style = getComputedStyle(el);
            out[keyOf(el)] = props.map(name => style.getPropertyValue(name));
        }
        return out;
    };
    return {
        view: collect(document.querySelector(root)),
        shell: shell ? collect(document.querySelector(shell)) : {},
    };
}"""


MASK_CLOCK_TEXT_JS = """([selectors, liveSelectors]) => {
    for (const el of document.querySelectorAll(selectors.join(','))) el.textContent = '00:00';
    // The browser clock is frozen at the end of the seeded history.
    for (const el of document.querySelectorAll(liveSelectors.join(','))) {
        const time = Date.parse(el.textContent);
        if (!Number.isNaN(time) && time >= Date.now()) el.textContent = '00:00';
    }
    // "Deviating since" bars are placed relative to the current time; pin their geometry.
    for (const el of document.querySelectorAll('.cs-since')) {
        el.style.left = '50%';
        el.style.width = '50%';
    }
}"""

SHAPE_JS = """root => {
    const el = document.querySelector(root);
    return el ? [el.querySelectorAll('*').length, el.scrollHeight, document.body.scrollHeight] : null;
}"""


class _OpenRequests:
    """Requests the page has started and not yet finished. Views fetch their data
    when they are switched to, long after the page reached its load state."""

    def __init__(self, page):
        self.pending = set()
        page.on("request", self._started)
        page.on("requestfinished", self._ended)
        page.on("requestfailed", self._ended)

    def _started(self, request):
        self.pending.add(request)

    def _ended(self, request):
        self.pending.discard(request)


def _wait_until_settled(page, requests, root=DASHBOARD["root"], checks=3, interval_ms=300, limit_ms=15000):
    """Views fill in after their requests and charts draw on the next frames; wait
    until no request is open and the view's element count and height stop changing."""
    page.wait_for_function(READY_JS, arg=root, timeout=20000)
    previous, stable, waited = None, 0, 0
    while waited < limit_ms:
        shape = page.evaluate(SHAPE_JS, root)
        stable = stable + 1 if shape == previous and not requests.pending else 0
        if stable >= checks:
            return
        previous = shape
        page.wait_for_timeout(interval_ms)
        waited += interval_ms
    raise TimeoutError("view did not settle")


def _views(page):
    return page.eval_on_selector_all(
        ".topnav [data-view]", "nodes => [...new Set(nodes.map(node => node.dataset.view))]")


def _settings_sections(page):
    return page.eval_on_selector_all(
        "#settings-index [data-section], #settings-sidebar .nav-item[data-section]",
        "nodes => [...new Set(nodes.map(node => node.dataset.section))]")


def _snapshot(page, requests, out: Path, name: str, surface: dict) -> None:
    _wait_until_settled(page, requests, surface["root"])
    page.evaluate(MASK_CLOCK_TEXT_JS, [list(CLOCK_TEXT_SELECTORS), list(LIVE_TIMESTAMP_SELECTORS)])
    page.evaluate("() => document.fonts.ready")
    page.screenshot(path=str(out / f"{name}.png"), full_page=True, animations="disabled")
    styles = page.evaluate(STYLE_JS, [list(STYLE_PROPERTIES), surface["root"], surface["shell"]])
    (out / f"{name}.json").write_text(json.dumps(styles, sort_keys=True), encoding="utf-8")


def capture(url: str, out: Path, now: datetime, password: str | None = None) -> int:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    count = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for theme in THEMES:
            for size, viewport in VIEWPORTS.items():
                context = browser.new_context(
                    viewport=viewport, color_scheme=theme, reduced_motion="reduce",
                    locale="en-US", timezone_id="UTC",
                )
                context.clock.set_fixed_time(now)
                page = context.new_page()
                requests = _OpenRequests(page)
                base = url.rstrip("/")
                suffix = f"--{theme}--{size}"
                if password:
                    page.goto(base + "/login?lang=en", wait_until="networkidle")
                    page.add_style_tag(content=STILL_CSS)
                    _snapshot(page, requests, out, "login" + suffix, LOGIN)
                    count += 1
                    page.fill("#login-password", password)
                    with page.expect_navigation(wait_until="networkidle"):
                        page.press("#login-password", "Enter")
                page.goto(base + "/?lang=en", wait_until="networkidle")
                page.add_style_tag(content=STILL_CSS)
                for view in _views(page):
                    page.evaluate("view => switchView(view)", view)
                    _snapshot(page, requests, out, view + suffix, DASHBOARD)
                    count += 1
                page.goto(base + "/settings?lang=en", wait_until="networkidle")
                page.add_style_tag(content=STILL_CSS)
                for section in _settings_sections(page):
                    page.evaluate("id => switchSection(id)", section)
                    _snapshot(page, requests, out, f"settings-{section}{suffix}", SETTINGS)
                    count += 1
                context.close()
        browser.close()
    return count


def _pixel_diff(base: Path, head: Path, diff_path: Path) -> dict:
    from PIL import Image, ImageChops

    before = Image.open(base).convert("RGB")
    after = Image.open(head).convert("RGB")
    width, height = min(before.width, after.width), min(before.height, after.height)
    delta = ImageChops.difference(before.crop((0, 0, width, height)), after.crop((0, 0, width, height)))
    mask = delta.convert("L").point(lambda value: 255 if value > PIXEL_TOLERANCE else 0)
    changed = mask.histogram()[255]
    if changed:
        highlight = after.crop((0, 0, width, height)).copy()
        highlight.paste((255, 0, 64), mask=mask)
        highlight.save(diff_path)
    return {
        "changed_ratio": changed / float(width * height),
        "size_before": [before.width, before.height],
        "size_after": [after.width, after.height],
    }


def _style_diff(base: Path, head: Path) -> dict:
    before = json.loads(base.read_text(encoding="utf-8"))
    after = json.loads(head.read_text(encoding="utf-8"))
    changes = []
    added = removed = 0
    for part in ("shell", "view"):
        old, new = before.get(part, {}), after.get(part, {})
        added += len(new.keys() - old.keys())
        removed += len(old.keys() - new.keys())
        for key in sorted(old.keys() & new.keys()):
            for prop, a, b in zip(STYLE_PROPERTIES, old[key], new[key]):
                if a != b:
                    changes.append(f"{key} {prop}: {a} -> {b}")
    return {"changed": changes, "added": added, "removed": removed}


def compare(base_dir: Path, head_dir: Path, out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    rows, unchanged = [], 0
    names = sorted({path.stem for path in head_dir.glob("*.png")} | {path.stem for path in base_dir.glob("*.png")})
    for name in names:
        base_png, head_png = base_dir / f"{name}.png", head_dir / f"{name}.png"
        if not base_png.exists() or not head_png.exists():
            rows.append((name, "new view" if head_png.exists() else "view removed", "", ""))
            continue
        pixels = _pixel_diff(base_png, head_png, out / f"{name}.diff.png")
        styles = _style_diff(base_dir / f"{name}.json", head_dir / f"{name}.json")
        size_note = "" if pixels["size_before"] == pixels["size_after"] else (
            f" (height {pixels['size_before'][1]} -> {pixels['size_after'][1]} px)")
        style_count = len(styles["changed"]) + styles["added"] + styles["removed"]
        if pixels["changed_ratio"] < 0.0005 and not style_count and not size_note:
            unchanged += 1
            continue
        sample = "; ".join(styles["changed"][:3])
        rows.append((name, f"{pixels['changed_ratio']:.2%}{size_note}",
                     f"{len(styles['changed'])} changed, {styles['added']} added, {styles['removed']} removed",
                     sample))
    lines = ["## Visual review", "",
             f"{len(names)} renderings compared, {unchanged} without visible or style changes.", ""]
    if rows:
        lines += ["| View · theme · size | Pixels changed | Element styles | Examples |", "|---|---|---|---|"]
        lines += [f"| `{name}` | {pixels} | {styles} | {sample.replace('|', '/')} |" for name, pixels, styles, sample in rows]
        lines += ["", "Screenshots and highlighted differences are in the `visual-review` artifact."]
    summary = "\n".join(lines) + "\n"
    (out / "summary.md").write_text(summary, encoding="utf-8")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture", help="render every view and settings section of a running instance")
    cap.add_argument("--url", required=True)
    cap.add_argument("--out", required=True, type=Path)
    cap.add_argument("--now", help="ISO time for the browser clock (default: now, to the minute)")
    cap.add_argument("--password", help="admin password: also capture the login page, then sign in")
    cmp_ = sub.add_parser("compare", help="compare two captures")
    cmp_.add_argument("--base", required=True, type=Path)
    cmp_.add_argument("--head", required=True, type=Path)
    cmp_.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "capture":
        now = (datetime.fromisoformat(args.now) if args.now
               else datetime.now(timezone.utc).replace(second=0, microsecond=0))
        count = capture(args.url, args.out, now, args.password)
        print(f"captured {count} renderings into {args.out}")
        return 0 if count else 1
    print(compare(args.base, args.head, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
