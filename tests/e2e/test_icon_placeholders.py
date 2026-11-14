"""Icon placeholders reserve the size of the icon that replaces them."""

import pytest

# Wraps lucide.createIcons: each visible placeholder is measured and tagged
# before the swap; lucide copies the tag onto the SVG, which is measured after.
PROBE = """
(() => {
    window.__iconShifts = [];
    let api;
    Object.defineProperty(window, 'lucide', {
        configurable: true,
        get() { return api; },
        set(value) {
            const original = value.createIcons;
            value.createIcons = function(options) {
                const before = new Map();
                document.querySelectorAll('[data-lucide]').forEach((node, index) => {
                    const box = node.getBoundingClientRect();
                    if (!node.getClientRects().length) return;
                    const id = 'probe-' + (window.__iconProbe = (window.__iconProbe || 0) + 1);
                    node.setAttribute('data-icon-probe', id);
                    before.set(id, {name: node.getAttribute('data-lucide'), w: box.width, h: box.height});
                });
                const result = original.apply(this, arguments);
                before.forEach((size, id) => {
                    const svg = document.querySelector('svg[data-icon-probe="' + id + '"]');
                    if (!svg) return;
                    const box = svg.getBoundingClientRect();
                    if (Math.abs(box.width - size.w) > 0.5 || Math.abs(box.height - size.h) > 0.5) {
                        window.__iconShifts.push(size.name + ' ' + size.w + 'x' + size.h + ' -> ' + box.width + 'x' + box.height);
                    }
                    svg.removeAttribute('data-icon-probe');
                });
                return result;
            };
            api = value;
        },
    });
})();
"""


@pytest.mark.parametrize("path", ["/", "/settings"])
def test_icon_placeholders_keep_the_icon_size(page, live_server, path):
    page.add_init_script(PROBE)
    page.goto(live_server + path)
    page.wait_for_load_state("networkidle")
    assert page.evaluate("window.__iconProbe") > 10
    shifts = page.evaluate("window.__iconShifts")
    assert shifts == [], "\n".join(shifts)
