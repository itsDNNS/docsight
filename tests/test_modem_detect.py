"""Opt-in local modem detection (app/modem_detect.py)."""

import io
from pathlib import Path

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.response import HTTPResponse

from app import modem_detect
from app.drivers import driver_registry

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeResponse:
    def __init__(self, body: bytes, encoding="utf-8"):
        self._body = body
        self.encoding = encoding

    def iter_content(self, chunk_size):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_get(pages):
    """pages: url -> bytes body; anything else fails like an unreachable host."""
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url not in pages:
            raise requests.ConnectionError(url)
        return FakeResponse(pages[url])

    get.calls = calls
    return get


def test_fixture_pages_suggest_their_driver():
    sb6183 = (FIXTURES / "sb6183" / "RgConnect.asp.html").read_text()
    cm1000 = (FIXTURES / "cm1000" / "DocsisStatus.asp.html").read_text()
    assert modem_detect.match_drivers(sb6183) == ["sb6183"]
    assert modem_detect.match_drivers(cm1000) == ["cm1000"]


def test_matching_reads_visible_text_case_insensitively():
    page = "<html><head><title>FRITZ!Box 6690 Cable</title></head><body>Willkommen</body></html>"
    assert modem_detect.match_drivers(page) == ["fritzbox"]
    assert modem_detect.match_drivers("<p>Vodafone&nbsp;Station</p>") == ["vodafone_station"]
    assert modem_detect.match_drivers("<p>Router login</p>") == []
    assert modem_detect.match_drivers(None) == []


def test_ambiguous_models_offer_every_candidate():
    assert modem_detect.match_drivers("<title>ARRIS SB8200</title>") == ["surfboard", "sb8200_cbn"]


def test_suggestions_are_limited_to_installed_drivers():
    assert modem_detect.match_drivers("<title>SB8200</title>", known_drivers={"surfboard"}) == ["surfboard"]


def test_every_keyword_belongs_to_a_builtin_driver():
    builtins = {key for key, _ in driver_registry.get_available_drivers()}
    assert set(modem_detect.DRIVER_KEYWORDS) <= builtins
    assert all(keywords and all(k == k.lower() for k in keywords) for keywords in modem_detect.DRIVER_KEYWORDS.values())


def test_detect_probes_only_the_fixed_addresses_with_a_short_timeout():
    get = fake_get({
        "http://192.168.100.1": b"<title>NETGEAR Modem CM1000v2</title>",
        "https://10.0.0.1": b"<title>Login</title>",
    })
    devices = modem_detect.detect_modems(get=get)

    assert devices == [
        {"host": "192.168.100.1", "url": "http://192.168.100.1", "drivers": ["cm1000"]},
        {"host": "10.0.0.1", "url": "https://10.0.0.1", "drivers": []},
    ]
    probed = {url for url, _ in get.calls}
    expected = {f"{scheme}://{host}" for host in modem_detect.CANDIDATE_HOSTS for scheme in ("http", "https")}
    # HTTPS is only tried where HTTP failed.
    assert probed == expected - {"https://192.168.100.1"}
    assert all(kwargs["timeout"] == modem_detect.PROBE_TIMEOUT_SECONDS for _, kwargs in get.calls)
    assert all("auth" not in kwargs and "data" not in kwargs for _, kwargs in get.calls)


def test_start_pages_are_read_only_up_to_the_limit():
    filler = b"x" * (modem_detect.MAX_BODY_BYTES + 10)
    get = fake_get({"http://192.168.0.1": filler + b"Vodafone Station"})
    assert modem_detect.probe_host("192.168.0.1", get=get) == {
        "host": "192.168.0.1", "url": "http://192.168.0.1", "drivers": []}


HITRON_LOGIN_PAGE = b'<html><head><title></title><script src="lib/jquery.hitronext.js"></script></head></html>'


def test_hitron_login_page_model_is_read_from_its_public_version_endpoint():
    version = b'{"errCode": "000", "modelName": "CODA-4582-RES", "MacAddress": "00:00:00:00:00:00"}'
    get = fake_get({
        "http://192.168.0.1": HITRON_LOGIN_PAGE,
        "http://192.168.0.1/1/Device/CM/Version": version,
    })

    assert modem_detect.probe_host("192.168.0.1", get=get) == {
        "host": "192.168.0.1", "url": "http://192.168.0.1", "drivers": ["hitron_coda_4680"]}
    assert [url for url, _ in get.calls] == ["http://192.168.0.1", "http://192.168.0.1/1/Device/CM/Version"]
    assert get.calls[0][1] == get.calls[1][1]


@pytest.mark.parametrize("version", [None, b"<html></html>", b'["CODA-4680"]', b'{"modelName": 4680}', b"[" * 60000])
def test_unusable_hitron_version_reply_suggests_nothing(version):
    pages = {"http://192.168.0.1": HITRON_LOGIN_PAGE}
    if version is not None:
        pages["http://192.168.0.1/1/Device/CM/Version"] = version

    assert modem_detect.probe_host("192.168.0.1", get=fake_get(pages))["drivers"] == []


@pytest.mark.parametrize("charset", ["no-such-charset", "idna"])
def test_unusable_charset_does_not_break_detection(charset):
    def get(url, **kwargs):
        return FakeResponse(b"<title>CODA-4680</title>", encoding=charset)

    assert modem_detect.probe_host("192.168.0.1", get=get) is None


class Body(io.BytesIO):
    def close(self):
        self.bytes_read = self.tell()
        super().close()


def fake_transport(replies, sent):
    """Stands in for the network below requests: url -> (status, headers, body)."""
    def send(adapter, request, **kwargs):
        sent.append((request.url, request.headers.get("Authorization"), kwargs.get("proxies")))
        status, headers, body = replies[request.url]
        send.bodies[request.url] = Body(body)
        raw = HTTPResponse(body=send.bodies[request.url], headers=headers, status=status, preload_content=False)
        return adapter.build_response(request, raw)
    send.bodies = {}
    return send


def test_redirects_are_followed_only_on_the_probed_address(monkeypatch):
    sent = []
    monkeypatch.setattr(HTTPAdapter, "send", fake_transport({
        "http://192.168.0.1/": (302, {"Location": "/webpages/login.html"}, b""),
        "http://192.168.0.1/webpages/login.html": (200, {}, HITRON_LOGIN_PAGE),
        "http://192.168.0.1/1/Device/CM/Version": (302, {"Location": "http://example.com/"}, b""),
        "http://example.com/": (200, {}, b'{"modelName": "CODA-4680"}'),
    }, sent))

    assert modem_detect.probe_host("192.168.0.1")["drivers"] == []
    assert [url for url, _, _ in sent] == [
        "http://192.168.0.1/", "http://192.168.0.1/webpages/login.html", "http://192.168.0.1/1/Device/CM/Version"]


@pytest.mark.parametrize("location", [
    "http://example.com\\@192.168.0.1/",
    "http://user:secret@192.168.0.1/",
    "http://%C4%80:secret@192.168.0.1/",
])
def test_redirects_to_another_host_or_with_credentials_are_not_followed(monkeypatch, location):
    sent = []
    monkeypatch.setattr(HTTPAdapter, "send", fake_transport({
        "http://192.168.0.1/": (302, {"Location": location}, b""),
    }, sent))

    assert modem_detect.probe_host("192.168.0.1") is not None
    assert sent == [("http://192.168.0.1/", None, {})]


def test_redirect_replies_are_not_read(monkeypatch):
    transport = fake_transport({
        "http://192.168.0.1/": (302, {"Location": "/webpages/login.html"}, b"x" * (4 * modem_detect.MAX_BODY_BYTES)),
        "http://192.168.0.1/webpages/login.html": (200, {}, b"<title>CODA-4680</title>"),
    }, [])
    monkeypatch.setattr(HTTPAdapter, "send", transport)

    assert modem_detect.probe_host("192.168.0.1")["drivers"] == ["hitron_coda_4680"]
    assert transport.bodies["http://192.168.0.1/"].bytes_read == 0


@pytest.mark.parametrize("status", [200, 302])
def test_malformed_location_does_not_break_detection(monkeypatch, status):
    monkeypatch.setattr(HTTPAdapter, "send", fake_transport({
        "http://192.168.0.1/": (status, {"Location": "http://[bad"}, b"<title>CODA-4680</title>"),
    }, []))

    assert modem_detect.probe_host("192.168.0.1") is not None


def test_probes_ignore_netrc_credentials_and_proxies(monkeypatch, tmp_path):
    netrc = tmp_path / "netrc"
    netrc.write_text("machine 192.168.0.1 login user password secret\n")
    netrc.chmod(0o600)
    monkeypatch.setenv("NETRC", str(netrc))
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:3128")
    sent = []
    monkeypatch.setattr(HTTPAdapter, "send", fake_transport({
        "http://192.168.0.1/": (200, {}, b"<title>CODA-4680</title>"),
    }, sent))

    assert modem_detect.probe_host("192.168.0.1")["drivers"] == ["hitron_coda_4680"]
    assert sent == [("http://192.168.0.1/", None, {})]


def test_coda_4582_names_suggest_the_coda_4680_driver():
    assert modem_detect.match_drivers("<title>CODA-4582-RES Login</title>") == ["hitron_coda_4680"]
    assert modem_detect.match_drivers("<p>coda4582</p>") == ["hitron_coda_4680"]


def test_nothing_answering_returns_no_devices():
    assert modem_detect.detect_modems(get=fake_get({})) == []


@pytest.fixture
def setup_client(tmp_path):
    from app.app_factory import create_app
    from app.config import ConfigManager

    application = create_app(config_manager=ConfigManager(str(tmp_path)))
    application.config["TESTING"] = True
    return application.test_client()


def test_detect_endpoint_takes_no_input_and_returns_devices(setup_client, monkeypatch):
    seen = {}

    def detect(known_drivers):
        seen["known"] = known_drivers
        return [{"host": "192.168.178.1", "url": "http://192.168.178.1", "drivers": ["fritzbox"]}]

    monkeypatch.setattr(modem_detect, "detect_modems", detect)
    response = setup_client.post("/api/setup/detect-modem", json={"hosts": ["203.0.113.5"]})
    assert response.status_code == 200
    assert response.get_json() == {"devices": [
        {"host": "192.168.178.1", "url": "http://192.168.178.1", "drivers": ["fritzbox"]}]}
    assert "fritzbox" in seen["known"]
    assert setup_client.get("/api/setup/detect-modem").status_code == 405
