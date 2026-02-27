"""Weather collector — fetches outdoor temperature from Open-Meteo API."""

import logging
from datetime import datetime, timedelta, timezone

from .base import Collector, CollectorResult
from ..weather import OpenMeteoClient

log = logging.getLogger("docsis.collector.weather")


class WeatherCollector(Collector):
    """Fetches outdoor temperature data and caches it locally.

    On first run, backfills historical data to match the existing signal
    history window. Subsequent polls fetch only the latest hourly data.
    """

    name = "weather"

    def __init__(self, config_mgr, storage, web, poll_interval=3600):
        super().__init__(poll_interval)
        self._config_mgr = config_mgr
        self._storage = storage
        self._web = web
        self._client = None
        self._last_coords = None
        self._backfilled = False

    def is_enabled(self) -> bool:
        return self._config_mgr.is_weather_configured()

    def _ensure_client(self):
        """Re-initialize client if configured coordinates changed."""
        lat = self._config_mgr.get("weather_latitude")
        lon = self._config_mgr.get("weather_longitude")
        coords = (lat, lon)
        if coords != self._last_coords:
            self._client = OpenMeteoClient(lat, lon)
            self._last_coords = coords
            log.info("Weather: lat=%s, lon=%s", lat, lon)

    def collect(self) -> CollectorResult:
        self._ensure_client()

        try:
            # Backfill historical data on first run
            if not self._backfilled and self._storage.get_weather_count() == 0:
                self._backfill()
                self._backfilled = True

            # Fetch recent data (last 24h + current)
            records = self._client.get_current()
            if records:
                self._storage.save_weather_data(records)
                self._web.update_state(weather_latest={
                    "timestamp": records[-1]["timestamp"],
                    "temperature": records[-1]["temperature"],
                })
                log.debug("Weather: saved %d hourly records", len(records))

            return CollectorResult(source=self.name, data=records[-1] if records else None)
        except Exception as e:
            return CollectorResult(source=self.name, success=False, error=str(e))

    def _backfill(self):
        """Fetch historical temperature data to match existing signal history."""
        try:
            # Default: 90 days of history (Open-Meteo archive supports years back)
            now = datetime.now(timezone.utc)
            end_date = now.strftime("%Y-%m-%d")
            start_date = (now - timedelta(days=90)).strftime("%Y-%m-%d")

            records = self._client.get_historical(start_date, end_date)
            if records:
                self._storage.save_weather_data(records)
                log.info("Weather backfill: saved %d records (%s to %s)",
                         len(records), start_date, end_date)
        except Exception as e:
            log.warning("Weather backfill failed: %s", e)
