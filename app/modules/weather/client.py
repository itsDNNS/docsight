"""Open-Meteo weather API client for outdoor temperature data."""

import logging

import requests

log = logging.getLogger("docsis.weather")

# Open-Meteo API endpoints (free, no API key required)
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


class OpenMeteoClient:
    """Fetch hourly temperature data from the Open-Meteo API."""

    def __init__(self, latitude, longitude, timeout=15):
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def get_current(self):
        """Fetch current temperature and recent hourly data (last 24h + forecast).

        Returns:
            list of dicts: [{"timestamp": "...", "temperature": float}, ...]
        """
        resp = self.session.get(
            FORECAST_URL,
            params={
                "latitude": self.latitude,
                "longitude": self.longitude,
                "hourly": "temperature_2m",
                "past_days": 1,
                "forecast_days": 1,
                "timezone": "UTC",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return self._parse_hourly(resp.json())

    def get_historical(self, start_date, end_date):
        """Fetch historical hourly temperature data for a date range.

        Args:
            start_date: ISO date string (YYYY-MM-DD)
            end_date: ISO date string (YYYY-MM-DD)

        Returns:
            list of dicts: [{"timestamp": "...", "temperature": float}, ...]
        """
        resp = self.session.get(
            ARCHIVE_URL,
            params={
                "latitude": self.latitude,
                "longitude": self.longitude,
                "hourly": "temperature_2m",
                "start_date": start_date,
                "end_date": end_date,
                "timezone": "UTC",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return self._parse_hourly(resp.json())

    @staticmethod
    def _parse_hourly(data):
        """Parse Open-Meteo hourly response into list of dicts."""
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        results = []
        for ts, temp in zip(times, temps):
            if temp is not None:
                results.append({
                    "timestamp": ts.replace("T", " ") + ":00Z" if "Z" not in ts else ts,
                    "temperature": round(temp, 1),
                })
        return results
