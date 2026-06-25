"""E2E tests for the Modulation Performance module (v2)."""

import pytest
from playwright.sync_api import expect


# ── Navigation ──

class TestModulationNavigation:
    """Sidebar nav → module tab activation."""

    def test_sidebar_has_modulation_link(self, demo_page):
        nav = demo_page.locator('.nav-item[data-view="modulation"]')
        assert nav.count() > 0

    def test_sidebar_link_text(self, demo_page):
        nav = demo_page.locator('.nav-item[data-view="modulation"]')
        text = nav.text_content().strip()
        assert "Modulation" in text

    def test_click_opens_modulation_view(self, demo_page):
        demo_page.locator('.nav-item[data-view="modulation"]').click()
        view = demo_page.locator("#view-modulation")
        expect(view).to_be_visible()

    def test_modulation_nav_marked_active(self, demo_page):
        demo_page.locator('.nav-item[data-view="modulation"]').click()
        nav = demo_page.locator('.nav-item[data-view="modulation"]')
        assert "active" in nav.get_attribute("class")

    def test_live_view_hidden_when_modulation_active(self, demo_page):
        demo_page.locator('.nav-item[data-view="modulation"]').click()
        live = demo_page.locator("#view-dashboard")
        expect(live).not_to_be_visible()

    def test_switch_back_to_live(self, demo_page):
        demo_page.locator('.nav-item[data-view="modulation"]').click()
        demo_page.locator('.nav-item[data-view="live"]').click()
        live = demo_page.locator("#view-dashboard")
        expect(live).to_be_visible()

    def test_hash_routing(self, page, live_server):
        page.goto(f"{live_server}#modulation")
        page.wait_for_load_state("networkidle")
        view = page.locator("#view-modulation")
        expect(view).to_be_visible()

    def test_home_hides_modulation_context_when_family_kpis_render(self, demo_page):
        expect(demo_page.locator(".hero-modulation-context")).to_have_count(0)
        expect(demo_page.locator("#metric-ds-sc-qam-power-card")).to_be_visible()
        expect(demo_page.locator("#metric-ds-ofdm-power-card")).to_be_visible()
        expect(demo_page.locator("#metric-us-sc-qam-card")).to_be_visible()
        expect(demo_page.locator("#metric-us-ofdma-card")).to_be_visible()

        demo_page.locator('.nav-item[data-view="modulation"]').click()

        expect(demo_page.locator("#view-modulation")).to_be_visible()

    def test_home_family_kpis_include_modulation_context_inline(self, demo_page):
        for card_id, label in [
            ("metric-ds-sc-qam-power-card", "DS POWER (SC-QAM)"),
            ("metric-ds-ofdm-power-card", "DS POWER (OFDM)"),
            ("metric-ds-sc-qam-snr-card", "DS SNR (SC-QAM)"),
            ("metric-ds-ofdm-mer-card", "DS MER (OFDM)"),
            ("metric-us-sc-qam-card", "US POWER (SC-QAM)"),
            ("metric-us-ofdma-card", "US POWER (OFDMA)"),
        ]:
            card = demo_page.locator(f"#{card_id}")
            expect(card).to_be_visible()
            expect(card).to_contain_text(label)
            modulation_row = card.locator(".metric-modulation-row")
            expect(modulation_row).to_be_visible()
            expect(modulation_row.locator(".badge")).to_have_count(0)
            expect(modulation_row.locator(".metric-sub-label")).to_have_text("Modulation:")
            value = modulation_row.locator(".range")
            expect(value).to_contain_text("QAM")
            expect(value).not_to_contain_text("Modulation:")

    def test_home_family_kpis_share_hero_without_modulation_card(self, page, live_server):
        page.set_viewport_size({"width": 1280, "height": 900})
        page.goto(live_server)
        page.wait_for_load_state("networkidle")

        visual = page.locator(".hero-visual-row")
        health = page.locator(".hero-channel-health")
        chart = page.locator(".hero-chart-wrap")
        expect(visual).to_be_visible()
        expect(health).to_be_visible()
        expect(chart).to_be_visible()
        expect(page.locator(".hero-modulation-context")).to_have_count(0)

        layout = page.evaluate(
            """
            () => {
                const rect = (selector) => {
                    const r = document.querySelector(selector).getBoundingClientRect();
                    return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height};
                };
                return {
                    visual: rect('.hero-visual-row'),
                    health: rect('.hero-channel-health'),
                    chart: rect('.hero-chart-wrap'),
                    gridColumns: getComputedStyle(document.querySelector('.hero-visual-row')).gridTemplateColumns,
                };
            }
            """
        )

        assert layout["gridColumns"].count("px") >= 2
        assert layout["health"]["right"] <= layout["chart"]["left"] + 1
        assert abs(layout["health"]["top"] - layout["chart"]["top"]) <= 16
        assert layout["visual"]["height"] <= 360

    def test_home_hero_stacks_without_modulation_card_overflow(self, page, live_server):
        for width in (393, 760, 1100):
            page.set_viewport_size({"width": width, "height": 900})
            page.goto(live_server)
            page.wait_for_load_state("networkidle")

            layout = page.evaluate(
                """
                () => {
                    const rect = (selector) => {
                        const r = document.querySelector(selector).getBoundingClientRect();
                        return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height};
                    };
                    return {
                        overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                        health: rect('.hero-channel-health'),
                        chart: rect('.hero-chart-wrap'),
                        contextCount: document.querySelectorAll('.hero-modulation-context').length,
                        gridColumns: getComputedStyle(document.querySelector('.hero-visual-row')).gridTemplateColumns,
                    };
                }
                """
            )

            assert layout["overflowX"] <= 1
            assert layout["contextCount"] == 0
            assert layout["gridColumns"].count("px") == 1
            assert layout["chart"]["bottom"] <= layout["health"]["top"] + 1


# ── Tab Structure ──

class TestModulationTabStructure:
    """Template elements present after tab activation."""

    @pytest.fixture(autouse=True)
    def navigate_to_modulation(self, demo_page):
        demo_page.locator('.nav-item[data-view="modulation"]').click()
        demo_page.wait_for_timeout(500)
        self.page = demo_page

    def test_has_title(self):
        title = self.page.locator("#view-modulation h2")
        assert title.count() > 0
        assert "Modulation" in title.text_content()

    def test_direction_tabs_present(self):
        tabs = self.page.locator("#modulation-direction-tabs .trend-tab")
        assert tabs.count() == 2

    def test_us_tab_active_by_default(self):
        us = self.page.locator('#modulation-direction-tabs .trend-tab[data-dir="us"]')
        assert "active" in us.get_attribute("class")

    def test_ds_tab_not_active_by_default(self):
        ds = self.page.locator('#modulation-direction-tabs .trend-tab[data-dir="ds"]')
        assert "active" not in ds.get_attribute("class")

    def test_range_tabs_present(self):
        tabs = self.page.locator("#modulation-range-tabs .trend-tab")
        assert tabs.count() == 3

    def test_7days_active_by_default(self):
        tab7 = self.page.locator('#modulation-range-tabs .trend-tab[data-days="7"]')
        assert "active" in tab7.get_attribute("class")

    def test_kpi_cards_present(self):
        cards = self.page.locator(".mod-kpi-item")
        assert cards.count() == 3

    def test_overview_container_present(self):
        overview = self.page.locator("#modulation-overview")
        expect(overview).to_be_visible()

    def test_intraday_container_hidden(self):
        intraday = self.page.locator("#modulation-intraday")
        expect(intraday).not_to_be_visible()


# ── Controls ──

class TestModulationControls:
    """Direction and range toggle interaction."""

    @pytest.fixture(autouse=True)
    def navigate_to_modulation(self, demo_page):
        demo_page.locator('.nav-item[data-view="modulation"]').click()
        demo_page.wait_for_function(
            "() => (window._modCharts || []).length > 0",
            timeout=150_000,
        )
        self.page = demo_page

    def test_switch_to_ds(self):
        ds = self.page.locator('#modulation-direction-tabs .trend-tab[data-dir="ds"]')
        ds.click()
        self.page.wait_for_timeout(300)
        assert "active" in ds.get_attribute("class")
        us = self.page.locator('#modulation-direction-tabs .trend-tab[data-dir="us"]')
        assert "active" not in us.get_attribute("class")

    def test_switch_to_today(self):
        today = self.page.locator('#modulation-range-tabs .trend-tab[data-days="1"]')
        today.click()
        self.page.wait_for_timeout(300)
        assert "active" in today.get_attribute("class")

    def test_switch_to_30_days(self):
        d30 = self.page.locator('#modulation-range-tabs .trend-tab[data-days="30"]')
        d30.click()
        self.page.wait_for_timeout(300)
        assert "active" in d30.get_attribute("class")

    def test_30_day_charts_bound_x_axis_labels(self):
        d30 = self.page.locator('#modulation-range-tabs .trend-tab[data-days="30"]')
        d30.click()
        self.page.wait_for_function(
            """
            () => (window._modCharts || []).some((chart) => {
                const samples = chart.data && chart.data[0] ? chart.data[0].length : 0;
                return samples >= 30;
            })
            """,
            timeout=150_000,
        )

        chart_tick_counts = self.page.evaluate(
            """
            () => (window._modCharts || []).map((chart) => {
                const samples = chart.data && chart.data[0] ? chart.data[0].length : 0;
                const axis = chart.axes && chart.axes[0];
                const ticks = axis && axis.splits ? axis.splits(chart).length : 0;
                return {samples, ticks};
            })
            """
        )

        dense_charts = [item for item in chart_tick_counts if item["samples"] >= 30]
        assert dense_charts, f"Expected 30-day charts, got {chart_tick_counts}"
        for item in dense_charts:
            assert item["ticks"] < item["samples"], item
            assert item["ticks"] <= 8, item

    def test_switch_direction_then_back(self):
        ds = self.page.locator('#modulation-direction-tabs .trend-tab[data-dir="ds"]')
        us = self.page.locator('#modulation-direction-tabs .trend-tab[data-dir="us"]')
        ds.click()
        self.page.wait_for_timeout(200)
        us.click()
        self.page.wait_for_timeout(200)
        assert "active" in us.get_attribute("class")
        assert "active" not in ds.get_attribute("class")

    def test_today_shows_intraday(self):
        today = self.page.locator('#modulation-range-tabs .trend-tab[data-days="1"]')
        today.click()
        self.page.wait_for_timeout(1000)
        intraday = self.page.locator("#modulation-intraday")
        expect(intraday).to_be_visible()
        overview = self.page.locator("#modulation-overview")
        expect(overview).not_to_be_visible()

    def test_capacity_panel_updates_for_selected_range_and_today(self):
        panel = self.page.locator("#modulation-capacity-panel")
        expect(panel).to_be_visible()
        expect(self.page.locator("#mod-capacity-range-label")).to_contain_text("7d")
        expect(self.page.locator("#mod-cap-ds-min")).to_contain_text("Mbps")
        expect(self.page.locator("#mod-cap-us-tariff")).not_to_have_text("—")

        today = self.page.locator('#modulation-range-tabs .trend-tab[data-days="1"]')
        today.click()
        self.page.wait_for_timeout(1000)
        expect(panel).to_be_visible()
        expect(self.page.locator("#mod-capacity-range-label")).to_contain_text("Selected day")


# ── API Integration ──

class TestModulationAPI:
    """API endpoints return valid data through the live server."""

    def test_distribution_api_returns_200(self, live_server, page):
        resp = page.request.get(f"{live_server}/api/modulation/distribution")
        assert resp.status == 200

    def test_distribution_api_returns_json(self, live_server, page):
        resp = page.request.get(f"{live_server}/api/modulation/distribution")
        data = resp.json()
        assert "direction" in data
        assert "protocol_groups" in data
        assert "aggregate" in data

    def test_distribution_api_has_protocol_groups(self, live_server, page):
        resp = page.request.get(f"{live_server}/api/modulation/distribution")
        data = resp.json()
        groups = data.get("protocol_groups", [])
        if groups:
            pg = groups[0]
            assert "docsis_version" in pg
            assert "max_qam" in pg
            assert "health_index" in pg
            assert "days" in pg

    def test_distribution_api_direction_param(self, live_server, page):
        resp = page.request.get(f"{live_server}/api/modulation/distribution?direction=ds")
        data = resp.json()
        assert data["direction"] == "ds"

    def test_distribution_api_has_disclaimer(self, live_server, page):
        resp = page.request.get(f"{live_server}/api/modulation/distribution")
        data = resp.json()
        assert "disclaimer" in data

    def test_intraday_api_returns_200(self, live_server, page):
        resp = page.request.get(f"{live_server}/api/modulation/intraday")
        assert resp.status == 200

    def test_intraday_api_returns_json(self, live_server, page):
        resp = page.request.get(f"{live_server}/api/modulation/intraday")
        data = resp.json()
        assert "direction" in data
        assert "date" in data
        assert "protocol_groups" in data

    def test_trend_api_returns_200(self, live_server, page):
        resp = page.request.get(f"{live_server}/api/modulation/trend")
        assert resp.status == 200

    def test_trend_api_returns_list(self, live_server, page):
        resp = page.request.get(f"{live_server}/api/modulation/trend")
        data = resp.json()
        assert isinstance(data, list)


# ── KPI Card Behavior ──

class TestModulationKPIs:
    """KPI cards update with data after tab loads."""

    @pytest.fixture(autouse=True)
    def navigate_to_modulation(self, demo_page):
        demo_page.locator('.nav-item[data-view="modulation"]').click()
        demo_page.wait_for_timeout(1500)
        self.page = demo_page

    def test_health_index_populated(self):
        val = self.page.locator("#mod-kpi-health")
        text = val.text_content().strip()
        assert text != "" and text is not None

    def test_lowqam_populated(self):
        val = self.page.locator("#mod-kpi-lowqam")
        text = val.text_content().strip()
        assert text != "" and text is not None

    def test_density_populated(self):
        val = self.page.locator("#mod-kpi-density")
        text = val.text_content().strip()
        assert text != "" and text is not None

    def test_health_has_color_class(self):
        val = self.page.locator("#mod-kpi-health")
        cls = val.get_attribute("class") or ""
        text = val.text_content().strip()
        if text != "\u2014":
            assert "good" in cls or "warning" in cls or "critical" in cls


# ── Protocol Groups ──

class TestProtocolGroups:
    """Protocol group sections rendered after data load."""

    @pytest.fixture(autouse=True)
    def navigate_to_modulation(self, demo_page):
        demo_page.locator('.nav-item[data-view="modulation"]').click()
        demo_page.locator(".mod-protocol-group").first.wait_for(
            state="visible",
            timeout=150_000,
        )
        self.page = demo_page

    def test_protocol_groups_rendered(self):
        groups = self.page.locator(".mod-protocol-group")
        assert groups.count() >= 1

    def test_group_has_header(self):
        headers = self.page.locator(".mod-protocol-group-header")
        assert headers.count() >= 1

    def test_group_has_kpi_row(self):
        rows = self.page.locator(".mod-group-kpi-row")
        assert rows.count() >= 1

    def test_group_has_charts(self):
        canvases = self.page.locator("[id^='mod-dist-chart-']")
        assert canvases.count() >= 1

    def test_disclaimer_visible(self):
        disclaimer = self.page.locator("#mod-disclaimer")
        expect(disclaimer).to_be_visible()

    def test_upstream_protocol_groups_have_context_specific_legend_hints(self, live_server):
        resp = self.page.request.get(f"{live_server}/api/modulation/distribution?direction=us&days=7")
        groups = resp.json().get("protocol_groups", [])
        has_us_docsis31 = any(str(group.get("docsis_version")) == "3.1" for group in groups)
        has_us_docsis30 = any(str(group.get("docsis_version")) == "3.0" for group in groups)
        if not (has_us_docsis31 or has_us_docsis30):
            pytest.skip("Demo data has no US DOCSIS 3.0 or 3.1 protocol group")

        if has_us_docsis31:
            us_d31_group = self.page.locator(
                '.mod-protocol-group[data-direction="us"][data-docsis-version="3.1"]'
            ).first
            expect(
                us_d31_group.locator(".modulation-custom-legend-hint").filter(
                    has_text="US DOCSIS 3.1 upstream"
                )
            ).to_be_visible()

        if has_us_docsis30:
            us_d30_group = self.page.locator(
                '.mod-protocol-group[data-direction="us"][data-docsis-version="3.0"]'
            ).first
            expect(
                us_d30_group.locator(".modulation-custom-legend-hint").filter(
                    has_text="US DOCSIS 3.0 upstream"
                )
            ).to_be_visible()

        self.page.locator('#modulation-direction-tabs .trend-tab[data-dir="ds"]').click()
        self.page.wait_for_timeout(1500)
        expect(self.page.locator(".modulation-custom-legend-hint")).to_have_count(0)


# ── No Console Errors ──

class TestNoConsoleErrors:
    """Module should not produce JS errors."""

    def test_no_errors_on_load(self, page, live_server):
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(f"{live_server}#modulation")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        assert len(errors) == 0, f"JS errors: {errors}"
