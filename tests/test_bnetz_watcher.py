"""Tests for BNetzA file watcher collector."""

import os
import pytest
from unittest.mock import MagicMock, patch

from app.collectors.bnetz_watcher import BnetzWatcherCollector, _read_marker, _append_marker


class TestBnetzWatcherEnabled:
    def _make_collector(self, watch_configured=True):
        config_mgr = MagicMock()
        config_mgr.is_bnetz_watch_configured.return_value = watch_configured
        config_mgr.get.side_effect = lambda k, *a: {
            "bnetz_watch_dir": "/data/bnetz",
        }.get(k, a[0] if a else None)
        storage = MagicMock()
        return BnetzWatcherCollector(config_mgr=config_mgr, storage=storage), config_mgr, storage

    def test_is_enabled_true(self):
        c, *_ = self._make_collector(watch_configured=True)
        assert c.is_enabled() is True

    def test_is_enabled_false(self):
        c, *_ = self._make_collector(watch_configured=False)
        assert c.is_enabled() is False

    def test_name(self):
        c, *_ = self._make_collector()
        assert c.name == "bnetz_watcher"

    def test_default_poll_interval(self):
        c, *_ = self._make_collector()
        assert c.poll_interval_seconds == 300


class TestBnetzWatcherCollect:
    def _make_collector(self, watch_dir):
        config_mgr = MagicMock()
        config_mgr.is_bnetz_watch_configured.return_value = True
        config_mgr.get.side_effect = lambda k, *a: {
            "bnetz_watch_dir": watch_dir,
        }.get(k, a[0] if a else None)
        storage = MagicMock()
        storage.save_bnetz_measurement.return_value = 1
        return BnetzWatcherCollector(config_mgr=config_mgr, storage=storage), config_mgr, storage

    def test_missing_dir_returns_failure(self):
        c, *_ = self._make_collector("/nonexistent/path/12345")
        result = c.collect()
        assert result.success is False
        assert "does not exist" in result.error

    def test_empty_dir_returns_zero(self, tmp_path):
        c, _, storage = self._make_collector(str(tmp_path))
        result = c.collect()
        assert result.success is True
        assert result.data == {"imported": 0, "errors": 0}
        storage.save_bnetz_measurement.assert_not_called()

    @patch("app.collectors.bnetz_watcher.BnetzWatcherCollector._import_pdf")
    def test_imports_new_pdf(self, mock_import, tmp_path):
        # Create a test PDF file
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 test")

        c, _, storage = self._make_collector(str(tmp_path))
        result = c.collect()

        assert result.success is True
        assert result.data["imported"] == 1
        mock_import.assert_called_once()
        # File should be moved to processed/
        assert not pdf_path.exists()
        assert (tmp_path / "processed" / "test.pdf").exists()

    @patch("app.collectors.bnetz_watcher.BnetzWatcherCollector._import_csv")
    def test_imports_new_csv(self, mock_import, tmp_path):
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("Datum;Download\n15.03.2026;100,0\n")

        c, _, storage = self._make_collector(str(tmp_path))
        result = c.collect()

        assert result.success is True
        assert result.data["imported"] == 1
        mock_import.assert_called_once()
        assert not csv_path.exists()
        assert (tmp_path / "processed" / "test.csv").exists()

    @patch("app.collectors.bnetz_watcher.BnetzWatcherCollector._import_pdf")
    def test_skips_already_imported(self, mock_import, tmp_path):
        # Write marker with already-imported filename
        marker = tmp_path / ".imported"
        marker.write_text("test.pdf\n")

        # Create the same file
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 test")

        c, _, storage = self._make_collector(str(tmp_path))
        result = c.collect()

        assert result.success is True
        assert result.data["imported"] == 0
        mock_import.assert_not_called()

    @patch("app.collectors.bnetz_watcher.BnetzWatcherCollector._import_pdf")
    @patch("app.collectors.bnetz_watcher.BnetzWatcherCollector._import_csv")
    def test_mixed_pdf_and_csv(self, mock_csv, mock_pdf, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"%PDF-test")
        (tmp_path / "b.csv").write_text("Datum;Download\n15.03.2026;100\n")

        c, _, storage = self._make_collector(str(tmp_path))
        result = c.collect()

        assert result.success is True
        assert result.data["imported"] == 2
        mock_pdf.assert_called_once()
        mock_csv.assert_called_once()

    @patch("app.collectors.bnetz_watcher.BnetzWatcherCollector._import_pdf")
    def test_ignores_non_pdf_csv_files(self, mock_import, tmp_path):
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")

        c, _, storage = self._make_collector(str(tmp_path))
        result = c.collect()

        assert result.success is True
        assert result.data["imported"] == 0
        mock_import.assert_not_called()

    @patch("app.collectors.bnetz_watcher.BnetzWatcherCollector._import_pdf")
    def test_error_handling_corrupt_file(self, mock_import, tmp_path):
        mock_import.side_effect = ValueError("Cannot read PDF")
        (tmp_path / "bad.pdf").write_bytes(b"not a pdf")

        c, _, storage = self._make_collector(str(tmp_path))
        result = c.collect()

        assert result.success is False
        assert result.data is None  # failure result has no data
        assert "failed to import" in result.error.lower()

    @patch("app.collectors.bnetz_watcher.BnetzWatcherCollector._import_pdf")
    def test_partial_failure(self, mock_import, tmp_path):
        """One file succeeds, one fails. Should still return success."""
        call_count = [0]
        def side_effect(fpath):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("bad file")
        mock_import.side_effect = side_effect

        (tmp_path / "a.pdf").write_bytes(b"bad")
        (tmp_path / "b.pdf").write_bytes(b"good")

        c, _, storage = self._make_collector(str(tmp_path))
        result = c.collect()

        assert result.success is True
        assert result.data["imported"] == 1
        assert result.data["errors"] == 1

    @patch("app.collectors.bnetz_watcher.BnetzWatcherCollector._import_pdf")
    def test_marker_persistence(self, mock_import, tmp_path):
        (tmp_path / "test.pdf").write_bytes(b"%PDF-test")

        c, _, storage = self._make_collector(str(tmp_path))
        c.collect()

        # Marker should contain the filename
        marker = tmp_path / ".imported"
        assert marker.exists()
        assert "test.pdf" in marker.read_text()

    def test_get_status_includes_watch_dir(self):
        config_mgr = MagicMock()
        config_mgr.is_bnetz_watch_configured.return_value = True
        config_mgr.get.side_effect = lambda k, *a: {
            "bnetz_watch_dir": "/data/bnetz",
        }.get(k, a[0] if a else None)
        storage = MagicMock()

        c = BnetzWatcherCollector(config_mgr=config_mgr, storage=storage)
        status = c.get_status()

        assert status["name"] == "bnetz_watcher"
        assert status["watch_dir"] == "/data/bnetz"
        assert status["last_import_count"] == 0


class TestMarkerHelpers:
    def test_read_marker_nonexistent(self, tmp_path):
        result = _read_marker(str(tmp_path / "nonexistent"))
        assert result == set()

    def test_read_marker_with_content(self, tmp_path):
        marker = tmp_path / ".imported"
        marker.write_text("file1.pdf\nfile2.csv\n")
        result = _read_marker(str(marker))
        assert result == {"file1.pdf", "file2.csv"}

    def test_read_marker_ignores_blank_lines(self, tmp_path):
        marker = tmp_path / ".imported"
        marker.write_text("file1.pdf\n\n  \nfile2.csv\n")
        result = _read_marker(str(marker))
        assert result == {"file1.pdf", "file2.csv"}

    def test_append_marker(self, tmp_path):
        marker = tmp_path / ".imported"
        _append_marker(str(marker), ["file1.pdf", "file2.csv"])
        content = marker.read_text()
        assert "file1.pdf" in content
        assert "file2.csv" in content

    def test_append_marker_adds_to_existing(self, tmp_path):
        marker = tmp_path / ".imported"
        marker.write_text("existing.pdf\n")
        _append_marker(str(marker), ["new.pdf"])
        content = marker.read_text()
        assert "existing.pdf" in content
        assert "new.pdf" in content
