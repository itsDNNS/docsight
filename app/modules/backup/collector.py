"""Scheduled backup collector."""

import logging
import time
from datetime import datetime

from app.collectors.base import Collector, CollectorResult

log = logging.getLogger("docsis.collector.backup")


class BackupCollector(Collector):
    """Collector that creates scheduled backups."""

    name = "backup"

    def __init__(self, config_mgr, poll_interval=86400, **kwargs):
        self._config_mgr = config_mgr
        interval_hours = self._get_interval_hours(config_mgr, poll_interval // 3600)
        super().__init__(interval_hours * 3600)
        self._seed_last_poll()

    def _seed_last_poll(self):
        """Set _last_poll from newest backup on disk to survive container restarts.

        Seeds from the newest file regardless of source (scheduled or manual).
        This means a manual backup can shift the automatic schedule after a
        restart, which is acceptable: the guarantee is "at least one backup
        every <interval>", not "backups at a fixed time of day".
        """
        from .backup import list_backups
        backup_path = self._config_mgr.get("backup_path", "/backup")
        backups = list_backups(backup_path)
        if not backups:
            return
        try:
            dt = datetime.fromisoformat(backups[0]["modified"])
            self._last_poll = dt.timestamp()
            age_hours = (time.time() - self._last_poll) / 3600
            log.info("Backup schedule seeded from disk — newest backup is %.1fh old", age_hours)
        except (ValueError, TypeError):
            pass

    @staticmethod
    def _get_interval_hours(config_mgr, default_hours=24):
        """Return configured backup interval in hours as int."""
        try:
            value = int(config_mgr.get("backup_interval_hours", default_hours))
        except (TypeError, ValueError):
            return default_hours
        return value if value > 0 else default_hours

    @staticmethod
    def _get_retention(config_mgr, default_keep=5):
        """Return backup retention as int."""
        try:
            value = int(config_mgr.get("backup_retention", default_keep))
        except (TypeError, ValueError):
            return default_keep
        return value if value > 0 else default_keep

    def is_enabled(self):
        return self._config_mgr.is_backup_configured()

    def collect(self):
        from .backup import create_backup_to_file, cleanup_old_backups
        data_dir = self._config_mgr.data_dir
        backup_path = self._config_mgr.get("backup_path", "/backup")
        retention = self._get_retention(self._config_mgr)

        try:
            filename = create_backup_to_file(data_dir, backup_path)
            cleanup_old_backups(backup_path, keep=retention)
            log.info("Scheduled backup created: %s", filename)
            return CollectorResult.ok(self.name, {"filename": filename})
        except Exception as e:
            log.error("Scheduled backup failed: %s", e)
            return CollectorResult.failure(self.name, str(e))
