"""E2E tests for the channels view."""

from pathlib import Path

from playwright.sync_api import expect


class TestChannelsView:
    """Channels view navigation and content."""

    def test_switch_to_channels_view(self, demo_page):
        demo_page.locator('.nav-item[data-view="channels"]').click()
        channels = demo_page.locator("#view-channels")
        assert channels.is_visible()

    def test_channels_view_hides_live(self, demo_page):
        demo_page.locator('.nav-item[data-view="channels"]').click()
        live = demo_page.locator("#view-live")
        assert not live.is_visible()

    def test_channels_nav_marked_active(self, demo_page):
        nav = demo_page.locator('.nav-item[data-view="channels"]')
        nav.click()
        assert "active" in nav.get_attribute("class")

    def test_tg_channels_survive_collection_and_rendering(self, vodafone_tg_server, page):
        from app.storage import SnapshotStorage

        page.goto(vodafone_tg_server.base_url)
        downstream = page.locator(".dashboard-channel-panel").filter(
            has=page.locator(".channel-title", has_text="Downstream")
        )
        scqam = downstream.locator(".docsis-group").filter(
            has=page.locator(".docsis-group-header", has_text="DOCSIS 3.0 SC-QAM")
        )
        expect(scqam).to_have_count(1)
        scqam.locator(".docsis-group-header").click()
        rows = scqam.locator("tbody tr")
        expect(rows).to_have_count(2)
        expect(rows.nth(0).locator("td").nth(0)).to_have_text("7")
        expect(rows.nth(0).locator("td").nth(3)).to_have_text("40.0 dB")
        expect(rows.nth(1).locator("td").nth(0)).to_have_text("8")
        expect(rows.nth(1).locator("td").nth(3)).to_have_text("40.5 dB")

        resp = page.request.get(f"{vodafone_tg_server.base_url}/api/channels")
        assert resp.status == 200
        channels = resp.json()
        assert {ch["channel_id"] for ch in channels["ds_channels"]} == {7, 8, 193}
        assert {ch["channel_id"] for ch in channels["us_channels"]} == {6, 41}

        storage = SnapshotStorage(str(Path(vodafone_tg_server.data_dir) / "docsis_history.db"))
        timestamp, = storage.get_snapshot_list()
        raw = storage.get_snapshot_raw_data(timestamp)
        for direction, version, ids in (
            ("channelDs", "docsis30", [7, 8]), ("channelDs", "docsis31", [193]),
            ("channelUs", "docsis30", [6]), ("channelUs", "docsis31", [41]),
        ):
            assert [ch["channelID"] for ch in raw[direction][version]] == ids
