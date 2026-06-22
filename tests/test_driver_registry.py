import pytest
from app.drivers.registry import DriverRegistry
from app.drivers.base import ModemDriver


class FakeDriver(ModemDriver):
    def login(self): pass
    def get_docsis_data(self): return {}
    def get_device_info(self): return {}
    def get_connection_info(self): return {}


class FlagDriver(FakeDriver):
    def __init__(self, url, user, password, *, force_mode=False):
        super().__init__(url, user, password)
        self.force_mode = force_mode


class TestDriverRegistry:
    def setup_method(self):
        self.reg = DriverRegistry()

    def test_register_and_load_builtin(self):
        self.reg.register_builtin("fake", "tests.test_driver_registry.FakeDriver", "Fake Modem")
        driver = self.reg.load_driver("fake", "http://x", "u", "p")
        assert isinstance(driver, FakeDriver)

    def test_load_builtin_passes_init_kwargs(self):
        self.reg.register_builtin(
            "flagged",
            "tests.test_driver_registry.FlagDriver",
            "Flagged Modem",
            init_kwargs={"force_mode": True},
        )

        driver = self.reg.load_driver("flagged", "http://x", "u", "p")

        assert isinstance(driver, FlagDriver)
        assert driver.force_mode is True

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown modem_type"):
            self.reg.load_driver("nonexistent", "http://x", "u", "p")

    def test_get_available_drivers_sorted(self):
        self.reg.register_builtin("bbb", "tests.test_driver_registry.FakeDriver", "BBB Modem")
        self.reg.register_builtin("aaa", "tests.test_driver_registry.FakeDriver", "AAA Modem")
        result = self.reg.get_available_drivers()
        assert result == [("aaa", "AAA Modem"), ("bbb", "BBB Modem")]

    def test_has_driver(self):
        assert not self.reg.has_driver("fake")
        self.reg.register_builtin("fake", "tests.test_driver_registry.FakeDriver", "Fake")
        assert self.reg.has_driver("fake")

    def test_registered_builtin_keys_are_the_only_available_driver_keys(self):
        self.reg.register_builtin("fake", "tests.test_driver_registry.FakeDriver", "Fake")
        assert self.reg.get_all_type_keys() == {"fake"}


class TestGenericDriver:
    def setup_method(self):
        from app.drivers.generic import GenericDriver
        self.driver = GenericDriver("http://x", "", "")

    def test_login_is_noop(self):
        self.driver.login()  # should not raise

    def test_get_docsis_data_returns_valid_structure(self):
        data = self.driver.get_docsis_data()
        assert "channelDs" in data
        assert "channelUs" in data
        assert "docsis30" in data["channelDs"]
        assert "docsis31" in data["channelDs"]
        assert data["channelDs"]["docsis30"] == []
        assert data["channelDs"]["docsis31"] == []

    def test_get_device_info_returns_dict(self):
        info = self.driver.get_device_info()
        assert info["model"] == "Generic Router"
        assert "sw_version" in info

    def test_get_connection_info_returns_dict(self):
        info = self.driver.get_connection_info()
        assert isinstance(info, dict)

    def test_generic_in_builtin_registry(self):
        from app.drivers import driver_registry
        assert driver_registry.has_driver("generic")
