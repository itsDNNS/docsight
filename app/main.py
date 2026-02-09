"""Main entrypoint: MQTT loop + Flask web server + FritzBox polling."""

import logging
import os
import threading
import time

from . import fritzbox, analyzer, web
from .config import ConfigManager
from .mqtt_publisher import MQTTPublisher
from .storage import SnapshotStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("docsis.main")


def run_web(port):
    """Run Flask in a separate thread."""
    web.app.run(host="0.0.0.0", port=port, use_reloader=False)


def polling_loop(config_mgr, storage, stop_event):
    """Run the FritzBox polling loop until stop_event is set."""
    config = config_mgr.get_all()

    log.info("FritzBox: %s (user: %s)", config["fritz_url"], config["fritz_user"])
    log.info("Poll interval: %ds", config["poll_interval"])

    # Connect MQTT (optional)
    mqtt_pub = None
    if config_mgr.is_mqtt_configured():
        mqtt_user = config["mqtt_user"] or None
        mqtt_password = config["mqtt_password"] or None
        mqtt_pub = MQTTPublisher(
            host=config["mqtt_host"],
            port=int(config["mqtt_port"]),
            user=mqtt_user,
            password=mqtt_password,
            topic_prefix=config["mqtt_topic_prefix"],
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

    sid = None
    device_info = None
    connection_info = None
    discovery_published = False

    while not stop_event.is_set():
        try:
            sid = fritzbox.login(
                config["fritz_url"], config["fritz_user"], config["fritz_password"]
            )

            if device_info is None:
                device_info = fritzbox.get_device_info(config["fritz_url"], sid)
                log.info("FritzBox model: %s (%s)", device_info["model"], device_info["sw_version"])

            if connection_info is None:
                connection_info = fritzbox.get_connection_info(config["fritz_url"], sid)
                if connection_info:
                    ds = connection_info.get("max_downstream_kbps", 0) // 1000
                    us = connection_info.get("max_upstream_kbps", 0) // 1000
                    log.info("Connection: %d/%d Mbit/s (%s)", ds, us, connection_info.get("connection_type", ""))
                    web.update_state(connection_info=connection_info)

            data = fritzbox.get_docsis_data(config["fritz_url"], sid)
            analysis = analyzer.analyze(data)

            if mqtt_pub:
                if not discovery_published:
                    mqtt_pub.publish_discovery(device_info)
                    mqtt_pub.publish_channel_discovery(
                        analysis["ds_channels"], analysis["us_channels"], device_info
                    )
                    discovery_published = True
                    time.sleep(1)
                mqtt_pub.publish_data(analysis)

            web.update_state(analysis=analysis)
            storage.save_snapshot(analysis)

        except Exception as e:
            log.error("Poll error: %s", e)
            web.update_state(error=e)

        # Wait for poll_interval, but check stop_event every second
        for _ in range(int(config["poll_interval"])):
            if stop_event.is_set():
                break
            time.sleep(1)

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
