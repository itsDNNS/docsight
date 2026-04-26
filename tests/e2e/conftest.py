"""E2E test fixtures — live server via multiprocessing + waitress."""

import multiprocessing
import os
import socket
import time

import pytest
import requests

_MP_CTX = multiprocessing.get_context("spawn")
_WAITRESS_KWARGS = {"threads": 2, "_quiet": True, "asyncore_use_poll": True}


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """WSL2-friendly Chromium launch arguments to prevent flakiness."""
    return {
        **browser_type_launch_args,
        "args": [
            *(browser_type_launch_args.get("args", [])),
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--no-sandbox",
        ],
    }


def _find_free_port():
    """Return an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(data_dir, port, admin_password=None):
    """Boot a real DOCSight instance inside a child process."""
    import os

    os.environ["DATA_DIR"] = data_dir
    os.environ["DEMO_MODE"] = "1"
    os.environ["LOG_LEVEL"] = "WARNING"

    from app.config import ConfigManager
    from app.storage import SnapshotStorage
    from app import web, analyzer
    from app.event_detector import EventDetector
    from app.collectors.demo import DemoCollector  # noqa: F811

    cfg = ConfigManager(data_dir)
    save_data = {"demo_mode": True, "modem_type": "demo"}
    if admin_password:
        save_data["admin_password"] = admin_password
    cfg.save(save_data)

    db_path = os.path.join(data_dir, "docsis_history.db")
    storage = SnapshotStorage(db_path, max_days=7)
    storage.set_timezone("UTC")

    web.init_storage(storage)
    web.init_config(cfg)
    web.init_collector(None)
    web.init_collectors([])

    # Load modules so templates render correctly
    from app.module_loader import ModuleLoader

    builtin_path = os.path.join(os.path.dirname(__file__), "..", "..", "app", "modules")
    builtin_path = os.path.abspath(builtin_path)
    module_loader = ModuleLoader(
        web.app, search_paths=[builtin_path], disabled_ids=set()
    )
    module_loader.load_all()
    web.init_modules(module_loader)
    web.setup_module_templates(module_loader)

    # Register module blueprints
    existing = {b.name for b in web.app.blueprints.values()}
    for mod in module_loader.get_enabled_modules():
        if hasattr(mod, "blueprint") and mod.blueprint:
            if mod.blueprint.name not in existing:
                web.app.register_blueprint(mod.blueprint)
                existing.add(mod.blueprint.name)

    # Initialize module storage tables (needed for demo data seeding)
    try:
        from app.modules.speedtest.storage import SpeedtestStorage
        SpeedtestStorage(db_path)
    except ImportError:
        pass
    try:
        from app.modules.bqm.storage import BqmStorage
        BqmStorage(db_path)
    except ImportError:
        pass
    try:
        from app.modules.bnetz.storage import BnetzStorage
        BnetzStorage(db_path)
    except ImportError:
        pass
    try:
        from app.modules.journal.storage import JournalStorage
        JournalStorage(db_path)
    except ImportError:
        pass

    # Seed demo data via DemoCollector
    event_detector = EventDetector()
    collector = DemoCollector(
        analyzer_fn=analyzer.analyze,
        event_detector=event_detector,
        storage=storage,
        mqtt_pub=None,
        web=web,
        poll_interval=300,
    )
    collector.collect()

    from waitress import serve

    serve(web.app, host="127.0.0.1", port=port, **_WAITRESS_KWARGS)


def _wait_for_server(port, timeout=150):
    """Poll /health until the server responds or timeout."""
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"Live server on port {port} did not start within {timeout}s")


@pytest.fixture(scope="session")
def _demo_data_dir(tmp_path_factory):
    """Session-scoped temp directory for the demo server."""
    return str(tmp_path_factory.mktemp("docsight_e2e"))


@pytest.fixture(scope="session")
def _auth_data_dir(tmp_path_factory):
    """Session-scoped temp directory for the auth server."""
    return str(tmp_path_factory.mktemp("docsight_e2e_auth"))


@pytest.fixture(scope="session")
def live_server(_demo_data_dir):
    """Start a DOCSight demo server (no auth) and return its base URL."""
    port = _find_free_port()
    proc = _MP_CTX.Process(
        target=_start_server,
        args=(_demo_data_dir, port),
        daemon=True,
    )
    proc.start()
    try:
        _wait_for_server(port)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.join(timeout=5)


@pytest.fixture(scope="session")
def auth_server(_auth_data_dir):
    """Start a DOCSight server with admin password and return its base URL."""
    port = _find_free_port()
    proc = _MP_CTX.Process(
        target=_start_server,
        args=(_auth_data_dir, port, "e2e-test-password"),
        daemon=True,
    )
    proc.start()
    try:
        _wait_for_server(port)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.join(timeout=5)


@pytest.fixture()
def demo_page(page, live_server):
    """Navigate to the demo server dashboard."""
    page.goto(live_server)
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture()
def settings_page(page, live_server):
    """Navigate to the settings page."""
    page.goto(f"{live_server}/settings")
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture()
def auth_page(page, auth_server):
    """Provide a page pointed at the auth-protected server."""
    return page


# ── Unconfigured server (setup wizard) ──


def _start_unconfigured_server(data_dir, port):
    """Boot a DOCSight instance that is NOT configured — shows /setup."""
    os.environ["DATA_DIR"] = data_dir
    os.environ.pop("DEMO_MODE", None)
    os.environ["LOG_LEVEL"] = "WARNING"

    from app.config import ConfigManager
    from app import web

    cfg = ConfigManager(data_dir)
    # Do NOT call cfg.save() — leave unconfigured so /setup renders

    web.init_config(cfg)
    web.init_storage(None)
    web.init_collector(None)
    web.init_collectors([])

    from waitress import serve

    serve(web.app, host="127.0.0.1", port=port, **_WAITRESS_KWARGS)


@pytest.fixture(scope="session")
def _setup_data_dir(tmp_path_factory):
    """Session-scoped temp directory for the unconfigured server."""
    return str(tmp_path_factory.mktemp("docsight_e2e_setup"))


@pytest.fixture(scope="session")
def setup_server(_setup_data_dir):
    """Start an unconfigured DOCSight server and return its base URL."""
    port = _find_free_port()
    proc = _MP_CTX.Process(
        target=_start_unconfigured_server,
        args=(_setup_data_dir, port),
        daemon=True,
    )
    proc.start()
    try:
        _wait_for_server(port)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.join(timeout=5)


@pytest.fixture()
def setup_page(page, setup_server):
    """Navigate to the unconfigured server — lands on /setup."""
    page.goto(setup_server)
    page.wait_for_load_state("networkidle")
    return page


# ── FritzBox server (segment utilization) ──


def _start_fritzbox_server(data_dir, port):
    """Boot a DOCSight instance with modem_type=fritzbox and seeded segment data."""
    import os
    from datetime import datetime, timedelta, timezone

    os.environ["DATA_DIR"] = data_dir
    os.environ["DEMO_MODE"] = "1"
    os.environ["LOG_LEVEL"] = "WARNING"

    from app.config import ConfigManager
    from app.storage import SnapshotStorage
    from app import web, analyzer
    from app.event_detector import EventDetector
    from app.collectors.demo import DemoCollector

    cfg = ConfigManager(data_dir)
    cfg.save({"demo_mode": True, "modem_type": "fritzbox"})

    db_path = os.path.join(data_dir, "docsis_history.db")
    storage = SnapshotStorage(db_path, max_days=7)
    storage.set_timezone("UTC")

    web.init_storage(storage)
    web.init_config(cfg)
    web.init_collector(None)
    web.init_collectors([])

    from app.module_loader import ModuleLoader

    builtin_path = os.path.join(os.path.dirname(__file__), "..", "..", "app", "modules")
    builtin_path = os.path.abspath(builtin_path)
    module_loader = ModuleLoader(
        web.app, search_paths=[builtin_path], disabled_ids=set()
    )
    module_loader.load_all()
    web.init_modules(module_loader)
    web.setup_module_templates(module_loader)

    existing = {b.name for b in web.app.blueprints.values()}
    for mod in module_loader.get_enabled_modules():
        if hasattr(mod, "blueprint") and mod.blueprint:
            if mod.blueprint.name not in existing:
                web.app.register_blueprint(mod.blueprint)
                existing.add(mod.blueprint.name)

    # Initialize module storage tables
    try:
        from app.modules.speedtest.storage import SpeedtestStorage
        SpeedtestStorage(db_path)
    except ImportError:
        pass
    try:
        from app.modules.bqm.storage import BqmStorage
        BqmStorage(db_path)
    except ImportError:
        pass
    try:
        from app.modules.bnetz.storage import BnetzStorage
        BnetzStorage(db_path)
    except ImportError:
        pass
    try:
        from app.modules.journal.storage import JournalStorage
        JournalStorage(db_path)
    except ImportError:
        pass

    # Seed demo data
    event_detector = EventDetector()
    collector = DemoCollector(
        analyzer_fn=analyzer.analyze,
        event_detector=event_detector,
        storage=storage,
        mqtt_pub=None,
        web=web,
        poll_interval=300,
    )
    collector.collect()

    # Seed segment utilization data (48h of samples, 1 per minute)
    from app.storage.segment_utilization import SegmentUtilizationStorage
    import random

    seg_storage = SegmentUtilizationStorage(db_path)
    now = datetime.now(timezone.utc)
    random.seed(42)
    for i in range(2880):  # 48h * 60 min
        ts = (now - timedelta(minutes=2880 - i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ds_total = 15.0 + random.uniform(-5, 25)
        us_total = 8.0 + random.uniform(-3, 15)
        ds_own = ds_total * random.uniform(0.01, 0.15)
        us_own = us_total * random.uniform(0.01, 0.10)
        seg_storage.save_at(ts, round(ds_total, 1), round(us_total, 1),
                            round(ds_own, 2), round(us_own, 2))

    from waitress import serve
    serve(web.app, host="127.0.0.1", port=port, **_WAITRESS_KWARGS)


@pytest.fixture(scope="session")
def _fritzbox_data_dir(tmp_path_factory):
    """Session-scoped temp directory for the FritzBox server."""
    return str(tmp_path_factory.mktemp("docsight_e2e_fritzbox"))


@pytest.fixture(scope="session")
def fritzbox_server(_fritzbox_data_dir):
    """Start a DOCSight server with modem_type=fritzbox and segment data."""
    port = _find_free_port()
    proc = _MP_CTX.Process(
        target=_start_fritzbox_server,
        args=(_fritzbox_data_dir, port),
        daemon=True,
    )
    proc.start()
    try:
        _wait_for_server(port)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.join(timeout=5)


@pytest.fixture()
def fritzbox_page(page, fritzbox_server):
    """Navigate to the FritzBox server dashboard."""
    page.goto(fritzbox_server)
    page.wait_for_load_state("networkidle")
    return page
