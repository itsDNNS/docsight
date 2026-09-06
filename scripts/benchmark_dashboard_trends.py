#!/usr/bin/env python3
"""Compare real DOCSight sources using one isolated synthetic input database.

Example (use this script and interpreter for BOTH source trees):
  .venv/bin/python scripts/benchmark_dashboard_trends.py \
    --repo /path/to/baseline --repo /path/to/changed \
    --seed-dir /tmp/docsight-signal-seed --output /tmp/trends.json

See scripts/benchmark_dashboard_trends.md for measurement scope and flags.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

SCRIPT = Path(__file__).resolve()
MARKER = 'docsight-synthetic-trends-v1'


def configure_source(repo):
    # Never inherit application credentials, configured data directories or URLs.
    allowed = {'PATH', 'HOME', 'TMPDIR', 'TEMP', 'SYSTEMROOT', 'LANG'}
    for key in list(os.environ):
        if key not in allowed:
            del os.environ[key]
    os.environ['TZ'] = 'UTC'
    if hasattr(time, 'tzset'):
        time.tzset()
    sys.path.insert(0, str(repo))
    os.chdir(repo)
    # Only local benchmark HTTP connections are allowed, even if a module tries
    # to use an inherited integration. No collectors are constructed or started.
    def audit(event, args):
        if event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1', '::1', 'localhost', None):
            raise RuntimeError('Benchmark blocked outbound DNS lookup')
        if event in ('socket.connect', 'socket.sendto'):
            address = args[-1]
            if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1'):
                raise RuntimeError('Benchmark blocked outbound connection')
    sys.addaudithook(audit)


def seed(directory, days):
    from app import analyzer
    from app.storage import SnapshotStorage
    from app.modules.speedtest.storage import SpeedtestStorage
    from app.modules.connection_monitor.storage import ConnectionMonitorStorage

    directory.mkdir(parents=True, exist_ok=False)
    db = directory / 'docsis_history.db'
    SnapshotStorage(str(db), max_days=days + 1)
    # Use shipped synthetic channel definitions through the real analyzer.
    raw = json.loads(Path('app/fixtures/demo_channels.json').read_text())
    analysis = analyzer.analyze(raw)
    analysis['analysis_meta'] = analyzer.get_analysis_metadata()
    analyzer.apply_cumulative_error_baseline(analysis, copy.deepcopy(analysis))
    anchor = datetime.now(timezone.utc).replace(microsecond=0)
    count = days * 288
    with sqlite3.connect(db) as conn:
        for i in range(count):
            stamp = anchor - timedelta(seconds=(count - 1 - i) * 300 + 60)
            summary = dict(analysis['summary'])
            summary.update(ds_power_avg=round(2 + math.sin(i / 17), 2),
                           us_power_avg=round(42 + math.cos(i / 31), 2),
                           ds_snr_avg=round(37 + math.sin(i / 23), 2),
                           ds_correctable_errors=i * 250,
                           ds_uncorrectable_errors=i * 3)
            conn.execute('INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?, ?, ?, ?)',
                         (stamp.strftime('%Y-%m-%dT%H:%M:%SZ'), json.dumps(summary),
                          json.dumps(analysis['ds_channels']), json.dumps(analysis['us_channels'])))
    SpeedtestStorage(str(db))
    with sqlite3.connect(db) as conn:
        conn.executemany('INSERT INTO speedtest_results (id, timestamp, download_mbps, upload_mbps, ping_ms) VALUES (?, ?, ?, ?, ?)',
                         [(i + 1, (anchor - timedelta(hours=i * 3 + 1)).strftime('%Y-%m-%dT%H:%M:%SZ'), 900 + i, 49, 12) for i in range(8)])
    cm = ConnectionMonitorStorage(str(directory / 'connection_monitor.db'))
    for target in range(2):
        target_id = cm.create_target(f'Synthetic target {target}', '192.0.2.' + str(target + 1))
        cm.save_samples([{'target_id': target_id, 'timestamp': anchor.timestamp() - 86400 + 5 * i + 1,
                          'latency_ms': round(15 + 4 * math.sin(i / 29), 2), 'timeout': 0, 'probe_method': 'icmp'}
                         for i in range(17280)])
    manifest = {'marker': MARKER, 'anchor': anchor.isoformat(), 'days': days, 'snapshots': count,
                'visible_snapshots': 288, 'connection_samples': 34560,
                'summary_bytes': len(json.dumps(summary).encode()),
                'large_fields_bytes': {key: len(json.dumps(summary.get(key)).encode()) for key in
                                       ('signal_families', 'error_baseline', 'error_counter_coverage')}}
    # Checkpoint input files once; every measured source gets fresh copies.
    for path in directory.glob('*.db'):
        with sqlite3.connect(path) as conn:
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        manifest.setdefault('sha256', {})[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / 'seed.json').write_text(json.dumps(manifest, indent=2))
    return manifest


def stats(values):
    return {'first': values[0], 'warm': values[1:], 'warm_median': statistics.median(values[1:]),
            'warm_min': min(values[1:]), 'warm_max': max(values[1:]),
            'warm_stdev': statistics.pstdev(values[1:])}


def timed(call):
    started = time.perf_counter()
    value = call()
    return (time.perf_counter() - started) * 1000, value


@contextmanager
def running_http(app):
    from waitress import create_server
    server = create_server(app, host='127.0.0.1', port=0, threads=4)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.effective_port}'
    finally:
        # Close sockets on the event-loop thread, avoiding a select/close race.
        server.trigger.pull_trigger(lambda: server.asyncore.close_all(map=server._map))
        thread.join(timeout=10)
        server.task_dispatcher.shutdown()
        if thread.is_alive():
            raise RuntimeError('Benchmark HTTP server did not stop')


def measure(args):
    from app.app_factory import create_app, default_module_loader_factory
    from app.config import ConfigManager
    from app.runtime import get_runtime
    from app.storage import SnapshotStorage
    import app.tz as tz
    from app.blueprints import data_bp

    manifest = json.loads((args.seed_dir / 'seed.json').read_text())
    if manifest['marker'] != MARKER:
        raise ValueError('Not a synthetic benchmark seed')
    for name, expected in manifest['sha256'].items():
        if hashlib.sha256((args.seed_dir / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Seed database changed: ' + name)
    anchor = datetime.fromisoformat(manifest['anchor'])
    class WindowClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return anchor.astimezone(tz) if tz else anchor.replace(tzinfo=None)
    # Fix only rolling-window clocks, never performance clocks or API results.
    tz.datetime = WindowClock
    data_bp.datetime = WindowClock
    with tempfile.TemporaryDirectory(prefix='docsight-trends-run-') as temporary:
        data_dir = Path(temporary)
        for path in args.seed_dir.glob('*.db'):
            if args.modules == 'disabled' and path.name == 'connection_monitor.db':
                continue
            shutil.copy2(path, data_dir / path.name)
        db = data_dir / 'docsis_history.db'
        config = ConfigManager(str(data_dir))
        config.save({'modem_type': 'generic', 'timezone': 'UTC', 'update_check_enabled': False,
                     'demo_mode': False, 'poll_interval': 86400})
        storage = SnapshotStorage(str(db), max_days=manifest['days'] + 1)
        storage.set_timezone('UTC')
        loader = default_module_loader_factory(config, search_paths=[]) if args.modules == 'enabled' else None
        app = create_app(config_manager=config, storage=storage, module_loader_factory=loader, environ={})
        runtime = get_runtime(app)
        latest = storage.get_latest_snapshot()
        runtime.update_state(analysis=latest, poll_interval=86400,
                             device_info={'model': 'Synthetic benchmark modem'},
                             connection_info={'max_downstream_kbps': 1000000, 'max_upstream_kbps': 50000})
        with running_http(app) as base:
            updated = hasattr(storage, 'get_signal_summary_since')
            signal_path = '/api/trends/signal?range=1d' if updated else '/api/trends?range=1d'
            def http(path):
                with urllib.request.urlopen(base + path, timeout=120) as response:
                    return response.read()
            result = {'repo': str(args.repo[0]), 'modules': args.modules, 'updated_signal_path': updated,
                      'seed': manifest, 'python': sys.version, 'platform': platform.platform(),
                      'waitress_threads': 4, 'transport': 'loopback HTTP, no proxy or compression',
                      'first_run': 'ordinary first measurement; OS/SQLite caches are not controlled',
                      'storage_ms': {}, 'api': {}}
            for name, call in [('legacy', lambda: storage.get_summary_since(24))] + (
                    [('signal', lambda: storage.get_signal_summary_since(24))] if updated else []):
                values = [timed(call) for _ in range(args.runs + 1)]
                result['storage_ms'][name] = {**stats([v[0] for v in values]), 'rows': len(values[-1][1])}
            for name, path in [('render_critical', signal_path), ('legacy', '/api/trends?range=1d')]:
                values = [timed(lambda: http(path)) for _ in range(args.runs + 1)]
                result['api'][name] = {'ms': stats([v[0] for v in values]),
                                       'bytes': len(values[-1][1]), 'rows': len(json.loads(values[-1][1]))}
            # Measure real four-thread contention including the retained legacy work.
            parallel = []
            for _ in range(args.runs + 1):
                barrier = threading.Barrier(args.parallel)
                def cycle(_):
                    barrier.wait()
                    started = time.perf_counter()
                    if updated:
                        critical_ms, body = timed(lambda: http(signal_path))
                        legacy_ms, legacy_body = timed(lambda: http('/api/trends?range=1d'))
                        return {'critical_ms': critical_ms, 'legacy_ms': legacy_ms,
                                'total_ms': (time.perf_counter() - started) * 1000, 'bytes': len(body) + len(legacy_body)}
                    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                        both = list(pool.map(lambda path: timed(lambda: http(path)),
                                             ['/api/trends?range=1d', '/api/trends']))
                    return {'critical_ms': both[0][0], 'legacy_ms': both[1][0],
                            'total_ms': (time.perf_counter() - started) * 1000,
                            'bytes': sum(len(v[1]) for v in both)}
                with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
                    parallel.append(list(pool.map(cycle, range(args.parallel))))
            result['parallel_dashboard_api_cycles'] = parallel
            result['browser'] = browser_measure(base, anchor, args)
            return result


def browser_measure(base, anchor, args):
    from playwright.sync_api import sync_playwright
    probe_js = SCRIPT.with_name('dashboard_trends_probe.js').read_text()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        result = {'chromium': browser.version, 'viewport': [1440, 1000], 'runs': [], 'parallel_pages': []}
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, timezone_id='UTC', service_workers='block')
        context.add_init_script(probe_js)
        context.add_init_script('''(() => { const Original = Date; const anchor = %d;
            window.Date = class extends Original { constructor(...args) { super(...(args.length ? args : [anchor])); }
                static now() { return anchor; } }; })();''' % int(anchor.timestamp() * 1000))
        # Fail closed if any browser script attempts a non-local request. Actual
        # local API and HTML responses are always supplied by the real server.
        outbound = []
        def guard(route):
            if route.request.url.startswith(base + '/'):
                route.continue_()
            else:
                outbound.append(route.request.url)
                route.abort()
        context.route('**/*', guard)

        def finish(page):
            deadline = time.monotonic() + 120
            while not page.evaluate('() => dashboardTrendsProbe.paints.length > 0'):
                if time.monotonic() >= deadline:
                    raise RuntimeError('No actual Hero curve detected: ' + json.dumps(page.evaluate(
                        '() => ({url: location.href, charts: dashboardTrendsProbe.charts, body: document.body.innerText.slice(0, 1000)})')))
                page.wait_for_timeout(20)
            page.wait_for_load_state('networkidle', timeout=120000)
            return page.evaluate('''() => {
                const resources = performance.getEntriesByType('resource');
                const nav = performance.getEntriesByType('navigation')[0];
                const trends = resources.filter(r => r.name.includes('/api/trends'));
                const signal = trends.find(r => r.name.includes('/trends/signal')) || trends.find(r => r.name.includes('range=1d'));
                const paint = dashboardTrendsProbe.paints[0];
                return {curve_paint_ms: paint.time, signal_to_curve_ms: paint.time - signal.startTime,
                    curve_points: paint.points, curve_colored_pixels: paint.coloredPixels,
                    dom_content_loaded_ms: nav.domContentLoadedEventEnd, load_ms: nav.loadEventEnd,
                    all_requests_finished_ms: Math.max(nav.responseEnd, ...resources.map(r => r.responseEnd)),
                    request_count: resources.length + 1,
                    decoded_bytes: nav.decodedBodySize + resources.reduce((sum,r) => sum+r.decodedBodySize,0),
                    transferred_bytes: nav.transferSize + resources.reduce((sum,r) => sum+r.transferSize,0),
                    trends: trends.map(r => ({url: new URL(r.name).pathname + new URL(r.name).search,
                        start_ms:r.startTime, ttfb_ms:r.responseStart-r.requestStart, duration_ms:r.duration,
                        decoded_bytes:r.decodedBodySize, transferred_bytes:r.transferSize})),
                    active_hero_charts: dashboardTrendsProbe.charts.filter(c => !c.destroyed).length};
            }''')
        for _ in range(args.browser_runs + 1):
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base, wait_until='domcontentloaded', timeout=120000)
            measurement = finish(page)
            measurement['page_errors'] = errors
            result['runs'].append(measurement)
            page.close()
        # Fire all navigations before waiting; every page executes its original
        # or updated frontend against the same four Waitress worker threads.
        pages = [context.new_page() for _ in range(args.parallel)]
        for page in pages:
            page.goto(base, wait_until='commit', timeout=120000)
        result['parallel_pages'] = [finish(page) for page in pages]
        for key in ('curve_paint_ms', 'signal_to_curve_ms', 'all_requests_finished_ms', 'load_ms'):
            result[key] = stats([run[key] for run in result['runs']])
        result['blocked_outbound'] = outbound
        browser.close()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repo', type=Path, action='append', required=True)
    parser.add_argument('--seed-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('dashboard-trends-benchmark.json'))
    parser.add_argument('--runs', type=int, default=5, help='Warm storage/API/stress runs after one first run')
    parser.add_argument('--browser-runs', type=int, default=3, help='Warm browser runs after one first run')
    parser.add_argument('--parallel', type=int, default=4, help='Concurrent dashboards; Waitress always has four threads')
    parser.add_argument('--days', type=int, default=92)
    parser.add_argument('--modules', choices=['enabled', 'disabled', 'both'], default='both')
    parser.add_argument('--worker', choices=['seed', 'measure'], help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.repo = [repo.resolve() for repo in args.repo]
    args.seed_dir = args.seed_dir.resolve()
    args.output = args.output.resolve()
    if min(args.runs, args.browser_runs, args.parallel, args.days) < 1:
        parser.error('run counts, parallelism and days must be positive')
    if args.worker:
        configure_source(args.repo[0])
        result = seed(args.seed_dir, args.days) if args.worker == 'seed' else measure(args)
        args.output.write_text(json.dumps(result, indent=2))
        return
    def child(repo, kind, output, modules='enabled'):
        command = [sys.executable, str(SCRIPT), '--worker', kind, '--repo', str(repo),
                   '--seed-dir', str(args.seed_dir), '--output', str(output), '--modules', modules,
                   '--runs', str(args.runs), '--browser-runs', str(args.browser_runs),
                   '--parallel', str(args.parallel), '--days', str(args.days)]
        subprocess.run(command, check=True)
    with tempfile.TemporaryDirectory(prefix='docsight-trends-results-') as temporary:
        part = Path(temporary) / 'part.json'
        if not args.seed_dir.exists():
            child(args.repo[0], 'seed', part)
        results = []
        for repo in args.repo:
            for modules in (['enabled', 'disabled'] if args.modules == 'both' else [args.modules]):
                print(f'Measuring {repo} ({modules} modules)', flush=True)
                child(repo, 'measure', part, modules)
                results.append(json.loads(part.read_text()))
                args.output.write_text(json.dumps(results, indent=2))
        print(f'Report: {args.output}')


if __name__ == '__main__':
    main()
