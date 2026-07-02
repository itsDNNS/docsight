"""Log redaction checks for community module registry/download URLs."""

import logging

from app import module_download


def test_safe_url_label_removes_path_query_and_credentials():
    label = module_download.safe_url_label("https://user:secret@example.com/private/path?token=abc")

    assert label == "https://example.com"
    assert "secret" not in label
    assert "private" not in label
    assert "token" not in label


def test_safe_url_label_treats_malformed_ports_as_invalid():
    assert module_download.safe_url_label("https://evil.example:999999/path?token=abc") == "<invalid-url>"


def test_registry_fetch_handles_malformed_port_without_raising(caplog):
    url = "https://evil.example:999999/private/registry.json?token=abc"

    with caplog.at_level(logging.ERROR, logger="docsis.module_download"):
        assert module_download.fetch_registry(url) == []

    assert "<invalid-url>" in caplog.text
    assert "999999" not in caplog.text
    assert "private" not in caplog.text


def test_registry_fetch_logs_redacted_untrusted_url(caplog):
    url = "https://user:secret@evil.example/private/registry.json?token=abc"

    with caplog.at_level(logging.ERROR, logger="docsis.module_download"):
        assert module_download.fetch_registry(url) == []

    rendered = caplog.text
    assert "https://evil.example" in rendered
    assert "secret" not in rendered
    assert "private" not in rendered
    assert "token=abc" not in rendered


def test_download_logs_redacted_untrusted_nested_urls(caplog, monkeypatch, tmp_path):
    entries = [
        {"name": "module.py", "type": "file", "download_url": "https://user:secret@evil.example/file.py?token=abc"},
        {"name": "nested", "type": "dir", "url": "https://user:secret@evil.example/nested?token=abc"},
    ]

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            import json
            return json.dumps(entries).encode("utf-8")

    monkeypatch.setattr(module_download.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    with caplog.at_level(logging.WARNING, logger="docsis.module_download"):
        assert module_download.download_github_directory("https://api.github.com/repos/example/repo/contents", str(tmp_path)) is True

    rendered = caplog.text
    assert "https://evil.example" in rendered
    assert "secret" not in rendered
    assert "file.py" not in rendered
    assert "token=abc" not in rendered
