#!/usr/bin/env python3
"""Validate, select, run, and aggregate deterministic file-level E2E shards."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Windows can validate manifests only
    resource = None

ROOT = Path(__file__).resolve().parents[1]
E2E_DIR = ROOT / "tests" / "e2e"
DEFAULT_MANIFEST = E2E_DIR / "shards.json"
EXPECTED_TOTAL = 545


class ManifestError(ValueError):
    """The shard manifest does not exactly cover the E2E file set."""


class ResultError(RuntimeError):
    """Shard artifacts do not prove a complete successful test union."""


@dataclass(frozen=True)
class ResultSummary:
    total: int
    per_shard: tuple[int, ...]
    wall_seconds: tuple[float, ...]
    job_wall_seconds: tuple[float, ...]
    cpu_seconds: float
    peak_rss_kb: int


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read shard manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestError("shard manifest root must be an object")
    return manifest


def validate_manifest(manifest: dict, e2e_dir: Path = E2E_DIR) -> tuple[str, ...]:
    if manifest.get("version") != 1:
        raise ManifestError("unsupported shard manifest version")
    shards = manifest.get("shards")
    if not isinstance(shards, list) or not shards:
        raise ManifestError("shard manifest must contain shards")
    shard_ids = [shard.get("id") for shard in shards]
    if shard_ids != list(range(1, len(shards) + 1)):
        raise ManifestError("shard ids must be consecutive and ordered from 1")

    listed = [name for shard in shards for name in shard.get("files", [])]
    counts = Counter(listed)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if duplicates:
        raise ManifestError(f"duplicate files in shard manifest: {duplicates}")

    actual = {path.name for path in e2e_dir.glob("test_*.py")}
    listed_set = set(listed)
    stale = sorted(listed_set - actual)
    if stale:
        raise ManifestError(f"stale files in shard manifest: {stale}")
    missing = sorted(actual - listed_set)
    if missing:
        raise ManifestError(f"missing files from shard manifest: {missing}")
    if any(Path(name).name != name or not name.startswith("test_") for name in listed):
        raise ManifestError("manifest entries must be plain test_*.py file names")

    expected_total = manifest.get("expected_total")
    collected_counts = [shard.get("collected_cases") for shard in shards]
    if expected_total is not None:
        if not all(isinstance(count, int) and count > 0 for count in collected_counts):
            raise ManifestError("every shard needs a positive collected_cases count")
        if sum(collected_counts) != expected_total:
            raise ManifestError("shard collected_cases do not equal expected_total")
    return tuple(listed)


def _selected_shard(manifest: dict, shard_id: int) -> dict:
    validate_manifest(manifest)
    try:
        return next(shard for shard in manifest["shards"] if shard["id"] == shard_id)
    except StopIteration as exc:
        raise ManifestError(f"unknown shard {shard_id}") from exc


def shard_files(manifest: dict, shard_id: int, reverse: bool = False) -> list[str]:
    files = list(_selected_shard(manifest, shard_id)["files"])
    return list(reversed(files)) if reverse else files


def _selection(manifest: dict, args) -> dict:
    if args.all:
        selected = {
            "id": "all",
            "files": list(validate_manifest(manifest)),
            "collected_cases": manifest["expected_total"],
        }
    else:
        selected = _selected_shard(manifest, args.shard)
    run_files = list(selected["files"])
    if args.reverse:
        run_files.reverse()
    return {**selected, "run_files": run_files}


def _junit_totals(path: Path) -> tuple[int, int, int, int]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ResultError(f"cannot read JUnit result {path}: {exc}") from exc
    roots = [root] if "tests" in root.attrib else list(root.findall("testsuite"))
    return tuple(
        sum(int(element.attrib.get(name, "0")) for element in roots)
        for name in ("tests", "failures", "errors", "skipped")
    )


def _child_usage() -> tuple[float, float, int]:
    if resource is None:
        return 0.0, 0.0, 0
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime, usage.ru_stime, usage.ru_maxrss


def _marked_process_inventory(marker: str) -> tuple[list[dict], list[dict]]:
    """Return Linux processes/listeners inheriting this run's unique marker."""
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return [], []
    marker_bytes = f"DOCSIGHT_E2E_RUN_ID={marker}".encode()
    listener_inodes = {}
    for table in (proc_root / "net/tcp", proc_root / "net/tcp6"):
        try:
            lines = table.read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) > 9 and fields[3] == "0A":
                listener_inodes[fields[9]] = int(fields[1].rsplit(":", 1)[1], 16)

    processes = []
    listeners = []
    for environ_path in proc_root.glob("[0-9]*/environ"):
        try:
            environment = environ_path.read_bytes().split(b"\0")
            if marker_bytes not in environment:
                continue
            pid = int(environ_path.parent.name)
            name = (environ_path.parent / "comm").read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            continue
        processes.append({"pid": pid, "name": name})
        try:
            file_descriptors = (environ_path.parent / "fd").iterdir()
        except OSError:
            continue
        for descriptor in file_descriptors:
            try:
                target = descriptor.readlink().as_posix()
            except OSError:
                continue
            if target.startswith("socket:[") and target.endswith("]"):
                inode = target[8:-1]
                if inode in listener_inodes:
                    listeners.append(
                        {"pid": pid, "name": name, "port": listener_inodes[inode]}
                    )
    return sorted(processes, key=lambda item: item["pid"]), sorted(
        listeners, key=lambda item: (item["pid"], item["port"])
    )


def _read_receipt(path: Path) -> dict:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResultError(f"invalid run receipt {path}: {exc}") from exc
    if not isinstance(receipt, dict):
        raise ResultError(f"run receipt {path} must be an object")
    return receipt


def summarize_results(
    results_root: Path,
    manifest: dict,
    *,
    expected_total: int,
    e2e_dir: Path = E2E_DIR,
) -> ResultSummary:
    canonical_files = list(validate_manifest(manifest, e2e_dir))
    metadata_paths = sorted(results_root.rglob("shard-metadata.json"))
    by_shard = {}
    for metadata_path in metadata_paths:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResultError(f"invalid shard metadata {metadata_path}: {exc}") from exc
        shard_id = metadata.get("shard")
        if shard_id in by_shard:
            raise ResultError(f"duplicate shard result for shard {shard_id}")
        by_shard[shard_id] = (metadata_path.parent, metadata)

    if "all" in by_shard:
        expected_shards = [
            {
                "id": "all",
                "files": canonical_files,
                "collected_cases": expected_total,
            }
        ]
    else:
        expected_shards = manifest["shards"]
    required_ids = [shard["id"] for shard in expected_shards]
    missing_ids = sorted(set(required_ids) - set(by_shard), key=str)
    if missing_ids:
        raise ResultError(f"missing shard result artifacts: {missing_ids}")
    unexpected_ids = sorted(set(by_shard) - set(required_ids), key=str)
    if unexpected_ids:
        raise ResultError(f"unexpected shard result artifacts: {unexpected_ids}")

    all_nodes = []
    per_shard = []
    wall_seconds = []
    job_wall_seconds = []
    total_cpu_seconds = 0.0
    peak_rss_kb = 0
    for shard in expected_shards:
        shard_id = shard["id"]
        directory, metadata = by_shard[shard_id]
        if metadata.get("files") != shard["files"]:
            raise ResultError(f"shard {shard_id} file receipt does not match manifest")
        try:
            nodes = [
                line.strip()
                for line in (directory / "collected.txt")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
        except OSError as exc:
            raise ResultError(f"missing collection result for shard {shard_id}") from exc
        allowed_prefixes = tuple(f"tests/e2e/{name}::" for name in shard["files"])
        if any(not node.startswith(allowed_prefixes) for node in nodes):
            raise ResultError(f"shard {shard_id} collected nodes outside its manifest")
        if len(nodes) != shard["collected_cases"]:
            raise ResultError(
                f"shard {shard_id} collected {len(nodes)} nodes; "
                f"expected {shard['collected_cases']}"
            )

        junit = _junit_totals(directory / "junit.xml")
        tests, failures, errors, skipped = junit
        if tests != len(nodes) or failures or errors or skipped:
            raise ResultError(
                f"shard {shard_id} has failed, errored, or skipped tests "
                f"(tests={tests}, failures={failures}, errors={errors}, skipped={skipped})"
            )
        receipt = _read_receipt(directory / "run-receipt.json")
        expected_junit = dict(
            zip(("tests", "failures", "errors", "skipped"), junit, strict=True)
        )
        if receipt.get("selection") != shard_id or receipt.get("junit") != expected_junit:
            raise ResultError(f"shard {shard_id} run receipt does not match JUnit")
        if receipt.get("returncode") != 0:
            raise ResultError(f"shard {shard_id} run receipt reports failure")
        if receipt.get("retry_count") != 0:
            raise ResultError(f"shard {shard_id} used retries")
        if any(
            receipt.get(field)
            for field in (
                "baseline_processes",
                "baseline_listeners",
                "leaked_processes",
                "leaked_listeners",
            )
        ):
            raise ResultError(f"shard {shard_id} reports process or listener leaks")
        for field in ("started_utc", "ended_utc", "platform"):
            if not isinstance(receipt.get(field), str) or not receipt[field]:
                raise ResultError(f"shard {shard_id} run receipt lacks {field}")
        wall = receipt.get("wall_seconds")
        job_wall = receipt.get("job_wall_seconds")
        cpu = receipt.get("cpu_seconds")
        rss = receipt.get("peak_rss_kb")
        if not isinstance(wall, (int, float)) or wall < 0:
            raise ResultError(f"shard {shard_id} has invalid wall time")
        if not isinstance(job_wall, (int, float)) or job_wall < wall:
            raise ResultError(f"shard {shard_id} has invalid job wall time")
        if not isinstance(cpu, (int, float)) or cpu < 0:
            raise ResultError(f"shard {shard_id} has invalid CPU time")
        if not isinstance(rss, int) or rss < 0:
            raise ResultError(f"shard {shard_id} has invalid peak RSS")
        if shard_id != "all" and wall >= 720:
            raise ResultError(f"shard {shard_id} exceeded the 12-minute wall limit")
        if shard_id != "all" and job_wall >= 720:
            raise ResultError(f"shard {shard_id} exceeded the 12-minute job wall limit")

        per_shard.append(len(nodes))
        all_nodes.extend(nodes)
        wall_seconds.append(float(wall))
        job_wall_seconds.append(float(job_wall))
        total_cpu_seconds += float(cpu)
        peak_rss_kb = max(peak_rss_kb, rss)

    duplicates = sorted(node for node, count in Counter(all_nodes).items() if count > 1)
    if duplicates:
        raise ResultError(f"duplicate collected node ids: {duplicates[:5]}")
    if len(all_nodes) != expected_total:
        raise ResultError(
            f"collected union is {len(all_nodes)}; expected exactly {expected_total}"
        )
    baseline_cpu_seconds = manifest.get("baseline_cpu_seconds")
    if required_ids != ["all"]:
        if not isinstance(baseline_cpu_seconds, (int, float)) or baseline_cpu_seconds <= 0:
            raise ResultError("manifest lacks a measured positive baseline_cpu_seconds")
        if total_cpu_seconds > baseline_cpu_seconds * 1.25:
            raise ResultError(
                f"aggregate CPU {total_cpu_seconds:.2f}s exceeds the 25% budget over "
                f"baseline {baseline_cpu_seconds:.2f}s"
            )
    return ResultSummary(
        len(all_nodes),
        tuple(per_shard),
        tuple(wall_seconds),
        tuple(job_wall_seconds),
        total_cpu_seconds,
        peak_rss_kb,
    )


def _write_metadata(output_dir: Path, shard: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "shard-metadata.json").write_text(
        json.dumps(
            {"shard": shard["id"], "files": shard["files"]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _collect(args, manifest: dict) -> int:
    shard = _selection(manifest, args)
    files = shard["run_files"]
    output_dir = Path(args.output_dir)
    _write_metadata(output_dir, shard)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        *(str(E2E_DIR / name) for name in files),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (output_dir / "collection.log").write_text(completed.stdout, encoding="utf-8")
    nodes = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.startswith("tests/e2e/") and "::" in line
    ]
    if completed.returncode == 0:
        (output_dir / "collected.txt").write_text(
            "".join(f"{node}\n" for node in nodes), encoding="utf-8"
        )
        if len(nodes) != shard["collected_cases"]:
            print(
                f"selection {shard['id']} collected {len(nodes)} cases; "
                f"expected {shard['collected_cases']}",
                file=sys.stderr,
            )
            return 1
    else:
        sys.stdout.write(completed.stdout)
    return completed.returncode


def _run(args, manifest: dict) -> int:
    selection = _selection(manifest, args)
    pytest_args = list(args.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args.pop(0)
    command = [
        sys.executable,
        "-m",
        "pytest",
        *(str(E2E_DIR / name) for name in selection["run_files"]),
        *pytest_args,
    ]
    junit_path = ROOT / args.junit if args.junit and not args.junit.is_absolute() else args.junit
    receipt_path = (
        ROOT / args.receipt if args.receipt and not args.receipt.is_absolute() else args.receipt
    )
    if junit_path is not None:
        junit_path.parent.mkdir(parents=True, exist_ok=True)
        command.append(f"--junitxml={junit_path}")
    if args.receipt is None:
        return subprocess.call(command, cwd=ROOT)
    if junit_path is None:
        raise ManifestError("--receipt requires --junit")

    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    marker = f"{os.getpid()}-{selection['id']}-{time.time_ns()}"
    environment = os.environ.copy()
    environment["DOCSIGHT_E2E_RUN_ID"] = marker
    baseline_processes, baseline_listeners = _marked_process_inventory(marker)
    before_user, before_system, _ = _child_usage()
    started_utc = dt.datetime.now(dt.UTC).isoformat()
    started = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    wall_seconds = time.monotonic() - started
    job_started_epoch = os.environ.get("E2E_JOB_STARTED_EPOCH")
    if job_started_epoch is None:
        job_wall_seconds = wall_seconds
    else:
        try:
            job_wall_seconds = time.time() - float(job_started_epoch)
        except ValueError:
            job_wall_seconds = wall_seconds
    ended_utc = dt.datetime.now(dt.UTC).isoformat()
    after_user, after_system, peak_rss_kb = _child_usage()
    leaked_processes = []
    leaked_listeners = []
    for _ in range(50):
        leaked_processes, leaked_listeners = _marked_process_inventory(marker)
        if not leaked_processes and not leaked_listeners:
            break
        time.sleep(0.1)
    try:
        junit = dict(
            zip(
                ("tests", "failures", "errors", "skipped"),
                _junit_totals(junit_path),
                strict=True,
            )
        )
    except ResultError:
        junit = None
    receipt = {
        "selection": selection["id"],
        "started_utc": started_utc,
        "ended_utc": ended_utc,
        "wall_seconds": round(wall_seconds, 3),
        "job_wall_seconds": round(max(job_wall_seconds, wall_seconds), 3),
        "cpu_seconds": round(
            (after_user - before_user) + (after_system - before_system), 3
        ),
        "peak_rss_kb": peak_rss_kb,
        "platform": platform.platform(),
        "retry_count": 0,
        "returncode": completed.returncode,
        "junit": junit,
        "baseline_processes": baseline_processes,
        "baseline_listeners": baseline_listeners,
        "leaked_processes": leaked_processes,
        "leaked_listeners": leaked_listeners,
    }
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if leaked_processes or leaked_listeners:
        print("E2E process/listener leak detected; see run receipt", file=sys.stderr)
        return 1
    if selection["id"] != "all" and wall_seconds >= 720:
        print("E2E shard exceeded the 12-minute wall limit", file=sys.stderr)
        return 1
    if selection["id"] != "all" and job_wall_seconds >= 720:
        print("E2E shard exceeded the 12-minute job wall limit", file=sys.stderr)
        return 1
    return completed.returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")

    def add_selection(parser):
        selection = parser.add_mutually_exclusive_group(required=True)
        selection.add_argument("--shard", type=int)
        selection.add_argument("--all", action="store_true")
        parser.add_argument("--reverse", action="store_true")

    list_parser = subparsers.add_parser("list")
    add_selection(list_parser)

    collect_parser = subparsers.add_parser("collect")
    add_selection(collect_parser)
    collect_parser.add_argument("--output-dir", required=True)

    run_parser = subparsers.add_parser("run")
    add_selection(run_parser)
    run_parser.add_argument("--junit", type=Path)
    run_parser.add_argument("--receipt", type=Path)
    run_parser.add_argument("pytest_args", nargs=argparse.REMAINDER)

    summary_parser = subparsers.add_parser("summarize")
    summary_parser.add_argument("--results-root", type=Path, required=True)
    summary_parser.add_argument("--expected-total", type=int, default=EXPECTED_TOTAL)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        validate_manifest(manifest)
        if args.command == "validate":
            print(
                f"{len(manifest['shards'])} shards cover "
                f"{len(validate_manifest(manifest))} files and "
                f"{manifest['expected_total']} cases"
            )
        elif args.command == "list":
            print("\n".join(_selection(manifest, args)["run_files"]))
        elif args.command == "collect":
            return _collect(args, manifest)
        elif args.command == "run":
            return _run(args, manifest)
        else:
            summary = summarize_results(
                args.results_root,
                manifest,
                expected_total=args.expected_total,
            )
            print(
                f"complete E2E union: {summary.total} cases "
                f"across shards {summary.per_shard}; wall={summary.wall_seconds}; "
                f"job-wall={summary.job_wall_seconds}; "
                f"cpu={summary.cpu_seconds:.2f}s; peak-rss={summary.peak_rss_kb} KiB"
            )
    except (ManifestError, ResultError) as exc:
        print(f"E2E shard validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
