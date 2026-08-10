"""SQLite snapshot storage for DOCSIS timeline."""

from __future__ import annotations

from .base import StorageBase, ALLOWED_MIME_TYPES, MAX_ATTACHMENT_SIZE, MAX_ATTACHMENTS_PER_ENTRY
from .snapshot import SnapshotMethods
from .events import EventMethods
from .analysis import AnalysisMethods
from .tokens import TokenMethods
from .smart_capture import SmartCaptureMethods
from .cleanup import CleanupMethods
from .device import DeviceStorageMethods
from .pwa_push import PwaPushMethods

__all__ = [
    "SnapshotStorage",
    "ALLOWED_MIME_TYPES",
    "MAX_ATTACHMENT_SIZE",
    "MAX_ATTACHMENTS_PER_ENTRY",
]


class SnapshotStorage(
    TokenMethods,
    SnapshotMethods,
    EventMethods,
    AnalysisMethods,
    SmartCaptureMethods,
    CleanupMethods,
    DeviceStorageMethods,
    PwaPushMethods,
    StorageBase,
):
    """Persist DOCSIS analysis snapshots to SQLite."""
