"""Regression contracts for modulation visual rerender synchronization."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULATION_VISUAL_TEST = ROOT / "tests" / "e2e" / "test_modulation_visual.py"


def _function_calls(function: ast.FunctionDef) -> list[ast.Call]:
    return [node for node in ast.walk(function) if isinstance(node, ast.Call)]


def _method_call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def test_chart_rerender_checks_use_deterministic_render_wait():
    tree = ast.parse(MODULATION_VISUAL_TEST.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    expected_waits = {
        "test_charts_rerender_on_direction_switch": {
            "direction": "ds",
            "min_samples": 7,
        },
        "test_charts_rerender_on_range_switch": {
            "direction": "us",
            "min_samples": 30,
        },
    }

    for method_name in expected_waits:
        method = functions.get(method_name)
        assert method is not None, f"modulation visual test must define {method_name}"
        call_names = [_method_call_name(call) for call in _function_calls(method)]
        assert "wait_for_timeout" not in call_names, (
            f"{method_name} must wait for the resulting chart, not a fixed timeout"
        )

    helper = functions.get("_wait_for_distribution_chart")
    assert helper is not None, "rerender checks must share a deterministic chart wait"
    helper_calls = _function_calls(helper)
    helper_call_names = [_method_call_name(call) for call in helper_calls]
    assert "wait_for_timeout" not in helper_call_names, (
        "_wait_for_distribution_chart must wait for chart state, not a fixed timeout"
    )
    wait_calls = [
        call for call in helper_calls if _method_call_name(call) == "wait_for_function"
    ]
    assert len(wait_calls) == 1, "chart wait helper must use page.wait_for_function"
    timeout_keywords = [
        keyword for keyword in wait_calls[0].keywords if keyword.arg == "timeout"
    ]
    assert len(timeout_keywords) == 1, (
        "chart wait helper's wait_for_function call must set an explicit timeout"
    )

    for method_name, expected in expected_waits.items():
        method = functions.get(method_name)
        assert method is not None, f"modulation visual test must define {method_name}"
        helper_calls = [
            call
            for call in _function_calls(method)
            if _method_call_name(call) == "_wait_for_distribution_chart"
        ]
        assert len(helper_calls) == 1, (
            f"{method_name} must wait once for the resulting distribution chart"
        )
        keywords = {keyword.arg: keyword.value for keyword in helper_calls[0].keywords}
        assert "direction" in keywords, (
            f"{method_name} chart wait must pass the direction keyword"
        )
        assert "min_samples" in keywords, (
            f"{method_name} chart wait must pass the min_samples keyword"
        )
        assert ast.literal_eval(keywords["direction"]) == expected["direction"]
        assert ast.literal_eval(keywords["min_samples"]) == expected["min_samples"]
