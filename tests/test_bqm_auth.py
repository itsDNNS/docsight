"""Tests for ThinkBroadband share URL helpers."""

from unittest.mock import MagicMock, patch

import pytest

from app.modules.bqm.auth import (
    extract_share_id,
    is_csv_url,
    fetch_share_csv,
    validate_share_id,
    ThinkBroadbandBatchAbort,
)


class TestExtractShareId:
    def test_full_csv_url(self):
        url = "https://www.thinkbroadband.com/broadband/monitoring/quality/share/bd77751689f2f7b8d47d99899335aef060c9e768-2-y.csv"
        assert extract_share_id(url) == "bd77751689f2f7b8d47d99899335aef060c9e768-2"

    def test_full_png_url(self):
        url = "https://www.thinkbroadband.com/broadband/monitoring/quality/share/bd77751689f2f7b8d47d99899335aef060c9e768-2.png"
        assert extract_share_id(url) == "bd77751689f2f7b8d47d99899335aef060c9e768-2"

    def test_bare_hash(self):
        assert extract_share_id("abc123def456789012345678901234567890abcd-2") == "abc123def456789012345678901234567890abcd-2"

    def test_live_csv_suffix(self):
        url = "https://www.thinkbroadband.com/broadband/monitoring/quality/share/abc123def456789012345678901234567890abcd-2-l.csv"
        assert extract_share_id(url) == "abc123def456789012345678901234567890abcd-2"

    def test_xml_suffix(self):
        url = "https://www.thinkbroadband.com/broadband/monitoring/quality/share/abc123def456789012345678901234567890abcd-2.xml"
        assert extract_share_id(url) == "abc123def456789012345678901234567890abcd-2"

    def test_empty(self):
        assert extract_share_id("") is None
        assert extract_share_id(None) is None

    def test_invalid_url(self):
        assert extract_share_id("https://example.com/foo") is None


class TestIsCsvUrl:
    def test_csv_url(self):
        assert is_csv_url("https://example.com/share/abc-2-y.csv") is True

    def test_png_url(self):
        assert is_csv_url("https://example.com/share/abc-2.png") is False

    def test_xml_url(self):
        assert is_csv_url("https://example.com/share/abc-2.xml") is True

    def test_empty(self):
        assert is_csv_url("") is False
        assert is_csv_url(None) is False


def _response(status=200, text="", content_type="text/csv"):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.headers = {"Content-Type": content_type}
    return resp


class TestFetchShareCsv:
    @patch("app.modules.bqm.auth.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = _response(200, '"Timestamp",data\n"2026-01-01",100', "text/csv")
        result = fetch_share_csv("abc123-2", "y")
        assert result.startswith('"Timestamp"')
        mock_get.assert_called_once()

    @patch("app.modules.bqm.auth.requests.get")
    def test_rate_limit_raises(self, mock_get):
        mock_get.return_value = _response(429, "rate limited")
        with pytest.raises(ThinkBroadbandBatchAbort):
            fetch_share_csv("abc123-2", "y")

    @patch("app.modules.bqm.auth.requests.get")
    def test_not_found(self, mock_get):
        mock_get.return_value = _response(404, "not found")
        assert fetch_share_csv("abc123-2", "y") == ""

    @patch("app.modules.bqm.auth.requests.get")
    def test_non_csv_content(self, mock_get):
        mock_get.return_value = _response(200, "<html>not csv</html>", "text/html")
        assert fetch_share_csv("abc123-2", "y") == ""

    @patch("app.modules.bqm.auth.requests.get")
    def test_non_csv_content_type_is_not_logged(self, mock_get, caplog):
        sensitive_content_type = "text/html; password=secret123"
        mock_get.return_value = _response(200, "<html>not csv</html>", sensitive_content_type)

        with caplog.at_level("WARNING", logger="docsis.bqm.auth"):
            assert fetch_share_csv("abc123-2", "y") == ""

        assert "ThinkBroadband response is not CSV" in caplog.text
        assert sensitive_content_type not in caplog.text
        assert "secret123" not in caplog.text


class TestValidateShareId:
    @patch("app.modules.bqm.auth.fetch_share_csv")
    def test_valid(self, mock_fetch):
        mock_fetch.return_value = '"Timestamp",data'
        assert validate_share_id("abc123-2") is True

    @patch("app.modules.bqm.auth.fetch_share_csv")
    def test_invalid(self, mock_fetch):
        mock_fetch.return_value = ""
        assert validate_share_id("abc123-2") is False

    @patch("app.modules.bqm.auth.fetch_share_csv")
    def test_batch_abort(self, mock_fetch):
        mock_fetch.side_effect = ThinkBroadbandBatchAbort("429")
        assert validate_share_id("abc123-2") is False
