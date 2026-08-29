"""Static ownership guard for production SQLite policy and schema code."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
SQLITE_OWNER = Path("app/storage/sqlite.py")
MIGRATION_OWNER = Path("app/storage/migrations.py")
DDL_OWNERS = {
    Path("app/storage/schema.py"),
    MIGRATION_OWNER,
    *(Path(f"app/modules/{name}/migrations.py") for name in (
        "weather", "journal", "speedtest", "bqm", "bnetz", "connection_monitor",
        "de_tkg_compensation",
    )),
}
DDL_PATTERN = re.compile(
    r"(?:^|;)\s*(?:CREATE\s+TABLE|ALTER\s+TABLE|CREATE\s+(?:UNIQUE\s+)?INDEX|DROP\s+TABLE)\b",
    re.I | re.M,
)
POLICY_PATTERN = re.compile(
    r"\bPRAGMA\s+(?:busy_timeout|foreign_keys|query_only)\b|"
    r"\bPRAGMA\s+journal_mode\s*=|\bVACUUM\s+INTO\b",
    re.I,
)


def _production_trees():
    for path in APP.rglob("*.py"):
        relative = path.relative_to(ROOT)
        yield relative, ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))


def _static_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("{}")
        return "".join(parts)
    return None


def _call_owners(tree):
    sqlite_aliases = {"sqlite3"}
    direct_connects = set()
    shared_connects = {"connect_sqlite"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlite3":
                    sqlite_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
            for alias in node.names:
                if alias.name == "connect":
                    direct_connects.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module in {
            "app.storage.sqlite", "storage.sqlite", "sqlite"
        }:
            for alias in node.names:
                if alias.name == "connect_sqlite":
                    shared_connects.add(alias.asname or alias.name)

    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in sqlite_aliases
            and func.attr == "connect"
        ) or (isinstance(func, ast.Name) and func.id in direct_connects):
            findings.append(("sqlite3.connect", node.lineno))
        elif isinstance(func, ast.Name) and func.id in shared_connects:
            findings.append(("connect_sqlite", node.lineno))
        elif isinstance(func, ast.Attribute) and func.attr in {"commit", "rollback", "executemany"}:
            findings.append((func.attr, node.lineno))
    return findings


def test_connection_transaction_and_bulk_ownership():
    violations = []
    required = {"sqlite3.connect", "commit", "rollback", "executemany"}
    observed = set()
    for relative, tree in _production_trees():
        for marker, line in _call_owners(tree):
            if relative == SQLITE_OWNER:
                observed.add(marker)
            else:
                violations.append(f"{relative}:{line}: {marker}")
    assert observed >= required
    assert violations == []


def test_policy_pragma_and_vacuum_ownership_ignores_comments_and_non_sql_strings():
    violations = []
    owner_markers = []
    for relative, tree in _production_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "execute" or not node.args:
                continue
            sql_node = node.args[0]
            if isinstance(sql_node, ast.Constant) and isinstance(sql_node.value, str):
                sql = sql_node.value
            elif isinstance(sql_node, ast.JoinedStr):
                sql = "".join(
                    value.value
                    for value in sql_node.values
                    if isinstance(value, ast.Constant) and isinstance(value.value, str)
                )
            else:
                continue
            if not POLICY_PATTERN.search(sql):
                continue
            if relative == SQLITE_OWNER:
                owner_markers.append(sql)
            else:
                violations.append(f"{relative}:{node.lineno}")
    assert owner_markers
    assert violations == []


def test_ddl_ownership_uses_exact_allowlist():
    missing = sorted(str(path) for path in DDL_OWNERS if not (ROOT / path).is_file())
    assert missing == []

    violations = []
    observed = set()
    for relative, tree in _production_trees():
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(parents.get(node), ast.JoinedStr):
                continue
            sql = _static_string(node)
            if sql is not None and DDL_PATTERN.search(sql):
                if relative in DDL_OWNERS:
                    observed.add(relative)
                else:
                    violations.append(f"{relative}:{getattr(node, 'lineno', '?')}")
    assert observed == DDL_OWNERS
    assert violations == []
