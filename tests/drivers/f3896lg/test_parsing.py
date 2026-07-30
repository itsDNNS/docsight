"""Tests for F3896LG (Liberty Global REST) channel parsing and derived values."""

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.analyzer import analyze
from app.drivers.f3896lg import F3896LGDriver


class TestLogin:
    def test_login_ok(self, driver):
        driver.login()  # must not raise

    def test_login_accepts_registration_in_progress(self, driver):
        with patch.object(
            driver,
            "_get",
            return_value={"registration": {"registrationComplete": False}},
        ):
            driver.login()

    @pytest.mark.parametrize(
        "payload",
        [{}, {"registration": None}, {"registration": []}],
    )
    def test_login_rejects_missing_or_invalid_registration(self, driver, payload):
        with (
            patch.object(driver, "_get", return_value=payload),
            pytest.raises(
                RuntimeError,
                match="F3896LG REST API returned unexpected registration payload",
            ),
        ):
            driver.login()

    def test_login_wraps_connection_error(self, driver):
        with (
            patch.object(
                driver,
                "_get",
                side_effect=requests.ConnectionError("connection refused"),
            ),
            pytest.raises(
                RuntimeError,
                match=r"^F3896LG REST API not reachable:",
            ),
        ):
            driver.login()


class TestTransport:
    @pytest.mark.parametrize("payload", [None, []])
    def test_get_rejects_non_object_json(self, driver, payload):
        response = MagicMock()
        response.json.return_value = payload
        driver._session.get.side_effect = None
        driver._session.get.return_value = response

        with pytest.raises(
            RuntimeError,
            match="F3896LG REST API returned a non-object JSON payload",
        ):
            driver._get("cablemodem/downstream")

    def test_tls_verification_is_local_to_session(self):
        with patch("urllib3.disable_warnings") as disable_warnings:
            driver = F3896LGDriver("https://192.168.100.1", "", "")

        assert driver._session.verify is False
        disable_warnings.assert_not_called()

    @pytest.mark.parametrize(
        "payload",
        [{}, {"downstream": []}, {"downstream": {"channels": {}}}],
    )
    def test_get_docsis_data_rejects_invalid_nested_payload(self, driver, payload):
        with patch.object(driver, "_get", return_value=payload), pytest.raises(
            RuntimeError,
            match=r"invalid downstream (payload|channels)",
        ):
            driver.get_docsis_data()


class TestDownstream:
    def test_locked_scqam_count(self, driver):
        data = driver.get_docsis_data()
        # 3 sc_qam in fixture, 1 unlocked -> skipped
        assert len(data["channelDs"]["docsis30"]) == 2

    def test_unlocked_channel_skipped(self, driver):
        data = driver.get_docsis_data()
        ids = [ch["channelID"] for ch in data["channelDs"]["docsis30"]]
        assert 3 not in ids

    def test_scqam_fields(self, driver):
        ch = driver.get_docsis_data()["channelDs"]["docsis30"][0]
        assert ch["channelID"] == 1
        assert ch["frequency"] == "411 MHz"
        assert ch["powerLevel"] == -4.3
        assert ch["mer"] == 39
        assert ch["mse"] == -39
        assert ch["modulation"] == "256QAM"
        assert ch["corrErrors"] == 26
        assert ch["nonCorrErrors"] == 0

    def test_ofdm_channel(self, driver):
        ds31 = driver.get_docsis_data()["channelDs"]["docsis31"]
        assert len(ds31) == 1
        ch = ds31[0]
        assert ch["channelID"] == 41
        assert ch["type"] == "OFDM"
        # firmware reports OFDM power scaled x10: -118 -> -11.8 dBmV
        assert ch["powerLevel"] == -11.8
        assert ch["frequency"] == ""
        assert ch["modulation"] == "OFDM"
        assert ch["profile_modulation"] == "4096QAM"
        # rxMer 0 means "not reported" on this firmware
        assert ch["mer"] is None
        assert ch["corrErrors"] == 1361678039
        assert ch["nonCorrErrors"] == 483483438

    @pytest.mark.parametrize(
        ("rx_mer", "expected"),
        [(0, None), (0.0, None), ("0", None), ("0.0", None), (390, 39.0), ("390", 39.0)],
    )
    def test_ofdm_rxmer_is_normalized(self, driver, rx_mer, expected):
        channels = [{
            "channelType": "ofdm",
            "channelId": 41,
            "firstActiveSubcarrier": 1108,
            "modulation": "qam_4096",
            "lockStatus": True,
            "rxMer": rx_mer,
            "power": -118,
        }]

        _, ds31 = driver._parse_downstream(channels)

        assert ds31[0]["mer"] == expected

    def test_invalid_ofdm_rxmer_retains_channel(self, driver, caplog):
        channels = [{
            "channelType": "ofdm",
            "channelId": 41,
            "firstActiveSubcarrier": 1108,
            "modulation": "qam_4096",
            "lockStatus": True,
            "rxMer": "invalid",
            "power": -118,
            "correctedErrors": 12,
            "uncorrectedErrors": 3,
        }]

        with caplog.at_level(logging.WARNING, logger="docsis.driver.f3896lg"):
            _, ds31 = driver._parse_downstream(channels)

        assert len(ds31) == 1
        assert ds31[0]["mer"] is None
        assert ds31[0]["frequency"] == ""
        assert ds31[0]["powerLevel"] == -11.8
        assert ds31[0]["profile_modulation"] == "4096QAM"
        assert ds31[0]["corrErrors"] == 12
        assert ds31[0]["nonCorrErrors"] == 3
        assert caplog.messages == [
            "Invalid F3896LG OFDM rxMer 'invalid'; using no MER",
        ]

    def test_invalid_ofdm_power_retains_channel(self, driver, caplog):
        channels = [{
            "channelType": "ofdm",
            "channelId": 41,
            "firstActiveSubcarrier": 1108,
            "modulation": "qam_4096",
            "lockStatus": True,
            "rxMer": 390,
            "power": "invalid",
        }]

        with caplog.at_level(logging.WARNING, logger="docsis.driver.f3896lg"):
            _, ds31 = driver._parse_downstream(channels)

        assert len(ds31) == 1
        assert ds31[0]["powerLevel"] is None
        assert ds31[0]["mer"] == 39.0
        assert caplog.messages == [
            "Invalid F3896LG OFDM power 'invalid'; using no power",
        ]

    def test_unknown_channel_type_is_skipped(self, driver, caplog):
        with caplog.at_level(logging.DEBUG, logger="docsis.driver.f3896lg"):
            ds30, ds31 = driver._parse_downstream([
                {"channelType": "mystery", "lockStatus": True},
            ])

        assert ds30 == []
        assert ds31 == []
        assert caplog.messages == [
            "Skipping unknown downstream channel type 'mystery'",
        ]


class TestUpstream:
    def test_atdma_channels(self, driver):
        us30 = driver.get_docsis_data()["channelUs"]["docsis30"]
        assert len(us30) == 2
        ch = us30[0]
        assert ch["channelID"] == 6
        assert ch["frequency"] == "49.6 MHz"
        assert ch["powerLevel"] == 42.5
        assert ch["modulation"] == "64QAM"
        assert ch["multiplex"] == "ATDMA"

    def test_ofdma_channel(self, driver):
        us31 = driver.get_docsis_data()["channelUs"]["docsis31"]
        assert len(us31) == 1
        ch = us31[0]
        assert ch["channelID"] == 12
        assert ch["type"] == "OFDMA"
        # firmware reports OFDMA power scaled x10: 380 -> 38.0 dBmV
        assert ch["powerLevel"] == 38.0
        assert ch["frequency"] == ""
        assert ch["modulation"] == "OFDMA"
        assert ch["profile_modulation"] == "256QAM"

    def test_unknown_channel_type_is_skipped(self, driver, caplog):
        with caplog.at_level(logging.DEBUG, logger="docsis.driver.f3896lg"):
            us30, us31 = driver._parse_upstream([
                {"channelType": "mystery", "lockStatus": True},
            ])

        assert us30 == []
        assert us31 == []
        assert caplog.messages == [
            "Skipping unknown upstream channel type 'mystery'",
        ]

    def test_invalid_ofdma_power_retains_channel(self, driver, caplog):
        channels = [{
            "channelType": "ofdma",
            "channelId": 12,
            "firstActiveSubcarrier": 74,
            "modulation": "qam_256",
            "lockStatus": True,
            "power": "invalid",
        }]

        with caplog.at_level(logging.WARNING, logger="docsis.driver.f3896lg"):
            _, us31 = driver._parse_upstream(channels)

        assert len(us31) == 1
        assert us31[0]["powerLevel"] is None
        assert us31[0]["profile_modulation"] == "256QAM"
        assert caplog.messages == [
            "Invalid F3896LG OFDMA power 'invalid'; using no power",
        ]


@pytest.mark.parametrize(
    "parser_name",
    ["_parse_downstream", "_parse_upstream"],
)
def test_non_object_channel_entries_are_skipped(driver, parser_name):
    assert getattr(driver, parser_name)([None, "invalid", []]) == ([], [])


class TestAnalyzerIntegration:
    def test_ofdm_profile_modulations_survive_normalization(self, driver):
        analysis = analyze(driver.get_docsis_data())

        ofdm = next(ch for ch in analysis["ds_channels"] if ch["channel_family"] == "ofdm")
        ofdma = next(ch for ch in analysis["us_channels"] if ch["channel_family"] == "ofdma")
        assert ofdm["modulation"] == "OFDM"
        assert ofdm["profile_modulation"] == "4096QAM"
        assert ofdma["modulation"] == "OFDMA"
        assert ofdma["profile_modulation"] == "256QAM"


class TestDeviceInfo:
    def test_device_info(self, driver):
        info = driver.get_device_info()
        assert info["manufacturer"] == "Sagemcom"
        assert info["model"] == "F3896LG (Virgin Media Hub 5)"
        assert "sw_version" not in info
        assert info["docsis_status"] == "operational"
        assert info["uptime_seconds"] == 72394


class TestConnectionInfo:
    def test_provisioned_rates(self, driver):
        conn = driver.get_connection_info()
        assert conn["max_downstream_kbps"] == 1230000
        assert conn["max_upstream_kbps"] == 110000
        assert conn["connection_type"] == "DOCSIS 3.1"

    def test_highest_positive_rate_wins_independently_of_flow_order(self, driver):
        flows = {
            "serviceFlows": [
                {"serviceFlow": {
                    "direction": "downstream",
                    "maxTrafficRate": 1230000450,
                }},
                {"serviceFlow": {
                    "direction": "downstream",
                    "maxTrafficRate": "invalid",
                }},
                {"serviceFlow": {
                    "direction": "upstream",
                    "maxTrafficRate": 110000274,
                }},
                {"serviceFlow": {
                    "direction": "downstream",
                    "maxTrafficRate": 100000000,
                }},
                {"serviceFlow": {
                    "direction": "upstream",
                    "maxTrafficRate": 0,
                }},
                {"serviceFlow": {
                    "direction": "upstream",
                    "maxTrafficRate": -1,
                }},
                {"serviceFlow": {"direction": "downstream"}},
                {"serviceFlow": {
                    "direction": "upstream",
                    "maxTrafficRate": 20000000,
                }},
            ],
        }
        with patch.object(driver, "_get", return_value=flows):
            conn = driver.get_connection_info()

        assert conn == {
            "max_downstream_kbps": 1230000,
            "max_upstream_kbps": 110000,
            "connection_type": "DOCSIS 3.1",
        }


@pytest.mark.parametrize(
    ("method_name", "expected"),
    [
        (
            "get_device_info",
            {
                "manufacturer": "Sagemcom",
                "model": "F3896LG (Virgin Media Hub 5)",
            },
        ),
        ("get_connection_info", {"connection_type": "DOCSIS 3.1"}),
    ],
)
def test_optional_metadata_is_fail_soft_for_non_object_json(
    driver,
    method_name,
    expected,
):
    response = MagicMock()
    response.json.return_value = []
    driver._session.get.side_effect = None
    driver._session.get.return_value = response

    assert getattr(driver, method_name)() == expected


class TestRegistry:
    def test_registered(self):
        from app.drivers import driver_registry
        assert "f3896lg" in driver_registry.get_all_type_keys()

    def test_setup_hints(self):
        from app.drivers import driver_registry

        hints = driver_registry.get_driver_hints()["f3896lg"]
        assert hints["default_url"] == "https://192.168.100.1"
        assert hints["credentials_required"] is False
