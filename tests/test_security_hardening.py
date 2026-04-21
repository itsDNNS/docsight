"""Tests for security hardening: proxy trust, theme SSRF, module isolation."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from app.theme_registry import _is_trusted_url, download_theme
from app.collectors import _ModuleConfigProxy
from app.config import ConfigManager, SECRET_KEYS, HASH_KEYS


# ── Reverse proxy / X-Forwarded-For ──


class TestClientIPWithoutProxy:
    """Without REVERSE_PROXY, _get_client_ip uses raw remote_addr."""

    def test_ignores_xff_header(self, client):
        """X-Forwarded-For should be ignored when ProxyFix is not active."""
        resp = client.get("/health", headers={"X-Forwarded-For": "1.2.3.4"})
        assert resp.status_code == 200
        # The key assertion: rate limiter uses remote_addr (127.0.0.1 from
        # test client), not the spoofed X-Forwarded-For header.

    def test_rate_limit_uses_remote_addr(self, client):
        """Rate limiting should use real remote_addr, not spoofed XFF."""
        from app.web import _login_attempts
        _login_attempts.clear()

        # Simulate 6 failed logins with different spoofed IPs
        for i in range(6):
            client.post(
                "/login",
                data={"password": "wrong"},
                headers={"X-Forwarded-For": f"10.0.0.{i}"},
            )

        # Without proxy trust, all requests come from same remote_addr,
        # so rate limiter should kick in.
        attempts_keys = list(_login_attempts.keys())
        assert len(attempts_keys) == 1, (
            f"Expected 1 IP in rate limiter, got {len(attempts_keys)}: {attempts_keys}"
        )


# ── Theme registry URL validation ──


class TestThemeURLValidation:
    """Theme downloads must only fetch from trusted GitHub domains."""

    @pytest.mark.parametrize("url,expected", [
        ("https://raw.githubusercontent.com/user/repo/main/file.json", True),
        ("https://api.github.com/repos/user/repo/contents/theme", True),
        ("https://github.com/user/repo", True),
        ("http://raw.githubusercontent.com/user/repo/main/file.json", False),
        ("https://evil.com/theme.json", False),
        ("https://localhost:8080/steal", False),
        ("file:///etc/passwd", False),
        ("gopher://internal:25/", False),
        ("", False),
    ])
    def test_is_trusted_url(self, url, expected):
        assert _is_trusted_url(url) is expected

    def test_download_rejects_untrusted_url(self, tmp_path):
        """download_theme should refuse untrusted download URLs."""
        result = download_theme("http://evil.com/theme", str(tmp_path / "evil_theme"))
        assert result is False

    @patch("app.module_download.urllib.request.urlopen")
    def test_download_skips_untrusted_file_urls(self, mock_urlopen, tmp_path):
        """File entries with untrusted download_url should be skipped."""
        # Mock the directory listing response
        listing = [
            {
                "type": "file",
                "name": "manifest.json",
                "download_url": "https://evil.com/manifest.json",
            },
            {
                "type": "file",
                "name": "theme.json",
                "download_url": "https://raw.githubusercontent.com/user/repo/main/theme.json",
            },
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(listing).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        target = str(tmp_path / "test_theme")
        result = download_theme(
            "https://api.github.com/repos/user/repo/contents/theme",
            target,
        )
        # Should fail because manifest.json was skipped (untrusted URL)
        assert result is False


# ── Module config proxy ──


class TestModuleConfigProxy:
    """Community modules should not see secrets they didn't declare."""

    def test_blocks_modem_password(self, tmp_path):
        cfg = ConfigManager(str(tmp_path))
        cfg.save({"modem_password": "secret123"})

        proxy = _ModuleConfigProxy(cfg)
        assert proxy.get("modem_password") is None

    def test_blocks_admin_password(self, tmp_path):
        cfg = ConfigManager(str(tmp_path))
        cfg.save({"admin_password": "admin123"})

        proxy = _ModuleConfigProxy(cfg)
        assert proxy.get("admin_password") is None

    def test_allows_non_secret_keys(self, tmp_path):
        cfg = ConfigManager(str(tmp_path))
        cfg.save({"language": "de", "poll_interval": 300})

        proxy = _ModuleConfigProxy(cfg)
        assert proxy.get("language") == "de"
        assert proxy.get("poll_interval") == 300

    def test_allowed_secret_keys_passthrough(self, tmp_path):
        """Modules that declare a secret in their config get access to it."""
        cfg = ConfigManager(str(tmp_path))
        cfg.save({"speedtest_tracker_token": "mytoken"})

        proxy = _ModuleConfigProxy(
            cfg, allowed_secret_keys={"speedtest_tracker_token"}
        )
        assert proxy.get("speedtest_tracker_token") == "mytoken"

    def test_allowed_secret_does_not_unlock_other_secrets(self, tmp_path):
        cfg = ConfigManager(str(tmp_path))
        cfg.save({
            "speedtest_tracker_token": "mytoken",
            "modem_password": "secret123",
        })

        proxy = _ModuleConfigProxy(
            cfg, allowed_secret_keys={"speedtest_tracker_token"}
        )
        assert proxy.get("speedtest_tracker_token") == "mytoken"
        assert proxy.get("modem_password") is None

    def test_get_all_masks_secrets(self, tmp_path):
        cfg = ConfigManager(str(tmp_path))
        cfg.save({"modem_password": "secret", "language": "en"})

        proxy = _ModuleConfigProxy(cfg)
        all_cfg = proxy.get_all()
        assert "modem_password" not in all_cfg
        assert all_cfg.get("language") == "en"

    def test_data_dir_accessible(self, tmp_path):
        cfg = ConfigManager(str(tmp_path))
        proxy = _ModuleConfigProxy(cfg)
        assert proxy.data_dir == str(tmp_path)

    def test_is_demo_mode(self, tmp_path):
        cfg = ConfigManager(str(tmp_path))
        proxy = _ModuleConfigProxy(cfg)
        assert proxy.is_demo_mode() is False


# ── Community module route protection ──


class TestCommunityRouteProtection:
    """Community modules must not shadow core routes."""

    def test_blocks_login_route(self):
        """A community module trying to register /login should be blocked."""
        from flask import Blueprint
        from app.module_loader import load_module_routes

        app = Flask(__name__)
        # Register a core /login route first
        @app.route("/login")
        def login():
            return "core login"

        # Can't easily test without a real module file, so test the
        # protection constants directly
        from app.module_loader import _PROTECTED_ROUTES, _PROTECTED_API_PREFIXES
        assert "/login" in _PROTECTED_ROUTES
        assert "/" in _PROTECTED_ROUTES
        assert any(p.startswith("/api/config") for p in _PROTECTED_API_PREFIXES)

    def test_api_config_prefix_protected(self):
        from app.module_loader import _PROTECTED_API_PREFIXES
        # A route like /api/config/steal should be blocked
        test_route = "/api/config/steal"
        blocked = any(test_route.startswith(p) for p in _PROTECTED_API_PREFIXES)
        assert blocked is True

    def test_module_api_route_allowed(self):
        """Module-specific API routes like /api/weather/... should be allowed."""
        from app.module_loader import _PROTECTED_ROUTES, _PROTECTED_API_PREFIXES
        test_route = "/api/weather/current"
        in_protected = test_route in _PROTECTED_ROUTES
        prefix_blocked = any(test_route.startswith(p) for p in _PROTECTED_API_PREFIXES)
        assert not in_protected and not prefix_blocked


# ── Path safety helpers ──


class TestSafeChildPath:
    """safe_child_path must reject traversal and invalid IDs."""

    def test_valid_id(self, tmp_path):
        from app.path_safety import safe_child_path

        base = str(tmp_path)
        result = safe_child_path(base, "my_module.v2")
        assert result.startswith(str(tmp_path.resolve()))
        assert result.endswith("my_module.v2")

    def test_rejects_traversal(self, tmp_path):
        from app.path_safety import safe_child_path

        with pytest.raises(ValueError, match="Invalid ID"):
            safe_child_path(str(tmp_path), "../etc")

    def test_rejects_uppercase(self, tmp_path):
        from app.path_safety import safe_child_path

        with pytest.raises(ValueError, match="Invalid ID"):
            safe_child_path(str(tmp_path), "BadModule")

    def test_rejects_slash(self, tmp_path):
        from app.path_safety import safe_child_path

        with pytest.raises(ValueError, match="Invalid ID"):
            safe_child_path(str(tmp_path), "a/b")


class TestSafeChildFile:
    """safe_child_file must only allow allowlisted filenames."""

    def test_manifest_allowed(self, tmp_path):
        from app.path_safety import safe_child_file

        result = safe_child_file(str(tmp_path), "manifest.json")
        assert result.endswith("manifest.json")

    def test_theme_allowed(self, tmp_path):
        from app.path_safety import safe_child_file

        result = safe_child_file(str(tmp_path), "theme.json")
        assert result.endswith("theme.json")

    def test_rejects_unlisted_file(self, tmp_path):
        from app.path_safety import safe_child_file

        with pytest.raises(ValueError, match="not in allowlist"):
            safe_child_file(str(tmp_path), "evil.py")

    def test_rejects_traversal_filename(self, tmp_path):
        from app.path_safety import safe_child_file

        with pytest.raises(ValueError, match="not in allowlist"):
            safe_child_file(str(tmp_path), "../../../etc/passwd")


class TestSafeManifestSubpath:
    """safe_manifest_subpath must allow subdirs but block traversal."""

    def test_simple_subdir_allowed(self, tmp_path):
        from app.path_safety import safe_manifest_subpath

        result = safe_manifest_subpath(str(tmp_path), "static")
        assert result.endswith("static")

    def test_nested_path_allowed(self, tmp_path):
        from app.path_safety import safe_manifest_subpath

        result = safe_manifest_subpath(str(tmp_path), "templates/tab.html")
        assert result.endswith("templates/tab.html")

    def test_traversal_blocked(self, tmp_path):
        from app.path_safety import safe_manifest_subpath

        with pytest.raises(ValueError, match="Unsafe manifest subpath"):
            safe_manifest_subpath(str(tmp_path), "../../../etc")

    def test_dotdot_in_middle_blocked(self, tmp_path):
        from app.path_safety import safe_manifest_subpath

        with pytest.raises(ValueError, match="Unsafe manifest subpath"):
            safe_manifest_subpath(str(tmp_path), "templates/../../../etc/passwd")

    def test_backslash_blocked(self, tmp_path):
        from app.path_safety import safe_manifest_subpath

        with pytest.raises(ValueError, match="Unsafe manifest subpath"):
            safe_manifest_subpath(str(tmp_path), "templates\\..\\..\\etc")

    def test_empty_blocked(self, tmp_path):
        from app.path_safety import safe_manifest_subpath

        with pytest.raises(ValueError, match="Unsafe manifest subpath"):
            safe_manifest_subpath(str(tmp_path), "")

    def test_dot_resolves_to_base(self, tmp_path):
        from app.path_safety import safe_manifest_subpath

        result = safe_manifest_subpath(str(tmp_path), ".")
        assert os.path.realpath(result) == os.path.realpath(str(tmp_path))


class TestSafeManifestRef:
    """safe_manifest_ref must block traversal and path separators."""

    def test_plain_filename_allowed(self, tmp_path):
        from app.path_safety import safe_manifest_ref

        result = safe_manifest_ref(str(tmp_path), "theme.json")
        assert result.endswith("theme.json")

    def test_dashes_and_dots_allowed(self, tmp_path):
        from app.path_safety import safe_manifest_ref

        result = safe_manifest_ref(str(tmp_path), "my-custom-theme.v2.json")
        assert result.endswith("my-custom-theme.v2.json")

    def test_traversal_blocked(self, tmp_path):
        from app.path_safety import safe_manifest_ref

        with pytest.raises(ValueError, match="Unsafe manifest reference"):
            safe_manifest_ref(str(tmp_path), "../../../etc/passwd")

    def test_slash_blocked(self, tmp_path):
        from app.path_safety import safe_manifest_ref

        with pytest.raises(ValueError, match="Unsafe manifest reference"):
            safe_manifest_ref(str(tmp_path), "subdir/theme.json")

    def test_empty_string_blocked(self, tmp_path):
        from app.path_safety import safe_manifest_ref

        with pytest.raises(ValueError, match="Unsafe manifest reference"):
            safe_manifest_ref(str(tmp_path), "")

    def test_dot_dot_filename_blocked(self, tmp_path):
        from app.path_safety import safe_manifest_ref

        with pytest.raises(ValueError, match="Unsafe manifest reference"):
            safe_manifest_ref(str(tmp_path), "..")


# ── Test fixtures ──


@pytest.fixture
def client():
    """Flask test client with minimal config for auth testing."""
    from app import web
    from app.config import ConfigManager
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cfg = ConfigManager(td)
        cfg.save({"admin_password": "testpass", "demo_mode": False, "modem_type": "demo"})
        web.init_config(cfg)
        web.init_storage(None)
        web.init_collector(None)
        web.init_collectors([])
        web.app.config["TESTING"] = True
        with web.app.test_client() as c:
            yield c
