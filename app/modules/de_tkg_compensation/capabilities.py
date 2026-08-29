"""Per-request capability gates for optional supporting modules."""

from __future__ import annotations

import os


_MODULE_IDS = {
    "reports": "docsight.reports",
    "evidence": "docsight.evidence",
    "journal": "docsight.journal",
    "connection_monitor": "docsight.connection_monitor",
    "bnetz": "docsight.bnetz",
}


def get_capabilities(config_manager, module_loader, *, connection_db_path: str) -> dict[str, bool]:
    enabled_ids = {
        module.id for module in (module_loader.get_enabled_modules() if module_loader else [])
    }
    result = {
        name: module_id in enabled_ids for name, module_id in _MODULE_IDS.items()
    }
    result["connection_monitor_source"] = bool(
        result["connection_monitor"] and os.path.isfile(connection_db_path)
    )
    result["demo_mode"] = bool(
        config_manager and config_manager.is_demo_mode()
    )
    return result
