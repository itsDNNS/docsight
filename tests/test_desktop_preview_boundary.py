from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app import web
from app.config import ConfigManager
from app.runtime import current_runtime


def test_desktop_preview_mode_requires_explicit_env_flag(monkeypatch):
    monkeypatch.delenv("DOCSIGHT_DESKTOP_MODE", raising=False)
    assert web.is_desktop_preview_mode() is False

    monkeypatch.setenv("DOCSIGHT_DESKTOP_MODE", "0")
    assert web.is_desktop_preview_mode() is False

    monkeypatch.setenv("DOCSIGHT_DESKTOP_MODE", "1")
    assert web.is_desktop_preview_mode() is True


@pytest.mark.parametrize(("desktop", "dismissed"), [(False, False), (True, False), (True, True)])
def test_desktop_preview_badge_and_notice_follow_env_flag_and_dismissal(
    tmp_path, monkeypatch, route_app, desktop, dismissed
):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("DOCSIGHT_DESKTOP_MODE", raising=False)
    if desktop:
        monkeypatch.setenv("DOCSIGHT_DESKTOP_MODE", "1")
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({"demo_mode": True, "dismissed_notice_ids": [web.DESKTOP_PREVIEW_NOTICE_ID] if dismissed else []})
    current_runtime().config_manager = manager
    current_runtime().storage = None

    shown = desktop and not dismissed
    notice_id, doc_url = web.DESKTOP_PREVIEW_NOTICE_ID, web.DESKTOP_PREVIEW_DOC_URL
    dismiss = f"[data-action=\"dismissMaintainerNotice\"][data-action-args='[\"{notice_id}\"]']"
    # Each page's own notice: a line that opens the notice center, or a card with its link and dismiss button.
    page_actions = {"/": ['[data-action="openNoticeCenter"]'], "/settings": [dismiss, f'a[href="{doc_url}"]']}
    with route_app.test_client() as client:
        for path, actions in page_actions.items():
            soup = BeautifulSoup(client.get(path).get_data(as_text=True), "html.parser")
            assert (soup.select_one(f'a.desktop-preview-badge-sidebar[href="{doc_url}"]') is not None) is desktop, path
            center = soup.select_one(f'[data-notice-center-item="{notice_id}"]')
            assert (center is not None and center.select_one(f'a[href="{doc_url}"]') is not None) is desktop, path
            assert (center is not None and center.select_one(dismiss) is not None) is shown, path
            # Top bar and sidebar badges, plus the badge on the Settings card while it shows.
            labels = [badge.get_text(strip=True) for badge in soup.select(".desktop-preview-badge, .desktop-preview-notice .badge")]
            assert labels == ["Desktop Preview"] * (2 * desktop + (path == "/settings" and shown)), path
            notice = soup.select_one(f'[data-notice-id="{notice_id}"]')
            assert (notice is not None) is shown, path
            assert notice is None or all(notice.select_one(action) for action in actions), path
