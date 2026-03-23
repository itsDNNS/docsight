"""Tests for security audit findings: SSRF, restore rate-limit, XSS filter."""

import io
import json
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.module_download import fetch_registry, is_trusted_url


# ── Finding 1: SSRF via registry URL ──


class TestFetchRegistrySSRF:
    """fetch_registry must reject untrusted URLs."""

    def test_rejects_http_url(self):
        result = fetch_registry("http://evil.com/registry.json")
        assert result == []

    def test_rejects_internal_url(self):
        result = fetch_registry("http://169.254.169.254/latest/meta-data/")
        assert result == []

    def test_rejects_file_url(self):
        result = fetch_registry("file:///etc/passwd")
        assert result == []

    def test_rejects_localhost(self):
        result = fetch_registry("http://localhost:8080/registry.json")
        assert result == []

    def test_rejects_untrusted_https(self):
        result = fetch_registry("https://evil.com/registry.json")
        assert result == []

    @patch("app.module_download.urllib.request.urlopen")
    def test_allows_trusted_github_url(self, mock_urlopen):
        registry_data = {"modules": [
            {"id": "test", "name": "Test", "version": "1.0",
             "download_url": "https://github.com/x", "min_app_version": "1.0"}
        ]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(registry_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_registry(
            "https://raw.githubusercontent.com/user/repo/main/registry.json"
        )
        assert len(result) == 1
        assert result[0]["id"] == "test"

    @patch("app.module_download.urllib.request.urlopen")
    def test_allows_github_api_url(self, mock_urlopen):
        registry_data = {"themes": [
            {"id": "t1", "name": "Theme", "version": "1.0",
             "download_url": "https://github.com/x", "min_app_version": "1.0"}
        ]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(registry_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_registry(
            "https://api.github.com/repos/user/repo/contents/registry.json",
            key="themes",
        )
        assert len(result) == 1


# ── Finding 2: Restore rate-limiting ──


class TestRestoreRateLimit:
    """Unauthenticated restore endpoints must be rate-limited."""

    @pytest.fixture
    def client(self):
        from flask import Flask
        from app.config import ConfigManager
        from app.modules.backup.routes import bp as backup_bp

        test_app = Flask(__name__)
        test_app.config["TESTING"] = True
        test_app.secret_key = "test-secret"

        with tempfile.TemporaryDirectory() as td:
            cfg = ConfigManager(td)
            cfg.save({"demo_mode": False})

            # Patch the getters that backup routes use
            with patch("app.modules.backup.routes.get_config_manager", return_value=cfg), \
                 patch("app.modules.backup.routes._auth_required", return_value=False), \
                 patch("app.modules.backup.routes._get_client_ip", return_value="127.0.0.1"):
                test_app.register_blueprint(backup_bp)
                with test_app.test_client() as c:
                    yield c

    @pytest.fixture(autouse=True)
    def _clear_rate_limits(self):
        from app.modules.backup import routes as br
        br._restore_attempts.clear()
        yield
        br._restore_attempts.clear()

    def test_restore_validate_rate_limited(self, client):
        """After 5 attempts, further unauthenticated restore/validate should be blocked."""
        for i in range(5):
            resp = client.post(
                "/api/restore/validate",
                data={"file": (io.BytesIO(b"dummy"), "backup.tar.gz")},
                content_type="multipart/form-data",
            )
            assert resp.status_code != 429, f"Blocked too early on attempt {i+1}"

        # 6th attempt should be rate-limited
        resp = client.post(
            "/api/restore/validate",
            data={"file": (io.BytesIO(b"dummy"), "backup.tar.gz")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 429

    def test_restore_rate_limited(self, client):
        """After 5 attempts, further unauthenticated restore should be blocked."""
        for i in range(5):
            client.post(
                "/api/restore",
                data={"file": (io.BytesIO(b"dummy"), "backup.tar.gz")},
                content_type="multipart/form-data",
            )

        resp = client.post(
            "/api/restore",
            data={"file": (io.BytesIO(b"dummy"), "backup.tar.gz")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 429

    def test_authenticated_restore_not_rate_limited(self):
        """Configured+authenticated instances skip the rate limit path entirely."""
        from flask import Flask
        from app.config import ConfigManager
        from app.modules.backup import routes as br

        br._restore_attempts.clear()

        test_app = Flask(__name__)
        test_app.config["TESTING"] = True
        test_app.secret_key = "test-secret"

        with tempfile.TemporaryDirectory() as td:
            cfg = ConfigManager(td)
            cfg.save({"admin_password": "testpass", "modem_type": "demo"})

            with patch("app.modules.backup.routes.get_config_manager", return_value=cfg), \
                 patch("app.modules.backup.routes._auth_required", return_value=False), \
                 patch("app.modules.backup.routes._get_client_ip", return_value="127.0.0.1"):
                from app.modules.backup.routes import bp as backup_bp
                fresh_bp = type(backup_bp)(backup_bp.name + "_auth_test", backup_bp.import_name)
                for deferred in backup_bp.deferred_functions:
                    fresh_bp.record(deferred)
                test_app.register_blueprint(backup_bp)
                with test_app.test_client() as c:
                    for i in range(10):
                        resp = c.post(
                            "/api/restore/validate",
                            data={"file": (io.BytesIO(b"dummy"), "backup.tar.gz")},
                            content_type="multipart/form-data",
                        )
                        # Configured instance skips rate-limit code path
                        assert resp.status_code != 429, f"Rate-limited on attempt {i+1}"


# ── Finding 3: XSS in safe_html filter ──


class TestSafeHtmlXSS:
    """safe_html filter must strip javascript: hrefs and event handlers."""

    @pytest.fixture
    def filter_fn(self):
        from app.web import safe_html_filter
        return safe_html_filter

    def test_strips_javascript_href(self, filter_fn):
        result = str(filter_fn('<a href="javascript:alert(1)">click</a>'))
        assert "javascript:" not in result.lower()
        # The tag itself should remain but href neutralized
        assert "<a" in result

    def test_strips_javascript_href_mixed_case(self, filter_fn):
        result = str(filter_fn('<a href="JavaScript:alert(1)">click</a>'))
        assert "javascript:" not in result.lower()

    def test_strips_javascript_href_spaces(self, filter_fn):
        result = str(filter_fn('<a href=" javascript:void(0)">click</a>'))
        assert "javascript:" not in result.lower()

    def test_strips_onclick(self, filter_fn):
        result = str(filter_fn('<a href="#" onclick="alert(1)">click</a>'))
        assert "onclick" not in result.lower()

    def test_strips_unquoted_onclick(self, filter_fn):
        result = str(filter_fn('<a onclick=alert(1) href="#">click</a>'))
        assert "onclick" not in result.lower()
        assert "alert" not in result.lower()

    def test_strips_unquoted_onmouseover(self, filter_fn):
        result = str(filter_fn('<b onmouseover=alert(1)>bold</b>'))
        assert "onmouseover" not in result.lower()

    def test_javascript_href_replaced_with_hash(self, filter_fn):
        result = str(filter_fn('<a href="javascript:alert(1)">click</a>'))
        assert 'href="#"' in result
        assert "javascript:" not in result.lower()

    def test_unquoted_javascript_href(self, filter_fn):
        result = str(filter_fn('<a href=javascript:alert(1)>click</a>'))
        assert "javascript:" not in result.lower()

    def test_html_entity_javascript_bypass(self, filter_fn):
        """Tab entity inside javascript: scheme must be caught."""
        result = str(filter_fn('<a href="java&#9;script:alert(1)">click</a>'))
        assert 'href="#"' in result

    def test_newline_javascript_bypass(self, filter_fn):
        """Newline inside javascript: scheme must be caught."""
        result = str(filter_fn('<a href="java\nscript:alert(1)">click</a>'))
        assert 'href="#"' in result

    def test_slash_separated_onclick(self, filter_fn):
        """Slash-separated event handler must be stripped."""
        result = str(filter_fn('<a/onclick=alert(1) href="#">click</a>'))
        assert "onclick" not in result.lower()

    def test_data_uri_blocked(self, filter_fn):
        result = str(filter_fn('<a href="data:text/html,<script>alert(1)</script>">x</a>'))
        assert 'href="#"' in result

    def test_vbscript_blocked(self, filter_fn):
        result = str(filter_fn('<a href="vbscript:msgbox(1)">x</a>'))
        assert 'href="#"' in result

    def test_relative_path_allowed(self, filter_fn):
        result = str(filter_fn('<a href="/docs/help">help</a>'))
        assert 'href="/docs/help"' in result

    def test_hash_link_allowed(self, filter_fn):
        result = str(filter_fn('<a href="#section">jump</a>'))
        assert 'href="#section"' in result

    def test_no_space_before_onclick(self, filter_fn):
        """onclick directly after closing quote must be stripped."""
        result = str(filter_fn('<a href="/page"onclick="alert(1)">click</a>'))
        assert "onclick" not in result.lower()
        assert "alert" not in result.lower()

    def test_strips_onmouseover(self, filter_fn):
        result = str(filter_fn('<b onmouseover="alert(1)">bold</b>'))
        assert "onmouseover" not in result.lower()
        assert "<b" in result

    def test_strips_onerror(self, filter_fn):
        result = str(filter_fn('<em onerror="fetch(\'evil\')">text</em>'))
        assert "onerror" not in result.lower()

    def test_strips_formaction(self, filter_fn):
        result = str(filter_fn('<a formaction="https://evil.com">click</a>'))
        assert "formaction" not in result.lower()

    def test_allows_safe_href(self, filter_fn):
        result = str(filter_fn('<a href="https://example.com">link</a>'))
        assert 'href="https://example.com"' in result

    def test_allows_safe_tags(self, filter_fn):
        result = str(filter_fn("<b>bold</b> <em>italic</em> <br> <strong>s</strong>"))
        assert "<b>" in result
        assert "<em>" in result
        assert "<br>" in result
        assert "<strong>" in result

    def test_strips_script_tag(self, filter_fn):
        result = str(filter_fn("<script>alert(1)</script>"))
        assert "<script" not in result

    def test_strips_img_tag(self, filter_fn):
        result = str(filter_fn('<img src="x" onerror="alert(1)">'))
        assert "<img" not in result

    def test_combined_attack(self, filter_fn):
        """Multiple attack vectors in one string."""
        html = (
            '<a href="javascript:alert(1)" onclick="steal()">click</a>'
            '<script>document.cookie</script>'
            '<b onmouseover="fetch(\'evil\')">bold</b>'
        )
        result = str(filter_fn(html))
        assert "javascript:" not in result.lower()
        assert "onclick" not in result.lower()
        assert "<script" not in result.lower()
        assert "onmouseover" not in result.lower()
        assert "<a" in result  # tag preserved
        assert "<b" in result  # tag preserved
