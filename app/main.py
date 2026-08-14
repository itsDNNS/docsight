"""Main entrypoint: collector orchestrator + Flask web server."""

import json as _json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import analyzer, web
from .app_factory import create_app, default_module_loader_factory
from .base_path import validate_base_path_configuration
from .config import ConfigManager
from .event_detector import EventDetector
from .module_paths import get_modules_dir
from .runtime import DocsightRuntime, get_runtime
from .server_lifecycle import ServerLifecycleController
from .storage import SnapshotStorage
from .tz import guess_iana_timezone, utc_cutoff
from .waitress_server import WaitressServerAdapter

from .collectors import discover_collectors

try:
    from .drivers.surfboard import TransientHtmlChannelPageError as _TransientHtmlError
except ImportError:
    class _TransientHtmlError(Exception):  # type: ignore[no-redef]
        """Stub -- never raised when surfboard driver is absent."""

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("docsis.main")

COLLECTOR_LONG_RUNNING_SECONDS = 120


class _AuditJsonFormatter(logging.Formatter):
    """Structured JSON formatter for the audit logger."""

    def format(self, record):
        return _json.dumps({
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "event": record.getMessage(),
        }, ensure_ascii=False)


if os.environ.get("DOCSIGHT_AUDIT_JSON", "").strip() == "1":
    _audit = logging.getLogger("docsis.audit")
    _handler = logging.StreamHandler()
    _handler.setFormatter(_AuditJsonFormatter())
    _audit.addHandler(_handler)
    _audit.propagate = False


def run_web(
    application,
    port: int,
    server_lifecycle: ServerLifecycleController | None = None,
) -> None:
    """Run production web server in a separate thread."""
    from waitress import create_server

    host = get_web_host()
    server = WaitressServerAdapter(
        create_server(
            application,
            host=host,
            port=port,
            threads=4,
        )
    )
    lifecycle = server_lifecycle or ServerLifecycleController()
    lifecycle.attach(server)
    server.run()


def get_web_host():
    """Return the configured web bind address, preserving the server default."""
    return os.environ.get("WEB_HOST", "0.0.0.0")


def _wait_for_web_thread(
    web_thread,
    stop_polling,
    server_lifecycle: ServerLifecycleController | None = None,
):
    """Keep the process alive until the web server stops, then stop pollers."""
    try:
        while web_thread.is_alive():
            time.sleep(0.25)
        if server_lifecycle is not None and server_lifecycle.close_requested:
            log.info("Web server stopped after shutdown request")
        else:
            log.error("Web server stopped unexpectedly")
    except KeyboardInterrupt:
        log.info("Shutting down")
        return
    finally:
        stop_polling()
    if os.environ.get("DOCSIGHT_DESKTOP_MODE", "").strip() != "1":
        raise RuntimeError("Web server stopped unexpectedly")


def _apply_timezone(cfg):
    """Apply the configured timezone where the platform supports TZ reloads."""
    tz = cfg.get("timezone")
    if tz:
        os.environ["TZ"] = tz
        if hasattr(time, "tzset"):
            time.tzset()


def _handle_config_changed(config_mgr, storage, stop_polling, start_polling):
    """Reload config and apply runtime changes after a web UI save."""
    log.info("Configuration changed, restarting polling loop")
    stop_polling()
    config_mgr._load()
    _apply_timezone(config_mgr)
    storage.max_days = config_mgr.get("history_days", 7)
    if config_mgr.is_configured():
        start_polling()


def _get_modem_config_key(config_mgr):
    """Return modem config tuple for driver hot-swap change detection."""
    return (
        config_mgr.get("modem_type", "fritzbox"),
        config_mgr.get("modem_url", ""),
        config_mgr.get("modem_user", ""),
        config_mgr.get("modem_password", ""),
    )


def polling_loop(config_mgr, storage, stop_event, runtime: DocsightRuntime):
    """Flat orchestrator: tick every second, let each collector decide when to poll."""
    config = config_mgr.get_all()

    log.info("Modem: %s (user: %s)", config["modem_url"], config["modem_user"])
    log.info("Poll interval: %ds", config["poll_interval"])

    # Connect MQTT (optional, loaded from module if available)
    mqtt_pub = None
    mqtt_cls = None
    module_loader = runtime.get_module_loader()
    if module_loader:
        for mod in module_loader.get_enabled_modules():
            if mod.publisher_class and mod.id == 'docsight.mqtt':
                mqtt_cls = mod.publisher_class
                break

    if mqtt_cls and config_mgr.is_mqtt_configured():
        mqtt_user = config["mqtt_user"] or None
        mqtt_password = config["mqtt_password"] or None
        mqtt_tls_insecure = str(config.get("mqtt_tls_insecure", "")).strip().lower() in ("true", "1", "yes", "on")
        mqtt_pub = mqtt_cls(
            host=config["mqtt_host"],
            port=int(config["mqtt_port"]),
            user=mqtt_user,
            password=mqtt_password,
            topic_prefix=config["mqtt_topic_prefix"],
            ha_prefix=config["mqtt_discovery_prefix"],
            tls_insecure=mqtt_tls_insecure,
            web_port=int(config["web_port"]),
            public_url=config.get("public_url", ""),
        )
        try:
            mqtt_pub.connect()
            log.info("MQTT: %s:%s (prefix: %s)", config["mqtt_host"], config["mqtt_port"], config["mqtt_topic_prefix"])
        except Exception as e:
            log.warning("MQTT connection failed: %s (continuing without MQTT)", e)
            mqtt_pub = None
    elif config_mgr.is_mqtt_configured() and not mqtt_cls:
        log.warning("MQTT configured but docsight.mqtt module not available (disabled?)")
    else:
        log.info("MQTT not configured, running without Home Assistant integration")

    # Notifications (optional)
    notifier = None
    if config_mgr.is_notify_configured():
        from .notifier import NotificationDispatcher
        notifier = NotificationDispatcher(config_mgr, storage=storage)
        log.info("Notifications: configured")

    # Smart Capture (always instantiated — _is_enabled() gates at runtime)
    from .smart_capture import SmartCaptureEngine, Trigger
    from .smart_capture.sub_filters import (
        modulation_sub_filter, snr_sub_filter, error_spike_sub_filter,
        health_sub_filter, packet_loss_sub_filter,
    )
    smart_capture = SmartCaptureEngine(storage, config_mgr)
    smart_capture.register_trigger(Trigger(
        event_type="modulation_change",
        config_key="sc_trigger_modulation",
        min_severity="warning", require_details={"direction": "downgrade"},
        sub_filter=modulation_sub_filter,
    ))
    smart_capture.register_trigger(Trigger(
        event_type="snr_change",
        config_key="sc_trigger_snr", min_severity="warning",
        sub_filter=snr_sub_filter,
    ))
    smart_capture.register_trigger(Trigger(
        event_type="error_spike",
        config_key="sc_trigger_error_spike",
        sub_filter=error_spike_sub_filter,
    ))
    smart_capture.register_trigger(Trigger(
        event_type="health_change",
        config_key="sc_trigger_health", min_severity="warning",
        sub_filter=health_sub_filter,
    ))
    smart_capture.register_trigger(Trigger(
        event_type="cm_packet_loss_warning",
        config_key="sc_trigger_packet_loss",
        sub_filter=packet_loss_sub_filter,
    ))
    log.info("Smart Capture: registered %d trigger(s)", len(smart_capture.triggers))

    runtime.update_state(poll_interval=config["poll_interval"])

    event_detector = EventDetector(hysteresis=config_mgr.get("health_hysteresis", 0))
    collectors = discover_collectors(
        config_mgr, storage, event_detector, mqtt_pub, runtime, analyzer,
        notifier=notifier, smart_capture=smart_capture,
    )

    # Wire STT adapter if STT configured and not demo mode
    if config_mgr.is_speedtest_configured() and not config_mgr.is_demo_mode():
        from .smart_capture.adapters.speedtest import SpeedtestAdapter
        stt_adapter = SpeedtestAdapter(storage, config_mgr)
        smart_capture.register_speedtest_adapter(stt_adapter)
        stt_collector = next((c for c in collectors if c.name == "speedtest"), None)
        if stt_collector:
            stt_collector.on_import = stt_adapter.on_results_imported
            log.info("Smart Capture: STT adapter wired to speedtest collector")

    # Wire Smart Capture to Connection Monitor collector
    cm_collector = next((c for c in collectors if c.name == "connection_monitor"), None)
    if cm_collector and hasattr(cm_collector, 'set_smart_capture'):
        cm_collector.set_smart_capture(smart_capture)
        log.info("Smart Capture: wired to Connection Monitor collector")

    # Inject collectors into web layer for manual polling and status endpoint
    modem_collector = next((c for c in collectors if c.name in ("modem", "demo")), None)
    if modem_collector:
        runtime.modem_collector = modem_collector
    runtime.collectors = collectors

    # Track modem config for driver hot-swap detection
    modem_config_key = (
        _get_modem_config_key(config_mgr)
        if modem_collector and modem_collector.name == "modem"
        else None
    )

    log.info(
        "Collectors: %s",
        ", ".join(
            f"{c.name} ({c.poll_interval_seconds}s)"
            for c in collectors
            if c.is_enabled()
        ),
    )

    def _run_collector(collector):
        """Run a single collector with _collect_lock to prevent overlap with manual poll."""
        if not collector._collect_lock.acquire(timeout=0):
            log.debug("%s: skipped (collect already in progress)", collector.name)
            return collector, None
        try:
            return collector, collector.collect()
        finally:
            collector._collect_lock.release()

    executor = ThreadPoolExecutor(
        max_workers=len(collectors), thread_name_prefix="collector"
    )
    in_flight = {}

    def _process_in_flight():
        """Record completed collector runs and warn once for long-running work."""
        now = time.monotonic()
        for future, state in list(in_flight.items()):
            collector = state["collector"]
            if not future.done():
                elapsed = now - state["submitted_at"]
                if (
                    elapsed >= COLLECTOR_LONG_RUNNING_SECONDS
                    and not state["warned"]
                ):
                    state["warned"] = True
                    log.warning(
                        "%s: still running after %ds",
                        collector.name,
                        COLLECTOR_LONG_RUNNING_SECONDS,
                    )
                continue

            del in_flight[future]
            try:
                _, result = future.result()
                if result is None:
                    continue  # skipped (collect lock busy)
                if result.success:
                    collector.record_success()
                else:
                    collector.record_failure()
                    log.warning("%s: %s", collector.name, result.error)
            except _TransientHtmlError:
                collector.record_skip()
                log.warning(
                    "%s: transient HTML response, skipping poll", collector.name
                )
            except Exception as e:
                collector.record_failure()
                log.error("%s error: %s", collector.name, e)
                if collector.name in ("modem", "demo"):
                    runtime.update_state(error=e)

    try:
        while not stop_event.is_set():
            _process_in_flight()

            # ── Driver hot-swap: detect modem config change ──
            if modem_config_key is not None and modem_collector:
                new_key = _get_modem_config_key(config_mgr)
                if new_key != modem_config_key:
                    log.info(
                        "Modem config changed (%s -> %s), hot-swapping driver",
                        modem_config_key[0], new_key[0],
                    )
                    from .collectors.modem import ModemCollector
                    from .drivers import driver_registry
                    new_driver = driver_registry.load_driver(*new_key)
                    new_modem = ModemCollector(
                        driver=new_driver,
                        analyzer_fn=analyzer.analyze,
                        event_detector=event_detector,
                        storage=storage,
                        mqtt_pub=mqtt_pub,
                        web=runtime,
                        poll_interval=config_mgr.get("poll_interval", 900),
                        notifier=notifier,
                        smart_capture=smart_capture,
                    )
                    collectors = [
                        new_modem if c is modem_collector else c
                        for c in collectors
                    ]
                    modem_collector = new_modem
                    runtime.modem_collector = new_modem
                    runtime.collectors = collectors
                    runtime.reset_modem_state()
                    modem_config_key = new_key
                    log.info("Driver hot-swapped to %s", new_key[0])

            for collector in collectors:
                if stop_event.is_set():
                    break
                if any(
                    state["collector"].name == collector.name
                    for state in in_flight.values()
                ):
                    continue
                if not collector.is_enabled():
                    continue
                if not collector.should_poll():
                    continue
                future = executor.submit(_run_collector, collector)
                in_flight[future] = {
                    "collector": collector,
                    "submitted_at": time.monotonic(),
                    "warned": False,
                }

            _process_in_flight()

            # ── Smart Capture expiry check (every 60s) ──
            if smart_capture:
                expiry_counter = runtime.derived_storage.value("smart_capture_expiry_counter", 0) + 1
                runtime.derived_storage.set_value("smart_capture_expiry_counter", expiry_counter)
                if expiry_counter >= 60:
                    runtime.derived_storage.set_value("smart_capture_expiry_counter", 0)
                    match_window = config_mgr.get("sc_speedtest_match_window", 900)
                    try:
                        expiry_minutes = max(10, int(match_window) // 60 + 5)
                    except (TypeError, ValueError):
                        expiry_minutes = 20
                    cutoff = utc_cutoff(minutes=expiry_minutes)
                    expired = storage.expire_stale_fired(cutoff, action_type="capture")
                    if expired:
                        log.info("Smart Capture: expired %d stale speedtest executions",
                                 expired)
                    # Expire orphaned PENDING executions (Speedtest Tracker not configured)
                    pending_expired = storage.expire_stale_pending(cutoff)
                    if pending_expired:
                        log.info("Smart Capture: expired %d orphaned pending executions",
                                 pending_expired)

            stop_event.wait(1)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        for c in collectors:
            if hasattr(c, "stop"):
                try:
                    c.stop()
                except Exception:
                    pass

    # Cleanup MQTT
    if mqtt_pub:
        try:
            mqtt_pub.disconnect()
        except Exception:
            pass
    log.info("Polling loop stopped")


def main(server_lifecycle: ServerLifecycleController | None = None):
    validate_base_path_configuration(os.environ)
    data_dir = os.environ.get("DATA_DIR", "/data")
    config_mgr = ConfigManager(data_dir)
    _apply_timezone(config_mgr)

    log.info("DOCSight starting")

    db_path = os.path.join(data_dir, "docsis_history.db")
    storage = SnapshotStorage(db_path, max_days=config_mgr.get("history_days", 7))

    # UTC migration + timezone setup
    tz_name = config_mgr.get("timezone") or guess_iana_timezone()
    storage.migrate_to_utc(tz_name)
    storage.set_timezone(tz_name)

    # Polling thread management
    poll_thread = None
    poll_stop = None
    runtime = None

    def stop_polling():
        nonlocal poll_thread, poll_stop
        if poll_thread and poll_thread.is_alive():
            poll_stop.set()
            poll_thread.join(timeout=10)
        poll_thread = None
        poll_stop = None

    def start_polling():
        nonlocal poll_thread, poll_stop
        stop_polling()
        runtime.reset_modem_state()
        poll_stop = threading.Event()
        poll_thread = threading.Thread(
            target=polling_loop, args=(config_mgr, storage, poll_stop, runtime), daemon=True
        )
        poll_thread.start()
        log.info("Polling loop started")

    def on_config_changed():
        """Called when config is saved via web UI."""
        _handle_config_changed(config_mgr, storage, stop_polling, start_polling)

    builtin_path = os.path.join(os.path.dirname(__file__), "modules")
    community_path = get_modules_dir()
    application = create_app(
        config_manager=config_mgr,
        storage=storage,
        on_config_changed=on_config_changed,
        module_loader_factory=default_module_loader_factory(
            config_mgr,
            builtin_base_path=builtin_path,
            search_paths=[community_path],
        ),
        environ=os.environ,
    )
    runtime = get_runtime(application)

    # Start Flask
    web_port = config_mgr.get("web_port", 8765)
    web_host = get_web_host()
    lifecycle = server_lifecycle or ServerLifecycleController()
    web_thread = threading.Thread(
        target=run_web,
        args=(application, web_port, lifecycle),
        daemon=True,
    )
    web_thread.start()
    log.info("Web UI started on %s:%d", web_host, web_port)

    # Start polling if already configured
    if config_mgr.is_configured():
        start_polling()
    else:
        log.info("Not configured yet - open http://localhost:%d for setup", web_port)

    # Keep the main thread alive while the web server owns its listener. If the
    # server thread cannot bind, return so the desktop launcher can perform its
    # bounded fresh-process recovery instead of waiting for readiness forever.
    _wait_for_web_thread(web_thread, stop_polling, lifecycle)


if __name__ == "__main__":
    main()
