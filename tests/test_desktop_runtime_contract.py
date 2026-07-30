"""Focused tests for the shared desktop runtime contract boundary."""

from pathlib import Path

import pytest

from app import desktop_runtime_contract as contract

TOKEN = "A" * 43


def test_runtime_contract_round_trips_exact_environment_and_fields():
    state = contract.RuntimeState.create(
        pid=4242,
        port=8765,
        application_version="v1.2.3",
        process_start_time=133700000,
        instance_token=TOKEN,
    )

    assert contract.RuntimeState.from_environment(
        state.export_environment()
    ) == state
    assert set(state.to_mapping()) == contract.RUNTIME_STATE_FIELDS
    assert tuple(state.export_environment()) == (
        contract.INSTANCE_TOKEN_ENV,
        contract.INSTANCE_PID_ENV,
        contract.INSTANCE_START_TIME_ENV,
        contract.INSTANCE_VERSION_ENV,
        contract.WEB_PORT_ENV,
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (contract.INSTANCE_PID_ENV, "true"),
        (contract.INSTANCE_START_TIME_ENV, "0"),
        (contract.WEB_PORT_ENV, "65536"),
        (contract.INSTANCE_VERSION_ENV, "bad\nversion"),
        (contract.INSTANCE_TOKEN_ENV, "short"),
    ],
)
def test_runtime_contract_rejects_invalid_environment(name, value):
    env = contract.RuntimeState.create(
        pid=4242,
        port=8765,
        application_version="v1.2.3",
        process_start_time=133700000,
        instance_token=TOKEN,
    ).export_environment()
    env[name] = value

    with pytest.raises(ValueError):
        contract.RuntimeState.from_environment(env)


def test_shared_app_runtime_modules_never_import_packaging():
    app_dir = Path(__file__).resolve().parents[1] / "app"

    for name in ("desktop_runtime.py", "desktop_runtime_contract.py"):
        assert "packaging" not in (app_dir / name).read_text(encoding="utf-8")
