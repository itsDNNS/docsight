"""Focused regressions for reproducible report request windows."""

from unittest.mock import Mock, patch

import pytest



def _call_route(route, path, *, storage=None, state=None, generated="artifact"):
    from app.modules.reports import routes

    if storage is None:
        storage = Mock()
        storage.get_range_data.return_value = []
    generator_name = "generate_report" if route == "report" else "generate_complaint_text"
    generator_value = b"%PDF-test" if route == "report" else generated
    with app.test_request_context(path), \
         patch.object(routes, "get_storage", return_value=storage), \
         patch.object(routes, "get_config_manager", return_value=None), \
         patch.object(routes, "get_state", return_value=state or {}), \
         patch.object(routes, generator_name, return_value=generator_value) as generator:
        result = getattr(getattr(routes, f"api_{route}"), "__wrapped__")()
    return result, storage, generator


def _status_json(result):
    if isinstance(result, tuple):
        response, status = result
        return status, response.get_json()
    return result.status_code, result.get_json()


def test_exact_complaint_window_succeeds_without_live_analysis():
    from app.modules.reports import routes

    storage = Mock()
    storage.get_range_data.return_value = [{
        "timestamp": "2026-05-02T12:00:00Z",
        "summary": {"health": "good"},
        "ds_channels": [],
        "us_channels": [],
    }]

    with app.test_request_context(
        "/api/complaint?from=2026-05-01T00:00:00Z&to=2026-05-03T00:00:00Z"
    ), patch.object(routes, "get_storage", return_value=storage), \
         patch.object(routes, "get_config_manager", return_value=None), \
         patch.object(routes, "get_state", return_value={}), \
         patch.object(routes, "generate_complaint_text", return_value="historical") as generate:
        response = getattr(routes.api_complaint, "__wrapped__")()

    assert response.status_code == 200
    assert response.get_json() == {
        "text": "historical",
        "lang": "en",
        "window": {
            "from": "2026-05-01T00:00:00Z",
            "to": "2026-05-03T00:00:00Z",
        },
    }
    storage.get_range_data.assert_called_once_with(
        "2026-05-01T00:00:00Z", "2026-05-03T00:00:00Z"
    )
    assert generate.call_args.kwargs["report_start"] == "2026-05-01T00:00:00Z"
    assert generate.call_args.kwargs["report_end"] == "2026-05-03T00:00:00Z"
    assert "current_analysis" not in generate.call_args.kwargs


@pytest.mark.parametrize("route", ["report", "complaint"])
@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        (
            "from=2026-05-01T00:00:00Z&to=2026-05-03T00:00:00Z",
            ("2026-05-01T00:00:00Z", "2026-05-03T00:00:00Z"),
        ),
        (
            "from=2026-05-01T02:30:00%2B02:30&to=2026-05-03T01:00:00%2B01:00",
            ("2026-05-01T00:00:00Z", "2026-05-03T00:00:00Z"),
        ),
    ],
)
def test_exact_window_normalizes_utc_and_offsets_for_both_endpoints(
    route, bounds, expected
):
    result, storage, generator = _call_route(
        route,
        f"/api/{route}?{bounds}",
    )

    assert _status_json(result)[0] == 200
    storage.get_range_data.assert_called_once_with(*expected)
    assert generator.call_args.kwargs["report_start"] == expected[0]
    assert generator.call_args.kwargs["report_end"] == expected[1]
    if route == "complaint":
        assert result.get_json()["window"] == {
            "from": "2026-05-01T00:00:00Z",
            "to": "2026-05-03T00:00:00Z",
        }


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("from=2026-05-01T00:00:00Z", {
            "error": "Both 'from' and 'to' are required",
            "code": "window_bounds_required",
        }),
        ("to=2026-05-01T00:00:00Z", {
            "error": "Both 'from' and 'to' are required",
            "code": "window_bounds_required",
        }),
        ("from=not-a-date&to=2026-05-01T00:00:00Z", {
            "error": "'from' must be a valid ISO-8601 timestamp",
            "code": "window_invalid_timestamp",
            "field": "from",
        }),
        ("from=2026-05-01T00:00:00&to=2026-05-02T00:00:00Z", {
            "error": "'from' must include a timezone",
            "code": "window_timezone_required",
            "field": "from",
        }),
        ("from=2026-05-03T00:00:00Z&to=2026-05-01T00:00:00Z", {
            "error": "'from' must not be after 'to'",
            "code": "window_invalid_order",
        }),
        ("from=2026-01-01T00:00:00Z&to=2026-04-02T00:00:00Z", {
            "error": "Report window must not exceed 90 days",
            "code": "window_too_large",
        }),
        ("days=7&from=2026-05-01T00:00:00Z&to=2026-05-02T00:00:00Z", {
            "error": "'days' cannot be combined with 'from' and 'to'",
            "code": "window_ambiguous_mode",
        }),
        ("days=not-an-integer", {
            "error": "'days' must be an integer",
            "code": "window_invalid_days",
            "field": "days",
        }),
    ],
)
@pytest.mark.parametrize("route", ["report", "complaint"])
def test_window_validation_returns_stable_json_400(route, query, expected):
    result, storage, generator = _call_route(route, f"/api/{route}?{query}")

    assert _status_json(result) == (400, expected)
    storage.get_range_data.assert_not_called()
    generator.assert_not_called()


@pytest.mark.parametrize(
    ("query", "expected_days"),
    [("", 7), ("?days=12", 12), ("?days=0", 1), ("?days=999", 90)],
)
@pytest.mark.parametrize("route", ["report", "complaint"])
def test_rolling_window_default_explicit_and_clamp_remain_compatible(
    route, query, expected_days
):
    from app.modules.reports import routes

    storage = Mock()
    storage.get_range_data.return_value = []
    generator_name = "generate_report" if route == "report" else "generate_complaint_text"
    generator_value = b"%PDF-test" if route == "report" else "text"
    with app.test_request_context(f"/api/{route}{query}"), \
         patch.object(routes, "get_storage", return_value=storage), \
         patch.object(routes, "get_config_manager", return_value=None), \
         patch.object(routes, "get_state", return_value={}), \
         patch.object(routes, "utc_now", return_value="2026-08-13T12:00:00Z"), \
         patch.object(routes, "utc_cutoff", return_value="2026-08-06T12:00:00Z") as cutoff, \
         patch.object(routes, generator_name, return_value=generator_value):
        response = getattr(getattr(routes, f"api_{route}"), "__wrapped__")()

    assert response.status_code == 200
    cutoff.assert_called_once_with(days=expected_days)
    storage.get_range_data.assert_called_once_with(
        "2026-08-06T12:00:00Z", "2026-08-13T12:00:00Z"
    )


def test_pdf_route_uses_latest_snapshot_data_without_live_analysis():
    snapshots = [{
        "timestamp": "2026-05-01T12:00:00Z",
        "summary": {"health": "good"},
        "ds_channels": [],
        "us_channels": [],
    }]
    storage = Mock()
    storage.get_range_data.return_value = snapshots

    result, _, generator = _call_route(
        "report",
        "/api/report?from=2026-05-01T00:00:00Z&to=2026-05-02T00:00:00Z",
        storage=storage,
        state={"connection_info": {"device_name": "export-time configuration"}},
    )

    assert result.status_code == 200
    assert generator.call_args.args[0] == snapshots
    assert generator.call_args.kwargs["connection_info"] == {
        "device_name": "export-time configuration"
    }
    assert len(generator.call_args.args) == 1


def test_automatic_bnetz_lookup_uses_normalized_exact_window():
    from app.modules.reports import routes

    storage = Mock(db_path="/tmp/report-period.db")
    storage.get_range_data.return_value = []
    bnetz_storage = Mock()
    bnetz_storage.get_bnetz_in_range.return_value = [{
        "id": 8,
        "verdict_download": "deviation",
        "verdict_upload": "ok",
    }]
    with app.test_request_context(
        "/api/complaint?include_bnetz=true"
        "&from=2026-05-01T02:00:00%2B02:00&to=2026-05-03T02:00:00%2B02:00"
    ), patch.object(routes, "get_storage", return_value=storage), \
         patch.object(routes, "get_config_manager", return_value=None), \
         patch.object(routes, "get_state", return_value={}), \
         patch("app.modules.bnetz.storage.BnetzStorage", return_value=bnetz_storage), \
         patch.object(routes, "generate_complaint_text", return_value="text") as generate:
        response = getattr(routes.api_complaint, "__wrapped__")()

    assert response.status_code == 200
    bnetz_storage.get_bnetz_in_range.assert_called_once_with(
        "2026-05-01T00:00:00Z", "2026-05-03T00:00:00Z"
    )
    assert generate.call_args.kwargs["bnetz_data"]["id"] == 8


def test_explicit_bnetz_id_keeps_id_lookup_compatibility():
    from app.modules.reports import routes

    storage = Mock(db_path="/tmp/report-period.db")
    storage.get_range_data.return_value = []
    bnetz_storage = Mock()
    bnetz_storage.get_bnetz_measurements.return_value = [{"id": 7}, {"id": 9}]
    with app.test_request_context(
        "/api/complaint?bnetz_id=9"
        "&from=2026-05-01T00:00:00Z&to=2026-05-02T00:00:00Z"
    ), patch.object(routes, "get_storage", return_value=storage), \
         patch.object(routes, "get_config_manager", return_value=None), \
         patch.object(routes, "get_state", return_value={}), \
         patch("app.modules.bnetz.storage.BnetzStorage", return_value=bnetz_storage), \
         patch.object(routes, "generate_complaint_text", return_value="text") as generate:
        response = getattr(routes.api_complaint, "__wrapped__")()

    assert response.status_code == 200
    bnetz_storage.get_bnetz_measurements.assert_called_once_with(limit=100)
    bnetz_storage.get_bnetz_in_range.assert_not_called()
    assert generate.call_args.kwargs["bnetz_data"] == {"id": 9}
