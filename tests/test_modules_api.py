"""Tests for module management API endpoints."""

import os

import pytest

from app.module_loader import ModuleLoader
from app.app_factory import create_app
from app.config import ConfigManager

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _create_module_app(config_manager, search_paths, *, disabled_ids=None):
    loader_box = []

    def build(application):
        loader = ModuleLoader(
            application,
            search_paths=search_paths,
            disabled_ids=disabled_ids,
        )
        loader.load_all()
        loader_box.append(loader)
        return loader

    application = create_app(
        config_manager=config_manager,
        module_loader_factory=build,
        environ={},
        testing=True,
    )
    return application, loader_box[0]


@pytest.fixture
def app_with_modules(tmp_path):
    """Create a Flask app with modules loaded."""
    app, loader = _create_module_app(
        ConfigManager(str(tmp_path / "modules-app")),
        [FIXTURE_DIR],
    )
    yield app, loader



class TestGetModules:
    """GET /api/modules returns all discovered modules."""

    def test_returns_all_modules(self, app_with_modules):
        app, loader = app_with_modules
        with app.test_client() as c:
            resp = c.get("/api/modules")
            assert resp.status_code == 200
            data = resp.get_json()
            assert isinstance(data, list)
            assert len(data) == 2
            ids = {m["id"] for m in data}
            assert "test.integration" in ids
            assert "test.ui" in ids

    def test_module_fields(self, app_with_modules):
        app, _ = app_with_modules
        with app.test_client() as c:
            resp = c.get("/api/modules")
            data = resp.get_json()
            mod = next(m for m in data if m["id"] == "test.integration")
            for field in ("name", "version", "type", "author", "enabled", "builtin", "error", "description"):
                assert field in mod

    def test_disabled_module_shown(self, tmp_path):
        """Disabled modules appear in the list with enabled=False."""
        config = ConfigManager(str(tmp_path / "config"))
        app, _ = _create_module_app(
            config,
            [FIXTURE_DIR],
            disabled_ids={"test.integration"},
        )
        with app.test_client() as c:
            resp = c.get("/api/modules")
            data = resp.get_json()
            mod = next(m for m in data if m["id"] == "test.integration")
            assert mod["enabled"] is False


class TestEnableDisable:
    """POST /api/modules/<id>/enable and /disable."""

    @pytest.fixture(autouse=True)
    def setup_app(self, tmp_path):
        self.config_mgr = ConfigManager(str(tmp_path))
        self.config_mgr.save({"disabled_modules": ""})
        self.app, self.loader = _create_module_app(
            self.config_mgr,
            [FIXTURE_DIR],
        )

        yield

    def test_disable_module(self):
        with self.app.test_client() as c:
            resp = c.post("/api/modules/test.integration/disable")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True
            assert data["restart_required"] is True

        disabled = self.config_mgr.get("disabled_modules", "")
        assert "test.integration" in disabled

    def test_enable_module(self):
        self.config_mgr.save({"disabled_modules": "test.integration"})

        with self.app.test_client() as c:
            resp = c.post("/api/modules/test.integration/enable")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True

        disabled = self.config_mgr.get("disabled_modules", "")
        assert "test.integration" not in disabled

    def test_disable_unknown_module(self):
        with self.app.test_client() as c:
            resp = c.post("/api/modules/nonexistent.module/disable")
            assert resp.status_code == 404

    def test_disable_already_disabled(self):
        self.config_mgr.save({"disabled_modules": "test.integration"})
        with self.app.test_client() as c:
            resp = c.post("/api/modules/test.integration/disable")
            assert resp.status_code == 200

    def test_enable_already_enabled(self):
        with self.app.test_client() as c:
            resp = c.post("/api/modules/test.integration/enable")
            assert resp.status_code == 200


class TestBatchModuleSettings:
    """POST /api/modules/batch applies module settings in one save."""

    @pytest.fixture(autouse=True)
    def setup_app(self, tmp_path):
        import json
        from app.config import ConfigManager

        threshold_data = {
            "downstream_power": {"_default": "256QAM", "256QAM": {"good": [-4, 13], "warning": [-6, 18], "critical": [-8, 20]}},
            "upstream_power": {"_default": "sc_qam", "sc_qam": {"good": [41, 47], "warning": [37, 51], "critical": [35, 53]}},
            "snr": {"_default": "256QAM", "256QAM": {"good_min": 33, "warning_min": 31, "critical_min": 30}},
        }
        for dirname, module_id, contributes in [
            ("regular", "test.integration", {}),
            ("vfkd", "test.thresholds_vfkd", {"thresholds": "thresholds.json"}),
            ("forum", "test.thresholds_forum", {"thresholds": "thresholds.json"}),
        ]:
            mod_dir = tmp_path / dirname
            mod_dir.mkdir()
            (mod_dir / "manifest.json").write_text(json.dumps({
                "id": module_id,
                "name": module_id,
                "description": "d",
                "version": "1.0.0",
                "author": "a",
                "minAppVersion": "2026.2",
                "type": "analysis" if contributes else "integration",
                "contributes": contributes,
            }))
            if contributes:
                (mod_dir / "thresholds.json").write_text(json.dumps(threshold_data))

        self.config_mgr = ConfigManager(str(tmp_path / "config"))
        self.config_mgr.save({"disabled_modules": "test.thresholds_forum"})
        from app import analyzer
        self._orig_thresholds = analyzer._thresholds.copy()
        self.app, self.loader = _create_module_app(
            self.config_mgr,
            [str(tmp_path)],
        )

        yield

        analyzer._thresholds = self._orig_thresholds

    def test_batch_applies_multiple_modules_and_threshold_exclusivity(self):
        with self.app.test_client() as c:
            resp = c.post("/api/modules/batch", json={"modules": [
                {"id": "test.integration", "enabled": False},
                {"id": "test.thresholds_vfkd", "enabled": False},
                {"id": "test.thresholds_forum", "enabled": True},
            ]})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["restart_required"] is True
        disabled = set(self.config_mgr.get("disabled_modules", "").split(","))
        assert "test.integration" in disabled
        assert "test.thresholds_vfkd" in disabled
        assert "test.thresholds_forum" not in disabled

    def test_batch_rejects_no_active_threshold_profile(self):
        with self.app.test_client() as c:
            resp = c.post("/api/modules/batch", json={"modules": [
                {"id": "test.thresholds_vfkd", "enabled": False},
                {"id": "test.thresholds_forum", "enabled": False},
            ]})

        assert resp.status_code == 409
        assert resp.get_json()["success"] is False

    def test_batch_rejects_multiple_active_threshold_profiles(self):
        with self.app.test_client() as c:
            resp = c.post("/api/modules/batch", json={"modules": [
                {"id": "test.thresholds_vfkd", "enabled": True},
                {"id": "test.thresholds_forum", "enabled": True},
            ]})

        assert resp.status_code == 409
        assert resp.get_json()["success"] is False


class TestThemeMutualExclusion:
    """Enabling a theme auto-disables others; cannot disable last theme."""

    @pytest.fixture
    def app_with_themes(self, tmp_path):
        """Create app with two theme modules."""
        import json
        for name, tid in [("theme1", "test.theme1"), ("theme2", "test.theme2")]:
            d = tmp_path / name
            d.mkdir()
            (d / "manifest.json").write_text(json.dumps({
                "id": tid, "name": name, "description": "d",
                "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
                "type": "theme",
                "contributes": {"theme": "theme.json"},
            }))
            (d / "theme.json").write_text(json.dumps({
                "dark": {"--bg": "#111", "--text": "#fff"},
                "light": {"--bg": "#fff", "--text": "#111"},
            }))

        config = ConfigManager(str(tmp_path / "config"))
        config.save({"disabled_modules": ""})
        app, loader = _create_module_app(config, [str(tmp_path)])

        yield app, loader, config

    def test_enable_theme_disables_other(self, app_with_themes):
        app, loader, config = app_with_themes
        with app.test_client() as c:
            resp = c.post("/api/modules/test.theme2/enable")
            assert resp.status_code == 200
            disabled = config.get("disabled_modules", "")
            assert "test.theme1" in disabled

    def test_disable_last_theme_blocked(self, app_with_themes):
        app, loader, config = app_with_themes
        config.save({"disabled_modules": "test.theme1"})
        with app.test_client() as c:
            resp = c.post("/api/modules/test.theme2/disable")
            assert resp.status_code == 409
            data = resp.get_json()
            assert data["success"] is False

    def test_serialize_includes_is_theme(self, app_with_themes):
        app, loader, config = app_with_themes
        with app.test_client() as c:
            resp = c.get("/api/modules")
            data = resp.get_json()
            theme = next(m for m in data if m["id"] == "test.theme1")
            assert theme["is_theme"] is True


class TestThemesAPI:
    """Test /api/themes endpoint."""

    @pytest.fixture
    def app_with_theme(self, tmp_path):
        import json
        d = tmp_path / "theme1"
        d.mkdir()
        (d / "manifest.json").write_text(json.dumps({
            "id": "test.theme1", "name": "Theme 1", "description": "d",
            "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
            "type": "theme", "contributes": {"theme": "theme.json"},
        }))
        (d / "theme.json").write_text(json.dumps({
            "dark": {"--bg": "#111", "--text": "#fff"},
            "light": {"--bg": "#fff", "--text": "#111"},
        }))

        config = ConfigManager(str(tmp_path / "config"))
        app, loader = _create_module_app(config, [str(tmp_path)])

        yield app, loader

    def test_get_themes_returns_theme_data(self, app_with_theme):
        app, loader = app_with_theme
        with app.test_client() as c:
            resp = c.get("/api/themes")
            assert resp.status_code == 200
            data = resp.get_json()
            assert len(data) == 1
            assert data[0]["id"] == "test.theme1"
            assert "dark" in data[0]["theme_data"]
            assert data[0]["theme_data"]["dark"]["--bg"] == "#111"
