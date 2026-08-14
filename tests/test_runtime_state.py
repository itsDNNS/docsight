from concurrent.futures import ThreadPoolExecutor

from app.runtime import RuntimeState


def test_runtime_state_preserves_update_and_reset_semantics():
    state = RuntimeState()
    state.update(
        analysis={"summary": {"health": "good"}},
        poll_interval=30,
        connection_info={"kind": "cable"},
        speedtest_latest={"id": 7},
    )
    state.update(analysis=None, error="offline")

    snapshot = state.snapshot()
    assert snapshot["analysis"]["summary"]["health"] == "good"
    assert snapshot["error"] == "offline"
    assert snapshot["poll_interval"] == 30

    state.reset_modem()
    snapshot = state.snapshot()
    assert snapshot["analysis"] is None
    assert snapshot["connection_info"] is None
    assert snapshot["speedtest_latest"] == {"id": 7}

    state.clear_speedtest_latest()
    assert state.snapshot()["speedtest_latest"] is None


def test_runtime_state_is_thread_safe():
    state = RuntimeState()

    def update(value):
        for _ in range(100):
            state.update(device_info={"value": value})
            assert "device_info" in state.snapshot()

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(update, range(4)))

    assert state.snapshot()["device_info"]["value"] in range(4)
