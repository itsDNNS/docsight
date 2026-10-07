"""Contracts for deterministic browser shard selection and aggregation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.e2e_shards import (
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
        "baseline_cases": 3,
        "baseline_calibration_seconds": 0.1,
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
    root,
    shard_id,
    files,
    node_ids,
    *,
    failures=0,
    receipt_overrides=None,
    attempt=None,
):
    name = f"full-e2e-shard-{shard_id}"
    if attempt is not None:
        name += f"-attempt-{attempt}"
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    metadata = {"shard": shard_id, "files": files}
    if attempt is not None:
        metadata["attempt"] = attempt
    (directory / "shard-metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
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
        "calibration_seconds": 0.1,
        "cpu_model": "test cpu",
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


def test_repository_manifest_covers_every_e2e_file_once():
    manifest = load_manifest(MANIFEST)
    validate_manifest(manifest, E2E_DIR)

    assert manifest["baseline_cpu_seconds"] > 0
    assert manifest["baseline_calibration_seconds"] > 0
    # The baseline was measured on the suite as it was then.
    assert 0 < manifest["baseline_cases"] <= manifest["expected_total"]


def test_workflow_matrix_runs_every_manifest_shard():
    """A shard added to the manifest must also get a runner, and vice versa."""
    manifest = load_manifest(MANIFEST)
    workflow = WORKFLOW.read_text(encoding="utf-8")
    ids = json.dumps([str(shard["id"]) for shard in manifest["shards"]], separators=(",", ":"))

    assert f"|| '{ids}'" in workflow
    assert f"max-parallel: {len(manifest['shards'])}" in workflow


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
        summarize_results(tmp_path, manifest, e2e_dir=e2e_dir)

    _write_result(tmp_path, 3, ["test_c.py"], ["tests/e2e/test_c.py::test_c"])
    assert summarize_results(
        tmp_path, manifest, e2e_dir=e2e_dir
    ).total == 3


@pytest.mark.parametrize("failed_attempt, passed_attempt", [(1, 2), (2, 3)])
def test_summary_validates_only_the_latest_attempt_of_each_shard(
    tmp_path, failed_attempt, passed_attempt
):
    """Re-running a failed shard leaves its earlier artifact behind; the newest
    attempt decides."""
    manifest = _manifest(["test_a.py"], ["test_b.py"], ["test_c.py"])
    e2e_dir = tmp_path / "e2e"
    e2e_dir.mkdir()
    for name in ("test_a.py", "test_b.py", "test_c.py"):
        (e2e_dir / name).write_text("", encoding="utf-8")
    for shard_id, name in ((1, "a"), (2, "b")):
        _write_result(
            tmp_path,
            shard_id,
            [f"test_{name}.py"],
            [f"tests/e2e/test_{name}.py::test_{name}"],
            attempt=1,
        )
    _write_result(
        tmp_path,
        3,
        ["test_c.py"],
        ["tests/e2e/test_c.py::test_c"],
        attempt=failed_attempt,
        receipt_overrides={"job_wall_seconds": 731.0, "wall_seconds": 640.0},
    )

    with pytest.raises(ResultError, match="shard 3 exceeded the 12-minute job wall"):
        summarize_results(tmp_path, manifest, e2e_dir=e2e_dir)

    _write_result(
        tmp_path,
        3,
        ["test_c.py"],
        ["tests/e2e/test_c.py::test_c"],
        attempt=passed_attempt,
    )
    assert summarize_results(tmp_path, manifest, e2e_dir=e2e_dir).total == 3


def test_summary_rejects_two_results_from_the_same_attempt(tmp_path):
    manifest = _manifest(["test_a.py"], ["test_b.py"], ["test_c.py"])
    e2e_dir = tmp_path / "e2e"
    e2e_dir.mkdir()
    for name in ("test_a.py", "test_b.py", "test_c.py"):
        (e2e_dir / name).write_text("", encoding="utf-8")
    for root in (tmp_path, tmp_path / "copy"):
        _write_result(
            root, 1, ["test_a.py"], ["tests/e2e/test_a.py::test_a"], attempt=2
        )

    with pytest.raises(ResultError, match="duplicate shard result for shard 1"):
        summarize_results(tmp_path, manifest, e2e_dir=e2e_dir)


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
        summarize_results(tmp_path, manifest, e2e_dir=e2e_dir)

    _write_result(
        tmp_path,
        2,
        ["test_b.py"],
        ["tests/e2e/test_b.py::test_b"],
        failures=1,
    )
    with pytest.raises(ResultError, match="failed, errored, or skipped"):
        summarize_results(tmp_path, manifest, e2e_dir=e2e_dir)


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
        ("calibration", "lacks a CPU calibration"),
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
        elif defect == "calibration":
            del receipt["calibration_seconds"]
        else:
            receipt["wall_seconds"] = None
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ResultError, match=match):
        summarize_results(tmp_path, manifest, e2e_dir=e2e_dir)


def _budget_run(tmp_path, manifest, receipts):
    e2e_dir = tmp_path / "e2e"
    e2e_dir.mkdir()
    for index, receipt in enumerate(receipts, 1):
        name = f"test_{index}.py"
        (e2e_dir / name).write_text("", encoding="utf-8")
        _write_result(tmp_path, index, [name], [f"tests/e2e/{name}::test_case"], receipt_overrides=receipt)
    return summarize_results(tmp_path, manifest, e2e_dir=e2e_dir)


def test_cpu_budget_compares_work_instead_of_runner_speed(tmp_path):
    manifest = _manifest(["test_1.py"], ["test_2.py"], ["test_3.py"])
    manifest["baseline_cpu_seconds"] = 300
    # A runner half as fast needs twice the CPU time for the same work.
    slow = {"cpu_seconds": 180, "calibration_seconds": 0.2}
    summary = _budget_run(tmp_path, manifest, [slow, slow, slow])
    assert summary.cpu_seconds == 540
    assert summary.normalized_cpu_seconds == pytest.approx(270)
    assert summary.cpu_budget_seconds == pytest.approx(375)


def test_cpu_budget_still_catches_more_work_on_a_fast_runner(tmp_path):
    manifest = _manifest(["test_1.py"], ["test_2.py"], ["test_3.py"])
    manifest["baseline_cpu_seconds"] = 300
    heavy = {"cpu_seconds": 130, "calibration_seconds": 0.1}
    with pytest.raises(ResultError, match=r"390.00s .*exceeds the 25% budget of 375.00s for 3 cases"):
        _budget_run(tmp_path, manifest, [heavy, heavy, heavy])


def test_cpu_budget_grows_with_the_suite(tmp_path):
    manifest = _manifest(["test_1.py"], ["test_2.py"], ["test_3.py"])
    manifest["baseline_cpu_seconds"] = 200
    manifest["baseline_cases"] = 2
    # 100 s per case at the baseline: three cases get 300 s plus 25 %.
    receipt = {"cpu_seconds": 120, "calibration_seconds": 0.1}
    assert _budget_run(tmp_path, manifest, [receipt] * 3).cpu_budget_seconds == pytest.approx(375)


@pytest.mark.parametrize("key", ["baseline_cpu_seconds", "baseline_cases", "baseline_calibration_seconds"])
def test_sharded_runs_need_the_measured_baseline(tmp_path, key):
    manifest = _manifest(["test_1.py"], ["test_2.py"], ["test_3.py"])
    del manifest[key]
    with pytest.raises(ResultError, match=f"lacks a measured positive {key}"):
        _budget_run(tmp_path, manifest, [{}, {}, {}])


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
        tmp_path, manifest, e2e_dir=e2e_dir
    )
    assert summary.per_shard == (3,)
    assert summary.wall_seconds == (1800.0,)
    assert summary.job_wall_seconds == (1800.0,)


def test_workflow_runs_safe_non_retrying_shards_and_an_always_gate():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "fail-fast: false" in workflow
    assert "single_process:" in workflow
    assert "'[\"1\",\"2\",\"3\",\"4\",\"5\",\"6\"]'" in workflow
    assert "max-parallel: 6" in workflow
    assert "E2E_JOB_STARTED_EPOCH" in workflow
    assert "python scripts/e2e_shards.py run" in workflow
    assert "python scripts/e2e_shards.py summarize" in workflow
    assert "--receipt" in workflow
    assert "run-receipt.json" in workflow
    assert "if: always()" in workflow
    assert "Upload shard results, logs, and traces" in workflow
    assert (
        "name: full-e2e-shard-${{ matrix.shard }}-attempt-${{ github.run_attempt }}"
        in workflow
    )
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
