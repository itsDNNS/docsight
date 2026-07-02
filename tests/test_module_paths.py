"""Contracts for community module storage paths."""

from pathlib import Path

from app.module_paths import DEFAULT_MODULES_DIR, get_modules_dir

ROOT = Path(__file__).resolve().parents[1]


def test_default_modules_dir_is_persisted_data_volume(monkeypatch):
    monkeypatch.delenv("MODULES_DIR", raising=False)

    assert DEFAULT_MODULES_DIR == "/data/modules"
    assert get_modules_dir() == "/data/modules"


def test_modules_dir_allows_explicit_override(monkeypatch):
    monkeypatch.setenv("MODULES_DIR", "/custom/modules")

    assert get_modules_dir() == "/custom/modules"


def test_runtime_and_install_api_share_module_dir_helper():
    main_py = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    modules_bp_py = (ROOT / "app" / "blueprints" / "modules_bp.py").read_text(encoding="utf-8")

    assert "from .module_paths import get_modules_dir" in main_py
    assert "from app.module_paths import get_modules_dir" in modules_bp_py
    assert "os.environ.get(\"MODULES_DIR\", \"/modules\")" not in main_py
    assert "os.environ.get(\"MODULES_DIR\", \"/modules\")" not in modules_bp_py


def test_container_prepares_community_module_storage():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")

    assert "mkdir -p /data/modules /modules" in dockerfile
    assert "chown -R appuser:appuser /data /modules" in dockerfile
    assert "mkdir -p /data/modules" in entrypoint
    assert "chown appuser:appuser /data/modules" in entrypoint
    assert "repair_owner_if_needed /data" in entrypoint
    assert "stat -c '%u:%g'" in entrypoint
    assert 'chown -R appuser:appuser "$target"' in entrypoint


def test_docker_healthcheck_uses_configured_web_port():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "os.environ.get('WEB_PORT', '8765')" in dockerfile
    assert "http://localhost:{port}/health" in dockerfile
    assert "localhost:8765/health" not in dockerfile
