"""Static registry for DOCSight's built-in modules.

Built-ins are part of the application release.  Keep their directory list and
Python contribution symbols explicit so startup does not discover core modules
by scanning a plugin directory.
"""

from __future__ import annotations

from dataclasses import dataclass


BUILTIN_MODULE_DIRS: tuple[str, ...] = (
    "backup",
    "bnetz",
    "bqm",
    "comparison",
    "connection_monitor",
    "evidence",
    "journal",
    "modulation",
    "mqtt",
    "reports",
    "smokeping",
    "speedtest",
    "theme_amber_terminal",
    "theme_catppuccin_mocha",
    "theme_classic",
    "theme_doom",
    "theme_dracula",
    "theme_gameboy",
    "theme_gruvbox",
    "theme_matrix",
    "theme_nord",
    "theme_ocean",
    "theme_one_dark",
    "theme_synthwave",
    "theme_tokyo_night",
    "theme_tribu",
    "thresholds_vfkd",
    "weather",
)


@dataclass(frozen=True)
class BuiltinPythonContributions:
    """Import paths for Python entry points owned by a built-in module."""

    collector: str | None = None
    publisher: str | None = None
    driver: str | None = None


BUILTIN_PYTHON_CONTRIBUTIONS: dict[str, BuiltinPythonContributions] = {
    "docsight.backup": BuiltinPythonContributions(
        collector="app.modules.backup.collector:BackupCollector",
    ),
    "docsight.bnetz": BuiltinPythonContributions(
        collector="app.modules.bnetz.collector:BnetzWatcherCollector",
    ),
    "docsight.bqm": BuiltinPythonContributions(
        collector="app.modules.bqm.collector:BQMCollector",
    ),
    "docsight.connection_monitor": BuiltinPythonContributions(
        collector="app.modules.connection_monitor.collector:ConnectionMonitorCollector",
    ),
    "docsight.mqtt": BuiltinPythonContributions(
        publisher="app.modules.mqtt.publisher:MQTTPublisher",
    ),
    "docsight.speedtest": BuiltinPythonContributions(
        collector="app.modules.speedtest.collector:SpeedtestCollector",
    ),
    "docsight.weather": BuiltinPythonContributions(
        collector="app.modules.weather.collector:WeatherCollector",
    ),
}
