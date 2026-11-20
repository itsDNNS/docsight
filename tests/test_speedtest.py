"""Tests for Speedtest Tracker client and API endpoint."""

import threading

import pytest
import requests
from unittest.mock import patch, MagicMock

from app.modules.speedtest.client import SpeedtestClient
from app.modules.speedtest.collector import SpeedtestCollector
from app.modules.speedtest.storage import SpeedtestStorage
from app.config import ConfigManager, PASSWORD_MASK
from app.runtime import current_runtime
from app.storage import SnapshotStorage
from app.storage.sqlite import write_transaction
from tests.test_smart_capture_api import configured_client

pytestmark = pytest.mark.usefixtures("route_app")


# ── Sample API responses ──

SAMPLE_RESULT = {
    "id": 1,
    "ping": 12.5,
    "download_bits": 1_100_000_000,
    "upload_bits": 55_000_000,
    "download_bits_human": "1.10 Gbps",
    "upload_bits_human": "55.00 Mbps",
    "status": "completed",
    "healthy": True,
    "created_at": "2025-01-15T10:30:00Z",
    "data": {
        "ping": {"jitter": 2.3},
        "packetLoss": 0.5,
        "timestamp": "2025-01-15T10:30:00Z",
    },
}

SAMPLE_RESULT_MINIMAL = {
    "id": 2,
    "ping": 8.0,
    "download_bits": 500_000_000,
    "upload_bits": 25_000_000,
    "download_bits_human": "500.00 Mbps",
    "upload_bits_human": "25.00 Mbps",
    "status": "completed",
    "healthy": None,
    "created_at": "2025-01-14T08:00:00Z",
    "data": {},
}

SAMPLE_API_RESPONSE = {
    "data": [SAMPLE_RESULT, SAMPLE_RESULT_MINIMAL],
}

# Speedtest Tracker lists a test as soon as it starts, without measurements
UNFINISHED_STATUSES = ("waiting", "started", "checking", "running", "benchmarking")
STARTED_RESULT = {"id": 3, "created_at": "2025-01-16T10:30:00Z", "data": {}}


SYNC_CALLS = [("get_results", {"per_page": 500}), ("get_newer_than", {"floor": 0, "known_ids": set()})]
# Replies that do not list results prove nothing about the Tracker's contents
REPLIES_WITHOUT_RESULTS = pytest.mark.parametrize(
    "reply", [{}, {"data": {}}, {"data": ""}, {"data": [{"status": "completed"}]}, {"data": [{"id": True}]}],
    ids=["missing", "object", "string", "without-id", "boolean-id"],
)


def _stt_api(stt):
    """Fake results endpoint paging through stt["data"] (newest first) like Speedtest Tracker."""
    def get(url, params, **kwargs):
        size, page = params["page[size]"], params.get("page[number]", 1)
        data = stt.get("data", [])
        body = {"meta": {"last_page": max(1, -(-len(data) // size))}}
        if "data" in stt:
            body["data"] = data[(page - 1) * size:page * size] if isinstance(data, list) else data
        return MagicMock(**{"json.return_value": body})
    return get


# ── Client Tests ──


class TestSpeedtestClient:
    def _make_client(self):
        return SpeedtestClient("http://speedtest.local:8999", "test-token")

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [SAMPLE_RESULT]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        results = client.get_latest(1)

        assert len(results) == 1
        r = results[0]
        assert r["download_mbps"] == 1100.0
        assert r["upload_mbps"] == 55.0
        assert r["ping_ms"] == 12.5
        assert r["jitter_ms"] == 2.3
        assert r["packet_loss_pct"] == 0.5
        assert r["download_human"] == "1.10 Gbps"
        assert r["timestamp"] == "2025-01-15T10:30:00Z"

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        results = client.get_latest(1)
        assert results == []

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_connection_error(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")

        client = self._make_client()
        results = client.get_latest(1)
        assert results == []

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_results_pagination(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {**SAMPLE_API_RESPONSE, "meta": {"last_page": 1}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        results = client.get_results(per_page=100)

        assert len(results) == 2
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["page[size]"] == 100
        assert params["page[number]"] == 1

    @REPLIES_WITHOUT_RESULTS
    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_full_read_reports_a_reply_without_results(self, mock_get, reply):
        """A full read that would mark the cache as reread must not take such a reply for an empty page."""
        mock_get.side_effect = _stt_api(reply)
        assert self._make_client().get_results_with_error(per_page=500) == ([], "Unexpected error, see the DOCSight log")

    @pytest.mark.parametrize("page", [
        {"data": [SAMPLE_RESULT]}, {"data": [SAMPLE_RESULT], "meta": {"last_page": 1}}, {"data": [], "meta": {"last_page": 2}},
    ], ids=["no-last-page", "last-page", "empty"])
    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_full_read_ending_on_a_page_that_links_to_more_is_incomplete(self, mock_get, page):
        mock_get.return_value.json.return_value = {**page, "links": {"next": "?page[number]=2"}}
        results, error = self._make_client().get_results_with_error(per_page=500)
        assert ([r["id"] for r in results], error) == ([1] if page["data"] else [], "Unexpected error, see the DOCSight log")

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_results_connection_error(self, mock_get):
        mock_get.side_effect = Exception("Timeout")

        client = self._make_client()
        results = client.get_results()
        assert results == []

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_parse_minimal_result(self, mock_get):
        """Result with empty data dict should not crash."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [SAMPLE_RESULT_MINIMAL]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        results = client.get_latest(1)

        assert len(results) == 1
        r = results[0]
        assert r["ping_ms"] == 8.0
        assert r["jitter_ms"] is None
        assert r["packet_loss_pct"] is None

    @pytest.mark.parametrize("method, kwargs", SYNC_CALLS)
    @pytest.mark.parametrize("status, kept", [
        *((status, False) for status in UNFINISHED_STATUSES),
        ("completed", True), ("failed", True), (None, True),
    ])
    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_sync_skips_unfinished_results(self, mock_get, status, kept, method, kwargs):
        item = {**STARTED_RESULT, "status": status}
        if status is None:
            del item["status"]  # older Speedtest Tracker versions send none
        mock_get.side_effect = _stt_api({"data": [item, SAMPLE_RESULT]})

        ids = [r["id"] for r in getattr(self._make_client(), method)(**kwargs)]
        assert sorted(ids) == ([1, 3] if kept else [1])

    @pytest.mark.parametrize("method, kwargs", SYNC_CALLS)
    @pytest.mark.parametrize("newest, broken", [(500, []), (501, [{"id": 1000, "data": "unparsable"}])],
                             ids=["complete", "parse-error"])
    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_sync_returns_500_distinct_results(self, mock_get, newest, broken, method, kwargs):
        """Pages do not overlap after skipping a running result, and a parse error keeps the cap."""
        running = {**STARTED_RESULT, "id": newest + 1, "status": "running"}
        items = [running, *({**SAMPLE_RESULT, "id": i} for i in range(newest, 0, -1)), *broken]
        mock_get.side_effect = _stt_api({"data": items})

        ids = [r["id"] for r in getattr(self._make_client(), method)(**kwargs)]
        assert sorted(ids) == list(range(newest - 499, newest + 1))

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_newer_than_scans_past_a_lower_id(self, mock_get):
        """Tracker sorts by creation time, which can tie, so a lower id can come first."""
        mock_get.side_effect = _stt_api({"data": [{**SAMPLE_RESULT, "id": i} for i in (7, 4, 6)]})

        assert [r["id"] for r in self._make_client().get_newer_than(5, {5})] == [6, 7]

    def test_auth_headers(self):
        client = self._make_client()
        assert client.session.headers["Authorization"] == "Bearer test-token"
        assert client.session.headers["Accept"] == "application/json"

    def test_explicit_null_measurements_stay_unknown(self):
        result = self._make_client()._parse_result({
            "ping": None, "data": {"ping": {"jitter": None}, "packetLoss": None},
        })
        assert result["ping_ms"] is None
        assert result["jitter_ms"] is None
        assert result["packet_loss_pct"] is None

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_insecure_tls_disables_certificate_verification(self, mock_get):
        """Self-hosted HTTPS instances with self-signed certs can opt out of cert verification."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [SAMPLE_RESULT]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = SpeedtestClient("https://speedtest.local:8443", "[REDACTED]", tls_insecure=True)
        results = client.get_latest(1)

        assert len(results) == 1
        assert mock_get.call_args.kwargs["verify"] is False

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_string_false_keeps_certificate_verification_enabled(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [SAMPLE_RESULT]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = SpeedtestClient("https://speedtest.local:8443", "[REDACTED]", tls_insecure="false")
        results = client.get_latest(1)

        assert len(results) == 1
        assert mock_get.call_args.kwargs["verify"] is True

    def test_url_trailing_slash(self):
        client = SpeedtestClient("http://example.com:8999/", "tok")
        assert client.base_url == "http://example.com:8999"

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_with_error_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [SAMPLE_RESULT]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        results, error = client.get_latest_with_error(1)
        assert len(results) == 1
        assert error is None

    @pytest.mark.parametrize(("raised", "expected"), [
        (requests.ConnectionError("Connection refused"), "Cannot reach Speedtest Tracker"),
        (requests.Timeout("timed out"), "Speedtest Tracker timeout"),
        (requests.ConnectTimeout("connect timed out"), "Speedtest Tracker timeout"),
        (requests.exceptions.InvalidHeader("Invalid header value b'Bearer leaked-token'"),
         "Unexpected error, see the DOCSight log"),
    ])
    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_with_error_reports_fixed_messages(self, mock_get, raised, expected):
        mock_get.side_effect = raised

        client = self._make_client()
        results, error = client.get_latest_with_error(1)
        assert results == []
        assert error == expected

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_with_error_http_error(self, mock_get):
        import requests as req
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = req.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        client = self._make_client()
        results, error = client.get_latest_with_error(1)
        assert results == []
        assert "401" in error


# ── Config Tests ──


class TestSpeedtestConfig:
    def test_is_speedtest_configured_false(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
        assert not mgr.is_speedtest_configured()

    def test_is_speedtest_configured_url_only(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({"modem_password": "test", "modem_type": "fritzbox", "speedtest_tracker_url": "http://x"})
        assert not mgr.is_speedtest_configured()

    def test_is_speedtest_configured_true(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({
            "modem_password": "test",
            "modem_type": "fritzbox",
            "speedtest_tracker_url": "http://x",
            "speedtest_tracker_token": "tok",
        })
        assert mgr.is_speedtest_configured()

    def test_token_is_encrypted(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({
            "modem_password": "test",
            "modem_type": "fritzbox",
            "speedtest_tracker_token": "my-secret-token",
        })
        # Raw value in file should not be the plaintext
        import json
        with open(mgr.config_path) as f:
            raw = json.load(f)
        assert raw["speedtest_tracker_token"] != "my-secret-token"
        # But get() returns decrypted
        assert mgr.get("speedtest_tracker_token") == "my-secret-token"

    def test_speedtest_tls_insecure_is_boolean_config(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({"speedtest_tls_insecure": "true"})
        assert mgr.get("speedtest_tls_insecure") is True


# ── API Tests ──



STT_CONFIG = {"speedtest_tracker_url": "http://speedtest.local:8999", "speedtest_tracker_token": "test-token"}


@pytest.fixture
def speedtest_client(tmp_path):
    with configured_client(tmp_path / "data", **STT_CONFIG) as client:
        yield client


@pytest.fixture(params=["route", "collector"])
def stt_sync(request, tmp_path):
    """One of the two sync callers over a cache of 50 results, the fake Tracker data, the cache and on_import."""
    storage = SnapshotStorage(str(tmp_path / "core.db"), max_days=7)
    cache = SpeedtestStorage(storage.db_path)
    cache.save_speedtest_results([
        {"id": i, "timestamp": "2025-01-01T00:00:00Z", "download_mbps": 100.0, "upload_mbps": 10.0,
         "download_human": "", "upload_human": "", "ping_ms": 5.0, "jitter_ms": 1.0, "packet_loss_pct": 0.0}
        for i in range(1, 51)
    ])
    stt = {}
    with patch("app.modules.speedtest.client.requests.Session.get", side_effect=_stt_api(stt)), \
            configured_client(tmp_path / "data", storage, **STT_CONFIG) as client:
        collector = SpeedtestCollector(current_runtime().config_manager, storage, current_runtime())
        collector.on_import = MagicMock()  # Smart Capture
        current_runtime().collectors = [collector]
        page = client.application.test_client  # a new client per request, so requests can overlap
        sync = collector.collect if request.param == "collector" else lambda: page().get("/api/speedtest")
        yield sync, stt, cache, collector.on_import


@pytest.mark.parametrize("newer", [[], [{**SAMPLE_RESULT, "id": 52}]], ids=["newest", "out-of-order"])
def test_running_result_is_cached_once_finished(stt_sync, newer):
    """A test still running is neither cached as failed nor taken for a wiped server."""
    sync, stt, cache, _ = stt_sync
    stt["data"] = [*newer, {**STARTED_RESULT, "id": 51, "status": "running"}, {**SAMPLE_RESULT, "id": 50}]
    sync()
    assert cache.get_speedtest_by_id(51) is None
    assert cache.get_speedtest_count() == 50 + len(newer)

    stt["data"][len(newer)] = {**SAMPLE_RESULT, "id": 51}
    sync()
    finished = cache.get_speedtest_by_id(51)
    assert (finished["download_mbps"], finished["ping_ms"]) == (1100.0, 12.5)


@REPLIES_WITHOUT_RESULTS
def test_reply_without_a_result_list_keeps_the_cache(stt_sync, reply):
    sync, stt, cache, _ = stt_sync
    stt.update(reply)
    sync()
    assert cache.get_speedtest_count() == 50


def _fail_writes(cache, when):
    """Make the writes `when` describes fail, like a full disk."""
    with write_transaction(cache.db_path) as conn:
        conn.execute(f"CREATE TRIGGER fail BEFORE {when} BEGIN SELECT RAISE(ABORT, 'full'); END")


def _reported_ids(on_import):
    return [[r["id"] for r in call.args[0]] for call in on_import.call_args_list]


def _cache_as_running(cache, result_id):
    """Cache a row the way older versions cached a running test: 0 Mbps and no ping."""
    cache.save_speedtest_results([SpeedtestClient("http://stt", "t")._parse_result({**STARTED_RESULT, "id": result_id})])


@pytest.mark.parametrize("empty", [False, True], ids=["filled-cache", "first-fill"])
def test_a_new_result_is_reported_once(stt_sync, empty):
    """Smart Capture links each newly cached result once, whichever caller caches it; a first fill is history."""
    sync, stt, cache, on_import = stt_sync
    if empty:
        cache.clear_cache()
    stt["data"] = [{**SAMPLE_RESULT, "id": 50}]
    sync()
    stt["data"].insert(0, {**SAMPLE_RESULT, "id": 51})
    _fail_writes(cache, "INSERT ON speedtest_results")
    sync()  # the save fails, so the next sync fetches the result again
    with write_transaction(cache.db_path) as conn:
        conn.execute("DROP TRIGGER fail")
    sync()
    sync()
    assert _reported_ids(on_import) == [[51]]


def test_a_sync_during_a_scheduled_one(stt_sync):
    """While a scheduled sync runs, another one is skipped and the page shows the cache at once.

    So an older Tracker answer is never taken for a reset after the other sync cached a newer result.
    """
    sync, stt, cache, on_import = stt_sync
    stt["data"] = [{**SAMPLE_RESULT, "id": 50}]
    fake, probed, resume = requests.Session.get.side_effect, threading.Event(), threading.Event()

    def first_request_waits(*args, **kwargs):
        reply = fake(*args, **kwargs)
        if not probed.is_set():
            probed.set()
            resume.wait(5)
        return reply

    requests.Session.get.side_effect = first_request_waits
    scheduled = threading.Thread(target=current_runtime().collectors[0].collect)
    scheduled.start()
    probed.wait(5)
    stt["data"].insert(0, {**SAMPLE_RESULT, "id": 51})
    reply = sync()
    resume.set()
    scheduled.join(5)
    assert reply is None or len(reply.get_json()) == 50
    assert cache.get_speedtest_count() == 51
    assert _reported_ids(on_import) == [[51]]


@pytest.mark.parametrize("still_running, newer", [(False, 0), (True, 0), (True, 5)],
                         ids=["finished", "still-running", "still-running-below-measured-rows"])
def test_a_row_cached_while_running_is_corrected(stt_sync, still_running, newer):
    """Older versions cached a running test like a failed one, also one that is still running after the update."""
    sync, stt, cache, _ = stt_sync
    if newer:  # only the newer results have measurements
        with write_transaction(cache.db_path) as conn:
            conn.execute("UPDATE speedtest_results SET download_mbps = 0, upload_mbps = 0, ping_ms = NULL")
    _cache_as_running(cache, 51)
    finished = {**SAMPLE_RESULT, "id": 51}
    stt["data"] = [*({**SAMPLE_RESULT, "id": i} for i in range(51 + newer, 51, -1)),
                   {**finished, "status": "running"} if still_running else finished]
    sync()
    stt["data"][-1] = finished
    sync()
    row = cache.get_speedtest_by_id(51)
    assert (row["download_mbps"], row["ping_ms"]) == (1100.0, 12.5)


@pytest.mark.parametrize("broken, failing, reread_again", [
    ([], None, False),
    ([{"id": 1000, "data": "unparsable"}], None, True),
    ([], "INSERT ON speedtest_meta WHEN NEW.key = 'running_rows_reread'", True),
], ids=["complete", "parse-error", "marker-write-fails"])
def test_a_filled_cache_is_reread_until_once_complete(stt_sync, broken, failing, reread_again):
    """A complete reread runs once; after an error or a lost marker the next sync rereads again."""
    sync, stt, cache, on_import = stt_sync
    stt["data"] = [*({**SAMPLE_RESULT, "id": i} for i in range(51, 0, -1)), *broken]
    if failing:
        _fail_writes(cache, failing)
    sync()
    _cache_as_running(cache, 0)  # below the range a delta sync rechecks
    stt["data"].insert(51, {**SAMPLE_RESULT, "id": 0})
    sync()
    assert (cache.get_speedtest_by_id(0)["ping_ms"] is not None) == reread_again
    assert _reported_ids(on_import) == [[51]]


def test_the_dashboard_follows_the_cache(stt_sync):
    """The dashboard shows the newest cached result, also after a new Tracker URL cleared the cache."""
    sync, stt, cache, _ = stt_sync
    stt["data"] = [{**SAMPLE_RESULT, "id": 50}]
    sync()
    assert current_runtime().get_state()["speedtest_latest"]["id"] == 50

    current_runtime().config_manager.save({"speedtest_tracker_url": "http://other.local:8999"})
    stt["data"] = {}  # the new server does not answer with results yet
    sync()
    assert cache.get_speedtest_count() == 0
    assert current_runtime().get_state()["speedtest_latest"] is None


@pytest.mark.parametrize("stt_sync", ["route"], indirect=True)
@pytest.mark.parametrize("setup", [
    lambda cache: current_runtime().collectors.clear(),
    lambda cache: _fail_writes(cache, "INSERT ON speedtest_meta"),
    lambda cache: current_runtime().config_manager.save({"demo_mode": True, "speedtest_tracker_url": None}),
], ids=["before-polling-starts", "url-check-fails", "demo-mode-before-polling-restarts"])
def test_the_speedtest_page_falls_back_to_the_cache(stt_sync, setup):
    """The page shows the cache when it cannot sync, and does not import what Smart Capture would miss before polling."""
    sync, stt, cache, _ = stt_sync
    stt["data"] = [{**SAMPLE_RESULT, "id": 51}]
    setup(cache)
    resp = sync()
    assert resp.status_code == 200
    assert len(resp.get_json()) == 50
    assert cache.get_speedtest_by_id(51) is None


class TestSpeedtestAPI:
    @pytest.mark.parametrize("result, download, ping", [
        (SAMPLE_RESULT, 1100.0, 12.5), ({**STARTED_RESULT, "status": "failed"}, 0, None),
    ])
    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_api_speedtest(self, mock_get, speedtest_client, result, download, ping):
        mock_get.side_effect = _stt_api({"data": [result]})

        resp = speedtest_client.get("/api/speedtest?days=7")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert (data[0]["download_mbps"], data[0]["ping_ms"]) == (download, ping)

    @pytest.mark.parametrize("newest, results", [(SAMPLE_RESULT, 1), ({**STARTED_RESULT, "status": "running"}, 0)])
    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_api_test_speedtest_success(self, mock_get, speedtest_client, newest, results):
        mock_get.side_effect = _stt_api({"data": [newest, SAMPLE_RESULT]})

        resp = speedtest_client.post("/api/test-speedtest", json={
            "speedtest_tracker_url": "http://speedtest.local:8999",
            "speedtest_tracker_token": PASSWORD_MASK,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["results"] == results
        assert ("latest" in data) is bool(results)
        assert mock_get.call_args.args[0] == "http://speedtest.local:8999/api/v1/results"
        assert mock_get.call_args.kwargs["verify"] is True

    @patch("app.blueprints.polling_bp.SpeedtestClient")
    def test_api_test_speedtest_rejects_unsaved_destination_without_requesting_it(
        self, mock_client, speedtest_client
    ):
        resp = speedtest_client.post("/api/test-speedtest", json={
            "speedtest_tracker_url": "http://attacker.example",
            "speedtest_tracker_token": PASSWORD_MASK,
        })

        assert resp.status_code == 200
        assert resp.get_json() == {
            "success": False,
            "error": "Save Speedtest Tracker settings before testing.",
        }
        mock_client.assert_not_called()

    @patch("app.blueprints.polling_bp.SpeedtestClient")
    def test_api_test_speedtest_uses_saved_credentials(self, mock_client, speedtest_client):
        mock_client.return_value.get_latest_with_error.return_value = ([], None)

        resp = speedtest_client.post("/api/test-speedtest", json={
            "speedtest_tracker_url": "http://speedtest.local:8999",
            "speedtest_tracker_token": "attacker-controlled-token",
        })

        assert resp.status_code == 200
        assert resp.get_json() == {"success": True, "results": 0}
        mock_client.assert_called_once_with(
            "http://speedtest.local:8999", "test-token", tls_insecure=False
        )

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_api_test_speedtest_allows_saved_destination_trailing_slash(
        self, mock_get, speedtest_client
    ):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        resp = speedtest_client.post("/api/test-speedtest", json={
            "speedtest_tracker_url": "http://speedtest.local:8999/",
            "speedtest_tracker_token": PASSWORD_MASK,
        })

        assert resp.status_code == 200
        assert resp.get_json() == {"success": True, "results": 0}
        assert mock_get.call_args.args[0] == "http://speedtest.local:8999/api/v1/results"

    @patch("app.blueprints.polling_bp.SpeedtestClient")
    def test_api_test_speedtest_keeps_the_saved_tls_policy(self, mock_client, speedtest_client):
        resp = speedtest_client.post("/api/test-speedtest", json={
            "speedtest_tracker_url": "http://speedtest.local:8999",
            "speedtest_tracker_token": PASSWORD_MASK,
            "speedtest_tls_insecure": "true",
        })

        assert resp.get_json() == {"success": False, "error": "Save Speedtest Tracker settings before testing."}
        mock_client.assert_not_called()

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_api_test_speedtest_passes_insecure_tls_flag(self, mock_get, speedtest_client):

        current_runtime().config_manager.save({
            "speedtest_tracker_url": "https://speedtest.local:8443", "speedtest_tls_insecure": True,
        })

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [SAMPLE_RESULT]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        resp = speedtest_client.post("/api/test-speedtest", json={
            "speedtest_tracker_url": "https://speedtest.local:8443",
            "speedtest_tracker_token": "[REDACTED]",
            "speedtest_tls_insecure": "true",
        })

        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert mock_get.call_args.args[0] == "https://speedtest.local:8443/api/v1/results"
        assert mock_get.call_args.kwargs["verify"] is False

    def test_api_test_speedtest_missing_fields(self, speedtest_client):
        resp = speedtest_client.post("/api/test-speedtest", json={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is False
        assert "required" in data["error"].lower()

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_api_test_speedtest_connection_error(self, mock_get, speedtest_client):
        import requests as req
        mock_get.side_effect = req.ConnectionError("Connection refused")

        resp = speedtest_client.post("/api/test-speedtest", json={
            "speedtest_tracker_url": "http://speedtest.local:8999",
            "speedtest_tracker_token": "[REDACTED]",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"success": False, "error": "Cannot reach Speedtest Tracker"}

    def test_signal_api_treats_legacy_unsupported_zero_error_counters_as_unavailable(self, speedtest_client, monkeypatch):
        import app.modules.speedtest.routes as speedtest_routes

        class SpeedtestStorage:
            def get_speedtest_by_id(self, result_id):
                return {"id": result_id, "timestamp": "2025-01-15T10:30:00Z"}

        class CoreStorage:
            def get_closest_snapshot(self, timestamp):
                return {
                    "timestamp": timestamp,
                    "summary": {
                        "errors_supported": False,
                        "health": "good",
                        "ds_correctable_errors": 0,
                        "ds_uncorrectable_errors": 0,
                    },
                    "us_channels": [],
                }

        monkeypatch.setattr(speedtest_routes, "_get_speedtest_storage", lambda: SpeedtestStorage())
        monkeypatch.setattr(speedtest_routes.current_runtime(), "storage", CoreStorage())

        resp = speedtest_client.get("/api/speedtest/1/signal")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["found"] is True
        assert data["ds_correctable_errors"] is None
        assert data["ds_uncorrectable_errors"] is None

    def test_signal_api_preserves_supported_zero_error_counters(self, speedtest_client, monkeypatch):
        import app.modules.speedtest.routes as speedtest_routes

        class SpeedtestStorage:
            def get_speedtest_by_id(self, result_id):
                return {"id": result_id, "timestamp": "2025-01-15T10:30:00Z"}

        class CoreStorage:
            def get_closest_snapshot(self, timestamp):
                return {
                    "timestamp": timestamp,
                    "summary": {
                        "errors_supported": True,
                        "health": "good",
                        "ds_correctable_errors": 0,
                        "ds_uncorrectable_errors": 0,
                    },
                    "us_channels": [],
                }

        monkeypatch.setattr(speedtest_routes, "_get_speedtest_storage", lambda: SpeedtestStorage())
        monkeypatch.setattr(speedtest_routes.current_runtime(), "storage", CoreStorage())

        resp = speedtest_client.get("/api/speedtest/1/signal")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["found"] is True
        assert data["ds_correctable_errors"] == 0
        assert data["ds_uncorrectable_errors"] == 0

    @pytest.mark.parametrize("config", [{}, {"demo_mode": True, "speedtest_tracker_url": None}],
                             ids=["not-configured", "demo-mode-without-storage"])
    def test_api_speedtest_without_a_tracker_to_ask(self, tmp_path, config):
        with configured_client(tmp_path / "data2", **config) as client:
            resp = client.get("/api/speedtest?days=7")
            assert resp.status_code == 200
            assert resp.get_json() == []


class TestSpeedtestRun:
    """Tests for POST /api/speedtest/run."""

    def _reset_rate_limit(self):
        current_runtime().derived_storage.set_value("speedtest_last_trigger", 0.0)

    @pytest.mark.parametrize("reply, result_id", [
        ({"data": {"id": 102}, "message": "Speedtest added to the queue."}, 102), ({}, None), ({"data": {"id": True}}, None),
    ], ids=["queued-test", "without-result", "boolean-id"])
    @patch("app.modules.speedtest.routes.requests.post")
    def test_run_success(self, mock_post, speedtest_client, reply, result_id):
        """The queued test's id lets the page wait for exactly that result."""
        self._reset_rate_limit()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = reply
        mock_post.return_value = mock_resp

        resp = speedtest_client.post("/api/speedtest/run")
        assert resp.status_code == 200
        assert resp.get_json() == {"success": True, "result_id": result_id}
        mock_post.assert_called_once()
        assert mock_post.call_args.kwargs["verify"] is True

    @patch("app.modules.speedtest.routes.requests.post")
    def test_run_uses_insecure_tls_config(self, mock_post, speedtest_client):
        self._reset_rate_limit()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        current_runtime().config_manager.save({"speedtest_tls_insecure": True})

        resp = speedtest_client.post("/api/speedtest/run")

        assert resp.status_code == 200
        assert mock_post.call_args.kwargs["verify"] is False

    @patch("app.modules.speedtest.routes.requests.post")
    def test_run_rate_limited(self, mock_post, speedtest_client):
        self._reset_rate_limit()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        resp1 = speedtest_client.post("/api/speedtest/run")
        assert resp1.status_code == 200

        resp2 = speedtest_client.post("/api/speedtest/run")
        assert resp2.status_code == 429
        assert "Rate limited" in resp2.get_json()["error"]

    @patch("app.modules.speedtest.routes.requests.post")
    def test_run_stt_error(self, mock_post, speedtest_client):
        self._reset_rate_limit()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_post.return_value = mock_resp

        resp = speedtest_client.post("/api/speedtest/run")
        assert resp.status_code == 502
        assert resp.get_json()["success"] is False

    @pytest.mark.parametrize(("raised", "status", "error"), [
        (requests.ConnectionError("refused"), 502, "Cannot reach Speedtest Tracker"),
        (requests.ConnectTimeout("connect timed out"), 504, "Speedtest Tracker timeout"),
        (requests.exceptions.InvalidHeader("Invalid header value b'Bearer leaked-token'"), 500,
         "Speedtest start failed. See the DOCSight log for details."),
    ], ids=["connection", "connect-timeout", "invalid-header"])
    @patch("app.modules.speedtest.routes.requests.post")
    def test_run_request_failures(self, mock_post, speedtest_client, caplog, raised, status, error):
        self._reset_rate_limit()
        mock_post.side_effect = raised

        resp = speedtest_client.post("/api/speedtest/run")
        assert (resp.status_code, resp.get_json()) == (status, {"success": False, "error": error})
        assert "leaked-token" not in caplog.text

    def test_run_not_configured(self, tmp_path):
        with configured_client(tmp_path / "data3") as client:
            resp = client.post("/api/speedtest/run")
            assert resp.status_code == 400
            assert "not configured" in resp.get_json()["error"]

    def test_run_blocked_in_demo_mode(self, tmp_path):
        with configured_client(
            tmp_path / "data4",
            **{"demo_mode": True, "speedtest_tracker_url": "http://speedtest.local:8999", "speedtest_tracker_token": "[REDACTED]"},
        ) as client:
            resp = client.post("/api/speedtest/run")
            assert resp.status_code == 400
            assert "demo" in resp.get_json()["error"].lower()
