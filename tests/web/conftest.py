import pytest

from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.modules.bnetz.storage import BnetzStorage
from app.runtime import get_runtime


@pytest.fixture
def config_mgr(tmp_path):
    data_dir = str(tmp_path / "web-default-data")
    mgr = ConfigManager(data_dir)
    mgr.save({"modem_password": "test", "modem_type": "fritzbox", "isp_name": "Vodafone"})
    return mgr


@pytest.fixture
def app(route_app):
    return route_app


@pytest.fixture(autouse=True)
def _app_context(app, config_mgr):
    get_runtime(app).config_manager = config_mgr
    with app.app_context():
        yield


@pytest.fixture
def client(app):
    with app.app_context(), app.test_client() as client:
        yield client


@pytest.fixture
def no_docsis_analysis():
    return {
        "summary": {
            "ds_total": 0, "us_total": 0,
            "ds_power_min": 0, "ds_power_max": 0, "ds_power_avg": 0,
            "us_power_min": 0, "us_power_max": 0, "us_power_avg": 0,
            "ds_snr_min": 0, "ds_snr_avg": 0, "ds_snr_max": 0,
            "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0,
            "ds_uncorr_pct": 0,
            "health": "good", "health_issues": [],
            "us_capacity_mbps": 0,
        },
        "ds_channels": [],
        "us_channels": [],
    }


@pytest.fixture
def storage_client(tmp_path, app):
    db_path = str(tmp_path / "test_web.db")
    storage = SnapshotStorage(db_path, max_days=7)
    bnetz_st = BnetzStorage(db_path)
    get_runtime(app).storage = storage
    with app.app_context(), app.test_client() as client:
        yield client, storage, bnetz_st
