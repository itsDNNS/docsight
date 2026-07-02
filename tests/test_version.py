"""Tests for application version provenance helpers."""

from app import version


def test_available_app_version_uses_exact_sources_only(monkeypatch):
    version.get_available_app_version.cache_clear()
    calls = []

    monkeypatch.setattr(version, "_read_version_file", lambda: None)

    def fake_git_tag(*args):
        calls.append(args)
        if args == ("--exact-match",):
            return None
        if args == ("--abbrev=0",):
            return "v2026-07-01.1"
        return None

    monkeypatch.setattr(version, "_git_tag", fake_git_tag)

    assert version.get_available_app_version() is None
    assert calls == [("--exact-match",)]


def test_display_app_version_may_fall_back_to_nearest_tag(monkeypatch):
    version.get_available_app_version.cache_clear()

    monkeypatch.setattr(version, "_read_version_file", lambda: None)
    monkeypatch.setattr(
        version,
        "_git_tag",
        lambda *args: "v2026-07-01.1" if args == ("--abbrev=0",) else None,
    )

    assert version.get_app_version() == "v2026-07-01.1"
