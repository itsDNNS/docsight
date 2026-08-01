from unittest.mock import MagicMock, call, patch

import pytest
import requests

from app.drivers.cm1000 import CM1000Driver

STATUS_HTML = """
<html><head><title>NETGEAR Cable Modem CM1000</title></head><body>
<table id="dsTable">
<tr><td><span class="thead">Channel</span></td><td><span class="thead">Lock Status</span></td><td><span class="thead">Modulation</span></td><td><span class="thead">Channel ID</span></td><td><span class="thead">Frequency</span></td><td><span class="thead">Power</span></td><td><span class="thead">SNR/MER</span></td><td><span class="thead">Unerrored Codewords</span></td><td><span class="thead">Correctable Codewords</span></td><td><span class="thead">Uncorrectable Codewords</span></td></tr>
<tr><td>1</td><td>Locked</td><td>256QAM</td><td>7</td><td>591000000 Hz</td><td>-2.5 dBmV</td><td>40.0 dB</td><td>1,000,000</td><td>1,234</td><td>5</td></tr>
<tr><td>2</td><td>Not Locked</td><td>256QAM</td><td>8</td><td>597000000 Hz</td><td>0.0 dBmV</td><td>0.0 dB</td><td>0</td><td>999</td><td>999</td></tr>
</table>
<table id="usTable">
<tr><th>Channel</th><th>Lock Status</th><th>Channel Type</th><th>Channel ID</th><th>Frequency</th><th>Power</th></tr>
<tr><td>1</td><td>Locked</td><td>ATDMA</td><td>3</td><td>29200000 Hz</td><td>43.5 dBmV</td></tr>
</table>
<table id="d31dsTable">
<tr><th>Channel</th><th>Lock Status</th><th>Modulation</th><th>Channel ID</th><th>Frequency</th><th>Power</th><th>SNR/MER</th><th>Active Subcarrier Number Range</th><th>Unerrored Codewords</th><th>Correctables</th><th>UnCorrectables</th></tr>
<tr><td>1</td><td>Locked</td><td>OFDM PLC</td><td>159</td><td>960000000 Hz</td><td>6.0 dBmV</td><td>41.2 dB</td><td>148 ~ 3947</td><td>999999</td><td>1,148</td><td>12</td></tr>
</table>
<table id="d31usTable">
<tr><th>Channel</th><th>Lock Status</th><th>Modulation</th><th>Channel ID</th><th>Frequency</th><th>Power</th></tr>
<tr><td>1</td><td>Locked</td><td>OFDMA Profile 12</td><td>41</td><td>36200000 Hz</td><td>36.5 dBmV</td></tr>
</table>
</body></html>
"""

NINE_COLUMN_HTML = """
<table id="dsTable">
<tr><td>Channel</td><td>Lock Status</td><td>Modulation</td><td>Channel ID</td><td>Frequency</td><td>Power</td><td>SNR</td><td>Correctables</td><td>UnCorrectables</td></tr>
<tr><td>1</td><td>Locked</td><td>QAM 256</td><td>1</td><td>387000000 Hz</td><td>5.8 dBmV</td><td>40.9 dB</td><td>7</td><td>2</td></tr>
</table>
"""

SIXTY_FOUR_QAM_HTML = """
<table id="dsTable">
<tr><th>Channel</th><th>Lock Status</th><th>Modulation</th><th>Channel ID</th><th>Frequency</th><th>Power</th><th>SNR</th><th>Correctables</th><th>UnCorrectables</th></tr>
<tr><td>1</td><td>Locked</td><td>64QAM</td><td>2</td><td>393000000 Hz</td><td>1.0 dBmV</td><td>35.0 dB</td><td>0</td><td>0</td></tr>
</table>
"""

LOGIN_HTML = """
<html><body><form name="login" action="/goform/GenieLogin">
<input type="hidden" name="webToken" value="abc123">
<input type="hidden" name="login" value="1">
<input type="text" name="loginUsername" value="">
<input type="password" name="loginPassword" value="">
<input type="submit" value="Log In">
</form></body></html>
"""

@pytest.fixture
def driver():
    return CM1000Driver("http://192.168.100.1/", "admin", "secret")


def response(text="", status=200):
    result = MagicMock()
    result.text = text
    result.status_code = status
    result.raise_for_status.side_effect = (
        requests.HTTPError(f"HTTP {status}") if status >= 400 else None
    )
    return result


def test_init_normalizes_url_and_sets_basic_auth(driver):
    assert driver._url == "http://192.168.100.1"
    assert driver._session.auth == ("admin", "secret")


def test_login_accepts_direct_basic_auth_status_page(driver):
    status = response(STATUS_HTML)
    with patch.object(driver._session, "get", return_value=status) as get:
        driver.login()
    get.assert_called_once_with("http://192.168.100.1/DocsisStatus.asp", timeout=30)
    assert driver._status_html == STATUS_HTML


def test_login_uses_genie_webtoken_form_flow(driver):
    wrapper = response("<html>login required</html>", status=401)
    login = response(LOGIN_HTML)
    submitted = response("ok")
    status = response(STATUS_HTML)

    with patch.object(driver._session, "get", side_effect=[wrapper, login, status]) as get, patch.object(
        driver._session, "post", return_value=submitted
    ) as post:
        driver.login()

    assert get.call_args_list == [
        call("http://192.168.100.1/DocsisStatus.asp", timeout=30),
        call("http://192.168.100.1/GenieLogin.asp", timeout=30),
        call("http://192.168.100.1/DocsisStatus.asp", timeout=30),
    ]
    post.assert_called_once_with(
        "http://192.168.100.1/goform/GenieLogin",
        data={
            "webToken": "abc123",
            "login": "1",
            "loginUsername": "admin",
            "loginPassword": "secret",
        },
        timeout=30,
    )
    assert driver._status_html == STATUS_HTML


def test_login_rejects_non_status_page_after_form_login(driver):
    with patch.object(
        driver._session,
        "get",
        side_effect=[response("login", 401), response(LOGIN_HTML), response("still login")],
    ), patch.object(driver._session, "post", return_value=response("ok")):
        with pytest.raises(RuntimeError, match="did not return DocsisStatus.asp"):
            driver.login()


def test_login_retries_once_on_connection_reset(driver):
    new_session = MagicMock()
    new_session.auth = ("admin", "secret")
    new_session.get.return_value = response(STATUS_HTML)

    with patch.object(driver._session, "get", side_effect=requests.ConnectionError("reset")), patch(
        "app.drivers.cm1000.requests.Session", return_value=new_session
    ):
        driver.login()

    assert driver._status_html == STATUS_HTML


def test_parses_all_four_channel_families(driver):
    driver._status_html = STATUS_HTML
    data = driver.get_docsis_data()

    ds30 = data["channelDs"]["docsis30"]
    us30 = data["channelUs"]["docsis30"]
    ds31 = data["channelDs"]["docsis31"]
    us31 = data["channelUs"]["docsis31"]

    assert ds30 == [{
        "channelID": 7,
        "frequency": "591 MHz",
        "powerLevel": -2.5,
        "mer": 40.0,
        "mse": -40.0,
        "modulation": "256QAM",
        "symbolRate": 5361,
        "corrErrors": 1234,
        "nonCorrErrors": 5,
    }]
    assert us30 == [{
        "channelID": 3,
        "frequency": "29.2 MHz",
        "powerLevel": 43.5,
        "modulation": "ATDMA",
        "multiplex": "ATDMA",
    }]
    assert ds31 == [{
        "channelID": 159,
        "type": "OFDM",
        "frequency": "960 MHz",
        "powerLevel": 6.0,
        "mer": 41.2,
        "mse": None,
        "modulation": "OFDM",
        "corrErrors": 1148,
        "nonCorrErrors": 12,
    }]
    assert us31 == [{
        "channelID": 41,
        "type": "OFDMA",
        "frequency": "36.2 MHz",
        "powerLevel": 36.5,
        "modulation": "OFDMA",
        "multiplex": "",
    }]


def test_header_mapping_supports_layout_without_unerrored_column(driver):
    driver._status_html = NINE_COLUMN_HTML
    channel = driver.get_docsis_data()["channelDs"]["docsis30"][0]
    assert channel["corrErrors"] == 7
    assert channel["nonCorrErrors"] == 2
    assert channel["modulation"] == "256QAM"
    assert channel["symbolRate"] == 5361


def test_sets_annex_b_symbol_rate_for_64qam_downstream(driver):
    driver._status_html = SIXTY_FOUR_QAM_HTML
    channel = driver.get_docsis_data()["channelDs"]["docsis30"][0]
    assert channel["modulation"] == "64QAM"
    assert channel["symbolRate"] == 5057


def test_status_html_is_reused_for_entire_collection_cycle(driver):
    driver._status_html = STATUS_HTML
    with patch.object(driver._session, "get") as get:
        driver.get_docsis_data()
        driver.get_device_info()
    get.assert_not_called()


def test_device_and_connection_info(driver):
    assert driver.get_device_info() == {
        "manufacturer": "Netgear",
        "model": "CM1000",
        "sw_version": "",
    }
    assert driver.get_connection_info() == {}

def test_load_via_registry():
    from app.drivers import load_driver
    loaded = load_driver("cm1000", "http://192.168.100.1", "admin", "secret")
    assert isinstance(loaded, CM1000Driver)
