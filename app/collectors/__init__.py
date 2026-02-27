"""Collector registry and discovery.

Provides a registry-based pattern for discovering and instantiating
data collectors based on runtime configuration.
"""

import logging

from .base import Collector, CollectorResult
from .modem import ModemCollector
from .demo import DemoCollector
from .speedtest import SpeedtestCollector
from .bqm import BQMCollector
from .bnetz_watcher import BnetzWatcherCollector
from .backup import BackupCollector
from .weather import WeatherCollector

log = logging.getLogger("docsis.collectors")

# Registry maps collector name → class
COLLECTOR_REGISTRY = {
    "modem": ModemCollector,
    "demo": DemoCollector,
    "speedtest": SpeedtestCollector,
    "bqm": BQMCollector,
    "bnetz_watcher": BnetzWatcherCollector,
    "backup": BackupCollector,
    "weather": WeatherCollector,
}


def discover_collectors(config_mgr, storage, event_detector, mqtt_pub, web, analyzer, notifier=None):
    """Discover and instantiate all available collectors based on config.

    Args:
        config_mgr: Configuration manager instance
        storage: SnapshotStorage instance
        event_detector: EventDetector instance
        mqtt_pub: MQTTPublisher instance (or None)
        web: Web module reference
        analyzer: Analyzer module reference
        notifier: NotificationDispatcher instance (or None)

    Returns:
        List of instantiated Collector objects ready to poll.
    """
    collectors = []
    config = config_mgr.get_all()

    # Demo collector (replaces modem when DEMO_MODE is active)
    if config_mgr.is_demo_mode():
        log.info("Demo mode active — using DemoCollector")
        collectors.append(DemoCollector(
            analyzer_fn=analyzer.analyze,
            event_detector=event_detector,
            storage=storage,
            mqtt_pub=mqtt_pub,
            web=web,
            poll_interval=config["poll_interval"],
            notifier=notifier,
        ))
    # Modem collector (available if modem configured)
    elif config_mgr.is_configured():
        from ..drivers import load_driver

        modem_type = config.get("modem_type", "fritzbox")
        driver = load_driver(
            modem_type,
            config["modem_url"],
            config["modem_user"],
            config["modem_password"],
        )
        log.info("Modem driver: %s", modem_type)

        collectors.append(ModemCollector(
            driver=driver,
            analyzer_fn=analyzer.analyze,
            event_detector=event_detector,
            storage=storage,
            mqtt_pub=mqtt_pub,
            web=web,
            poll_interval=config["poll_interval"],
            notifier=notifier,
        ))
    
    # Speedtest collector (available if speedtest configured, but not in demo mode)
    if config_mgr.is_speedtest_configured() and not config_mgr.is_demo_mode():
        collectors.append(SpeedtestCollector(
            config_mgr=config_mgr,
            storage=storage,
            web=web,
            poll_interval=300,
        ))

    # BQM collector (available if BQM configured, but not in demo mode)
    if config_mgr.is_bqm_configured() and not config_mgr.is_demo_mode():
        collectors.append(BQMCollector(
            config_mgr=config_mgr,
            storage=storage,
            poll_interval=86400,
        ))

    # BNetzA watcher collector (available if watch dir configured, not in demo mode)
    if config_mgr.is_bnetz_watch_configured() and not config_mgr.is_demo_mode():
        collectors.append(BnetzWatcherCollector(
            config_mgr=config_mgr,
            storage=storage,
        ))

    # Backup collector (available if backup configured, not in demo mode)
    if config_mgr.is_backup_configured() and not config_mgr.is_demo_mode():
        interval_hours = config_mgr.get("backup_interval_hours", 24)
        collectors.append(BackupCollector(
            config_mgr=config_mgr,
            poll_interval=interval_hours * 3600,
        ))

    # Weather collector (available if weather configured, not in demo mode)
    if config_mgr.is_weather_configured() and not config_mgr.is_demo_mode():
        collectors.append(WeatherCollector(
            config_mgr=config_mgr,
            storage=storage,
            web=web,
            poll_interval=3600,
        ))

    return collectors


__all__ = [
    "Collector",
    "CollectorResult",
    "COLLECTOR_REGISTRY",
    "discover_collectors",
    "ModemCollector",
    "DemoCollector",
    "SpeedtestCollector",
    "BQMCollector",
    "BnetzWatcherCollector",
    "BackupCollector",
    "WeatherCollector",
]
