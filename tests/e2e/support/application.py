"""Application construction and deterministic data seeding for E2E servers."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import pickle
import random
import shutil
import socket
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.e2e.support.profiles import ServerProfile, ServerTarget

_WAITRESS_KWARGS = {"threads": 2, "asyncore_use_poll": True}

# Directory shared by every server of one pytest run (all xdist workers
# included) that keeps the seeded demo history for reuse.
SEED_CACHE_ENV = "DOCSIGHT_E2E_SEED_CACHE"
_SEEDED_DATABASES = ("docsis_history.db", "connection_monitor.db")
_SEED_STATE_FILE = "seed-state.pickle"
_SQLITE_SIDE_FILES = ("-wal", "-shm", "-journal")


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


def demo_seed_cache_entry(profile: ServerProfile) -> Path | None:
    """Where the seeded demo history of this profile's module set is kept.

    Every configured profile without its own seed callback boots through
    DemoCollector, which computes nine months of analyzed snapshots and 30 BQM
    images: 20-30 CPU seconds per server, most of a shard's startup cost. The
    history does not depend on the mount path, proxy settings, or password, so
    servers that load the same modules for the same modem reuse the databases
    of the first one instead of computing them again.
    """
    root = os.environ.get(SEED_CACHE_ENV)
    if not root or not profile.configured or profile.seed_callback is not None:
        return None
    key = json.dumps(
        [profile.demo_mode, profile.modem_type, profile.disabled_modules]
    )
    return Path(root) / f"demo-{hashlib.sha256(key.encode()).hexdigest()[:16]}"


def restore_seeded_databases(entry: Path | None, data_dir: str) -> dict | None:
    """Copy a complete seed template into a fresh data directory.

    Returns the collector, storage, and runtime state the seeding left behind,
    or None when there is no template yet. A template only appears through an
    atomic rename once it is complete.
    """
    if entry is None:
        return None
    try:
        state = pickle.loads((entry / _SEED_STATE_FILE).read_bytes())
    except (OSError, pickle.UnpicklingError, EOFError):
        return None
    os.makedirs(data_dir, exist_ok=True)
    for name in state["files"]:
        shutil.copyfile(entry / name, Path(data_dir) / name)
    return state


def _fingerprint(value, collaborators=()):
    if any(value is collaborator for collaborator in collaborators):
        return ("identity", id(value))
    try:
        return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:  # noqa: BLE001 - anything unpicklable is compared by identity
        return ("identity", id(value))


def _observe(collector, runtime, storage, data_dir: str) -> dict:
    scopes = {
        "collector": dict(vars(collector)),
        "storage": dict(vars(storage)),
        "runtime": runtime.get_state(),
    }
    files = {}
    for path in Path(data_dir).iterdir():
        stat = path.stat()
        files[path.name] = (stat.st_size, stat.st_mtime_ns)
    return {
        "values": scopes,
        "fingerprints": {
            scope: {
                key: _fingerprint(value, (collector, runtime, storage))
                for key, value in values.items()
            }
            for scope, values in scopes.items()
        },
        "files": files,
    }


def _seed_template(before: dict, after: dict) -> dict | None:
    """The state seeding changed, or None when it cannot be replayed."""
    changed = {}
    for scope, fingerprints in after["fingerprints"].items():
        previous = before["fingerprints"][scope]
        if set(previous) - set(fingerprints):
            return None
        changed[scope] = {}
        for key, fingerprint in fingerprints.items():
            if previous.get(key) == fingerprint:
                continue
            if isinstance(fingerprint, tuple):
                return None
            changed[scope][key] = after["values"][scope][key]
    seeded = {
        name + suffix for name in _SEEDED_DATABASES for suffix in ("", *_SQLITE_SIDE_FILES)
    }
    for name, signature in after["files"].items():
        if name not in seeded and before["files"].get(name) != signature:
            return None
    files = [name for name in _SEEDED_DATABASES if name in after["files"]]
    if _SEEDED_DATABASES[0] not in files:
        return None
    return {**changed, "files": files}


def _publish_seed_template(entry: Path, template: dict, data_dir: str) -> None:
    staging = entry.parent / f".{entry.name}-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        for name in template["files"]:
            with closing(sqlite3.connect(Path(data_dir) / name)) as source, closing(
                sqlite3.connect(staging / name)
            ) as destination:
                source.backup(destination)
                # One self-contained file per database; the server sets its
                # own journal mode when it opens the copy.
                destination.execute("PRAGMA journal_mode=DELETE")
        (staging / _SEED_STATE_FILE).write_bytes(
            pickle.dumps(template, protocol=pickle.HIGHEST_PROTOCOL)
        )
        # A concurrent server may have published the same template first.
        os.rename(staging, entry)
    except OSError:
        pass
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def install_demo_seed_cache(
    collector, runtime, storage, entry: Path, state: dict | None, data_dir: str
) -> None:
    """Replay a restored seed, or seed normally and publish the result.

    DemoCollector seeds through `_seed_demo_data` on its first poll. With a
    restored template the databases already hold the history, so only the
    in-memory state that seeding produced is applied; the first live poll
    then runs unchanged. Without a template the real seeding runs and its
    result becomes the template, unless it changed something that cannot be
    replayed, in which case later servers simply seed again.
    """
    if state is not None:

        def replay_seed():
            for owner, scope in ((collector, "collector"), (storage, "storage")):
                for key, value in state[scope].items():
                    setattr(owner, key, copy.deepcopy(value))
            if state["runtime"]:
                runtime.update_state(**copy.deepcopy(state["runtime"]))

        collector._seed_demo_data = replay_seed
        return

    seed = collector._seed_demo_data

    def seed_and_publish():
        before = _observe(collector, runtime, storage, data_dir)
        seed()
        template = _seed_template(
            before, _observe(collector, runtime, storage, data_dir)
        )
        if template is not None:
            _publish_seed_template(entry, template, data_dir)

    collector._seed_demo_data = seed_and_publish


def serve_server(
    target: ServerTarget, *, listener_socket: socket.socket | None = None
) -> None:
    """Boot one E2E DOCSight variant inside a spawned child process."""

    # Read before the environment is replaced by the target's clean one.
    seed_entry = demo_seed_cache_entry(target.profile)
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
            "disabled_modules": target.profile.disabled_modules,
            "modem_type": target.profile.modem_type
            or ("demo" if target.profile.demo_mode else "generic"),
        }
        if target.admin_password:
            config_data["admin_password"] = target.admin_password
        config.save(config_data)

        seed_state = restore_seeded_databases(seed_entry, target.data_dir)
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
        if target.profile.seed_callback is not None:
            target.profile.seed_callback(runtime)
        else:
            collector = DemoCollector(
                analyzer_fn=analyzer.analyze,
                event_detector=EventDetector(),
                storage=storage,
                mqtt_pub=None,
                web=runtime,
                poll_interval=300,
            )
            if seed_entry is not None:
                install_demo_seed_cache(
                    collector,
                    runtime,
                    storage,
                    seed_entry,
                    seed_state,
                    target.data_dir,
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
