"""E2E tests for the channels view."""

from pathlib import Path

from playwright.sync_api import expect
from tests.e2e.support.navigation import open_view


class TestChannelsView:
    """Channels view navigation and content."""

    def test_switch_to_channels_view(self, demo_page):
        open_view(demo_page, "channels")
        channels = demo_page.locator("#view-channels")
        assert channels.is_visible()

    def test_channels_view_hides_live(self, demo_page):
        open_view(demo_page, "channels")
        live = demo_page.locator("#view-live")
        assert not live.is_visible()

    def test_channels_nav_marked_active(self, demo_page):
        open_view(demo_page, "channels")
        nav = demo_page.locator('.nav-item[data-view="channels"]')
        assert "active" in nav.get_attribute("class")

    def test_tg_channels_survive_collection_and_rendering(self, vodafone_tg_server, page):
        from app.storage import SnapshotStorage

        page.goto(vodafone_tg_server.base_url + "/#channels")
        downstream = page.locator("#view-channels .dashboard-channel-panel").filter(
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


class TestChannelStatusMatrix:
    """Status mode: channels x time cells, aggregated stable channels, row opens charts."""

    def _open(self, page):
        open_view(page, "channels")
        page.wait_for_selector("#channel-status-body .cs-direction")

    def test_status_is_the_default_mode(self, demo_page):
        self._open(demo_page)

        expect(demo_page.locator('#channel-mode-tabs .segmented-option.active')).to_have_attribute("data-value", "status")
        expect(demo_page.locator("#channel-panel-status")).to_be_visible()
        expect(demo_page.locator("#channel-panel-timeline")).to_be_hidden()
        assert "mode=status" in demo_page.evaluate("location.hash")
        cells = demo_page.locator("#channel-status-body .cs-row").first.locator(".cs-cell")
        expect(cells).to_have_count(48)
        expect(demo_page.locator("#channel-status-window")).to_contain_text("30 min")

    def test_every_current_channel_is_listed_once(self, demo_page):
        self._open(demo_page)
        channels = demo_page.request.get(demo_page.url.split("#")[0] + "api/channels").json()

        for direction, key in (("ds", "ds_channels"), ("us", "us_channels")):
            section = demo_page.locator(f'.cs-direction[data-direction="{direction}"]')
            listed = section.locator(".cs-row:not(.cs-aggregate)")
            expect(listed).to_have_count(len(channels[key]))

    def test_aggregated_row_expands_the_stable_channels(self, demo_page):
        self._open(demo_page)
        aggregate = demo_page.locator(".cs-aggregate").first
        others = demo_page.locator("#" + aggregate.get_attribute("aria-controls"))

        expect(others).to_be_hidden()
        aggregate.click()
        expect(aggregate).to_have_attribute("aria-expanded", "true")
        expect(others).to_be_visible()
        assert others.locator(".cs-row").count() > 0
        aggregate.click()
        expect(others).to_be_hidden()

    def test_row_opens_the_channel_timeline_with_the_same_range(self, demo_page):
        self._open(demo_page)
        demo_page.locator('#channel-status-time-tabs .segmented-option[data-value="6h"]').click()
        expect(demo_page.locator('#channel-status-time-tabs .segmented-option.active')).to_have_attribute("data-value", "6h")
        demo_page.wait_for_selector("#channel-status-body .cs-direction")
        assert "range=6h" in demo_page.evaluate("location.hash")

        aggregate = demo_page.locator(".cs-aggregate").first
        aggregate.click()
        row = demo_page.locator("#" + aggregate.get_attribute("aria-controls") + " .cs-row").first
        direction = row.get_attribute("data-direction")
        channel = row.get_attribute("data-channel-id")
        row.click()

        expect(demo_page.locator('#channel-mode-tabs .segmented-option.active')).to_have_attribute("data-value", "timeline")
        expect(demo_page.locator("#channel-panel-timeline")).to_be_visible()
        expect(demo_page.locator("#channel-select")).to_have_value(f"{direction}-{channel}")
        expect(demo_page.locator('#channel-time-tabs .segmented-option.active')).to_have_attribute("data-value", "6h")
        demo_page.wait_for_selector("#chart-ch-power .uplot canvas, #channel-charts canvas")
        hash_value = demo_page.evaluate("location.hash")
        assert f"mode=timeline&dir={direction}&channel={channel}&range=6h" in hash_value

    def test_status_deep_link_restores_the_range(self, demo_page):
        base = demo_page.url.split("#")[0]
        demo_page.goto(base + "#channels?mode=status&range=7d")
        demo_page.wait_for_selector("#channel-status-body .cs-direction")

        expect(demo_page.locator('#channel-status-time-tabs .segmented-option.active')).to_have_attribute("data-value", "7d")
        expect(demo_page.locator("#channel-status-window")).to_contain_text("3.5 h")

    def test_current_value_tables_live_on_the_channels_page(self, demo_page):
        expect(demo_page.locator("#view-dashboard .dashboard-channel-panel")).to_have_count(0)
        self._open(demo_page)
        expect(demo_page.locator("#view-channels .dashboard-channel-panel")).to_have_count(2)

    def test_home_links_to_all_channels(self, demo_page):
        demo_page.locator('.line-status-actions a[href="#channels?mode=status"]').click()
        demo_page.wait_for_selector("#channel-status-body .cs-direction")
        expect(demo_page.locator("#view-channels")).to_be_visible()
