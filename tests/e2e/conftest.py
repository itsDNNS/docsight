"""E2E test fixtures — live server via multiprocessing + waitress."""

import multiprocessing
import os
import socket
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

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


def _not_found(environ, start_response):
    """Reject every request that escapes a mounted DOCSight application."""
    from werkzeug.wrappers import Response

    return Response("Not Found\n", status=404)(environ, start_response)


def _mounted_app(application, mount_path):
    if not mount_path:
        return application
    from werkzeug.middleware.dispatcher import DispatcherMiddleware

    return DispatcherMiddleware(
        _not_found,
        {mount_path: application},
    )


@dataclass(frozen=True)
class _ServerTarget:
    """Pickle-safe configuration for one isolated E2E server process."""

    data_dir: str
    port: int
    configured: bool = True
    admin_password: str | None = None
    demo_mode: bool = True
    modem_type: str | None = None
    mount_path: str = ""
    base_path: str | None = None
    trusted_prefix_hops: int | None = None
    production_startup: bool = False
    post_seed_callback: Callable[[str], None] | None = None


def _configure_server_environment(target: _ServerTarget) -> None:
    os.environ["DATA_DIR"] = target.data_dir
    if target.demo_mode:
        os.environ["DEMO_MODE"] = "1"
    else:
        os.environ.pop("DEMO_MODE", None)
    os.environ["LOG_LEVEL"] = "WARNING"
    os.environ.pop("BASE_PATH", None)
    os.environ.pop("REVERSE_PROXY_PREFIX", None)
    if target.base_path is not None:
        os.environ["BASE_PATH"] = target.base_path
    if target.trusted_prefix_hops is not None:
        os.environ["REVERSE_PROXY_PREFIX"] = str(target.trusted_prefix_hops)


def _configure_base_path(target: _ServerTarget, application) -> None:
    if target.base_path is None and target.trusted_prefix_hops is None:
        return
    from app.base_path import configure_base_path

    configure_base_path(application)


def _initialize_modules(web, db_path: str) -> None:
    """Load built-ins and their storage tables exactly as production-like E2E needs."""
    from app.module_loader import ModuleLoader

    builtin_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "app", "modules")
    )
    module_loader = ModuleLoader(
        web.app, search_paths=[], disabled_ids=set(), builtin_base_path=builtin_path
    )
    module_loader.load_all()
    web.init_modules(module_loader)
    web.setup_module_templates(module_loader)

    existing = {blueprint.name for blueprint in web.app.blueprints.values()}
    for module in module_loader.get_enabled_modules():
        if hasattr(module, "blueprint") and module.blueprint:
            if module.blueprint.name not in existing:
                web.app.register_blueprint(module.blueprint)
                existing.add(module.blueprint.name)

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


def _serve_server(target: _ServerTarget) -> None:
    """Boot any E2E DOCSight server variant inside a child process."""
    if target.production_startup:
        os.environ["DATA_DIR"] = target.data_dir
        os.environ["WEB_HOST"] = "127.0.0.1"
        os.environ["WEB_PORT"] = str(target.port)
        os.environ.pop("DEMO_MODE", None)
        os.environ["LOG_LEVEL"] = "WARNING"
        from app.main import main

        main()
        return

    _configure_server_environment(target)

    from app import analyzer, web
    from app.config import ConfigManager

    config = ConfigManager(target.data_dir)
    if not target.configured:
        web.init_config(config)
        web.init_storage(None)
        web.init_collector(None)
        web.init_collectors([])
    else:
        from app.collectors.demo import DemoCollector
        from app.event_detector import EventDetector
        from app.storage import SnapshotStorage

        config_data = {
            "demo_mode": target.demo_mode,
            "modem_type": target.modem_type
            or ("demo" if target.demo_mode else "generic"),
        }
        if target.admin_password:
            config_data["admin_password"] = target.admin_password
        config.save(config_data)

        db_path = os.path.join(target.data_dir, "docsis_history.db")
        storage = SnapshotStorage(db_path, max_days=7)
        storage.set_timezone("UTC")
        web.init_storage(storage)
        web.init_config(config)
        web.init_collector(None)
        web.init_collectors([])
        _initialize_modules(web, db_path)

        collector = DemoCollector(
            analyzer_fn=analyzer.analyze,
            event_detector=EventDetector(),
            storage=storage,
            mqtt_pub=None,
            web=web,
            poll_interval=300,
        )
        collector.collect()
        if target.post_seed_callback is not None:
            target.post_seed_callback(db_path)

    _configure_base_path(target, web.app)

    from waitress import serve

    serve(
        _mounted_app(web.app, target.mount_path),
        host="127.0.0.1",
        port=target.port,
        **_WAITRESS_KWARGS,
    )


def _wait_for_server(port, timeout=150, mount_path=""):
    """Poll /health until the server responds or timeout."""
    url = f"http://127.0.0.1:{port}{mount_path}/health"
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


@contextmanager
def _running_processes(
    process_specs: list[tuple[Callable[..., None], tuple]],
    readiness_targets: list[tuple[int, str]],
) -> Iterator[None]:
    """Start, await, and always terminate an isolated group of child processes."""
    processes = []
    try:
        for process_target, args in process_specs:
            process = _MP_CTX.Process(target=process_target, args=args, daemon=True)
            process.start()
            processes.append(process)
        for port, mount_path in readiness_targets:
            _wait_for_server(port, mount_path=mount_path)
        yield
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join(timeout=5)


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
    target = _ServerTarget(_demo_data_dir, port)
    with _running_processes([(_serve_server, (target,))], [(port, "")]):
        yield f"http://127.0.0.1:{port}"


@pytest.fixture(scope="session")
def auth_server(_auth_data_dir):
    """Start a DOCSight server with admin password and return its base URL."""
    port = _find_free_port()
    credential = "e2e-test-password"
    target = _ServerTarget(
        _auth_data_dir,
        port,
        admin_password=credential,
    )
    with _running_processes([(_serve_server, (target,))], [(port, "")]):
        yield f"http://127.0.0.1:{port}"


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


@pytest.fixture(scope="session")
def _configured_data_dir(tmp_path_factory):
    """Session-scoped data directory for non-demo persisted-settings tests."""
    return str(tmp_path_factory.mktemp("docsight_e2e_configured"))


@pytest.fixture(scope="session")
def configured_server(_configured_data_dir):
    """Start a configured non-demo instance with seeded dashboard data."""
    port = _find_free_port()
    target = _ServerTarget(_configured_data_dir, port, demo_mode=False)
    with _running_processes([(_serve_server, (target,))], [(port, "")]):
        yield f"http://127.0.0.1:{port}"


@pytest.fixture()
def configured_page(page, configured_server):
    """Navigate to a configured non-demo dashboard."""
    page.goto(configured_server)
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture()
def auth_page(page, auth_server):
    """Provide a page pointed at the auth-protected server."""
    return page


# ── Unconfigured server (setup wizard) ──


@pytest.fixture()
def first_run_server(tmp_path):
    """Start a fresh production-path instance for one-click activation tests."""
    port = _find_free_port()
    target = _ServerTarget(
        str(tmp_path / "first-run"),
        port,
        configured=False,
        demo_mode=False,
        production_startup=True,
    )
    with _running_processes([(_serve_server, (target,))], [(port, "")]):
        yield f"http://127.0.0.1:{port}"


@pytest.fixture(scope="session")
def _setup_data_dir(tmp_path_factory):
    """Session-scoped temp directory for the unconfigured server."""
    return str(tmp_path_factory.mktemp("docsight_e2e_setup"))


@pytest.fixture(scope="session")
def setup_server(_setup_data_dir):
    """Start an unconfigured DOCSight server and return its base URL."""
    port = _find_free_port()
    target = _ServerTarget(
        _setup_data_dir,
        port,
        configured=False,
        demo_mode=False,
    )
    with _running_processes([(_serve_server, (target,))], [(port, "")]):
        yield f"http://127.0.0.1:{port}"


@pytest.fixture()
def isolated_setup_server(tmp_path):
    """Start an unconfigured server with fresh data for one language test."""
    data_dir = str(tmp_path / "isolated-setup")
    port = _find_free_port()
    target = _ServerTarget(
        data_dir,
        port,
        configured=False,
        demo_mode=False,
    )
    with _running_processes([(_serve_server, (target,))], [(port, "")]):
        yield {
            "url": f"http://127.0.0.1:{port}",
            "data_dir": data_dir,
        }


@pytest.fixture()
def setup_page(page, setup_server):
    """Navigate to the unconfigured server — lands on /setup."""
    page.goto(setup_server)
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture(
    scope="session",
    params=["", "/docsight"],
    ids=["root-mount", "docsight-mount"],
)
def path_prefix_servers(request, tmp_path_factory):
    """Serve auth and setup apps through real root/prefix WSGI mounts."""
    mount_path = request.param
    label = "root" if not mount_path else "docsight"
    auth_port = _find_free_port()
    setup_port = _find_free_port()
    credential = "browser-contract-password"
    auth_dir = str(tmp_path_factory.mktemp(f"docsight_mount_auth_{label}"))
    setup_dir = str(tmp_path_factory.mktemp(f"docsight_mount_setup_{label}"))
    auth_target = _ServerTarget(
        auth_dir,
        auth_port,
        admin_password=credential,
        mount_path=mount_path,
    )
    setup_target = _ServerTarget(
        setup_dir,
        setup_port,
        configured=False,
        demo_mode=False,
        mount_path=mount_path,
    )
    with _running_processes(
        [
            (_serve_server, (auth_target,)),
            (_serve_server, (setup_target,)),
        ],
        [(auth_port, mount_path), (setup_port, mount_path)],
    ):
        yield {
            "mount_path": mount_path,
            "app_url": f"http://127.0.0.1:{auth_port}{mount_path}",
            "setup_url": f"http://127.0.0.1:{setup_port}{mount_path}",
            "password": credential,
        }


_NETWORK_PREFIX_CASES = [
    pytest.param(
        {
            "label": "explicit_docsight",
            "mount_path": "/docsight",
            "base_path": "/docsight",
            "trusted_prefix_hops": None,
            "forwarded_prefix_chain": None,
        },
        id="explicit-docsight-mount",
    ),
    pytest.param(
        {
            "label": "trusted_docsight",
            "mount_path": "/docsight",
            "base_path": None,
            "trusted_prefix_hops": 2,
            "forwarded_prefix_chain": "/docsight, /docsight",
        },
        id="trusted-docsight-mount",
    ),
    pytest.param(
        {
            "label": "explicit_wrapper_shape",
            "mount_path": "/api/hassio_ingress/synthetic-test-entry",
            "base_path": "/api/hassio_ingress/synthetic-test-entry",
            "trusted_prefix_hops": None,
            "forwarded_prefix_chain": None,
        },
        id="explicit-wrapper-shaped-mount",
    ),
]


class _RedactedProxyServers(dict):
    def __repr__(self) -> str:
        return "<real proxy server contract>"


@pytest.fixture(scope="session", params=_NETWORK_PREFIX_CASES)
def real_proxy_servers(request, tmp_path_factory):
    """Run DOCSight behind a separate prefix-stripping HTTP proxy process."""
    from tests.e2e.prefix_proxy import serve_prefix_proxy

    case = request.param
    auth_upstream_port = _find_free_port()
    setup_upstream_port = _find_free_port()
    auth_proxy_port = _find_free_port()
    setup_proxy_port = _find_free_port()
    credential = "network-proxy-test-password"
    label = case["label"]
    auth_dir = str(tmp_path_factory.mktemp(f"network_proxy_auth_{label}"))
    setup_dir = str(tmp_path_factory.mktemp(f"network_proxy_setup_{label}"))

    auth_target = _ServerTarget(
        auth_dir,
        auth_upstream_port,
        admin_password=credential,
        base_path=case["base_path"],
        trusted_prefix_hops=case["trusted_prefix_hops"],
    )
    setup_target = _ServerTarget(
        setup_dir,
        setup_upstream_port,
        configured=False,
        demo_mode=False,
        base_path=case["base_path"],
        trusted_prefix_hops=case["trusted_prefix_hops"],
    )
    with _running_processes(
        [
            (_serve_server, (auth_target,)),
            (_serve_server, (setup_target,)),
            (
                serve_prefix_proxy,
                (
                    auth_proxy_port,
                    auth_upstream_port,
                    case["mount_path"],
                    case["forwarded_prefix_chain"],
                ),
            ),
            (
                serve_prefix_proxy,
                (
                    setup_proxy_port,
                    setup_upstream_port,
                    case["mount_path"],
                    case["forwarded_prefix_chain"],
                ),
            ),
        ],
        [
            (auth_proxy_port, case["mount_path"]),
            (setup_proxy_port, case["mount_path"]),
        ],
    ):
        yield _RedactedProxyServers(
            {
                "mount_path": case["mount_path"],
                "app_url": (
                    f"http://127.0.0.1:{auth_proxy_port}{case['mount_path']}"
                ),
                "setup_url": (
                    f"http://127.0.0.1:{setup_proxy_port}{case['mount_path']}"
                ),
                "password": credential,
            }
        )


# ── FritzBox server (segment utilization) ──


def _seed_fritzbox_segment_data(db_path: str) -> None:
    """Seed 48 hours of deterministic one-minute segment utilization samples."""
    import random
    from datetime import datetime, timedelta, timezone

    from app.storage.segment_utilization import SegmentUtilizationStorage

    segment_storage = SegmentUtilizationStorage(db_path)
    now = datetime.now(timezone.utc)
    random.seed(42)
    for index in range(2880):
        timestamp = (now - timedelta(minutes=2880 - index)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        downstream_total = 15.0 + random.uniform(-5, 25)
        upstream_total = 8.0 + random.uniform(-3, 15)
        downstream_own = downstream_total * random.uniform(0.01, 0.15)
        upstream_own = upstream_total * random.uniform(0.01, 0.10)
        segment_storage.save_at(
            timestamp,
            round(downstream_total, 1),
            round(upstream_total, 1),
            round(downstream_own, 2),
            round(upstream_own, 2),
        )


@pytest.fixture(scope="session")
def _fritzbox_data_dir(tmp_path_factory):
    """Session-scoped temp directory for the FritzBox server."""
    return str(tmp_path_factory.mktemp("docsight_e2e_fritzbox"))


@pytest.fixture(scope="session")
def fritzbox_server(_fritzbox_data_dir):
    """Start a DOCSight server with modem_type=fritzbox and segment data."""
    port = _find_free_port()
    target = _ServerTarget(
        _fritzbox_data_dir,
        port,
        modem_type="fritzbox",
        post_seed_callback=_seed_fritzbox_segment_data,
    )
    with _running_processes([(_serve_server, (target,))], [(port, "")]):
        yield f"http://127.0.0.1:{port}"


@pytest.fixture()
def fritzbox_page(page, fritzbox_server):
    """Navigate to the FritzBox server dashboard."""
    page.goto(fritzbox_server)
    page.wait_for_load_state("networkidle")
    return page
