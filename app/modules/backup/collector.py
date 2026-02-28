"""Scheduled backup collector."""

import logging

from app.collectors.base import Collector, CollectorResult

log = logging.getLogger("docsis.collector.backup")


class BackupCollector(Collector):
    """Collector that creates scheduled backups."""

    name = "backup"

    def __init__(self, config_mgr, poll_interval=86400, **kwargs):
        super().__init__(poll_interval)
        self._config_mgr = config_mgr

    def is_enabled(self):
        return self._config_mgr.is_backup_configured()

    def collect(self):
        from .backup import create_backup_to_file, cleanup_old_backups

        data_dir = self._config_mgr.data_dir
        backup_path = self._config_mgr.get("backup_path", "/backup")
        retention = self._config_mgr.get("backup_retention", 5)

        try:
            filename = create_backup_to_file(data_dir, backup_path)
            cleanup_old_backups(backup_path, keep=retention)
            log.info("Scheduled backup created: %s", filename)
            return CollectorResult.ok(self.name, {"filename": filename})
        except Exception as e:
            log.error("Scheduled backup failed: %s", e)
            return CollectorResult.failure(self.name, str(e))
