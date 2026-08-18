"""Network-free tests for the ARRIS SURFboard SB8200 (CBN firmware) driver."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from app.drivers.formats.xml_payloads import parse_sb8200_cbn_xml
from app.drivers.sb8200_cbn import Query, SB8200CBNDriver

# Captured from an SB8200v3 on AC01.01.008_122722_8200.03.07.733 and trimmed to
# the channels needed here. The serial number is redacted.
DOWNSTREAM_XML = (
    '<?xml version="1.0" encoding="utf-8"?><downstream_table><ds_num>3</ds_num>'
    "<downstream><freq>567000000</freq><pow>2.300</pow><snr>33</snr>"
    "<mod>256QAM</mod><chid>32</chid><IsLocked>1</IsLocked></downstream>"
    "<downstream><freq>411000000</freq><pow>0.400</pow><snr>35</snr>"
    "<mod>64QAM</mod><chid>8</chid><IsLocked>1</IsLocked></downstream>"
    "<downstream><freq>417000000</freq><pow>0.100</pow><snr>34</snr>"
    "<mod>256QAM</mod><chid>9</chid><IsLocked>0</IsLocked></downstream>"
    "</downstream_table>"
)
UPSTREAM_XML = (
    '<?xml version="1.0" encoding="utf-8"?><upstream_table><us_num>2</us_num>'
    "<upstream><usid>56</usid><freq>37000000</freq><power>49</power>"
    "<srate>5.120</srate><mod>64QAM</mod><channeltype>ATDMA</channeltype>"
    "<bandwidth>6400000</bandwidth><usLocked>1</usLocked></upstream>"
    "<upstream><usid>55</usid><freq>30600000</freq><power>48</power>"
    "<srate>5.120</srate><mod>64QAM</mod><channeltype>ATDMA</channeltype>"
    "<bandwidth>6400000</bandwidth><usLocked>0</usLocked></upstream>"
    "</upstream_table>"
)
OFDM_XML = (
    '<?xml version="1.0" encoding="utf-8"?><downstreamOFDM_table><downstream>'
    "<Receiver>1</Receiver><FFTType>4K</FFTType>"
    "<Subcarr0Frequency>605600000</Subcarr0Frequency><PLCLocked>YES</PLCLocked>"
    "<NCPLocked>YES</NCPLocked><MDC1Locked>YES</MDC1Locked>"
    "<PLCPower>1.100</PLCPower><plcFrequency>668000000</plcFrequency>"
    "<ScatrPilotAvgMer>39</ScatrPilotAvgMer><PlcScAvgMer>34</PlcScAvgMer>"
    "<DataScAvgMer>33</DataScAvgMer><ofdmModulation>QAM4096</ofdmModulation>"
    "<dsid>25</dsid><ofdmCorrected>904607089</ofdmCorrected>"
    "<ofdmUncorrectable>2612685723</ofdmUncorrectable>"
    "<ofdmIsLocked>1</ofdmIsLocked><ofdmIsActive>1</ofdmIsActive>"
    "</downstream><ds_num>1</ds_num></downstreamOFDM_table>"
)
OFDMA_XML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    "<upstreamOFDMA_table><us_num>0</us_num></upstreamOFDMA_table>"
)
SIGNAL_XML = (
    '<?xml version="1.0" encoding="utf-8"?><signal_table><sig_num>3</sig_num>'
    "<signal><dsid>25</dsid><unerrored>0</unerrored><correctable>0</correctable>"
    "<uncorrectable>0</uncorrectable></signal>"
    "<signal><dsid>32</dsid><unerrored>54275570015</unerrored>"
    "<correctable>226053938</correctable><uncorrectable>1212</uncorrectable></signal>"
    "<signal><dsid>8</dsid><unerrored>431</unerrored><correctable>7</correctable>"
    "<uncorrectable>3</uncorrectable></signal></signal_table>"
)
SYSTEM_INFO_XML = (
    '<?xml version="1.0" encoding="utf-8"?><cm_system_info>'
    "<HwModel>SB8200v3</HwModel>"
    "<SwVersion>AC01.01.008_122722_8200.03.07.733</SwVersion>"
    "<cm_hardware_version>0.03</cm_hardware_version>"
    "<cm_serial_number>REDACTEDSERIAL1</cm_serial_number>"
    "<cm_system_uptime>14day(s)20h:50m:40s</cm_system_uptime>"
    "<CurrentTime>17.08.2026, 18:36</CurrentTime><cm_status_OK>OK</cm_status_OK>"
    "<cm_status>OPERATIONAL</cm_status>"
    "<cm_network_access>Allowed</cm_network_access>"
    "<cm_docsis_mode>DOCSIS 3.1</cm_docsis_mode></cm_system_info>"
)
GLOBAL_SETTINGS_XML = (
    '<?xml version="1.0" encoding="utf-8"?><GlobalSettings>'
    "<AccessLevel>1</AccessLevel><title>CBN</title>"
    "<SwVersion>AC01.01.008_122722_8200.03.07.733</SwVersion>"
    "<HwModel>SB8200v3</HwModel></GlobalSettings>"
)

SESSION_TOKEN = "1132952832"
# Independently produced with:
#   openssl enc -aes-256-cbc -K sha256(token) -iv md5(token) -nosalt
ENCRYPTED_ADMIN = "SFM6U0I4MjAwdjM6YjBmY2RlMmUwN2I3ZTlmN2Q3NzZkNTg2ZjE1MTcwZWI="
ENCRYPTED_PASSWORD = "SFM6U0I4MjAwdjM6MDkzM2M4ZGI1YzMzYWU2ZWVhYjgzZGNiYzMwZTUxZjE="

GETTER_PAYLOADS = {
    str(Query.GLOBAL_SETTINGS.value): GLOBAL_SETTINGS_XML,
    str(Query.SYSTEM_INFO.value): SYSTEM_INFO_XML,
    str(Query.UPSTREAM_OFDMA_TABLE.value): OFDMA_XML,
    str(Query.DOWNSTREAM_OFDM_TABLE.value): OFDM_XML,
    str(Query.DOWNSTREAM_TABLE.value): DOWNSTREAM_XML,
    str(Query.UPSTREAM_TABLE.value): UPSTREAM_XML,
    str(Query.SIGNAL_TABLE.value): SIGNAL_XML,
}


def _response(text: str, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.content = text.encode()
    response.status_code = status
    return response


def _driver(url: str = "https://modem.invalid") -> SB8200CBNDriver:
    """Build a driver whose transport is mocked but whose cookie jar is real."""
    driver = SB8200CBNDriver(url, "admin", "s3cr3t-pw")
    session = MagicMock()
    session.cookies = requests.cookies.RequestsCookieJar()

    def get(_url: str, **kwargs):
        # The login page is what issues a fresh rotating CSRF token.
        session.cookies.set("sessionToken", SESSION_TOKEN)
        return _response("<html></html>")

    session.get.side_effect = get
    session.cookies.set("sessionToken", SESSION_TOKEN)
    driver._session = session
    return driver


def _serve(driver: SB8200CBNDriver, login_body: str = "successful;SID=2134823424") -> list[dict]:
    """Answer getter/setter posts from the captured payloads, recording calls."""
    calls: list[dict] = []

    def post(url: str, data: dict, **kwargs):
        calls.append({"url": url, "data": data})
        if url.endswith("setter.xml"):
            return _response(login_body)
        return _response(GETTER_PAYLOADS.get(data["fun"], ""))

    driver._session.post.side_effect = post
    return calls


class TestParser:
    def test_downstream_scqam_joins_the_separate_codeword_table(self):
        result = parse_sb8200_cbn_xml(
            DOWNSTREAM_XML, UPSTREAM_XML, OFDM_XML, OFDMA_XML, SIGNAL_XML
        )

        downstream = result.value["channelDs"]["docsis30"]
        assert downstream == [
            {
                "channelID": 32, "frequency": "567 MHz", "powerLevel": 2.3,
                "mer": 33.0, "mse": -33.0, "modulation": "256QAM",
                "symbolRate": 5361, "corrErrors": 226053938, "nonCorrErrors": 1212,
            },
            {
                "channelID": 8, "frequency": "411 MHz", "powerLevel": 0.4,
                "mer": 35.0, "mse": -35.0, "modulation": "64QAM",
                "symbolRate": 5057, "corrErrors": 7, "nonCorrErrors": 3,
            },
        ]

    def test_unlocked_channels_are_skipped_in_both_directions(self):
        result = parse_sb8200_cbn_xml(
            DOWNSTREAM_XML, UPSTREAM_XML, OFDM_XML, OFDMA_XML, SIGNAL_XML
        )

        assert [c["channelID"] for c in result.value["channelDs"]["docsis30"]] == [32, 8]
        assert [c["channelID"] for c in result.value["channelUs"]["docsis30"]] == [56]

    def test_downstream_ofdm_reports_the_band_start_and_keeps_mse_unset(self):
        result = parse_sb8200_cbn_xml(
            DOWNSTREAM_XML, UPSTREAM_XML, OFDM_XML, OFDMA_XML, SIGNAL_XML
        )

        assert result.value["channelDs"]["docsis31"] == [{
            "channelID": 25, "type": "OFDM", "frequency": "605.6 MHz",
            "powerLevel": 1.1, "mse": None, "mer": 33.0, "modulation": "4096QAM",
        }]

    def test_unreliable_ofdm_codeword_counters_are_reported_as_unsupported(self):
        """The firmware's OFDM counters climb ~1.3M/min on a healthy channel.

        Reporting them as measured codewords would pin downstream health at
        critical, so the lane must stay counter-unsupported instead.
        """
        result = parse_sb8200_cbn_xml(
            DOWNSTREAM_XML, UPSTREAM_XML, OFDM_XML, OFDMA_XML, SIGNAL_XML
        )

        ofdm = result.value["channelDs"]["docsis31"][0]
        assert "corrErrors" not in ofdm and "nonCorrErrors" not in ofdm
        assert ("unsupported_counters", "ofdm_codewords") in [
            (d.code, d.field) for d in result.diagnostics
        ]

    def test_upstream_reports_the_measured_symbol_rate(self):
        result = parse_sb8200_cbn_xml(
            DOWNSTREAM_XML, UPSTREAM_XML, OFDM_XML, OFDMA_XML, SIGNAL_XML
        )

        assert result.value["channelUs"]["docsis30"] == [{
            "channelID": 56, "frequency": "37 MHz", "powerLevel": 49.0,
            "modulation": "64QAM", "type": "ATDMA", "multiplex": "ATDMA",
            "symbolRate": 5120,
        }]

    def test_annex_b_symbol_rates_are_injected_per_modulation(self):
        result = parse_sb8200_cbn_xml(
            DOWNSTREAM_XML, UPSTREAM_XML, OFDM_XML, OFDMA_XML, SIGNAL_XML
        )

        rates = {c["modulation"]: c["symbolRate"] for c in result.value["channelDs"]["docsis30"]}
        assert rates == {"256QAM": 5361, "64QAM": 5057}

    def test_missing_codeword_table_keeps_channels_without_inventing_counters(self):
        result = parse_sb8200_cbn_xml(
            DOWNSTREAM_XML, UPSTREAM_XML, OFDM_XML, OFDMA_XML, None
        )

        downstream = result.value["channelDs"]["docsis30"]
        assert [c["channelID"] for c in downstream] == [32, 8]
        assert all("corrErrors" not in c and "nonCorrErrors" not in c for c in downstream)

    def test_malformed_codeword_table_degrades_to_a_diagnostic(self):
        result = parse_sb8200_cbn_xml(
            DOWNSTREAM_XML, UPSTREAM_XML, OFDM_XML, OFDMA_XML, "<signal_table>"
        )

        assert [c["channelID"] for c in result.value["channelDs"]["docsis30"]] == [32, 8]
        assert [(d.code, d.field) for d in result.diagnostics] == [
            ("invalid_xml", "signal_table"),
            ("unsupported_counters", "ofdm_codewords"),
        ]

    def test_malformed_required_table_returns_no_value(self):
        result = parse_sb8200_cbn_xml(
            "<downstream_table>", UPSTREAM_XML, OFDM_XML, OFDMA_XML, SIGNAL_XML
        )

        assert result.value is None
        assert [d.code for d in result.diagnostics] == ["invalid_xml"]

    def test_active_ofdma_lane_is_reported_as_unsupported_rather_than_guessed(self):
        ofdma = (
            "<upstreamOFDMA_table><us_num>1</us_num>"
            "<upstream><usid>9</usid></upstream></upstreamOFDMA_table>"
        )

        result = parse_sb8200_cbn_xml(
            DOWNSTREAM_XML, UPSTREAM_XML, OFDM_XML, ofdma, SIGNAL_XML
        )

        assert result.value["channelUs"]["docsis31"] == []
        assert [(d.code, d.direction) for d in result.diagnostics] == [
            ("unsupported_counters", "downstream"),
            ("unsupported_lane", "upstream"),
        ]

    def test_empty_tables_produce_empty_lanes(self):
        result = parse_sb8200_cbn_xml(
            "<downstream_table><ds_num>0</ds_num></downstream_table>",
            "<upstream_table><us_num>0</us_num></upstream_table>",
            None, None, None,
        )

        assert result.value == {
            "channelDs": {"docsis30": [], "docsis31": []},
            "channelUs": {"docsis30": [], "docsis31": []},
        }
        assert result.diagnostics == ()


class TestDriver:
    def test_plain_http_urls_are_upgraded(self):
        driver = SB8200CBNDriver("http://192.168.100.1", "admin", "pw")

        assert driver._url == "https://192.168.100.1"

    def test_login_matches_the_firmware_encryption_envelope(self):
        driver = _driver()
        calls = _serve(driver)

        driver.login()

        login = next(c for c in calls if c["url"].endswith("setter.xml"))
        assert login["data"]["fun"] == "15"
        assert login["data"]["Username"] == ENCRYPTED_ADMIN
        assert login["data"]["Password"] == ENCRYPTED_PASSWORD
        assert driver._session.cookies.get("SID") == "2134823424"

    def test_login_is_not_repeated_while_a_session_is_held(self):
        driver = _driver()
        calls = _serve(driver)

        driver.login()
        driver.login()

        assert sum(1 for c in calls if c["data"]["fun"] == "15") == 1

    def test_rejected_credentials_raise_without_echoing_the_response(self):
        driver = _driver()
        _serve(driver, login_body="failed;reason=KDGloginincorrect")

        with pytest.raises(RuntimeError) as excinfo:
            driver.login()

        assert "KDGloginincorrect" not in str(excinfo.value)
        assert driver._logged_in is False

    def test_expired_session_triggers_exactly_one_reauthentication(self):
        driver = _driver()
        driver._logged_in = True
        driver._hw_model = "SB8200v3"
        calls: list[dict] = []
        redirected = {"done": False}

        def post(url: str, data: dict, **kwargs):
            calls.append(data)
            if url.endswith("setter.xml"):
                return _response("successful;SID=1")
            if data["fun"] == str(Query.SYSTEM_INFO.value) and not redirected["done"]:
                redirected["done"] = True
                return _response("", status=302)
            return _response(GETTER_PAYLOADS.get(data["fun"], ""))

        driver._session.post.side_effect = post

        info = driver.get_device_info()

        assert info["model"] == "SB8200v3"
        assert sum(1 for c in calls if c["fun"] == "15") == 1

    def test_docsis_data_is_normalized_through_the_profile(self):
        driver = _driver()
        _serve(driver)

        data = driver.get_docsis_data()

        assert [c["channelID"] for c in data["channelDs"]["docsis30"]] == [32, 8]
        assert [c["channelID"] for c in data["channelDs"]["docsis31"]] == [25]
        assert [c["channelID"] for c in data["channelUs"]["docsis30"]] == [56]
        assert data["channelUs"]["docsis31"] == []

    def test_device_info_never_exposes_the_serial_number(self):
        driver = _driver()
        _serve(driver)

        info = driver.get_device_info()

        assert info == {
            "manufacturer": "ARRIS",
            "model": "SB8200v3",
            "hw_version": "0.03",
            "sw_version": "AC01.01.008_122722_8200.03.07.733",
            "docsis_status": "OPERATIONAL",
            "uptime_seconds": 1284640,
        }
        assert "REDACTEDSERIAL1" not in str(info)

    def test_connection_info_reports_mode_without_inventing_rates(self):
        driver = _driver()
        _serve(driver)

        assert driver.get_connection_info() == {"connection_type": "DOCSIS 3.1"}

    def test_unreadable_channel_payload_raises(self):
        driver = _driver()
        driver._session.post.side_effect = lambda url, data, **kw: _response("<downstream_table>")

        with pytest.raises(ValueError):
            driver.get_docsis_data()

    def test_oversized_response_is_refused_before_parsing(self):
        driver = _driver()
        oversized = _response("<downstream_table/>")
        oversized.content = b"x" * (1_048_576 + 1)
        driver._session.post.side_effect = lambda url, data, **kw: oversized

        with pytest.raises(RuntimeError, match="size limit"):
            driver.get_docsis_data()

    @pytest.mark.parametrize("uptime,expected", [
        ("14day(s)20h:50m:40s", 1284640),
        ("0day(s)0h:0m:5s", 5),
        ("nonsense", None),
        ("", None),
    ])
    def test_uptime_parsing(self, uptime, expected):
        assert SB8200CBNDriver._uptime_seconds(uptime) == expected
