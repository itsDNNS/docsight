"""Modem collector — DOCSIS data, analysis, events, MQTT, storage."""

import logging
import time

from .base import Collector, CollectorResult

log = logging.getLogger("docsis.collector.modem")


class ModemCollector(Collector):
    """Collects DOCSIS data from a modem driver, runs analysis, detects events,
    publishes to MQTT, and stores snapshots."""

    name = "modem"

    def __init__(self, driver, analyzer_fn, event_detector, storage, mqtt_pub, web, poll_interval):
        super().__init__(poll_interval)
        self._driver = driver
        self._analyzer = analyzer_fn  # Function reference, not module
        self._event_detector = event_detector
        self._storage = storage
        self._mqtt_pub = mqtt_pub
        self._web = web
        self._device_info = None
        self._connection_info = None
        self._discovery_published = False

    def collect(self) -> CollectorResult:
        self._driver.login()

        if self._device_info is None:
            self._device_info = self._driver.get_device_info()
            log.info(
                "Model: %s (%s)",
                self._device_info.get("model", "?"),
                self._device_info.get("sw_version", "?"),
            )
            self._web.update_state(device_info=self._device_info)

        if self._connection_info is None:
            self._connection_info = self._driver.get_connection_info()
            if self._connection_info:
                ds = self._connection_info.get("max_downstream_kbps", 0) // 1000
                us = self._connection_info.get("max_upstream_kbps", 0) // 1000
                conn_type = self._connection_info.get("connection_type", "")
                log.info("Connection: %d/%d Mbit/s (%s)", ds, us, conn_type)
                self._web.update_state(connection_info=self._connection_info)

        data = self._driver.get_docsis_data()
        analysis = self._analyzer(data)  # Call injected analyzer function

        # MQTT publishing
        if self._mqtt_pub:
            if not self._discovery_published:
                self._mqtt_pub.publish_discovery(self._device_info)
                self._mqtt_pub.publish_channel_discovery(
                    analysis["ds_channels"], analysis["us_channels"], self._device_info
                )
                self._discovery_published = True
                time.sleep(1)
            self._mqtt_pub.publish_data(analysis)

        # Web state + persistent storage
        self._web.update_state(analysis=analysis)
        self._storage.save_snapshot(analysis)

        # Event detection
        events = self._event_detector.check(analysis)
        if events:
            self._storage.save_events(events)
            log.info("Detected %d event(s)", len(events))

        return CollectorResult(source=self.name, data=analysis)
