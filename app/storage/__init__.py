"""SQLite snapshot storage for DOCSIS timeline."""

from __future__ import annotations

from typing import Type

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

_STORAGE_METHOD_GROUPS: tuple[Type[object], ...] = (
    TokenMethods,
    SnapshotMethods,
    EventMethods,
    AnalysisMethods,
    SmartCaptureMethods,
    CleanupMethods,
    DeviceStorageMethods,
    PwaPushMethods,
)


class SnapshotStorage(StorageBase):
    """Persist DOCSIS analysis snapshots to SQLite."""


def _install_storage_methods() -> None:
    for group in _STORAGE_METHOD_GROUPS:
        for name, value in group.__dict__.items():
            if name.startswith("__"):
                continue
            setattr(SnapshotStorage, name, value)


_install_storage_methods()
