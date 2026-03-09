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
    @patch("app.fritzbox.requests.get")
    def test_uses_rest_api_when_available(self, mock_get):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "productName": "FRITZ!Box 6690 Cable",
            "firmwareVersion": "8.10",
            "uptime": 1234,
        }
        mock_get.return_value = response

        info = fb.get_device_info("http://fritz.box", "sid123")

        assert info == {
            "model": "FRITZ!Box 6690 Cable",
            "sw_version": "8.10",
            "uptime_seconds": 1234,
        }
        assert mock_get.call_args.args[0] == "http://fritz.box/api/v0/generic/box"
        assert mock_get.call_args.kwargs["headers"]["Authorization"] == "AVM-SID sid123"

    @patch("app.fritzbox.requests.get")
    @patch("app.fritzbox.requests.post")
    def test_uses_home_json_when_available(self, mock_post, mock_get):
        mock_get.side_effect = RuntimeError("rest unavailable")
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

    @patch("app.fritzbox.requests.get")
    @patch("app.fritzbox.requests.post")
    def test_falls_back_to_boxinfo_when_home_is_not_json(self, mock_post, mock_get):
        mock_get.side_effect = RuntimeError("rest unavailable")
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
        rest_response = MagicMock()
        rest_response.raise_for_status = MagicMock()
        rest_response.json.return_value = {}

        html_response = MagicMock()
        html_response.raise_for_status = MagicMock()
        html_response.json.side_effect = ValueError("not json")
        html_response.text = "<html>login</html>"
        mock_post.side_effect = [html_response, html_response, html_response]

        tr064_response = MagicMock()
        tr064_response.raise_for_status = MagicMock()
        tr064_response.text = TR064_DESC_XML
        mock_get.side_effect = [rest_response, tr064_response]

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
        mock_get.side_effect = [RuntimeError("rest unavailable"), RuntimeError("network down")]

        post_response = MagicMock()
        post_response.raise_for_status = MagicMock()
        post_response.json.side_effect = ValueError("not json")
        mock_post.side_effect = [post_response, post_response, post_response]

        info = fb.get_device_info("http://fritz.box", "sid123")

        assert info == {"model": "FRITZ!Box", "sw_version": ""}


class TestGetConnectionInfo:
    @patch("app.fritzbox.requests.get")
    def test_uses_rest_api_when_available(self, mock_get):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "connections": [
                {
                    "downstream": 1140000,
                    "upstream": 58000,
                    "medium": "cable",
                }
            ]
        }
        mock_get.return_value = response

        info = fb.get_connection_info("http://fritz.box", "sid123")

        assert info == {
            "max_downstream_kbps": 1140000,
            "max_upstream_kbps": 58000,
            "connection_type": "cable",
        }
        assert mock_get.call_args.args[0] == "http://fritz.box/api/v0/generic/connections"
        assert mock_get.call_args.kwargs["headers"]["Authorization"] == "AVM-SID sid123"

    @patch("app.fritzbox.requests.get")
    @patch("app.fritzbox.requests.post")
    def test_falls_back_to_netmoni_when_rest_api_fails(self, mock_post, mock_get):
        mock_get.side_effect = RuntimeError("rest unavailable")

        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "data": {
                "connections": [
                    {
                        "downstream": 1000000,
                        "upstream": 50000,
                        "medium": "docsis",
                    }
                ]
            }
        }
        mock_post.return_value = response

        info = fb.get_connection_info("http://fritz.box", "sid123")

        assert info == {
            "max_downstream_kbps": 1000000,
            "max_upstream_kbps": 50000,
            "connection_type": "docsis",
        }
        assert mock_post.call_args.kwargs["data"]["page"] == "netMoni"


REST_SUBSETS = {
    "subsets": [
        {"id": 0, "label": "1h"},
        {"id": 1, "label": "24h"},
    ]
}


REST_SEGMENT = {
    "data": {
        "downstream": {
            "title": "Segment load downstream",
            "subtitle": "Network total",
            "total": [21, 48, 67],
            "ownShare": [4, 7, 10],
        },
        "upstream": {
            "title": "Segment load upstream",
            "subtitle": "Network total",
            "total": [12, 20, 39],
            "ownShare": [2, 3, 5],
        },
    }
}


DOC_OV_DATA = {
    "data": {
        "connectionData": {
            "modell": "FRITZ!Box 6690 Cable",
            "connectionType": "cable",
            "dsRate": "1150 Mbit/s",
            "usRate": "56,7 Mbit/s",
            "infoMiddle": {
                "details": [
                    {"text": "Kabel-Internet:", "value": "aktiv"},
                    {"text": "Verbindungsdauer:", "value": "2 Stunden und 9 Minuten"},
                    {"text": "Verbindungstyp:", "value": "DOCSIS 3.0 und DOCSIS 3.1"},
                ],
                "upDownInfos": {
                    "details": [{"dsValue": 33, "usValue": 4}],
                },
                "chartData": {
                    "title": "Nutzung der Kabel-Verbindung",
                    "subtitle": "im Downstream",
                    "max": 34398702,
                },
            },
            "infoLeft": {
                "details": [
                    {"text": "DOCSIS-Software-Version:", "value": "7.3.5.3.521"},
                    {"text": "CM MAC-Adresse:", "value": "50:E6:36:05:E4:37"},
                ]
            },
            "line": [{
                "trainState": "aktiv",
                "state": "ready",
                "mode": "DOCSIS 3.0 und DOCSIS 3.1",
                "time": "2 Stunden und 9 Minuten",
            }],
        }
    }
}


NET_MONI_DATA = {
    "data": {
        "sampling_interval": 5000,
        "sync_groups": [{
            "ds_bps_curr": [100, 200, 300],
            "ds_bps_curr_max": 300,
            "ds_bps_max": 1000,
            "us_realtime_bps_curr": [10, 15, 20],
            "us_background_bps_curr": [1, 2, 3],
            "us_important_bps_curr": [0, 0, 0],
            "us_default_bps_curr": [0, 1, 0],
            "us_bps_curr_max": 23,
            "us_bps_max": 200,
        }]
    }
}


class TestCableUtilization:
    @patch("app.fritzbox.requests.get")
    def test_get_cable_utilization_prefers_rest_segment_api(self, mock_get):
        responses = []
        for payload in (
            {"productName": "FRITZ!Box 6690 Cable", "firmwareVersion": "8.10"},
            {"connections": [{"downstream": 1150000, "upstream": 57000, "medium": "cable"}]},
            REST_SUBSETS,
            REST_SEGMENT,
        ):
            response = MagicMock()
            response.raise_for_status = MagicMock()
            response.json.return_value = payload
            responses.append(response)
        mock_get.side_effect = responses

        data = fb.get_cable_utilization("http://fritz.box", "sid123")

        assert data["supported"] is True
        assert data["source"] == "api_v0"
        assert data["duration"] == "1h"
        assert data["selected_range"] == {"id": 0, "label": "1h"}
        assert data["downstream"]["samples_percent"] == [21, 48, 67]
        assert data["downstream"]["current_percent"] == 67
        assert data["downstream"]["current_own_percent"] == 10
        assert data["upstream"]["samples_percent"] == [12, 20, 39]
        assert data["upstream"]["peak_percent"] == 39

    @patch("app.fritzbox.requests.get")
    @patch("app.fritzbox.requests.post")
    def test_get_cable_utilization_falls_back_to_legacy_pages(self, mock_post, mock_get):
        mock_get.side_effect = RuntimeError("rest unavailable")

        responses = []
        for payload in (
            None,
            None,
            None,
            {"data": {"connections": []}},
            DOC_OV_DATA,
            NET_MONI_DATA,
        ):
            response = MagicMock()
            response.raise_for_status = MagicMock()
            if payload is None:
                response.json.side_effect = ValueError("not json")
            else:
                response.json.return_value = payload
            responses.append(response)
        mock_post.side_effect = responses

        data = fb.get_cable_utilization("http://fritz.box", "sid123")

        assert data["supported"] is True
        assert data["source"] == "legacy"
        assert data["model"] == "FRITZ!Box 6690 Cable"
        assert data["channel_counts"] == {"downstream": 33, "upstream": 4}
        assert data["downstream"]["samples_bps"] == [100, 200, 300]
        assert data["upstream"]["samples_bps"] == [11, 18, 23]
        assert [call.kwargs["data"]["page"] for call in mock_post.call_args_list] == [
            "home",
            "boxinfo",
            "overview",
            "netMoni",
            "docOv",
            "netMoni",
        ]
