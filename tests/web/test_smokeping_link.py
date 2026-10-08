"""The SmokePing view links to the configured instance, and only over http(s)."""

import pytest

from app.web import _shell_nav_context, _web_link


@pytest.mark.parametrize("value, expected", [
    ("http://smokeping.lan/smokeping/", "http://smokeping.lan/smokeping"),
    ("  https://ping.example.net  ", "https://ping.example.net"),
    ("javascript:alert(1)", ""),
    ("JaVaScRiPt:alert(1)", ""),
    ("data:text/html,x", ""),
    ("//smokeping.lan", ""),
    ("smokeping.lan/smokeping", ""),
    ("", ""),
    (None, ""),
])
def test_only_web_addresses_become_links(value, expected):
    assert _web_link(value) == expected


def test_the_page_context_carries_only_the_checked_link(config_mgr):
    config_mgr.save({"smokeping_url": "javascript:alert(1)", "smokeping_targets": "Gateway"})
    assert _shell_nav_context(config_mgr)["smokeping_url"] == ""
    config_mgr.save({"smokeping_url": "http://smokeping.lan/smokeping/", "smokeping_targets": "Gateway"})
    assert _shell_nav_context(config_mgr)["smokeping_url"] == "http://smokeping.lan/smokeping"
