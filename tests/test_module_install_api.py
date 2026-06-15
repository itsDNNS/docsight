"""Tests for community module install/uninstall API endpoints."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.web import app, init_config, init_storage


@pytest.fixture
def storage(tmp_path):
    return SnapshotStorage(str(tmp_path / "test.db"), max_days=7)


@pytest.fixture
def client(tmp_path, storage):
    config_mgr = ConfigManager(str(tmp_path / "config"))
    config_mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
    init_config(config_mgr)
    init_storage(storage)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestModulesRegistry:
    def test_registry_returns_list(self, client):
        with patch("app.blueprints.modules_bp.get_config_manager") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            mock_cfg.return_value.get = MagicMock(return_value="https://raw.githubusercontent.com/itsDNNS/docsight-modules/main/registry.json")
            resp = client.get("/api/modules/registry")
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert isinstance(data, list)


class TestModulesInstall:
    def test_rejects_missing_fields(self, client):
        resp = client.post("/api/modules/install",
                           data=json.dumps({}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_rejects_path_traversal(self, client):
        resp = client.post("/api/modules/install",
                           data=json.dumps({"id": "../../../etc/passwd", "download_url": "https://api.github.com/test"}),
                           content_type="application/json")
        data = json.loads(resp.data)
        assert data["success"] is False

    def test_rejects_duplicate_builtin(self, client):
        with patch("app.blueprints.modules_bp.get_module_loader") as mock_loader:
            mock_mod = MagicMock()
            mock_mod.id = "docsight.speedtest"
            mock_loader.return_value.get_modules.return_value = [mock_mod]
            resp = client.post("/api/modules/install",
                               data=json.dumps({"id": "docsight.speedtest", "download_url": "https://api.github.com/test"}),
                               content_type="application/json")
            data = json.loads(resp.data)
            assert data["success"] is False
            assert "conflicts" in data.get("error", "").lower() or resp.status_code == 409


    def test_rejects_invalid_module_id(self, client):
        """Module ID with uppercase / special chars is rejected with 400."""
        resp = client.post("/api/modules/install",
                           data=json.dumps({"id": "INVALID-ID!", "download_url": "https://example.com"}),
                           content_type="application/json")
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["success"] is False
        assert "invalid" in data["error"].lower()

    def test_rejects_traversal_id_with_400(self, client):
        """Path-traversal ID is rejected with 400 (not just a generic error)."""
        resp = client.post("/api/modules/install",
                           data=json.dumps({"id": "../../etc/passwd", "download_url": "https://example.com"}),
                           content_type="application/json")
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["success"] is False

    def test_downloader_not_called_for_invalid_id(self, client):
        """Downloader must never be invoked when the module ID is invalid."""
        with patch("app.blueprints.modules_bp.download_github_directory") as mock_dl:
            resp = client.post("/api/modules/install",
                               data=json.dumps({"id": "../bad", "download_url": "https://example.com"}),
                               content_type="application/json")
            assert resp.status_code == 400
            mock_dl.assert_not_called()

    def test_successful_install_uses_configured_modules_dir(self, client, tmp_path, monkeypatch):
        """Community installs write below MODULES_DIR and persist disabled-by-default."""
        modules_dir = tmp_path / "modules"
        monkeypatch.setenv("MODULES_DIR", str(modules_dir))

        def fake_download(_url, target_dir):
            os.makedirs(target_dir, exist_ok=True)
            manifest = {
                "id": "community.test",
                "name": "Community Test",
                "description": "Test module",
                "version": "1.0.0",
                "author": "DOCSight",
                "minAppVersion": "2026.1",
                "type": "analysis",
                "contributes": {},
            }
            with open(os.path.join(target_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f)
            return True

        with patch("app.blueprints.modules_bp.download_github_directory", side_effect=fake_download):
            resp = client.post("/api/modules/install",
                               data=json.dumps({"id": "community.test", "download_url": "https://api.github.com/test"}),
                               content_type="application/json")

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True
        assert (modules_dir / "community.test" / "manifest.json").is_file()
        config = json.loads((tmp_path / "config" / "config.json").read_text(encoding="utf-8"))
        assert "community.test" in config["disabled_modules"].split(",")


class TestThemesInstall:
    def test_rejects_invalid_theme_id(self, client):
        """Theme ID with special chars or traversal patterns is rejected with 400."""
        for bad_id in ["../etc/passwd", "UPPER", "has spaces", "semi;colon"]:
            resp = client.post("/api/themes/install",
                               data=json.dumps({"id": bad_id, "download_url": "https://example.com"}),
                               content_type="application/json")
            assert resp.status_code == 400, f"Expected 400 for theme id {bad_id!r}, got {resp.status_code}"
            data = json.loads(resp.data)
            assert data["success"] is False


class TestModulesUninstall:
    def test_rejects_missing_id(self, client):
        resp = client.post("/api/modules/uninstall",
                           data=json.dumps({}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_rejects_not_installed(self, client):
        resp = client.post("/api/modules/uninstall",
                           data=json.dumps({"id": "nonexistent.module"}),
                           content_type="application/json")
        assert resp.status_code == 404

    def test_rejects_builtin_uninstall(self, client):
        with patch("app.blueprints.modules_bp._scan_installed_community_ids") as mock_scan, \
             patch("app.blueprints.modules_bp.get_module_loader") as mock_loader:
            mock_scan.return_value = {"docsight.speedtest": "docsight_speedtest"}
            mock_mod = MagicMock()
            mock_mod.id = "docsight.speedtest"
            mock_mod.builtin = True
            mock_loader.return_value.get_modules.return_value = [mock_mod]
            resp = client.post("/api/modules/uninstall",
                               data=json.dumps({"id": "docsight.speedtest"}),
                               content_type="application/json")
            assert resp.status_code == 403
