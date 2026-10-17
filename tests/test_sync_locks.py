"""Contracts for regenerating the uv dependency locks from their headers."""

from __future__ import annotations

import pytest

from scripts import sync_locks
from scripts.sync_locks import LOCKS, lock_command, unlisted_locks


def test_every_uv_lock_in_the_repo_is_regenerated():
    assert unlisted_locks() == []


@pytest.mark.parametrize("lock", LOCKS)
def test_each_lock_header_compiles_into_that_lock(lock):
    command = lock_command(lock)
    assert command[:3] == ["uv", "pip", "compile"]
    assert command[-2:] == ["-o", lock]
    assert "--generate-hashes" in command


def test_locks_compile_after_the_files_they_read():
    order = {lock: index for index, lock in enumerate(LOCKS)}
    for lock in LOCKS:
        command = lock_command(lock)
        sources = command[3:-2]
        for source in sources:
            if source in order:
                assert order[source] < order[lock], f"{lock} reads {source} before it is compiled"
    assert order["requirements.txt"] < order["packaging/windows/requirements-runtime-windows.txt"]


def test_a_header_that_writes_elsewhere_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text(
        f"{sync_locks.HEADER}\n#    uv pip compile requirements.in -o other.txt\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sync_locks, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="header is not"):
        lock_command("requirements.txt")
