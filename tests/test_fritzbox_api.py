"""Tests for the direct FritzBox API helpers in app.fritzbox."""

from unittest.mock import MagicMock, patch

from app import fritzbox as fb


TR064_DESC_XML = """<?xml version="1.0"?>
<root xmlns="urn:dslforum-org:device-1-0">
  <systemVersion>
    <Display>267.08.21</Display>
  </systemVersion>
  <device>
    <modelName>FRITZ!Box 6690 Cable</modelName>
    <modelDescription>FRITZ!Box 6690 Cable</modelDescription>
    <friendlyName>FRITZ!Box 6690 Cable</friendlyName>
  </device>
</root>
"""


class TestGetDeviceInfo:
    @patch("app.fritzbox.requests.post")
    def test_uses_overview_json_when_available(self, mock_post):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "data": {
                "fritzos": {
                    "Productname": "FRITZ!Box 6660 Cable",
                    "nspver": "8.02",
                    "Uptime": "1234",
                }
            }
        }
        mock_post.return_value = response

        info = fb.get_device_info("http://fritz.box", "sid123")

        assert info == {
            "model": "FRITZ!Box 6660 Cable",
            "sw_version": "8.02",
            "uptime_seconds": 1234,
        }

    @patch("app.fritzbox.requests.get")
    @patch("app.fritzbox.requests.post")
    def test_falls_back_to_tr064_when_overview_returns_html(self, mock_post, mock_get):
        html_response = MagicMock()
        html_response.raise_for_status = MagicMock()
        html_response.json.side_effect = ValueError("not json")
        html_response.text = "<html>login</html>"
        mock_post.return_value = html_response

        tr064_response = MagicMock()
        tr064_response.raise_for_status = MagicMock()
        tr064_response.text = TR064_DESC_XML
        mock_get.return_value = tr064_response

        info = fb.get_device_info("http://fritz.box", "sid123")

        assert info == {
            "model": "FRITZ!Box 6690 Cable",
            "sw_version": "267.08.21",
        }

    @patch("app.fritzbox.requests.get")
    @patch("app.fritzbox.requests.post")
    def test_returns_generic_fallback_when_overview_and_tr064_fail(self, mock_post, mock_get):
        post_response = MagicMock()
        post_response.raise_for_status = MagicMock()
        post_response.json.side_effect = ValueError("not json")
        mock_post.return_value = post_response

        mock_get.side_effect = RuntimeError("network down")

        info = fb.get_device_info("http://fritz.box", "sid123")

        assert info == {"model": "FRITZ!Box", "sw_version": ""}
