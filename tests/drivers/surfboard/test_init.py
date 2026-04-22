"""Tests for SURFboard driver initialization."""

from app.drivers.surfboard import SurfboardDriver

class TestDriverInit:
    def test_stores_credentials(self):
        d = SurfboardDriver("https://192.168.100.1", "admin", "pass123")
        assert d._url == "https://192.168.100.1"
        assert d._user == "admin"
        assert d._password == "pass123"

    def test_https_upgrade(self):
        d = SurfboardDriver("http://192.168.100.1", "admin", "pass")
        assert d._url == "https://192.168.100.1"

    def test_trailing_slash_removed(self):
        d = SurfboardDriver("https://192.168.100.1/", "admin", "pass")
        assert d._url == "https://192.168.100.1"

    def test_https_preserved(self):
        d = SurfboardDriver("https://10.0.0.1", "admin", "pass")
        assert d._url == "https://10.0.0.1"

    def test_ssl_verify_disabled(self):
        d = SurfboardDriver("https://192.168.100.1", "admin", "pass")
        assert d._session.verify is False

    def test_load_via_registry(self):
        from app.drivers import load_driver
        d = load_driver("surfboard", "https://192.168.100.1", "admin", "pass")
        assert isinstance(d, SurfboardDriver)


# -- Login --

