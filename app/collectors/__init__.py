"""Collector registry and discovery.

Provides a registry-based pattern for discovering and instantiating
data collectors based on runtime configuration.
"""

import logging

from .base import Collector, CollectorResult
from .modem import ModemCollector
from .demo import DemoCollector
from ..config import SECRET_KEYS, HASH_KEYS

log = logging.getLogger("docsis.collectors")


class _ModuleConfigProxy:
    """Read-only config proxy that hides secrets from community modules.

    Builtin modules receive the real ConfigManager.  Community modules
    get this proxy which blocks access to modem_password, admin_password,
    mqtt_password, and other secret/hash keys unless they are specifically
    declared in the module's own config defaults.
    """

    def __init__(self, config_mgr, allowed_secret_keys=frozenset()):
        self._cfg = config_mgr
        self._blocked = (SECRET_KEYS | HASH_KEYS) - set(allowed_secret_keys)

    def get(self, key, default=None):
        if key in self._blocked:
            return default
        return self._cfg.get(key, default)

    def get_all(self, mask_secrets=False):
        result = self._cfg.get_all(mask_secrets=True)
        for key in self._blocked:
            result.pop(key, None)
        return result

    def is_configured(self):
        return self._cfg.is_configured()

    def is_demo_mode(self):
        return self._cfg.is_demo_mode()

    @property
    def data_dir(self):
        return self._cfg.data_dir

# Registry maps collector name -> class
COLLECTOR_REGISTRY = {
    "modem": ModemCollector,
    "demo": DemoCollector,
}


def discover_collectors(config_mgr, storage, event_detector, mqtt_pub, web, analyzer, notifier=None, smart_capture=None):
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
            smart_capture=smart_capture,
        ))
    # Modem collector (available if modem configured)
    elif config_mgr.is_configured():
        from ..drivers import driver_registry

        modem_type = config.get("modem_type", "fritzbox")
        driver = driver_registry.load_driver(
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
            smart_capture=smart_capture,
        ))

        # Segment utilization collector (FritzBox only)
        if modem_type == "fritzbox":
            from .segment_utilization import SegmentUtilizationCollector
            segment_collector = SegmentUtilizationCollector(
                config_mgr=config_mgr,
                storage=storage,
                web=web,
            )
            if segment_collector.is_enabled():
                collectors.append(segment_collector)

    # ── Module collectors ──
    module_loader = web.get_module_loader() if hasattr(web, 'get_module_loader') else None
    if module_loader:
        for mod in module_loader.get_enabled_modules():
            if mod.collector_class:
                try:
                    # Community modules get a restricted config proxy that
                    # hides secrets not declared in their own config defaults.
                    if mod.builtin:
                        mod_cfg = config_mgr
                    else:
                        mod_cfg = _ModuleConfigProxy(
                            config_mgr,
                            allowed_secret_keys=set(mod.config_secrets) & SECRET_KEYS,
                        )
                    c = mod.collector_class(
                        config_mgr=mod_cfg,
                        storage=storage,
                        web=web,
                    )
                    collectors.append(c)
                    log.info("Module collector: %s (%s)", mod.id, c.name)
                except Exception as e:
                    log.warning("Module collector '%s' failed to init: %s", mod.id, e)

    return collectors


__all__ = [
    "Collector",
    "CollectorResult",
    "COLLECTOR_REGISTRY",
    "discover_collectors",
    "ModemCollector",
    "DemoCollector",
]
