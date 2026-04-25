"""SQLite snapshot storage for DOCSIS timeline."""

from .base import StorageBase, ALLOWED_MIME_TYPES, MAX_ATTACHMENT_SIZE, MAX_ATTACHMENTS_PER_ENTRY
from .snapshot import SnapshotMixin
from .events import EventMixin
from .analysis import AnalysisMixin
from .tokens import TokenMixin
from .smart_capture import SmartCaptureMixin
from .cleanup import CleanupMixin
from .device import DeviceStorageMixin

__all__ = [
    "SnapshotStorage",
    "ALLOWED_MIME_TYPES",
    "MAX_ATTACHMENT_SIZE",
    "MAX_ATTACHMENTS_PER_ENTRY",
]


class SnapshotStorage(
    TokenMixin,
    SnapshotMixin,
    EventMixin,
    AnalysisMixin,
    SmartCaptureMixin,
    CleanupMixin,
    DeviceStorageMixin,
    StorageBase,
):
    """Persist DOCSIS analysis snapshots to SQLite."""
    pass
