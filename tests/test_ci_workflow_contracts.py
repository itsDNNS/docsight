"""Contracts for path-routed CI workflows.

PyYAML follows YAML 1.1 and may parse the unquoted GitHub Actions ``on`` key
as boolean ``True``.  The loader below normalizes that quirk before assertions.
"""

from pathlib import Path
import re

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="CI workflow contracts run where the YAML test dependency is installed",
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

E2E_BROWSER_PATHS = [
    "app/templates/**",
    "app/static/**",
    "app/modules/**",
    "app/web.py",
    "app/blueprints/**",
    "app/tz.py",
    "app/i18n/**",
    "app/app_factory.py",
    "app/base_path.py",
    "app/glossary.py",
    "tests/e2e/**",
    "tests/test_e2e_harness.py",
    "tests/test_e2e_shards.py",
    "scripts/e2e_shards.py",
    "requirements.txt",
    "requirements-test.txt",
    ".github/workflows/full-e2e.yml",
]

DOCKER_PATHS = [
    "app/**",
    "tools/**",
    "requirements.txt",
    "Dockerfile",
    ".dockerignore",
    "entrypoint.sh",
    ".github/workflows/docker.yml",
]

TEST_FILTERS = {
    "docs": [
        "*.md",
        "docs/**",
        "packaging/windows/*.md",
    ],
    "python": [
        "app/**",
        "tests/**",
        "scripts/**",
        "tools/**",
        "packaging/windows/**",
        "!packaging/windows/*.md",
        "requirements.txt",
        "requirements-test.txt",
        "pytest.ini",
        ".github/workflows/*.yml",
    ],
    "windows": [
        "app/**",
        "tests/**",
        "scripts/**",
        "tools/**",
        "packaging/windows/**",
        "!packaging/windows/*.md",
        "requirements.txt",
        "requirements-test.txt",
        "packaging/windows/requirements-runtime-windows.txt",
        "packaging/windows/requirements-test-windows.txt",
        "pytest.ini",
        ".github/workflows/*.yml",
    ],
    "browser": E2E_BROWSER_PATHS + [".github/workflows/test.yml"],
    "js": [
        "package.json",
        "package-lock.json",
        "app/static/js/**",
        "app/static/sw.js",
        "app/static/vendor/**",
        "tests/js/**",
        ".github/workflows/test.yml",
    ],
    "i18n": [
        "app/i18n/**",
        "app/modules/**/i18n/**",
        "scripts/i18n_check.py",
        "tests/test_i18n_check.py",
        ".github/workflows/test.yml",
    ],
    "deps": ["requirements.txt", ".github/workflows/test.yml"],
}


def load_workflow(name):
    workflow = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    if "on" not in workflow and True in workflow:
        workflow["on"] = workflow.pop(True)
    return workflow


def parsed_filters(workflow):
    filter_step = next(
        step for step in workflow["jobs"]["changes"]["steps"]
        if step.get("id") == "filter"
    )
    return yaml.safe_load(filter_step["with"]["filters"]), filter_step


def compact(expression):
    return re.sub(r"\s+", " ", expression).strip()


def e2e_required(event_name, action=None, event_label=None, labels=(), browser=False):
    """Readable model of the exact predicate asserted against the workflow."""
    if event_name in {"schedule", "workflow_dispatch"}:
        return True
    if event_name != "pull_request":
        return False
    if action == "labeled":
        return event_label == "full-e2e"
    return "full-e2e" in labels or browser


def test_full_e2e_paths_concurrency_and_summary_contract():
    workflow = load_workflow("full-e2e.yml")
    filters, filter_step = parsed_filters(workflow)

    assert filters == {"browser": E2E_BROWSER_PATHS}
    assert re.fullmatch(r"dorny/paths-filter@[0-9a-f]{40}", filter_step["uses"])
    assert workflow["concurrency"]["group"] == (
        "full-e2e-${{ github.event.pull_request.number || github.run_id }}"
    )
    cancel_in_progress = compact(workflow["concurrency"]["cancel-in-progress"])
    assert cancel_in_progress == compact("""
        ${{
          github.event_name == 'pull_request' &&
          (
            github.event.action != 'labeled' ||
            github.event.label.name == 'full-e2e'
          )
        }}
    """)
    assert workflow["jobs"]["full-e2e"]["name"] == "full-e2e"
    assert workflow["jobs"]["full-e2e"]["permissions"] == {
        "contents": "read",
        "checks": "read",
    }

    required = compact(workflow["jobs"]["full-e2e"]["env"]["E2E_REQUIRED"])
    expected = compact("""
        ${{
          github.event_name == 'schedule' ||
          github.event_name == 'workflow_dispatch' ||
          (
            github.event_name == 'pull_request' &&
            (
              (github.event.action == 'labeled' && github.event.label.name == 'full-e2e') ||
              (
                github.event.action != 'labeled' &&
                (
                  contains(github.event.pull_request.labels.*.name, 'full-e2e') ||
                  needs.changes.outputs.browser == 'true'
                )
              )
            )
          )
        }}
    """)
    assert required == expected

    shard_if = compact(workflow["jobs"]["e2e-shards"]["if"])
    required_body = required.removeprefix("${{ ").removesuffix(" }}")
    assert "always() && !cancelled()" in shard_if
    assert "needs.changes.result == 'success'" in shard_if
    assert required_body in shard_if
    summarize = next(
        step for step in workflow["jobs"]["full-e2e"]["steps"]
        if step["name"].startswith("Verify complete successful")
    )["run"]
    assert "--expected-total 549" in summarize

    preserve = next(
        step for step in workflow["jobs"]["full-e2e"]["steps"]
        if step["name"] == "Preserve prior browser gate on unrelated labels"
    )
    preserve_if = compact(preserve["if"])
    assert "github.event.action == 'labeled'" in preserve_if
    assert "github.event.label.name != 'full-e2e'" in preserve_if
    assert re.fullmatch(r"actions/github-script@[0-9a-f]{40}", preserve["uses"])
    preserve_script = preserve["with"]["script"]
    for contract in (
        "check_name: 'full-e2e'",
        "filter: 'all'",
        "run.status === 'completed'",
        "run.app?.slug === 'github-actions'",
        "if (!previous)",
        "previous.conclusion !== 'success'",
        "core.setFailed",
    ):
        assert contract in preserve_script


@pytest.mark.parametrize(
    ("event_name", "action", "event_label", "labels", "browser", "expected"),
    [
        ("pull_request", "labeled", "documentation", (), True, False),
        ("pull_request", "labeled", "documentation", ("full-e2e",), False, False),
        ("pull_request", "labeled", "full-e2e", (), False, True),
        ("pull_request", "synchronize", None, (), True, True),
        ("pull_request", "synchronize", None, ("full-e2e",), False, True),
        ("pull_request", "synchronize", None, (), False, False),
        ("pull_request", "opened", None, ("full-e2e",), False, True),
        ("pull_request", "reopened", None, (), True, True),
        ("schedule", None, None, (), False, True),
        ("workflow_dispatch", None, None, (), False, True),
    ],
)
def test_full_e2e_requirement_truth_table(
    event_name, action, event_label, labels, browser, expected
):
    assert e2e_required(event_name, action, event_label, labels, browser) is expected


def test_docker_paths_tags_manual_and_concurrency_contract():
    workflow = load_workflow("docker.yml")
    triggers = workflow["on"]

    assert triggers["push"] == {
        "branches": ["main"],
        "tags": ["v*"],
        "paths": DOCKER_PATHS,
    }
    assert triggers["workflow_dispatch"] is None
    assert workflow["concurrency"] == {
        "group": "docker-${{ github.ref }}",
        "cancel-in-progress": "${{ github.ref == 'refs/heads/main' }}",
    }
    metadata_tags = next(
        step["with"]["tags"]
        for step in workflow["jobs"]["build-and-push"]["steps"]
        if step.get("id") == "meta"
    )
    assert "type=ref,event=tag" in metadata_tags
    assert "type=sha,enable=${{ github.event_name == 'workflow_dispatch'" in metadata_tags


def test_test_workflow_detector_schedule_and_exact_path_contracts():
    workflow = load_workflow("test.yml")
    triggers = workflow["on"]
    filters, filter_step = parsed_filters(workflow)

    assert triggers["schedule"] == [{"cron": "23 4 * * 1"}]
    assert "paths-ignore" not in triggers["push"]
    assert "paths-ignore" not in triggers["pull_request"]
    assert workflow["jobs"]["changes"]["if"] == "github.event_name != 'schedule'"
    assert workflow["jobs"]["changes"]["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }
    assert set(workflow["jobs"]["changes"]["outputs"]) == set(TEST_FILTERS)
    assert filters == TEST_FILTERS
    assert re.fullmatch(r"dorny/paths-filter@[0-9a-f]{40}", filter_step["uses"])
    assert filter_step["with"]["predicate-quantifier"] == "some-with-excludes"

    docs_run = next(
        step["run"] for step in workflow["jobs"]["docs"]["steps"]
        if step["name"] == "Run documentation contract tests"
    )
    for test_file in (
        "tests/test_public_launch_surface.py",
        "tests/test_defensive_review_docs.py",
        "tests/test_windows_packaging.py",
    ):
        assert test_file in docs_run


def test_test_workflow_jobs_are_routed_through_the_detector():
    jobs = load_workflow("test.yml")["jobs"]
    routes = {
        "docs": "docs",
        "test": "python",
        "test-windows": "windows",
        "mobile-e2e": "browser",
        "test-js": "js",
        "i18n": "i18n",
    }

    for job_name, output in routes.items():
        condition = compact(jobs[job_name]["if"])
        assert jobs[job_name]["needs"] == "changes"
        assert condition.startswith("always() && !cancelled() &&")
        assert "needs.changes.result == 'success'" in condition
        assert f"needs.changes.outputs.{output} == 'true'" in condition

    audit_if = compact(jobs["audit"]["if"])
    assert jobs["audit"]["needs"] == "changes"
    assert audit_if.startswith("always() && !cancelled() &&")
    assert "github.event_name == 'schedule'" in audit_if
    assert "needs.changes.result == 'success'" in audit_if
    assert "needs.changes.outputs.deps == 'true'" in audit_if


def test_tests_summary_is_always_present_and_fails_closed():
    summary = load_workflow("test.yml")["jobs"]["tests-summary"]
    assert summary["name"] == "tests-summary"
    assert set(summary["needs"]) == {
        "changes",
        "docs",
        "test",
        "test-windows",
        "mobile-e2e",
        "test-js",
        "i18n",
        "audit",
    }
    assert summary["if"] == "always()"

    step = summary["steps"][0]
    script = step["run"]
    assert set(step["env"]) == {
        "EVENT_NAME",
        "CHANGES_RESULT",
        "DOCS_CHANGED",
        "PYTHON_CHANGED",
        "WINDOWS_CHANGED",
        "BROWSER_CHANGED",
        "JS_CHANGED",
        "I18N_CHANGED",
        "DEPS_CHANGED",
        "DOCS_RESULT",
        "PYTHON_RESULT",
        "WINDOWS_RESULT",
        "BROWSER_RESULT",
        "JS_RESULT",
        "I18N_RESULT",
        "DEPS_RESULT",
    }
    assert 'result in {"failure", "cancelled"}' in script
    assert 'event_name == "schedule"' in script
    assert 'routes["deps"][1] != "success"' in script
    assert 'changes_result != "success"' in script
    assert 'changed not in {"true", "false"}' in script
    assert 'changed == "true" and result != "success"' in script


@pytest.mark.parametrize("name", ["full-e2e.yml", "docker.yml", "test.yml"])
def test_changed_workflows_keep_every_action_sha_pinned(name):
    workflow = load_workflow(name)
    uses = [
        step["uses"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "uses" in step
    ]
    assert uses
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", action) for action in uses)
