"""Architecture guards for the deterministic period aggregation boundary."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGGREGATION = ROOT / "app" / "aggregation"


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_consumers_do_not_reintroduce_private_period_aggregators():
    forbidden = {"_compute_worst_values", "_find_worst_channels", "_aggregate_period"}
    paths = [
        ROOT / "app" / "modules" / "reports" / "report.py",
        ROOT / "app" / "modules" / "comparison" / "routes.py",
        ROOT / "app" / "modules" / "evidence" / "routes.py",
    ]
    definitions = {
        node.name
        for path in paths
        for node in ast.walk(_tree(path))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert definitions.isdisjoint(forbidden)


def test_aggregation_imports_stay_pure_and_analyzer_boundary_is_narrow():
    forbidden_roots = {"flask", "sqlite3", "fpdf"}
    forbidden_app = {"app.storage", "app.web"}
    analyzer_names = set()
    for path in AGGREGATION.glob("*.py"):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
                    assert not any(alias.name.startswith(name) for name in forbidden_app)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module.split(".")[0] not in forbidden_roots
                assert not any(module.startswith(name) for name in forbidden_app)
                if module == "app.analyzer":
                    analyzer_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Call):
                called = node.func
                if isinstance(called, ast.Name):
                    assert called.id != "utc_now"
                elif isinstance(called, ast.Attribute):
                    assert not (
                        isinstance(called.value, ast.Name)
                        and called.value.id == "datetime"
                        and called.attr == "now"
                    )
    assert analyzer_names <= {"resolve_ds_power_thresholds", "resolve_snr_thresholds"}


def test_analyzer_never_imports_aggregation():
    for node in ast.walk(_tree(ROOT / "app" / "analyzer.py")):
        if isinstance(node, ast.Import):
            assert all("aggregation" not in alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert "aggregation" not in (node.module or "")


def test_threshold_context_raw_is_not_mutated_inside_aggregation():
    def contains_raw_access(node):
        return any(
            isinstance(child, ast.Attribute) and child.attr == "raw"
            for child in ast.walk(node)
        )

    forbidden_methods = {"update", "pop", "popitem", "clear", "setdefault"}
    for path in AGGREGATION.glob("*.py"):
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
                targets = list(getattr(node, "targets", []))
                target = getattr(node, "target", None)
                if target is not None:
                    targets.append(target)
                assert not any(contains_raw_access(candidate) for candidate in targets)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert not (
                    node.func.attr in forbidden_methods
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "raw"
                )


def test_documented_aggregation_api_and_entry_point_are_pinned():
    import app.aggregation as aggregation

    expected = {
        "AGGREGATION_SCHEMA_VERSION",
        "Coverage",
        "PeriodAggregate",
        "ThresholdContext",
        "Window",
        "aggregate_snapshot_period",
        "canonical_utc_timestamp",
        "derive_diagnostic_notes",
        "derive_historical",
        "report_bounds",
        "select_preferred_bnetz",
        "source_coverage",
    }
    assert set(aggregation.__all__) == expected
    definitions = []
    for path in (ROOT / "app").rglob("*.py"):
        definitions.extend(
            (path, node)
            for node in ast.walk(_tree(path))
            if isinstance(node, ast.FunctionDef)
            and node.name == "aggregate_snapshot_period"
        )
    assert len(definitions) == 1
    assert definitions[0][0] == AGGREGATION / "period.py"
