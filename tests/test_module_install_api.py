"""Tests for community module install/uninstall API endpoints."""

import json
import ntpath
import os
import posixpath
import shutil
from io import BytesIO
from types import SimpleNamespace
import pytest
from unittest.mock import patch, MagicMock

from app.blueprints.modules_bp import _remove_downloaded_module
from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.runtime import current_runtime
from app.theme_registry import download_theme


@pytest.fixture
def storage(tmp_path):
    return SnapshotStorage(str(tmp_path / "test.db"), max_days=7)


@pytest.fixture
def client(tmp_path, storage):
    config_mgr = ConfigManager(str(tmp_path / "config"))
    config_mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
    current_runtime().config_manager = config_mgr
    current_runtime().storage = storage
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_download_cleanup_is_confined_to_module_root(tmp_path):
    modules_dir = tmp_path / "modules"
    inside = modules_dir / "community.failed"
    outside = tmp_path / "outside"
    inside.mkdir(parents=True)
    outside.mkdir()

    _remove_downloaded_module(str(modules_dir), str(outside))
    _remove_downloaded_module(str(modules_dir), str(modules_dir))

    assert outside.is_dir()
    assert modules_dir.is_dir()
    assert inside.is_dir()

    _remove_downloaded_module(str(modules_dir), str(inside))

    assert not inside.exists()
    assert outside.is_dir()
    assert modules_dir.is_dir()


class TestModulesRegistry:
    def test_registry_returns_list(self, client):
        with patch("app.blueprints.modules_bp.current_runtime") as mock_cfg:
            mock_cfg.return_value.config_manager = MagicMock()
            mock_cfg.return_value.config_manager.get = MagicMock(return_value="https://raw.githubusercontent.com/itsDNNS/docsight-modules/main/registry.json")
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
        with patch("app.blueprints.modules_bp.current_runtime") as mock_loader:
            mock_mod = MagicMock()
            mock_mod.id = "docsight.speedtest"
            mock_loader.return_value.module_loader.get_modules.return_value = [mock_mod]
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

    def test_invalid_manifest_returns_422_and_removes_download(self, client, tmp_path, monkeypatch):
        """Downloaded manifests are client errors and never leave partial installs."""
        modules_dir = tmp_path / "modules"
        monkeypatch.setenv("MODULES_DIR", str(modules_dir))

        def fake_download(_url, target_dir):
            os.makedirs(target_dir, exist_ok=True)
            manifest = {
                "id": "community.invalid",
                "name": "Invalid",
                "description": "Invalid secret declaration",
                "version": "1.0.0",
                "author": "DOCSight",
                "minAppVersion": "2026.2",
                "type": "integration",
                "contributes": {},
                "config": {"token": ""},
                "config_secrets": ["missing"],
            }
            with open(os.path.join(target_dir, "manifest.json"), "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)
            return True

        with patch("app.blueprints.modules_bp.download_github_directory", side_effect=fake_download):
            response = client.post(
                "/api/modules/install",
                data=json.dumps(
                    {
                        "id": "community.invalid",
                        "download_url": "https://api.github.com/test",
                    }
                ),
                content_type="application/json",
            )

        assert response.status_code == 422
        assert json.loads(response.data) == {
            "success": False,
            "error": "Invalid module manifest",
        }
        assert not (modules_dir / "community.invalid").exists()

    def test_secret_claim_collision_is_rejected_during_install(
        self, client, tmp_path, monkeypatch
    ):
        """An installed module's plain config cannot be taken over as a secret."""
        modules_dir = tmp_path / "modules"
        victim_dir = modules_dir / "victim"
        victim_dir.mkdir(parents=True)
        shared_key = "shared_module_setting"
        victim_manifest = {
            "id": "community.victim",
            "name": "Victim",
            "description": "Existing module",
            "version": "1.0.0",
            "author": "DOCSight",
            "minAppVersion": "2026.2",
            "type": "integration",
            "contributes": {},
            "config": {shared_key: "victim-default"},
        }
        (victim_dir / "manifest.json").write_text(
            json.dumps(victim_manifest), encoding="utf-8"
        )
        monkeypatch.setenv("MODULES_DIR", str(modules_dir))

        def fake_download(_url, target_dir):
            os.makedirs(target_dir, exist_ok=True)
            claimant_manifest = {
                "id": "community.claimant",
                "name": "Claimant",
                "description": "Conflicting module",
                "version": "1.0.0",
                "author": "DOCSight",
                "minAppVersion": "2026.2",
                "type": "integration",
                "contributes": {},
                "config": {shared_key: ""},
                "config_secrets": [shared_key],
            }
            with open(
                os.path.join(target_dir, "manifest.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(claimant_manifest, handle)
            return True

        with patch(
            "app.blueprints.modules_bp.download_github_directory",
            side_effect=fake_download,
        ):
            response = client.post(
                "/api/modules/install",
                data=json.dumps(
                    {
                        "id": "community.claimant",
                        "download_url": "https://api.github.com/test",
                    }
                ),
                content_type="application/json",
            )

        assert response.status_code == 422
        assert json.loads(response.data) == {
            "success": False,
            "error": "Invalid module manifest",
        }
        assert victim_dir.exists()
        assert not (modules_dir / "community.claimant").exists()


class TestThemesInstall:
    download_url = "https://api.github.com/repos/example/themes/contents/theme"

    @pytest.mark.parametrize("path_module,base,expected", [
        (posixpath, "/", "/root_alias"),
        (posixpath, "//", "//root_alias"),
        (posixpath, "/Modules/../Themes/", "/Themes/root_alias"),
        (ntpath, "C:\\", "c:\\root_alias"),
        (ntpath, "C:/Modules/../Themes/", "c:\\themes\\root_alias"),
        (ntpath, "//SERVER/Share/", "\\\\server\\share\\root_alias"),
        (ntpath, "//SERVER/Share/Modules/../Themes/", "\\\\server\\share\\themes\\root_alias"),
    ])
    def test_occupied_check_uses_absolute_unresolved_path(self, client, monkeypatch, path_module, base, expected):
        from app.blueprints import modules_bp

        occupied = MagicMock(return_value=True)
        path_ops = SimpleNamespace(
            join=path_module.join, abspath=path_module.abspath,
            normcase=path_module.normcase, lexists=occupied,
        )
        # Keep foreign path operations local; resolving the entry is not allowed.
        monkeypatch.setattr(modules_bp, "os", SimpleNamespace(path=path_ops, sep=path_module.sep))
        monkeypatch.setattr(modules_bp, "get_modules_dir", lambda: base)
        with patch.object(modules_bp, "safe_child_path") as resolve, \
             patch.object(modules_bp, "download_theme") as download:
            response = client.post("/api/themes/install", json={
                "id": "root.alias", "download_url": self.download_url,
            })
        assert response.status_code == 409
        assert response.get_json() == {"success": False, "error": "Theme already installed"}
        occupied.assert_called_once_with(expected)
        resolve.assert_not_called()
        download.assert_not_called()

    @pytest.fixture
    def modules_dir(self, tmp_path, monkeypatch):
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        monkeypatch.setenv("MODULES_DIR", str(modules_dir))
        return modules_dir

    @pytest.mark.parametrize("download_result", ["empty", "failed"])
    @pytest.mark.parametrize("target_kind", [
        "directory", "file", "symlink", "dangling_symlink", "root_alias",
        "outside_symlink", "sibling_symlink",
    ])
    def test_existing_target_is_untouched(self, client, modules_dir, tmp_path, target_kind, download_result):
        target = modules_dir / "root_alias"
        sentinel = modules_dir / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        link_target = None
        if target_kind == "directory":
            target.mkdir()
            (target / "keep.txt").write_text("keep", encoding="utf-8")
        elif target_kind == "file":
            target.write_text("keep", encoding="utf-8")
        else:
            link_target = {
                "symlink": modules_dir / "existing",
                "dangling_symlink": modules_dir / "missing",
                "root_alias": modules_dir,
                "outside_symlink": tmp_path / "outside",
                "sibling_symlink": tmp_path / "modules_sibling",
            }[target_kind]
            if target_kind != "dangling_symlink":
                link_target.mkdir(exist_ok=True)
                (link_target / "keep.txt").write_text("keep", encoding="utf-8")
            target.symlink_to(link_target, target_is_directory=True)
            original_link = os.readlink(target)

        with patch("app.module_download.urllib.request.urlopen") as transport, \
             patch("app.blueprints.modules_bp.download_theme", wraps=download_theme) as download, \
             patch("shutil.rmtree") as remove:
            transport.return_value = BytesIO(b"[]")
            if download_result == "failed":
                transport.side_effect = OSError("download interrupted")
            response = client.post("/api/themes/install", json={
                "id": "root.alias", "download_url": self.download_url,
            })

            assert response.status_code == 409, (response.get_json(), remove.call_args_list)
            assert response.get_json() == {"success": False, "error": "Theme already installed"}
            download.assert_not_called()
            transport.assert_not_called()
            remove.assert_not_called()

        assert sentinel.read_text(encoding="utf-8") == "keep"
        if link_target is not None:
            assert target.is_symlink()
            assert os.readlink(target) == original_link
            assert target.resolve() == link_target.resolve()
            if target_kind == "dangling_symlink":
                assert not link_target.exists()
            else:
                assert (link_target / "keep.txt").read_text(encoding="utf-8") == "keep"
        elif target_kind == "directory":
            assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"
        else:
            assert target.read_text(encoding="utf-8") == "keep"

    @pytest.mark.parametrize("download_result", ["empty", "failed"])
    def test_failed_fresh_install_cleans_only_new_target(self, client, modules_dir, download_result):
        sentinel = modules_dir / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with patch("app.module_download.urllib.request.urlopen") as transport, \
             patch("shutil.rmtree", wraps=shutil.rmtree) as remove:
            transport.return_value = BytesIO(b"[]")
            if download_result == "failed":
                transport.side_effect = OSError("download interrupted")
            response = client.post("/api/themes/install", json={
                "id": "fresh.theme", "download_url": self.download_url,
            })

            assert response.status_code == 500
            assert response.get_json() == {"success": False, "error": "Download failed"}
            transport.assert_called_once_with(self.download_url, timeout=30)
            remove.assert_called_once_with(str(modules_dir.resolve() / "fresh_theme"), ignore_errors=True)
        assert not (modules_dir / "fresh_theme").exists()
        assert sentinel.read_text(encoding="utf-8") == "keep"

    def test_fresh_install_downloads_theme(self, client, modules_dir):
        files = {
            "manifest.json": {"id": "fresh.theme", "name": "Fresh", "description": "Test theme",
                              "version": "1.0.0", "author": "DOCSight", "minAppVersion": "2026.2",
                              "type": "theme", "contributes": {"theme": "theme.json"}},
            "theme.json": {"dark": {"--bg": "#111"}, "light": {"--bg": "#fff"}},
        }
        listing = [
            {"type": "file", "name": name,
             "download_url": f"https://raw.githubusercontent.com/example/themes/main/{name}"}
            for name in files
        ]
        responses = [BytesIO(json.dumps(data).encode()) for data in [listing, *files.values()]]
        with patch("app.module_download.urllib.request.urlopen", side_effect=responses) as transport, \
             patch("shutil.rmtree") as remove:
            response = client.post("/api/themes/install", json={
                "id": "fresh.theme", "download_url": self.download_url,
            })
            assert response.status_code == 200
            assert response.get_json() == {"success": True, "restart_required": True}
            assert transport.call_count == 3
            remove.assert_not_called()
        for name, data in files.items():
            assert json.loads((modules_dir / "fresh_theme" / name).read_text(encoding="utf-8")) == data

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
             patch("app.blueprints.modules_bp.current_runtime") as mock_loader:
            mock_scan.return_value = {"docsight.speedtest": "docsight_speedtest"}
            mock_mod = MagicMock()
            mock_mod.id = "docsight.speedtest"
            mock_mod.builtin = True
            mock_loader.return_value.module_loader.get_modules.return_value = [mock_mod]
            resp = client.post("/api/modules/uninstall",
                               data=json.dumps({"id": "docsight.speedtest"}),
                               content_type="application/json")
            assert resp.status_code == 403
