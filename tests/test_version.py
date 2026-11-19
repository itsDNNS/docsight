"""Tests for application version provenance helpers."""

import subprocess

from app import version


def test_available_app_version_uses_exact_sources_only(monkeypatch, clear_version_cache):
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


def test_display_app_version_may_fall_back_to_nearest_tag(running_app_version):
    assert running_app_version == "v2026-07-01.1"


def test_git_tag_ignores_the_callers_repository(tmp_path, monkeypatch):
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
           "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"], ["tag", "v-foreign"]):
        subprocess.run([*git, *args], check=True)
    monkeypatch.chdir(tmp_path)

    assert version._git_tag.__wrapped__("--abbrev=0") != "v-foreign"
