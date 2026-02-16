"""Main entrypoint: collector orchestrator + Flask web server."""

import logging
import os
import threading
import time

from . import analyzer, web
from .config import ConfigManager
from .event_detector import EventDetector
from .mqtt_publisher import MQTTPublisher
from .storage import SnapshotStorage

from .collectors import discover_collectors

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("docsis.main")


def run_web(port):
    """Run production web server in a separate thread."""
    from waitress import serve
    serve(web.app, host="0.0.0.0", port=port, threads=4, _quiet=True)


def polling_loop(config_mgr, storage, stop_event):
    """Flat orchestrator: tick every second, let each collector decide when to poll."""
    config = config_mgr.get_all()

    log.info("Modem: %s (user: %s)", config["modem_url"], config["modem_user"])
    log.info("Poll interval: %ds", config["poll_interval"])

    # Connect MQTT (optional)
    mqtt_pub = None
    if config_mgr.is_mqtt_configured():
        mqtt_user = config["mqtt_user"] or None
        mqtt_password = config["mqtt_password"] or None
        mqtt_tls_insecure = (config["mqtt_tls_insecure"] or "").strip().lower() == "true"
        mqtt_pub = MQTTPublisher(
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
    else:
        log.info("MQTT not configured, running without Home Assistant integration")

    web.update_state(poll_interval=config["poll_interval"])

    event_detector = EventDetector()
    collectors = discover_collectors(
        config_mgr, storage, event_detector, mqtt_pub, web, analyzer
    )

    # Inject collectors into web layer for manual polling and status endpoint
    modem_collector = next((c for c in collectors if c.name in ("modem", "demo")), None)
    if modem_collector:
        web.init_collector(modem_collector)
    web.init_collectors(collectors)

    log.info(
        "Collectors: %s",
        ", ".join(
            f"{c.name} ({c.poll_interval_seconds}s)"
            for c in collectors
            if c.is_enabled()
        ),
    )

    while not stop_event.is_set():
        for collector in collectors:
            if stop_event.is_set():
                break
            if not collector.is_enabled():
                continue
            if not collector.should_poll():
                continue
            try:
                result = collector.collect()
                if result.success:
                    collector.record_success()
                else:
                    collector.record_failure()
                    log.warning("%s: %s", collector.name, result.error)
            except Exception as e:
                collector.record_failure()
                log.error("%s error: %s", collector.name, e)
                if collector.name == "modem":
                    web.update_state(error=e)

        stop_event.wait(1)

    # Cleanup MQTT
    if mqtt_pub:
        try:
            mqtt_pub.disconnect()
        except Exception:
            pass
    log.info("Polling loop stopped")


def main():
    data_dir = os.environ.get("DATA_DIR", "/data")
    config_mgr = ConfigManager(data_dir)

    log.info("DOCSight starting")

    # Initialize snapshot storage
    db_path = os.path.join(data_dir, "docsis_history.db")
    storage = SnapshotStorage(db_path, max_days=config_mgr.get("history_days", 7))
    web.init_storage(storage)

    # Polling thread management
    poll_thread = None
    poll_stop = None

    def start_polling():
        nonlocal poll_thread, poll_stop
        if poll_thread and poll_thread.is_alive():
            poll_stop.set()
            poll_thread.join(timeout=10)
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
        # Update storage max_days
        storage.max_days = config_mgr.get("history_days", 7)
        if config_mgr.is_configured():
            start_polling()

    web.init_config(config_mgr, on_config_changed)

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
