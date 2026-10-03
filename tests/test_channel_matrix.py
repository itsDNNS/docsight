"""Channels status matrix view model."""

import pytest

from app.channel_matrix import CELL_COUNT, build_channel_matrix, localize_matrix

START = "2026-10-03T00:00:00Z"
END = "2026-10-04T00:00:00Z"


def _ts(minutes):
    hours, mins = divmod(minutes, 60)
    day = 3 + hours // 24
    return f"2026-10-{day:02d}T{hours % 24:02d}:{mins:02d}:00Z"


def _ch(channel_id, health="good", power=4.0, detail="", frequency=None, family="sc_qam"):
    return {"channel_id": channel_id, "frequency": frequency or f"{100 + channel_id} MHz", "power": power,
            "snr": 38.0, "modulation": "256QAM", "channel_family": family, "health": health,
            "health_detail": detail}


def _us(channel_id, health="good", power=44.5, detail=""):
    return {"channel_id": channel_id, "frequency": f"{30 + channel_id} MHz", "power": power,
            "modulation": "OFDMA", "channel_family": "ofdma", "profile_modulation": "256QAM",
            "health": health, "health_detail": detail}


def test_without_snapshots_there_are_no_directions():
    matrix = build_channel_matrix([], START, END)

    assert matrix["directions"] == [] and matrix["snapshots"] == 0
    assert matrix["cells"] == CELL_COUNT and matrix["cell_minutes"] == 30.0


def test_invalid_window_is_rejected():
    with pytest.raises(ValueError):
        build_channel_matrix([], END, START)


def test_stable_channels_share_the_aggregated_row():
    snapshots = [(_ts(m), [_ch(1), _ch(2)], []) for m in range(0, 24 * 60, 30)]

    block = build_channel_matrix(snapshots, START, END)["directions"][0]

    assert block["key"] == "ds" and block["total"] == 2
    assert block["deviating"] == []
    assert [row["channel_id"] for row in block["others"]] == [1, 2]
    assert block["others_cells"] == ["good"] * CELL_COUNT


def test_cells_keep_the_worst_state_and_gaps_stay_empty():
    snapshots = [
        (_ts(0), [_ch(1)], []),
        (_ts(10), [_ch(1, "warning", detail="power warning")], []),
        (_ts(20), [_ch(1)], []),
        (_ts(23 * 60 + 50), [_ch(1)], []),
    ]

    row = build_channel_matrix(snapshots, START, END)["directions"][0]["deviating"][0]

    assert row["cells"][0] == "warning"
    assert row["cells"][1:-1] == [None] * (CELL_COUNT - 2)
    assert row["cells"][-1] == "good"
    assert row["health"] == "good" and row["since"] is None
    assert row["deviating_cells"] == 1


def test_current_deviation_reports_since_and_the_measured_delta():
    snapshots = []
    for minutes in range(0, 24 * 60, 30):
        health = "tolerated" if minutes >= 18 * 60 else "good"
        power = 42.0 if health != "good" else 44.5
        snapshots.append((_ts(minutes), [_ch(1)], [_us(1), _us(5, health, power, "power tolerated low" if health != "good" else "")]))

    matrix = build_channel_matrix(snapshots, START, END)
    upstream = matrix["directions"][1]
    row = upstream["deviating"][0]

    assert row["channel_id"] == 5 and row["family"] == "OFDMA" and row["health"] == "tolerated"
    assert row["since"] == "2026-10-03T18:00:00Z" and row["since_pct"] == 75.0
    assert row["value"] == 42.0 and row["unit"] == "dBmV"
    assert row["measurement"]["delta"] < 0
    assert [r["channel_id"] for r in upstream["others"]] == [1]


def test_deviating_channels_are_sorted_by_current_severity_then_duration():
    snapshots = []
    for minutes in range(0, 24 * 60, 30):
        late = minutes >= 23 * 60
        snapshots.append((_ts(minutes), [
            _ch(1, "tolerated", detail="power tolerated"),
            _ch(2, "critical" if late else "good", detail="power critical" if late else ""),
            _ch(3),
            _ch(4, "warning" if minutes == 60 else "good", detail="snr warning" if minutes == 60 else ""),
        ], []))

    block = build_channel_matrix(snapshots, START, END)["directions"][0]

    assert [row["channel_id"] for row in block["deviating"]] == [2, 1, 4]
    assert [row["channel_id"] for row in block["others"]] == [3]


def test_rows_follow_the_newest_snapshot_and_match_by_frequency():
    snapshots = [
        (_ts(0), [_ch(1, "critical", detail="power critical", frequency="602 MHz"), _ch(9)], []),
        (_ts(60), [_ch(1, frequency="610 MHz")], []),
    ]

    block = build_channel_matrix(snapshots, START, END)["directions"][0]

    assert block["total"] == 1
    row = block["others"][0]
    assert row["cells"][2] == "good" and row["cells"][0] is None


def test_localize_converts_window_and_since():
    snapshots = [(_ts(m), [], [_us(5, "warning", 40.0, "power warning low")]) for m in (0, 30)]
    matrix = localize_matrix(build_channel_matrix(snapshots, START, END), "Europe/Berlin")

    assert matrix["start"] == "2026-10-03T02:00:00"
    assert matrix["end"] == "2026-10-04T02:00:00"
    assert matrix["directions"][0]["deviating"][0]["since"] == "2026-10-03T02:00:00"
