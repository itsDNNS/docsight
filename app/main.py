"""Main entrypoint: collector orchestrator + Flask web server."""

import json as _json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import analyzer, web
from .config import ConfigManager
from .event_detector import EventDetector
from .storage import SnapshotStorage

from .collectors import discover_collectors

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("docsis.main")


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


def run_web(port):
    """Run production web server in a separate thread."""
    from waitress import serve
    serve(web.app, host="0.0.0.0", port=port, threads=4, _quiet=True)


def _get_modem_config_key(config_mgr):
    """Return modem config tuple for driver hot-swap change detection."""
    return (
        config_mgr.get("modem_type", "fritzbox"),
        config_mgr.get("modem_url", ""),
        config_mgr.get("modem_user", ""),
        config_mgr.get("modem_password", ""),
    )


def polling_loop(config_mgr, storage, stop_event):
    """Flat orchestrator: tick every second, let each collector decide when to poll."""
    config = config_mgr.get_all()

    log.info("Modem: %s (user: %s)", config["modem_url"], config["modem_user"])
    log.info("Poll interval: %ds", config["poll_interval"])

    # Connect MQTT (optional, loaded from module if available)
    mqtt_pub = None
    mqtt_cls = None
    module_loader = web.get_module_loader() if hasattr(web, 'get_module_loader') else None
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
        notifier = NotificationDispatcher(config_mgr)
        log.info("Notifications: webhook configured")

    # Smart Capture (always instantiated — _is_enabled() gates at runtime)
    from .smart_capture import SmartCaptureEngine, Trigger
    from .smart_capture.sub_filters import (
        modulation_sub_filter, snr_sub_filter, error_spike_sub_filter,
        health_sub_filter, packet_loss_sub_filter,
    )
    smart_capture = SmartCaptureEngine(storage, config_mgr)
    smart_capture.register_trigger(Trigger(
        event_type="modulation_change", action_type="capture",
        config_key="sc_trigger_modulation",
        min_severity="warning", require_details={"direction": "downgrade"},
        sub_filter=modulation_sub_filter,
    ))
    smart_capture.register_trigger(Trigger(
        event_type="snr_change", action_type="capture",
        config_key="sc_trigger_snr", min_severity="warning",
        sub_filter=snr_sub_filter,
    ))
    smart_capture.register_trigger(Trigger(
        event_type="error_spike", action_type="capture",
        config_key="sc_trigger_error_spike",
        sub_filter=error_spike_sub_filter,
    ))
    smart_capture.register_trigger(Trigger(
        event_type="health_change", action_type="capture",
        config_key="sc_trigger_health", min_severity="warning",
        sub_filter=health_sub_filter,
    ))
    smart_capture.register_trigger(Trigger(
        event_type="cm_packet_loss_warning", action_type="capture",
        config_key="sc_trigger_packet_loss",
        sub_filter=packet_loss_sub_filter,
    ))
    log.info("Smart Capture: registered %d trigger(s)", len(smart_capture.triggers))

    web.update_state(poll_interval=config["poll_interval"])

    event_detector = EventDetector(hysteresis=config_mgr.get("health_hysteresis", 0))
    collectors = discover_collectors(
        config_mgr, storage, event_detector, mqtt_pub, web, analyzer,
        notifier=notifier, smart_capture=smart_capture,
    )

    # Wire STT adapter if STT configured and not demo mode
    if config_mgr.is_speedtest_configured() and not config_mgr.is_demo_mode():
        from .smart_capture.adapters.speedtest import SpeedtestAdapter
        stt_adapter = SpeedtestAdapter(storage, config_mgr)
        smart_capture.register_adapter("capture", stt_adapter)
        stt_collector = next((c for c in collectors if c.name == "speedtest"), None)
        if stt_collector:
            stt_collector.on_import = stt_adapter.on_results_imported
            log.info("Smart Capture: STT adapter wired to speedtest collector")

    # Inject collectors into web layer for manual polling and status endpoint
    modem_collector = next((c for c in collectors if c.name in ("modem", "demo")), None)
    if modem_collector:
        web.init_collector(modem_collector)
    web.init_collectors(collectors)

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
    try:
        while not stop_event.is_set():
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
                        web=web,
                        poll_interval=config_mgr.get("poll_interval", 900),
                        notifier=notifier,
                        smart_capture=smart_capture,
                    )
                    collectors = [
                        new_modem if c is modem_collector else c
                        for c in collectors
                    ]
                    modem_collector = new_modem
                    web.init_collector(new_modem)
                    web.init_collectors(collectors)
                    web.reset_modem_state()
                    modem_config_key = new_key
                    log.info("Driver hot-swapped to %s", new_key[0])

            futures = {}
            for collector in collectors:
                if stop_event.is_set():
                    break
                if not collector.is_enabled():
                    continue
                if not collector.should_poll():
                    continue
                future = executor.submit(_run_collector, collector)
                futures[future] = collector

            try:
                for future in as_completed(futures, timeout=120):
                    if stop_event.is_set():
                        break
                    collector = futures[future]
                    try:
                        _, result = future.result()
                        if result is None:
                            continue  # skipped (collect lock busy)
                        if result.success:
                            collector.record_success()
                        else:
                            collector.record_failure()
                            log.warning("%s: %s", collector.name, result.error)
                    except Exception as e:
                        collector.record_failure()
                        log.error("%s error: %s", collector.name, e)
                        if collector.name in ("modem", "demo"):
                            web.update_state(error=e)
            except TimeoutError:
                for future, collector in futures.items():
                    if not future.done():
                        log.error("%s: timed out after 120s", collector.name)
                        future.cancel()

            # ── Smart Capture expiry check (every 60s) ──
            if smart_capture:
                if not hasattr(polling_loop, '_sc_expiry_counter'):
                    polling_loop._sc_expiry_counter = 0
                polling_loop._sc_expiry_counter += 1
                if polling_loop._sc_expiry_counter >= 60:
                    polling_loop._sc_expiry_counter = 0
                    from .tz import utc_cutoff
                    cutoff = utc_cutoff(minutes=10)
                    for action_type in smart_capture.adapter_action_types:
                        expired = storage.expire_stale_fired(cutoff, action_type=action_type)
                        if expired:
                            log.info("Smart Capture: expired %d stale %s executions",
                                     expired, action_type)
                    # Expire orphaned PENDING executions (no adapter registered)
                    pending_expired = storage.expire_stale_pending(cutoff)
                    if pending_expired:
                        log.info("Smart Capture: expired %d orphaned pending executions",
                                 pending_expired)

            stop_event.wait(1)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # Cleanup MQTT
    if mqtt_pub:
        try:
            mqtt_pub.disconnect()
        except Exception:
            pass
    log.info("Polling loop stopped")


def main():
    def _apply_timezone(cfg):
        tz = cfg.get("timezone")
        if tz:
            os.environ["TZ"] = tz
            time.tzset()

    data_dir = os.environ.get("DATA_DIR", "/data")
    config_mgr = ConfigManager(data_dir)
    _apply_timezone(config_mgr)

    log.info("DOCSight starting")

    # Initialize snapshot storage
    db_path = os.path.join(data_dir, "docsis_history.db")
    storage = SnapshotStorage(db_path, max_days=config_mgr.get("history_days", 7))

    # UTC migration + timezone setup
    from .tz import guess_iana_timezone
    tz_name = config_mgr.get("timezone") or guess_iana_timezone()
    storage.migrate_to_utc(tz_name)
    storage.set_timezone(tz_name)

    web.init_storage(storage)

    # Polling thread management
    poll_thread = None
    poll_stop = None

    def start_polling():
        nonlocal poll_thread, poll_stop
        if poll_thread and poll_thread.is_alive():
            poll_stop.set()
            poll_thread.join(timeout=10)
        web.reset_modem_state()
        poll_stop = threading.Event()
        poll_thread = threading.Thread(
            target=polling_loop, args=(config_mgr, storage, poll_stop), daemon=True
        )
        poll_thread.start()
        log.info("Polling loop started")

    def on_config_changed():
        """Called when config is saved via web UI."""
        log.info("Configuration changed, restarting polling loop")
        # Reload config from file
        config_mgr._load()
        # Apply timezone change immediately
        _apply_timezone(config_mgr)
        # Update storage max_days
        storage.max_days = config_mgr.get("history_days", 7)
        if config_mgr.is_configured():
            start_polling()

    web.init_config(config_mgr, on_config_changed)

    # Module system
    from .module_loader import ModuleLoader

    builtin_path = os.path.join(os.path.dirname(__file__), "modules")
    community_path = os.environ.get("MODULES_DIR", "/modules")
    disabled_raw = config_mgr.get("disabled_modules", "")
    disabled_ids = {s.strip() for s in disabled_raw.split(",") if s.strip()}

    module_loader = ModuleLoader(
        web.app,
        search_paths=[builtin_path, community_path],
        disabled_ids=disabled_ids,
    )
    module_loader.load_all()
    from .drivers import driver_registry
    driver_registry.register_module_drivers(module_loader)
    web.init_modules(module_loader)
    web.setup_module_templates(module_loader)

    # Reverse proxy support: REVERSE_PROXY=1 (or number of proxy hops)
    # rewrites request.remote_addr from X-Forwarded-For so rate limiting
    # and audit logs see the real client IP, not the proxy IP.
    reverse_proxy = os.environ.get("REVERSE_PROXY", "").strip()
    if reverse_proxy:
        from werkzeug.middleware.proxy_fix import ProxyFix
        num_proxies = int(reverse_proxy) if reverse_proxy.isdigit() else 1
        web.app.wsgi_app = ProxyFix(
            web.app.wsgi_app,
            x_for=num_proxies,
            x_proto=num_proxies,
            x_host=0,
            x_prefix=0,
        )
        web.app.config["SESSION_COOKIE_SECURE"] = True
        log.info("Reverse proxy mode: trusting %d hop(s), secure cookies enabled", num_proxies)

    # Start Flask
    web_port = config_mgr.get("web_port", 8765)
    web_thread = threading.Thread(target=run_web, args=(web_port,), daemon=True)
    web_thread.start()
    log.info("Web UI started on port %d", web_port)

    # Start polling if already configured
    if config_mgr.is_configured():
        start_polling()
    else:
        log.info("Not configured yet - open http://localhost:%d for setup", web_port)

    # Keep main thread alive
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Shutting down")
        if poll_stop:
            poll_stop.set()


if __name__ == "__main__":
    main()
