"""Fetch ThinkBroadband BQM quality graphs."""

import logging
import urllib.request

log = logging.getLogger("docsis.thinkbroadband")


def fetch_graph(url, timeout=30):
    """Download BQM graph PNG from ThinkBroadband. Returns bytes or None on error."""
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DOCSight/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if len(data) < 100:
            log.warning("BQM graph too small (%d bytes), skipping", len(data))
            return None
        log.info("BQM graph fetched (%d bytes)", len(data))
        return data
    except Exception as e:
        log.error("Failed to fetch BQM graph: %s", e)
        return None
