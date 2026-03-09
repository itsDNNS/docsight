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
    def test_uses_home_json_when_available(self, mock_post):
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
        assert mock_post.call_args.kwargs["data"]["page"] == "home"

    @patch("app.fritzbox.requests.post")
    def test_falls_back_to_boxinfo_when_home_is_not_json(self, mock_post):
        home_response = MagicMock()
        home_response.raise_for_status = MagicMock()
        home_response.json.side_effect = ValueError("not json")

        boxinfo_response = MagicMock()
        boxinfo_response.raise_for_status = MagicMock()
        boxinfo_response.json.return_value = {
            "data": {
                "fritzos": {
                    "Productname": "FRITZ!Box 6690 Cable",
                    "nspver": "8.21",
                }
            }
        }

        mock_post.side_effect = [home_response, boxinfo_response]

        info = fb.get_device_info("http://fritz.box", "sid123")

        assert info == {
            "model": "FRITZ!Box 6690 Cable",
            "sw_version": "8.21",
        }
        assert [call.kwargs["data"]["page"] for call in mock_post.call_args_list] == [
            "home",
            "boxinfo",
        ]

    @patch("app.fritzbox.requests.get")
    @patch("app.fritzbox.requests.post")
    def test_falls_back_to_tr064_when_data_pages_return_html(self, mock_post, mock_get):
        html_response = MagicMock()
        html_response.raise_for_status = MagicMock()
        html_response.json.side_effect = ValueError("not json")
        html_response.text = "<html>login</html>"
        mock_post.side_effect = [html_response, html_response, html_response]

        tr064_response = MagicMock()
        tr064_response.raise_for_status = MagicMock()
        tr064_response.text = TR064_DESC_XML
        mock_get.return_value = tr064_response

        info = fb.get_device_info("http://fritz.box", "sid123")

        assert info == {
            "model": "FRITZ!Box 6690 Cable",
            "sw_version": "267.08.21",
        }
        assert [call.kwargs["data"]["page"] for call in mock_post.call_args_list] == [
            "home",
            "boxinfo",
            "overview",
        ]

    @patch("app.fritzbox.requests.get")
    @patch("app.fritzbox.requests.post")
    def test_returns_generic_fallback_when_all_sources_fail(self, mock_post, mock_get):
        post_response = MagicMock()
        post_response.raise_for_status = MagicMock()
        post_response.json.side_effect = ValueError("not json")
        mock_post.side_effect = [post_response, post_response, post_response]

        mock_get.side_effect = RuntimeError("network down")

        info = fb.get_device_info("http://fritz.box", "sid123")

        assert info == {"model": "FRITZ!Box", "sw_version": ""}
