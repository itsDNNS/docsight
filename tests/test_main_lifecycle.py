"""Focused lifecycle checks for the application entrypoint."""

from types import SimpleNamespace

import pytest

from app import main


def test_web_thread_exit_returns_normally_in_desktop_mode(monkeypatch):
    calls = []
    stopped_thread = SimpleNamespace(is_alive=lambda: False)
    monkeypatch.setenv("DOCSIGHT_DESKTOP_MODE", "1")

    main._wait_for_web_thread(
        stopped_thread,
        lambda: calls.append("stop_polling"),
    )

    assert calls == ["stop_polling"]


def test_web_thread_exit_raises_after_stopping_polling_in_server_mode(monkeypatch):
    calls = []
    stopped_thread = SimpleNamespace(is_alive=lambda: False)
    monkeypatch.delenv("DOCSIGHT_DESKTOP_MODE", raising=False)

    with pytest.raises(RuntimeError, match="Web server stopped unexpectedly"):
        main._wait_for_web_thread(
            stopped_thread,
            lambda: calls.append("stop_polling"),
        )

    assert calls == ["stop_polling"]


def test_keyboard_shutdown_stops_polling_resources(monkeypatch):
    calls = []
    monkeypatch.delenv("DOCSIGHT_DESKTOP_MODE", raising=False)

    def interrupted():
        raise KeyboardInterrupt

    main._wait_for_web_thread(
        SimpleNamespace(is_alive=interrupted),
        lambda: calls.append("stop_polling"),
    )

    assert calls == ["stop_polling"]
