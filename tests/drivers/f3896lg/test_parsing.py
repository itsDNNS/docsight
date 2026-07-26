"""Tests for F3896LG (Liberty Global REST) channel parsing and derived values."""


class TestLogin:
    def test_login_ok(self, driver):
        driver.login()  # must not raise


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
        # rxMer 0 means "not reported" on this firmware
        assert ch["mer"] is None
        assert ch["corrErrors"] == 1361678039
        assert ch["nonCorrErrors"] == 483483438


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
        assert ch["modulation"] == "OFDMA"


class TestDeviceInfo:
    def test_device_info(self, driver):
        info = driver.get_device_info()
        assert info["manufacturer"] == "Sagemcom"
        assert info["model"] == "F3896LG (Virgin Media Hub 5)"
        assert info["sw_version"] == "DOCSIS 3.1"
        assert info["docsis_status"] == "operational"
        assert info["uptime_seconds"] == 72394


class TestConnectionInfo:
    def test_provisioned_rates(self, driver):
        conn = driver.get_connection_info()
        assert conn["max_downstream_kbps"] == 1230000
        assert conn["max_upstream_kbps"] == 110000
        assert conn["connection_type"] == "DOCSIS 3.1"


class TestRegistry:
    def test_registered(self):
        from app.drivers import driver_registry
        assert "f3896lg" in driver_registry.get_all_type_keys()
