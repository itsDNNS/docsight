"""Replay synthetic TG HTTP responses through the real collection pipeline."""

from pathlib import Path
from unittest.mock import patch


def seed_vodafone_tg_data(runtime):
    from requests import Response

    from app.analyzer import analyze
    from app.collectors.modem import ModemCollector
    from app.drivers.vodafone_station import VodafoneStationDriver
    from app.event_detector import EventDetector

    html = (Path(__file__).parents[2] / "fixtures/vodafone_tg/status_docsis_data.html").read_text()
    responses = {
        "http://tg.test/php/status_docsis_data.php": html,
        "http://tg.test/php/status_status_data.php": """
            js_HWTypeVersion = 'TG6442VF';
            js_FWVersion = 'synthetic';
            js_ipv4addr = '';
            js_ipv6addr = '';
            js_UptimeSinceReboot = '0,3,25';
        """,
        "http://tg.test/?status_status": """
            _ga.modemConnectionStatus = 'DOCSIS Online';
            _ga.lastRebootReason = 'Power On';
        """,
    }

    def get(url, **kwargs):
        response = Response()
        response.status_code = 200
        response.encoding = "utf-8"
        response._content = responses[url].encode("utf-8")
        return response

    driver = VodafoneStationDriver("http://tg.test", "admin", "synthetic")
    # Start with an authenticated session; payload parsing remains real.
    driver._variant = driver.VARIANT_TG
    driver._tg_nonce = "test-session"
    driver._session.cookies.set("credential", "synthetic")
    collector = ModemCollector(
        driver=driver, analyzer_fn=analyze, event_detector=EventDetector(),
        storage=runtime.storage, mqtt_pub=None, web=runtime, poll_interval=300,
    )
    with patch.object(driver._session, "get", side_effect=get):
        collector.collect()
