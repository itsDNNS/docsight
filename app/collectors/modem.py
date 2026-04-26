"""Modem collector -- DOCSIS data, analysis, events, MQTT, storage."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from .base import Collector, CollectorResult
from ..analyzer import apply_spike_suppression
from ..gaming_index import compute_gaming_index
from ..types import AnalysisResult, ConnectionInfo, DeviceInfo

log = logging.getLogger("docsis.collector.modem")

def format_uptime(seconds: int) -> str:
    """Format uptime seconds into a human-readable string: Xd Yh Zm."""
    if seconds is None:
        return "unknown"

    days = seconds // (24 * 3600)
    seconds %= (24 * 3600)
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60

    return f"{days}d {hours}h {minutes}m"


class ModemCollector(Collector):
    """Collects DOCSIS data from a modem driver, runs analysis, detects events,
    publishes to MQTT, and stores snapshots."""

    name = "modem"

    def __init__(self, driver, analyzer_fn, event_detector, storage, mqtt_pub, web, poll_interval, notifier=None, smart_capture=None):
        super().__init__(poll_interval)
        self._driver = driver
        self._analyzer = analyzer_fn
        self._event_detector = event_detector
        self._storage = storage
        self._mqtt_pub = mqtt_pub
        self._web = web
        self._notifier = notifier
        self._smart_capture = smart_capture
        self._device_info: DeviceInfo | None = None
        self._connection_info: ConnectionInfo | None = None
        self._discovery_published = False

    def collect(self) -> CollectorResult:
        self._driver.login()

        first_fetch = self._device_info is None
        self._device_info = self._driver.get_device_info()
        if first_fetch:
            log.info(
                "Model: %s (%s, %s)",
                self._device_info.get("model", "?"),
                self._device_info.get("sw_version", "?"),
                self._device_info.get("docsis_status", "?"),
            )
        self._web.update_state(device_info=self._device_info)

        # Device state tracking (reboots, sw updates, IP changes)
        if self._device_info:
            uptime = self._device_info.get("uptime_seconds")
            sw_version = self._device_info.get("sw_version")
            ipv4 = self._device_info.get("wan_ipv4")
            ipv6 = self._device_info.get("wan_ipv6")
            reboot_reason = self._device_info.get("reboot_reason")

            old_state = self._storage.get_device_state()
            now = datetime.now(timezone.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            events_to_log = []

            # Detection: Compare current poll with last known state from DB
            sw_changed = False
            uptime_decreased = False
            ip_changed = False

            old_sw = old_state.get("sw_version") if old_state else None
            if sw_version and old_sw and sw_version != old_sw:
                sw_changed = True

            old_uptime = old_state.get("uptime_seconds") if old_state else None
            if uptime is not None and old_uptime is not None and uptime < old_uptime:
                uptime_decreased = True

            # IP change detection for both IPv4 and IPv6
            old_ipv4 = old_state.get("wan_ipv4") if old_state else None
            old_ipv6 = old_state.get("wan_ipv6") if old_state else None

            ipv4_changed = ipv4 and old_ipv4 and ipv4 != old_ipv4
            ipv6_changed = ipv6 and old_ipv6 and ipv6 != old_ipv6
            if ipv4_changed or ipv6_changed:
                ip_changed = True

            # Format IP change snippet for inclusion in reboot/update messages
            ip_msg = ""
            if ip_changed:
                if ipv4_changed and ipv6_changed:
                    ip_msg = f"WAN IPv4/v6: {old_ipv4} / {old_ipv6} → {ipv4} / {ipv6}"
                elif ipv4_changed:
                    ip_msg = f"WAN IPv4: {old_ipv4} → {ipv4}"
                else:
                    ip_msg = f"WAN IPv6: {old_ipv6} → {ipv6}"

            # Construct parts for inclusion in messages
            uptime_fmt = format_uptime(old_uptime)
            msg_parts = []
            if uptime_fmt != "unknown":
                msg_parts.append(f"Prior uptime: {uptime_fmt}")

            # Priority 1: Software Update (usually implies a reboot)
            if sw_changed:
                msg_parts.append(f"SW: {old_sw} → {sw_version}")
                if ip_changed:
                    msg_parts.append(ip_msg)
                if reboot_reason:
                    msg_parts.append(f"Reason: {reboot_reason}")
                
                events_to_log.append({
                    "timestamp": now_iso,
                    "severity": "info",
                    "event_type": "device_sw_update",
                    "message": ", ".join(msg_parts),
                    "details": {"old_sw": old_sw, "new_sw": sw_version, "reboot_reason": reboot_reason, "prior_uptime": old_uptime, "ip_changed": ip_changed}
                })
            # Priority 2: Standard Reboot (uptime drop without SW change)
            elif uptime_decreased:
                if ip_changed:
                    msg_parts.append(ip_msg)
                if reboot_reason:
                    msg_parts.append(f"Reason: {reboot_reason}")
                
                events_to_log.append({
                    "timestamp": now_iso,
                    "severity": "warning",
                    "event_type": "device_reboot",
                    "message": ", ".join(msg_parts),
                    "details": {"reboot_reason": reboot_reason, "prior_uptime": old_uptime, "ip_changed": ip_changed}
                })
            # Priority 3: Standalone IP change (no reboot detected)
            elif ip_changed:
                events_to_log.append({
                    "timestamp": now_iso,
                    "severity": "info",
                    "event_type": "device_ip_change",
                    "message": ip_msg,
                    "details": {"old_ipv4": old_ipv4, "new_ipv4": ipv4, "old_ipv6": old_ipv6, "new_ipv6": ipv6}
                })

            if events_to_log:
                self._storage.save_events(events_to_log)
                if self._notifier:
                    self._notifier.dispatch(events_to_log)

            # Update the state database to hold the current 'last known' values.
            self._storage.update_device_state(
                uptime if uptime is not None else old_uptime,
                sw_version if sw_version is not None else old_sw,
                ipv4 if ipv4 is not None else old_ipv4,
                ipv6 if ipv6 is not None else old_ipv6,
                now_iso
            )

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
        apply_spike_suppression(analysis, self._storage.get_latest_spike_timestamp())

        # MQTT publishing
        if self._mqtt_pub:
            if not self._discovery_published:
                self._mqtt_pub.publish_discovery(self._device_info)
                self._mqtt_pub.publish_channel_discovery(
                    analysis["ds_channels"], analysis["us_channels"], self._device_info
                )
                self._discovery_published = True
                time.sleep(1)
            speedtest = self._web._state.get("speedtest_latest")
            gi = compute_gaming_index(analysis, speedtest)
            self._mqtt_pub.publish_data(analysis, gaming_index=gi)

        # Web state + persistent storage
        self._web.update_state(analysis=analysis)
        self._storage.save_snapshot(analysis)

        # Event detection
        events = self._event_detector.check(analysis)
        if events:
            self._storage.save_events_with_ids(events)
            log.info("Detected %d event(s)", len(events))
            if self._notifier:
                self._notifier.dispatch(events)
            if self._smart_capture:
                self._smart_capture.evaluate(events)

        return CollectorResult(source=self.name, data=analysis)
