"""Network-free tests for the ARRIS SURFboard SB8200 (CBN firmware) driver."""

from __future__ import annotations

import base64
import hashlib
from unittest.mock import MagicMock

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import pytest
import requests

from app.drivers.formats.xml_payloads import parse_sb8200_cbn_xml
from app.drivers.sb8200_cbn import MAX_RESPONSE_BYTES, Query, SB8200CBNDriver

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
    response.raw.read.return_value = text.encode()
    return response


def _decrypt_envelope(field: str, token: str) -> str:
    """Decrypt a CBN login field, proving the modem could have read it.

    This is the inverse of the driver's encryption rather than a copy of it,
    so a field keyed with the wrong session token fails to decrypt.
    """
    payload = base64.b64decode(field).decode()
    ciphertext = bytes.fromhex(payload.split(":")[2])
    key = hashlib.sha256(token.encode()).digest()
    iv = hashlib.md5(token.encode(), usedforsecurity=False).digest()
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode()


def _driver(url: str = "https://modem.invalid", *, rotate: bool = False) -> SB8200CBNDriver:
    """Build a driver whose transport is mocked but whose cookie jar is real.

    With `rotate`, the fake reproduces the firmware's behaviour of issuing a
    new CSRF token on every response.
    """
    driver = SB8200CBNDriver(url, "admin", "s3cr3t-pw")
    session = MagicMock()
    session.cookies = requests.cookies.RequestsCookieJar()
    counter = {"n": 0}

    def next_token() -> str:
        if not rotate:
            return SESSION_TOKEN
        counter["n"] += 1
        return f"{int(SESSION_TOKEN) + counter['n']}"

    def get(_url: str, **kwargs):
        session.cookies.set("sessionToken", next_token())
        return _response("<html></html>")

    session.get.side_effect = get
    session.cookies.set("sessionToken", SESSION_TOKEN)
    driver._session = session
    driver._rotate_token = next_token
    return driver


def _serve(driver: SB8200CBNDriver, login_body: str = "successful;SID=2134823424") -> list[dict]:
    """Answer getter/setter posts from the captured payloads, recording calls."""
    calls: list[dict] = []

    def post(url: str, data: dict, **kwargs):
        calls.append({"url": url, "data": dict(data)})
        response = (
            _response(login_body) if url.endswith("setter.xml")
            else _response(GETTER_PAYLOADS.get(data["fun"], ""))
        )
        # The modem rotates its CSRF token on every response.
        driver._session.cookies.set("sessionToken", driver._rotate_token())
        return response

    driver._session.post.side_effect = post
    return calls


def _parse(
    ds: str | None = DOWNSTREAM_XML,
    us: str | None = UPSTREAM_XML,
    ofdm: str | None = OFDM_XML,
    ofdma: str | None = OFDMA_XML,
    signal: str | None = SIGNAL_XML,
):
    return parse_sb8200_cbn_xml(
        downstream_xml=ds, upstream_xml=us, downstream_ofdm_xml=ofdm,
        upstream_ofdma_xml=ofdma, signal_xml=signal,
    )


class TestParser:
    def test_downstream_scqam_joins_the_separate_codeword_table(self):
        assert _parse().value["channelDs"]["docsis30"] == [
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
        result = _parse()

        assert [c["channelID"] for c in result.value["channelDs"]["docsis30"]] == [32, 8]
        assert [c["channelID"] for c in result.value["channelUs"]["docsis30"]] == [56]

    def test_downstream_ofdm_reports_the_band_start_and_keeps_mse_unset(self):
        assert _parse().value["channelDs"]["docsis31"] == [{
            "channelID": 25, "type": "OFDM", "frequency": "605.6 MHz",
            "powerLevel": 1.1, "mse": None, "mer": 33.0, "modulation": "4096QAM",
        }]

    def test_unreliable_ofdm_codeword_counters_are_reported_as_unsupported(self):
        """The firmware's OFDM counters climb ~1.3M/min on a healthy channel.

        Reporting them as measured codewords would pin downstream health at
        critical, so the lane must stay counter-unsupported instead.
        """
        result = _parse()

        ofdm = result.value["channelDs"]["docsis31"][0]
        assert "corrErrors" not in ofdm and "nonCorrErrors" not in ofdm
        assert ("unsupported_counters", "ofdm_codewords") in [
            (d.code, d.field) for d in result.diagnostics
        ]

    def test_upstream_reports_the_measured_symbol_rate(self):
        assert _parse().value["channelUs"]["docsis30"] == [{
            "channelID": 56, "frequency": "37 MHz", "powerLevel": 49.0,
            "modulation": "64QAM", "multiplex": "ATDMA", "symbolRate": 5120,
        }]

    def test_missing_codeword_table_keeps_channels_without_inventing_counters(self):
        downstream = _parse(signal=None).value["channelDs"]["docsis30"]

        assert [c["channelID"] for c in downstream] == [32, 8]
        assert all("corrErrors" not in c and "nonCorrErrors" not in c for c in downstream)

    def test_malformed_codeword_table_degrades_to_a_diagnostic(self):
        result = _parse(signal="<signal_table>")

        assert [c["channelID"] for c in result.value["channelDs"]["docsis30"]] == [32, 8]
        assert ("invalid_xml", "signal_table") in [
            (d.code, d.field) for d in result.diagnostics
        ]

    def test_malformed_required_table_returns_no_value(self):
        result = _parse(ds="<downstream_table>")

        assert result.value is None
        assert [d.code for d in result.diagnostics] == ["invalid_xml"]

    @pytest.mark.parametrize("payload", [
        "<html><body>Login</body></html>",
        "<upstream_table><us_num>0</us_num></upstream_table>",
    ])
    def test_a_foreign_document_is_rejected_rather_than_read_as_zero_channels(self, payload):
        """An unauthenticated modem answers with a page, not an error.

        Treating that as a table holding no channels would look like a total
        signal loss and raise a false outage.
        """
        result = _parse(ds=payload)

        assert result.value is None
        assert [d.code for d in result.diagnostics] == ["invalid_xml"]

    def test_an_unknown_lock_marker_drops_the_row_with_a_diagnostic(self):
        downstream = (
            "<downstream_table><downstream><freq>567000000</freq><pow>2.3</pow>"
            "<snr>33</snr><mod>256QAM</mod><chid>32</chid>"
            "<IsLocked>Locked</IsLocked></downstream></downstream_table>"
        )

        result = _parse(ds=downstream)

        assert result.value["channelDs"]["docsis30"] == []
        assert ("unknown_lock_state", "IsLocked") in [
            (d.code, d.field) for d in result.diagnostics
        ]

    def test_a_missing_lock_marker_counts_as_locked(self):
        downstream = (
            "<downstream_table><downstream><freq>567000000</freq><pow>2.3</pow>"
            "<chid>32</chid></downstream></downstream_table>"
        )

        assert [c["channelID"] for c in _parse(ds=downstream).value["channelDs"]["docsis30"]] == [32]

    def test_an_unparsable_channel_is_reported_not_silently_dropped(self):
        downstream = (
            "<downstream_table><downstream><freq>567000000</freq><pow>nope</pow>"
            "<chid>32</chid><IsLocked>1</IsLocked></downstream></downstream_table>"
        )

        result = _parse(ds=downstream)

        assert result.value["channelDs"]["docsis30"] == []
        assert ("invalid_channel", "sc_qam") in [
            (d.code, d.field) for d in result.diagnostics
        ]

    def test_duplicate_and_unparsable_codeword_rows_are_reported(self):
        signal = (
            "<signal_table><signal><dsid>32</dsid><correctable>5</correctable>"
            "<uncorrectable>1</uncorrectable></signal>"
            "<signal><dsid>32</dsid><correctable>99</correctable>"
            "<uncorrectable>abc</uncorrectable></signal>"
            "<signal><dsid>x</dsid></signal></signal_table>"
        )

        result = _parse(signal=signal)

        codes = [d.code for d in result.diagnostics]
        assert "duplicate_row" in codes and "invalid_row" in codes
        first = result.value["channelDs"]["docsis30"][0]
        assert (first["corrErrors"], first["nonCorrErrors"]) == (5, 1)

    def test_active_ofdma_lane_is_reported_as_unsupported_rather_than_guessed(self):
        ofdma = (
            "<upstreamOFDMA_table><us_num>1</us_num>"
            "<upstream><usid>9</usid></upstream></upstreamOFDMA_table>"
        )

        result = _parse(ofdma=ofdma)

        assert result.value["channelUs"]["docsis31"] == []
        assert ("unsupported_lane", "upstream") in [
            (d.code, d.direction) for d in result.diagnostics
        ]

    @pytest.mark.parametrize("value", ["inf", "-inf", "nan", "1e400"])
    def test_non_finite_numbers_degrade_instead_of_crashing_the_poll(self, value):
        """Modem output is untrusted; a bad number must not escape the parser."""
        upstream = (
            "<upstream_table><upstream><usid>1</usid><freq>37000000</freq>"
            f"<power>49</power><srate>{value}</srate><usLocked>1</usLocked>"
            "</upstream></upstream_table>"
        )

        result = _parse(us=upstream)

        assert "symbolRate" not in result.value["channelUs"]["docsis30"][0]

    @pytest.mark.parametrize("value", ["inf", "nan"])
    def test_non_finite_power_is_rejected_rather_than_stored(self, value):
        upstream = (
            "<upstream_table><upstream><usid>1</usid><freq>37000000</freq>"
            f"<power>{value}</power><usLocked>1</usLocked></upstream></upstream_table>"
        )

        result = _parse(us=upstream)

        assert result.value["channelUs"]["docsis30"] == []
        assert ("invalid_channel", "sc_qam") in [
            (d.code, d.field) for d in result.diagnostics
        ]

    def test_empty_tables_produce_empty_lanes(self):
        result = _parse(
            ds="<downstream_table><ds_num>0</ds_num></downstream_table>",
            us="<upstream_table><us_num>0</us_num></upstream_table>",
            ofdm=None, ofdma=None, signal=None,
        )

        assert result.value == {
            "channelDs": {"docsis30": [], "docsis31": []},
            "channelUs": {"docsis30": [], "docsis31": []},
        }
        assert result.diagnostics == ()


class TestDriver:
    def test_plain_http_urls_are_upgraded(self):
        assert SB8200CBNDriver("http://192.168.100.1", "admin", "pw")._url == "https://192.168.100.1"

    def test_login_matches_the_firmware_encryption_envelope(self):
        driver = _driver()
        calls = _serve(driver)

        driver.login()

        login = next(c for c in calls if c["data"]["fun"] == "15")
        assert login["data"]["Username"] == ENCRYPTED_ADMIN
        assert login["data"]["Password"] == ENCRYPTED_PASSWORD
        assert driver._session.cookies.get("SID") == "2134823424"

    def test_credentials_are_keyed_with_the_token_the_request_carries(self):
        """The token rotates on every response, including the model lookup.

        Keying the envelope with a stale token yields credentials the modem
        cannot decrypt, so the posted token must be the one used.
        """
        driver = _driver(rotate=True)
        calls = _serve(driver)

        driver.login()

        login = next(c for c in calls if c["data"]["fun"] == "15")
        token = login["data"]["token"]
        assert _decrypt_envelope(login["data"]["Username"], token) == "admin"
        assert _decrypt_envelope(login["data"]["Password"], token) == "s3cr3t-pw"

    def test_login_is_not_repeated_while_a_session_is_held(self):
        driver = _driver()
        calls = _serve(driver)

        driver.login()
        driver.login()

        assert sum(1 for c in calls if c["data"]["fun"] == "15") == 1

    @pytest.mark.parametrize("body", [
        "unsuccessful;SID=0",
        "successful;SID=",
        "successful;SID=not a valid sid",
        "failed;reason=KDGloginincorrect",
    ])
    def test_only_a_well_formed_success_response_is_accepted(self, body):
        driver = _driver()
        _serve(driver, login_body=body)

        with pytest.raises(RuntimeError) as excinfo:
            driver.login()

        assert "KDGloginincorrect" not in str(excinfo.value)
        assert driver._logged_in is False
        assert driver._session.cookies.get("SID") is None

    def test_a_held_session_is_released_before_reauthenticating(self):
        """The modem permits one session, so the old one must be closed."""
        driver = _driver()
        calls = _serve(driver)
        driver.login()
        driver._logged_in = False

        driver.login()

        assert [c["data"]["fun"] for c in calls].count("16") == 1

    def test_expired_session_triggers_exactly_one_reauthentication(self):
        driver = _driver()
        driver._logged_in = True
        driver._hw_model = "SB8200v3"
        calls: list[dict] = []
        redirected = {"done": False}

        def post(url: str, data: dict, **kwargs):
            calls.append(dict(data))
            if url.endswith("setter.xml"):
                return _response("successful;SID=1")
            if data["fun"] == str(Query.SYSTEM_INFO.value) and not redirected["done"]:
                redirected["done"] = True
                return _response("")
            return _response(GETTER_PAYLOADS.get(data["fun"], ""))

        driver._session.post.side_effect = post

        assert driver.get_device_info()["model"] == "SB8200v3"
        assert sum(1 for c in calls if c["fun"] == "15") == 1

    def test_empty_body_without_a_held_session_does_not_retry_the_login(self):
        """The modem rate-limits repeated logins, so a poll must not loop."""
        driver = _driver()
        driver._logged_in = False
        calls: list[dict] = []

        def post(url: str, data: dict, **kwargs):
            calls.append(dict(data))
            return _response("")

        driver._session.post.side_effect = post

        with pytest.raises(RuntimeError, match="no data"):
            driver._get_data(Query.DOWNSTREAM_TABLE)
        assert [c for c in calls if c["fun"] == "15"] == []

    def test_a_redirect_is_treated_as_session_loss(self):
        """A lapsed session answers every table code with a 302.

        Measured on the device: after the session drops, fun=10/11/19 all
        redirect while fun=1 still returns 200.
        """
        driver = _driver()
        driver._logged_in = True
        driver._hw_model = "SB8200v3"
        calls: list[dict] = []
        redirected = {"done": False}

        def post(url: str, data: dict, **kwargs):
            calls.append(dict(data))
            if url.endswith("setter.xml"):
                return _response("successful;SID=1")
            if data["fun"] == str(Query.DOWNSTREAM_TABLE.value) and not redirected["done"]:
                redirected["done"] = True
                return _response("", status=302)
            return _response(GETTER_PAYLOADS.get(data["fun"], ""))

        driver._session.post.side_effect = post

        assert driver._get_data(Query.DOWNSTREAM_TABLE) == DOWNSTREAM_XML
        assert sum(1 for c in calls if c["fun"] == "15") == 1

    def test_a_persistent_redirect_gives_up_without_looping(self):
        """One login per call, so a wedged table cannot hammer the limiter."""
        driver = _driver()
        driver._logged_in = True
        driver._hw_model = "SB8200v3"
        calls: list[dict] = []

        def post(url: str, data: dict, **kwargs):
            calls.append(dict(data))
            if url.endswith("setter.xml"):
                return _response("successful;SID=1")
            return _response("", status=302)

        driver._session.post.side_effect = post

        with pytest.raises(RuntimeError, match="after re-authentication"):
            driver._get_data(Query.DOWNSTREAM_TABLE)
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

    def test_device_info_falls_back_without_claiming_measured_values(self):
        driver = _driver()
        driver._logged_in = False
        driver._session.post.side_effect = lambda url, data, **kw: _response("")

        assert driver.get_device_info() == {
            "manufacturer": "ARRIS", "model": "SB8200", "sw_version": "",
        }

    def test_connection_info_reports_mode_without_inventing_rates(self):
        driver = _driver()
        _serve(driver)

        assert driver.get_connection_info() == {"connection_type": "DOCSIS 3.1"}

    def test_unreadable_channel_payload_raises(self):
        driver = _driver()
        driver._session.post.side_effect = lambda url, data, **kw: _response("<downstream_table>")

        with pytest.raises(ValueError):
            driver.get_docsis_data()

    def test_transport_errors_propagate(self):
        driver = _driver()
        failing = _response("")
        failing.raise_for_status.side_effect = requests.HTTPError("boom")
        driver._session.post.side_effect = lambda url, data, **kw: failing

        with pytest.raises(requests.HTTPError):
            driver._get_data(Query.DOWNSTREAM_TABLE)

    def test_oversized_response_is_refused_before_parsing(self):
        driver = _driver()
        oversized = _response("<downstream_table/>")
        oversized.raw.read.return_value = b"x" * (MAX_RESPONSE_BYTES + 1)
        driver._session.post.side_effect = lambda url, data, **kw: oversized

        with pytest.raises(RuntimeError, match="size limit"):
            driver.get_docsis_data()

    def test_only_the_bounded_prefix_is_read_from_the_socket(self):
        driver = _driver()
        payload = _response(DOWNSTREAM_XML)
        driver._session.post.side_effect = lambda url, data, **kw: payload

        driver._get_data(Query.DOWNSTREAM_TABLE)

        payload.raw.read.assert_called_once_with(
            MAX_RESPONSE_BYTES + 1, decode_content=True
        )

    def test_cleanup_releases_the_single_web_ui_session(self):
        driver = _driver()
        _serve(driver)
        driver.login()
        session = driver._session

        SB8200CBNDriver._cleanup("https://modem.invalid", session)

        logouts = [
            c for c in session.post.call_args_list
            if c.kwargs.get("data", {}).get("fun") == str(16)
        ]
        assert logouts, "expected a logout post"
        assert session.cookies.get("SID") is None
        session.close.assert_called_once()

    def test_cleanup_never_raises(self):
        session = MagicMock()
        session.cookies = requests.cookies.RequestsCookieJar()
        session.cookies.set("SID", "1")
        session.post.side_effect = requests.ConnectionError("down")

        SB8200CBNDriver._cleanup("https://modem.invalid", session)

        session.close.assert_called_once()

    @pytest.mark.parametrize("uptime,expected", [
        ("14day(s)20h:50m:40s", 1284640),
        ("0day(s)0h:0m:5s", 5),
        ("nonsense", None),
        ("", None),
    ])
    def test_uptime_parsing(self, uptime, expected):
        assert SB8200CBNDriver._uptime_seconds(uptime) == expected
