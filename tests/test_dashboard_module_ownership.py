"""Enabled modules own their complete dashboard surface."""

from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from app.runtime import get_runtime


ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    "journal": ("entry-modal", "incident-container-modal", "import-modal"),
    "bqm": ("bqm-import-modal", "bqm-setup-modal"),
    "speedtest": ("speedtest-setup-modal",),
}


@pytest.fixture
def dashboard(make_config, make_app, builtin_module_loader_factory):
    def build(disabled="", configured=True):
        manager = make_config({
            "modem_type": "fritzbox", "modem_password": "test",
            "disabled_modules": disabled,
            "bqm_url": "https://www.thinkbroadband.com/broadband/monitoring/quality/share/abc.csv" if configured else "",
            "speedtest_tracker_url": "http://localhost:8999" if configured else "",
            "speedtest_tracker_token": "test" if configured else "",
        })
        app = make_app(config_manager=manager,
                       module_loader_factory=builtin_module_loader_factory(manager))
        assert not [m.error for m in get_runtime(app).module_loader.get_modules() if m.error]
        return app.test_client()
    return build


@pytest.mark.parametrize("prefix", ["", "/docsight"])
@pytest.mark.parametrize("name", MODULES)
def test_disabled_module_delivers_no_ui_or_script(dashboard, name, prefix):
    client = dashboard(disabled=f"docsight.{name}")
    env = {"SCRIPT_NAME": prefix}
    for page in ("/", "/settings"):
        response = client.get(page, environ_overrides=env)
        assert response.status_code == 200
        soup = BeautifulSoup(response.data, "html.parser")
        assert soup.select_one(f"#view-{name}") is None
        assert soup.select_one(f'.nav-item[data-view="{name}"]') is None
        assert soup.select_one(f'.nav-item[onclick="open{name.title()}SetupModal()"]') is None
        for dialog in MODULES[name]:
            assert soup.select_one(f"#{dialog}") is None
        assert not soup.select(f'script[src*="/modules/docsight.{name}/static/main.js"]')
        assert not soup.select(f'script[src*="/static/js/{name}.js"]')
    assert client.get(f"/modules/docsight.{name}/static/main.js", environ_overrides=env).status_code == 404


@pytest.mark.parametrize("prefix", ["", "/docsight"])
def test_configured_modules_render_once_with_versioned_scripts(dashboard, prefix):
    client = dashboard()
    for page in ("/", "/settings"):
        response = client.get(page, environ_overrides={"SCRIPT_NAME": prefix})
        assert response.status_code == 200
        soup = BeautifulSoup(response.data, "html.parser")
        scripts = [tag["src"] for tag in soup.select("script[src]")]
        for name, dialogs in MODULES.items():
            urls = [url for url in scripts if f"/modules/docsight.{name}/static/main.js" in url]
            assert len(urls) == 1
            assert urls[0].startswith(prefix + "/modules/") and "?v=" in urls[0]
            assert client.get(urls[0].removeprefix(prefix)).status_code == 200
            assert not (ROOT / f"app/static/js/{name}.js").exists()
            assert client.get(f"/static/js/{name}.js").status_code == 404
            if page == "/":
                assert len(soup.select(f".main-content > #view-{name}")) == 1
                for dialog in dialogs:
                    elements = soup.select(f"#{dialog}")
                    assert len(elements) == 1
                    assert elements[0].find_parent(class_="view") is None
        if page == "/":
            positions = lambda path: next(i for i, url in enumerate(scripts) if path in url)
            assert positions("js/dashboard.js") < positions("docsight.bqm/static/js/bqm-chart.js") < positions("docsight.bqm/static/main.js") < positions("js/dashboard-routing.js")
            assert soup.select_one("#view-bqm #bqm-csv-import-section") is not None
            assert soup.select_one("#view-correlation") is not None


@pytest.mark.parametrize("prefix", ["", "/docsight"])
def test_unconfigured_modules_keep_setup_without_empty_views(dashboard, prefix):
    response = dashboard(configured=False).get(
        "/", environ_overrides={"SCRIPT_NAME": prefix}
    )
    soup = BeautifulSoup(response.data, "html.parser")
    for name, hook in (("bqm", "Bqm"), ("speedtest", "Speedtest")):
        assert soup.select_one(f"#view-{name}") is None
        assert soup.select_one(f"#{name}-setup-modal") is not None
        assert soup.select_one(f'.nav-item[onclick="open{hook}SetupModal()"]') is not None
        script = soup.select_one(
            f'script[src*="/modules/docsight.{name}/static/main.js?v="]'
        )
        assert script is not None
        assert script["src"].startswith(prefix + "/modules/")


def test_module_asset_cache_generation():
    assert (ROOT / "app/static/sw.js").read_text().startswith("var CACHE_VERSION = 'v89';")
