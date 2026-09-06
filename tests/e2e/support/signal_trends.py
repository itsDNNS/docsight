"""Controlled network and real-canvas helpers for signal lifecycle tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic

PROBE = Path(__file__).resolve().parents[3] / 'scripts/dashboard_trends_probe.js'


def rows(value=1):
    now = datetime.now(timezone.utc)
    return [{'timestamp': (now - timedelta(minutes=10-i)).strftime('%Y-%m-%dT%H:%M:%SZ'),
             'ds_power_avg': value + i, 'us_power_avg': 42 + i, 'ds_snr_avg': 36 + i,
             'ds_uncorrectable_errors': i * i, 'speedtest_download': 100 + i * i,
             'connection_monitor_latency_ms': 10 + i * i} for i in range(3)]


def start(page, url, signal=None, legacy=None):
    page.add_init_script(path=PROBE)
    requests = {'signal': [], 'legacy': []}
    def handle(route):
        kind = 'signal' if '/trends/signal' in route.request.url else 'legacy'
        requests[kind].append(route)
        handler = signal if kind == 'signal' else legacy
        if handler:
            handler(route)
        else:
            route.fulfill(json=rows())
    page.route('**/api/trends**', handle)
    page.route('**/api/poll', lambda route: route.fulfill(json={'success': True}))
    page.goto(url, wait_until='domcontentloaded')
    return requests


def wait_count(page, items, count):
    deadline = monotonic() + 10
    while len(items) < count and monotonic() < deadline:
        page.wait_for_timeout(20)
    assert len(items) == count


def painted(page, value=None):
    wait_js(page, '''value => dashboardTrendsProbe.paints.some(p => value == null || p.first === value)''', value)


def spark_pixels(page, selector):
    return page.locator(selector).evaluate('''c => Array.from(c.getContext('2d').getImageData(0,0,c.width,c.height).data).some((v,i) => i%4===3 && v>0)''')


def click_refresh(page):
    page.locator('.hero-refresh-button').click()


def toggle_theme(page):
    page.evaluate('''() => {
        const toggle = document.getElementById('theme-toggle-sidebar');
        toggle.checked = !toggle.checked;
        toggle.dispatchEvent(new Event('change'));
    }''')


def wait_js(page, predicate, arg=None):
    # Runtime.evaluate avoids Playwright's string-eval polling under strict CSP.
    deadline = monotonic() + 10
    while not page.evaluate(predicate, arg):
        assert monotonic() < deadline, predicate
        page.wait_for_timeout(20)
