"""Contracts for deterministic browser shard selection and aggregation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.e2e_shards import (
    EXPECTED_TOTAL,
    ManifestError,
    ResultError,
    load_manifest,
    summarize_results,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
E2E_DIR = ROOT / "tests" / "e2e"
MANIFEST = E2E_DIR / "shards.json"
WORKFLOW = ROOT / ".github" / "workflows" / "full-e2e.yml"


def _manifest(*shards):
    return {
        "version": 1,
        "expected_total": 3,
        "baseline_cpu_seconds": 100,
        "shards": [
            {
                "id": index,
                "collected_cases": len(files),
                "files": list(files),
            }
            for index, files in enumerate(shards, 1)
        ],
    }


def _write_result(
    root, shard_id, files, node_ids, *, failures=0, receipt_overrides=None
):
    directory = root / f"full-e2e-shard-{shard_id}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "shard-metadata.json").write_text(
        json.dumps({"shard": shard_id, "files": files}), encoding="utf-8"
    )
    (directory / "collected.txt").write_text(
        "".join(f"{node_id}\n" for node_id in node_ids), encoding="utf-8"
    )
    (directory / "junit.xml").write_text(
        (
            f'<testsuites tests="{len(node_ids)}" failures="{failures}" '
            'errors="0" skipped="0"><testsuite/></testsuites>'
        ),
        encoding="utf-8",
    )
    receipt = {
        "selection": shard_id,
        "started_utc": "2026-08-15T10:00:00+00:00",
        "ended_utc": "2026-08-15T10:00:01+00:00",
        "wall_seconds": 1.0,
        "job_wall_seconds": 1.0,
        "cpu_seconds": 1.0,
        "peak_rss_kb": 1024,
        "platform": "test-linux",
        "retry_count": 0,
        "returncode": 0,
        "junit": {
            "tests": len(node_ids),
            "failures": failures,
            "errors": 0,
            "skipped": 0,
        },
        "baseline_processes": [],
        "baseline_listeners": [],
        "leaked_processes": [],
        "leaked_listeners": [],
    }
    receipt.update(receipt_overrides or {})
    (directory / "run-receipt.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )


def test_repository_manifest_covers_every_e2e_file_once_and_549_cases():
    manifest = load_manifest(MANIFEST)
    validated = validate_manifest(manifest, E2E_DIR)

    assert manifest["expected_total"] == EXPECTED_TOTAL == 549
    assert manifest["baseline_cpu_seconds"] > 0
    assert [shard["collected_cases"] for shard in manifest["shards"]] == [
        80,
        140,
        161,
        168,
    ]
    assert len(validated) == 28


@pytest.mark.parametrize("defect", ["missing", "duplicate", "stale"])
def test_manifest_validation_rejects_incomplete_or_ambiguous_membership(
    tmp_path, defect
):
    e2e_dir = tmp_path / "e2e"
    e2e_dir.mkdir()
    for name in ("test_a.py", "test_b.py", "test_c.py"):
        (e2e_dir / name).write_text("def test_case(): pass\n", encoding="utf-8")
    manifest = _manifest(["test_a.py"], ["test_b.py"], ["test_c.py"])
    if defect == "missing":
        manifest["shards"][2]["files"] = []
    elif defect == "duplicate":
        manifest["shards"][2]["files"] = ["test_a.py", "test_c.py"]
    else:
        manifest["shards"][2]["files"] = ["test_c.py", "test_removed.py"]

    with pytest.raises(ManifestError, match=defect):
        validate_manifest(manifest, e2e_dir)


def test_summary_requires_every_shard_and_exact_node_id_union(tmp_path):
    manifest = _manifest(["test_a.py"], ["test_b.py"], ["test_c.py"])
    e2e_dir = tmp_path / "e2e"
    e2e_dir.mkdir()
    for name in ("test_a.py", "test_b.py", "test_c.py"):
        (e2e_dir / name).write_text("", encoding="utf-8")
    _write_result(tmp_path, 1, ["test_a.py"], ["tests/e2e/test_a.py::test_a"])
    _write_result(tmp_path, 2, ["test_b.py"], ["tests/e2e/test_b.py::test_b"])

    with pytest.raises(ResultError, match="missing shard result.*3"):
        summarize_results(tmp_path, manifest, expected_total=3, e2e_dir=e2e_dir)

    _write_result(tmp_path, 3, ["test_c.py"], ["tests/e2e/test_c.py::test_c"])
    assert summarize_results(
        tmp_path, manifest, expected_total=3, e2e_dir=e2e_dir
    ).total == 3


def test_summary_rejects_cross_shard_nodes_and_failed_junit(tmp_path):
    manifest = _manifest(["test_a.py"], ["test_b.py"], ["test_c.py"])
    e2e_dir = tmp_path / "e2e"
    e2e_dir.mkdir()
    for name in ("test_a.py", "test_b.py", "test_c.py"):
        (e2e_dir / name).write_text("", encoding="utf-8")
    duplicate = "tests/e2e/test_a.py::test_a"
    _write_result(tmp_path, 1, ["test_a.py"], [duplicate])
    _write_result(tmp_path, 2, ["test_b.py"], [duplicate])
    _write_result(
        tmp_path,
        3,
        ["test_c.py"],
        ["tests/e2e/test_c.py::test_c"],
    )
    with pytest.raises(ResultError, match="outside its manifest"):
        summarize_results(tmp_path, manifest, expected_total=3, e2e_dir=e2e_dir)

    _write_result(
        tmp_path,
        2,
        ["test_b.py"],
        ["tests/e2e/test_b.py::test_b"],
        failures=1,
    )
    with pytest.raises(ResultError, match="failed, errored, or skipped"):
        summarize_results(tmp_path, manifest, expected_total=3, e2e_dir=e2e_dir)


@pytest.mark.parametrize(
    ("defect", "match"),
    [
        ("missing-receipt", "invalid run receipt"),
        ("wall", "12-minute"),
        ("job-wall", "12-minute job wall"),
        ("cpu", "25% budget"),
        ("retry", "used retries"),
        ("process", "process or listener leaks"),
        ("listener", "process or listener leaks"),
        ("missing-metric", "invalid wall time"),
    ],
)
def test_summary_rejects_incomplete_or_over_budget_run_receipts(
    tmp_path, defect, match
):
    manifest = _manifest(["test_a.py"], ["test_b.py"], ["test_c.py"])
    e2e_dir = tmp_path / "e2e"
    e2e_dir.mkdir()
    for index, name in enumerate(("test_a.py", "test_b.py", "test_c.py"), 1):
        (e2e_dir / name).write_text("", encoding="utf-8")
        _write_result(
            tmp_path,
            index,
            [name],
            [f"tests/e2e/{name}::test_{index}"],
        )

    receipt_path = tmp_path / "full-e2e-shard-1" / "run-receipt.json"
    if defect == "missing-receipt":
        receipt_path.unlink()
    else:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if defect == "wall":
            receipt["wall_seconds"] = 720
            receipt["job_wall_seconds"] = 720
        elif defect == "job-wall":
            receipt["job_wall_seconds"] = 720
        elif defect == "cpu":
            manifest["baseline_cpu_seconds"] = 1
        elif defect == "retry":
            receipt["retry_count"] = 1
        elif defect == "process":
            receipt["leaked_processes"] = [{"pid": 42, "name": "python"}]
        elif defect == "listener":
            receipt["leaked_listeners"] = [{"pid": 42, "port": 43129}]
        else:
            receipt["wall_seconds"] = None
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ResultError, match=match):
        summarize_results(tmp_path, manifest, expected_total=3, e2e_dir=e2e_dir)


def test_single_process_baseline_receipt_may_exceed_shard_wall_limit(tmp_path):
    manifest = _manifest(["test_a.py"], ["test_b.py"], ["test_c.py"])
    e2e_dir = tmp_path / "e2e"
    e2e_dir.mkdir()
    files = ["test_a.py", "test_b.py", "test_c.py"]
    for name in files:
        (e2e_dir / name).write_text("", encoding="utf-8")
    nodes = [f"tests/e2e/{name}::test_case" for name in files]
    _write_result(
        tmp_path,
        "all",
        files,
        nodes,
        receipt_overrides={
            "wall_seconds": 1800,
            "job_wall_seconds": 1800,
            "cpu_seconds": 1200,
        },
    )

    summary = summarize_results(
        tmp_path, manifest, expected_total=3, e2e_dir=e2e_dir
    )
    assert summary.per_shard == (3,)
    assert summary.wall_seconds == (1800.0,)
    assert summary.job_wall_seconds == (1800.0,)


def test_workflow_runs_safe_non_retrying_shards_and_an_always_gate():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "fail-fast: false" in workflow
    assert "single_process:" in workflow
    assert "'[\"1\",\"2\",\"3\",\"4\"]'" in workflow
    assert "max-parallel: 4" in workflow
    assert "E2E_JOB_STARTED_EPOCH" in workflow
    assert "python scripts/e2e_shards.py run" in workflow
    assert "python scripts/e2e_shards.py summarize" in workflow
    assert "--expected-total 549" in workflow
    assert "--receipt" in workflow
    assert "run-receipt.json" in workflow
    assert "if: always()" in workflow
    assert "Upload shard results, logs, and traces" in workflow
    assert "tests/e2e/screenshots/" in workflow
    assert "--tracing=retain-on-failure" in workflow
    assert "reverse:" in workflow
    assert "E2E_REVERSE" in workflow
    assert "CHANGE_DETECTION_RESULT" in workflow
    assert "Fail closed when PR change detection did not succeed" in workflow
    assert "actions/upload-artifact@v" not in workflow
    assert "actions/download-artifact@v" not in workflow
    assert "rerun" not in workflow.lower()
    assert "retry" not in workflow.lower()
    assert "$(" not in workflow
