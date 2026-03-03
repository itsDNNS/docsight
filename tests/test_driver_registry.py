import pytest
from unittest.mock import MagicMock
from app.drivers.registry import DriverRegistry
from app.drivers.base import ModemDriver


class FakeDriver(ModemDriver):
    def login(self): pass
    def get_docsis_data(self): return {}
    def get_device_info(self): return {}
    def get_connection_info(self): return {}


class TestDriverRegistry:
    def setup_method(self):
        self.reg = DriverRegistry()

    def test_register_and_load_builtin(self):
        self.reg.register_builtin("fake", "tests.test_driver_registry.FakeDriver", "Fake Modem")
        driver = self.reg.load_driver("fake", "http://x", "u", "p")
        assert isinstance(driver, FakeDriver)

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

    def test_module_driver_overrides_builtin(self):
        self.reg.register_builtin("fake", "tests.test_driver_registry.FakeDriver", "Built-in Fake")
        self.reg.register_module_driver("fake", FakeDriver, "Module Fake")
        result = self.reg.get_available_drivers()
        assert ("fake", "Module Fake") in result

    def test_module_driver_loads(self):
        self.reg.register_module_driver("custom", FakeDriver, "Custom Driver")
        driver = self.reg.load_driver("custom", "http://x", "u", "p")
        assert isinstance(driver, FakeDriver)

    def test_register_module_drivers_from_loader(self):
        mod = MagicMock()
        mod.driver_class = FakeDriver
        mod.contributes = {"driver": "driver.py:FakeDriver"}
        mod.id = "community.fake"
        mod.name = "Fake Community Driver"
        loader = MagicMock()
        loader.get_enabled_modules.return_value = [mod]
        self.reg.register_module_drivers(loader)
        assert self.reg.has_driver("community.fake")

    def test_register_module_drivers_skips_non_driver_modules(self):
        mod = MagicMock()
        mod.driver_class = None
        mod.contributes = {"collector": "collector.py:Foo"}
        mod.id = "community.collector"
        loader = MagicMock()
        loader.get_enabled_modules.return_value = [mod]
        self.reg.register_module_drivers(loader)
        assert not self.reg.has_driver("community.collector")


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
