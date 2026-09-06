"""Per-request capability gates for optional supporting modules."""

from __future__ import annotations

_MODULE_IDS = {
    "reports": "docsight.reports",
    "evidence": "docsight.evidence",
    "journal": "docsight.journal",
}


def get_capabilities(config_manager, module_loader) -> dict[str, bool]:
    enabled_ids = {
        module.id for module in (module_loader.get_enabled_modules() if module_loader else [])
    }
    result = {
        name: module_id in enabled_ids for name, module_id in _MODULE_IDS.items()
    }
    result["demo_mode"] = bool(
        config_manager and config_manager.is_demo_mode()
    )
    return result
