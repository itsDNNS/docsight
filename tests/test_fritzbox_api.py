"""Tests for direct FritzBox API helpers."""

from unittest.mock import MagicMock, patch

from app import fritzbox as fb


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
    @patch("app.fritzbox.requests.post")
    def test_get_cable_utilization_merges_docov_and_netmoni(self, mock_post):
        doc_ov = MagicMock()
        doc_ov.raise_for_status = MagicMock()
        doc_ov.json.return_value = DOC_OV_DATA

        net_moni = MagicMock()
        net_moni.raise_for_status = MagicMock()
        net_moni.json.return_value = NET_MONI_DATA

        mock_post.side_effect = [doc_ov, net_moni]

        data = fb.get_cable_utilization("http://fritz.box", "sid123")

        assert data["supported"] is True
        assert data["model"] == "FRITZ!Box 6690 Cable"
        assert data["duration"] == "2 Stunden und 9 Minuten"
        assert data["downstream_rate"] == "1150 Mbit/s"
        assert data["channel_counts"] == {"downstream": 33, "upstream": 4}
        assert data["downstream"]["samples_bps"] == [100, 200, 300]
        assert data["downstream"]["current_bps"] == 300
        assert data["upstream"]["samples_bps"] == [11, 18, 23]
        assert data["upstream"]["current_bps"] == 23
        assert [call.kwargs["data"]["page"] for call in mock_post.call_args_list] == [
            "docOv",
            "netMoni",
        ]
