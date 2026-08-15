"""Application construction and deterministic data seeding for E2E servers."""

from __future__ import annotations

import os
import random
import socket
from datetime import datetime, timedelta, timezone

from tests.e2e.support.profiles import ServerTarget

_WAITRESS_KWARGS = {"threads": 2, "asyncore_use_poll": True}


def _not_found(environ, start_response):
    """Reject every request that escapes a mounted DOCSight application."""

    from werkzeug.wrappers import Response

    return Response("Not Found\n", status=404)(environ, start_response)


def _mounted_app(application, mount_path):
    if not mount_path:
        return application
    from werkzeug.middleware.dispatcher import DispatcherMiddleware

    return DispatcherMiddleware(_not_found, {mount_path: application})


def _initialize_module_storage(db_path: str) -> None:
    """Initialize module tables used by deterministic E2E seed data."""

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


def seed_fritzbox_segment_data(db_path: str) -> None:
    """Seed 48 hours of deterministic one-minute utilization samples."""

    from app.storage.segment_utilization import SegmentUtilizationStorage

    segment_storage = SegmentUtilizationStorage(db_path)
    now = datetime.now(timezone.utc)
    generator = random.Random(42)
    for index in range(2880):
        timestamp = (now - timedelta(minutes=2880 - index)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        downstream_total = 15.0 + generator.uniform(-5, 25)
        upstream_total = 8.0 + generator.uniform(-3, 15)
        downstream_own = downstream_total * generator.uniform(0.01, 0.15)
        upstream_own = upstream_total * generator.uniform(0.01, 0.10)
        segment_storage.save_at(
            timestamp,
            round(downstream_total, 1),
            round(upstream_total, 1),
            round(downstream_own, 2),
            round(upstream_own, 2),
        )


def serve_server(
    target: ServerTarget, *, listener_socket: socket.socket | None = None
) -> None:
    """Boot one E2E DOCSight variant inside a spawned child process."""

    target.apply_environment()
    if target.profile.production_startup:
        if listener_socket is None:
            raise ValueError("production startup requires its reserved test socket")
        import waitress

        create_server = waitress.create_server

        def create_server_on_reserved_socket(application, **kwargs):
            kwargs.pop("host", None)
            kwargs.pop("port", None)
            return create_server(
                application, sockets=[listener_socket], **kwargs
            )

        waitress.create_server = create_server_on_reserved_socket
        from app.main import main

        main()
        return

    from app import analyzer
    from app.app_factory import create_app, default_module_loader_factory
    from app.config import ConfigManager
    from app.runtime import get_runtime

    config = ConfigManager(target.data_dir)
    if not target.profile.configured:
        storage = None
    else:
        from app.collectors.demo import DemoCollector
        from app.event_detector import EventDetector
        from app.storage import SnapshotStorage

        config_data = {
            "demo_mode": target.profile.demo_mode,
            "disabled_modules": "",
            "modem_type": target.profile.modem_type
            or ("demo" if target.profile.demo_mode else "generic"),
        }
        if target.admin_password:
            config_data["admin_password"] = target.admin_password
        config.save(config_data)

        db_path = os.path.join(target.data_dir, "docsis_history.db")
        storage = SnapshotStorage(db_path, max_days=7)
        storage.set_timezone("UTC")
        _initialize_module_storage(db_path)

    application = create_app(
        config_manager=config,
        storage=storage,
        module_loader_factory=default_module_loader_factory(
            config, search_paths=[]
        ),
        environ=os.environ,
        testing=True,
    )
    runtime = get_runtime(application)
    if target.profile.configured:
        collector = DemoCollector(
            analyzer_fn=analyzer.analyze,
            event_detector=EventDetector(),
            storage=storage,
            mqtt_pub=None,
            web=runtime,
            poll_interval=300,
        )
        collector.collect()
        if target.profile.post_seed_callback is not None:
            target.profile.post_seed_callback(db_path)

    from waitress.server import create_server

    kwargs = dict(_WAITRESS_KWARGS)
    if listener_socket is None:
        kwargs.update(host="127.0.0.1", port=target.port)
    else:
        kwargs["sockets"] = [listener_socket]
    server = create_server(
        _mounted_app(application, target.profile.mount_path), **kwargs
    )
    server.run()
