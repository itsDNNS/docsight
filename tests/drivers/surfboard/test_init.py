"""Tests for SURFboard driver initialization."""

from app.drivers.surfboard import SurfboardDriver

class TestDriverInit:
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
