"""Main entrypoint: MQTT loop + Flask web server + FritzBox polling."""

import logging
import os
import threading
import time

from . import fritzbox, analyzer, web, thinkbroadband
from .speedtest import SpeedtestClient
from .config import ConfigManager
from .mqtt_publisher import MQTTPublisher
from .storage import SnapshotStorage

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
    """Run the FritzBox polling loop until stop_event is set."""
    config = config_mgr.get_all()

    log.info("Modem: %s (user: %s)", config["modem_url"], config["modem_user"])
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
    bqm_last_date = None

    # Speedtest Tracker (optional, re-initialized on config change)
    stt_client = None
    stt_url = None

    while not stop_event.is_set():
        try:
            sid = fritzbox.login(
                config["modem_url"], config["modem_user"], config["modem_password"]
            )

            if device_info is None:
                device_info = fritzbox.get_device_info(config["modem_url"], sid)
                log.info("FritzBox model: %s (%s)", device_info["model"], device_info["sw_version"])
                web.update_state(device_info=device_info)

            if connection_info is None:
                connection_info = fritzbox.get_connection_info(config["modem_url"], sid)
                if connection_info:
                    ds = connection_info.get("max_downstream_kbps", 0) // 1000
                    us = connection_info.get("max_upstream_kbps", 0) // 1000
                    log.info("Connection: %d/%d Mbit/s (%s)", ds, us, connection_info.get("connection_type", ""))
                    web.update_state(connection_info=connection_info)

            data = fritzbox.get_docsis_data(config["modem_url"], sid)
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

            # Fetch BQM graph once per day
            if config_mgr.is_bqm_configured():
                today = time.strftime("%Y-%m-%d")
                if today != bqm_last_date:
                    image = thinkbroadband.fetch_graph(config_mgr.get("bqm_url"))
                    if image:
                        storage.save_bqm_graph(image)
                        bqm_last_date = today

            # Re-initialize Speedtest client if URL changed
            current_stt_url = config_mgr.get("speedtest_tracker_url") if config_mgr.is_speedtest_configured() else ""
            if current_stt_url != stt_url:
                if current_stt_url:
                    stt_client = SpeedtestClient(current_stt_url, config_mgr.get("speedtest_tracker_token"))
                    log.info("Speedtest Tracker: %s", current_stt_url)
                else:
                    stt_client = None
                stt_url = current_stt_url

            # Fetch latest speedtest result + delta cache
            if stt_client:
                results = stt_client.get_latest(1)
                if results:
                    web.update_state(speedtest_latest=results[0])
                # Delta fetch: cache new results in storage
                try:
                    last_id = storage.get_latest_speedtest_id()
                    cached_count = storage.get_speedtest_count()
                    if cached_count < 50:
                        # Initial or incomplete cache: full fetch (descending)
                        new_results = stt_client.get_results(per_page=2000)
                    else:
                        new_results = stt_client.get_newer_than(last_id)
                    if new_results:
                        storage.save_speedtest_results(new_results)
                        log.info("Cached %d new speedtest results (total: %d)", len(new_results), cached_count + len(new_results))
                except Exception as e:
                    log.warning("Speedtest delta cache failed: %s", e)

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
