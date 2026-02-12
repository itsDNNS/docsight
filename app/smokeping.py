"""Smokeping integration for DOCSight.

Fetches RRD data or CSV exports from a Smokeping instance and
presents latency/loss data alongside DOCSIS metrics.
"""

import logging
import re
import time

import requests

log = logging.getLogger("docsis.smokeping")


class SmokepingClient:
    """Client for fetching data from a Smokeping instance."""

    def __init__(self, base_url: str, target: str = ""):
        """Initialize Smokeping client.

        Args:
            base_url: Base URL of the Smokeping web interface (e.g. http://smokeping:8067)
            target: Target path in Smokeping hierarchy (e.g. "ISP.Router")
        """
        self.base_url = base_url.rstrip("/")
        self.target = target

    def get_graph_url(self, period: str = "3hours") -> str:
        """Return the URL for a Smokeping graph image.

        Args:
            period: Time period (3hours, 30hours, 10days, 365days)
        """
        target_param = self.target.replace(".", "/") if self.target else ""
        return f"{self.base_url}/smokeping/smokeping.cgi?target={target_param}&displaymode=n&start=end-{period}"

    def fetch_graph(self, period: str = "3hours") -> bytes | None:
        """Fetch Smokeping graph as PNG image bytes.

        Args:
            period: Time period for the graph.

        Returns:
            PNG image bytes or None on failure.
        """
        try:
            url = self.get_graph_url(period)
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            if r.headers.get("Content-Type", "").startswith("image/"):
                return r.content
            log.warning("Smokeping returned non-image content")
            return None
        except Exception as e:
            log.error("Failed to fetch Smokeping graph: %s", e)
            return None

    def fetch_data(self, start: str = "end-24h", end: str = "now") -> list[dict] | None:
        """Fetch Smokeping CSV data for a target.

        Tries the Smokeping CGI CSV export. Returns a list of dicts with:
            timestamp, median_ms, loss_pct, min_ms, max_ms, avg_ms

        Args:
            start: Start time (RRD-style, e.g. "end-24h", "end-7d")
            end: End time (RRD-style)

        Returns:
            List of data points or None on failure.
        """
        try:
            target_param = self.target.replace(".", "/") if self.target else ""
            url = (
                f"{self.base_url}/smokeping/smokeping.cgi"
                f"?target={target_param}&displaymode=c&start={start}&end={end}"
            )
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            return self._parse_csv(r.text)
        except Exception as e:
            log.error("Failed to fetch Smokeping data: %s", e)
            return None

    def _parse_csv(self, csv_text: str) -> list[dict]:
        """Parse Smokeping CSV output into data points."""
        results = []
        lines = csv_text.strip().split("\n")

        for line in lines:
            # Skip comments and headers
            if line.startswith("#") or not line.strip():
                continue

            parts = line.split(",")
            if len(parts) < 3:
                continue

            try:
                # Smokeping CSV format: timestamp, median_rtt, loss, rtt_1, rtt_2, ...
                timestamp = int(float(parts[0]))
                median = float(parts[1]) * 1000 if parts[1] and parts[1] != "U" else None
                loss_count = int(parts[2]) if parts[2] and parts[2] != "U" else 0

                # Parse individual RTTs
                rtts = []
                for p in parts[3:]:
                    if p and p != "U":
                        try:
                            rtts.append(float(p) * 1000)  # Convert to ms
                        except ValueError:
                            pass

                total_probes = len(parts) - 3  # number of probe columns
                loss_pct = (loss_count / total_probes * 100) if total_probes > 0 else 0

                results.append({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(timestamp)),
                    "median_ms": round(median, 2) if median else None,
                    "loss_pct": round(loss_pct, 1),
                    "min_ms": round(min(rtts), 2) if rtts else None,
                    "max_ms": round(max(rtts), 2) if rtts else None,
                    "avg_ms": round(sum(rtts) / len(rtts), 2) if rtts else None,
                })
            except (ValueError, IndexError):
                continue

        return results

    def health_check(self) -> bool:
        """Check if the Smokeping instance is reachable."""
        try:
            r = requests.get(f"{self.base_url}/smokeping/smokeping.cgi", timeout=5)
            return r.status_code == 200
        except Exception:
            return False
