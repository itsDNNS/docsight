"""BNetzA file watcher collector — auto-imports measurement PDFs and CSVs."""

import logging
import os
import shutil

from .base import Collector, CollectorResult

log = logging.getLogger("docsis.collector.bnetz_watcher")

IMPORTED_MARKER = ".imported"


class BnetzWatcherCollector(Collector):
    """Watches a directory for new BNetzA measurement files and auto-imports them."""

    name = "bnetz_watcher"

    def __init__(self, config_mgr, storage, poll_interval=300):
        super().__init__(poll_interval)
        self._config_mgr = config_mgr
        self._storage = storage
        self._last_import_count = 0

    def is_enabled(self) -> bool:
        return self._config_mgr.is_bnetz_watch_configured()

    def collect(self) -> CollectorResult:
        watch_dir = self._config_mgr.get("bnetz_watch_dir", "/data/bnetz")

        if not os.path.isdir(watch_dir):
            return CollectorResult.failure(
                self.name, f"Watch directory does not exist: {watch_dir}"
            )

        # Read set of already-imported filenames
        marker_path = os.path.join(watch_dir, IMPORTED_MARKER)
        imported = _read_marker(marker_path)

        # Scan for new PDF and CSV files
        new_files = []
        for fname in sorted(os.listdir(watch_dir)):
            lower = fname.lower()
            if (lower.endswith(".pdf") or lower.endswith(".csv")) and fname not in imported:
                new_files.append(fname)

        if not new_files:
            self._last_import_count = 0
            return CollectorResult.ok(self.name, data={"imported": 0, "errors": 0})

        imported_count = 0
        error_count = 0
        newly_imported = []

        for fname in new_files:
            fpath = os.path.join(watch_dir, fname)
            try:
                if fname.lower().endswith(".pdf"):
                    self._import_pdf(fpath)
                else:
                    self._import_csv(fpath)

                newly_imported.append(fname)
                imported_count += 1

                # Move to processed subdirectory
                processed_dir = os.path.join(watch_dir, "processed")
                os.makedirs(processed_dir, exist_ok=True)
                shutil.move(fpath, os.path.join(processed_dir, fname))

            except Exception as e:
                log.warning("Failed to import %s: %s", fname, e)
                error_count += 1

        # Update marker file with newly imported filenames
        if newly_imported:
            _append_marker(marker_path, newly_imported)

        self._last_import_count = imported_count

        log.info(
            "BNetzA watcher: imported %d, errors %d from %s",
            imported_count, error_count, watch_dir,
        )

        if error_count > 0 and imported_count == 0:
            return CollectorResult.failure(
                self.name,
                f"All {error_count} file(s) failed to import",
            )

        return CollectorResult.ok(
            self.name, data={"imported": imported_count, "errors": error_count}
        )

    def _import_pdf(self, fpath):
        """Import a single PDF file."""
        from ..bnetz_parser import parse_bnetz_pdf

        with open(fpath, "rb") as f:
            pdf_bytes = f.read()

        parsed = parse_bnetz_pdf(pdf_bytes)
        self._storage.save_bnetz_measurement(parsed, pdf_bytes, source="watcher")
        log.info("Imported BNetzA PDF: %s", os.path.basename(fpath))

    def _import_csv(self, fpath):
        """Import a single CSV file."""
        from ..bnetz_csv_parser import parse_bnetz_csv

        with open(fpath, "r", encoding="utf-8-sig") as f:
            content = f.read()

        parsed = parse_bnetz_csv(content)
        self._storage.save_bnetz_measurement(parsed, pdf_bytes=None, source="csv_import")
        log.info("Imported BNetzA CSV: %s", os.path.basename(fpath))

    def get_status(self) -> dict:
        """Return collector status with watch directory info."""
        status = super().get_status()
        status["watch_dir"] = self._config_mgr.get("bnetz_watch_dir", "/data/bnetz")
        status["last_import_count"] = self._last_import_count
        return status


def _read_marker(path):
    """Read the set of already-imported filenames from the marker file."""
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r") as f:
            return {line.strip() for line in f if line.strip()}
    except Exception:
        return set()


def _append_marker(path, filenames):
    """Append filenames to the marker file."""
    try:
        with open(path, "a") as f:
            for name in filenames:
                f.write(name + "\n")
    except Exception as e:
        log.warning("Failed to update marker file %s: %s", path, e)
