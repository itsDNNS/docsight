import io
import pytest

from app.web import app, init_config, init_storage
from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.modules.bnetz.storage import BnetzStorage


@pytest.fixture
def config_mgr(tmp_path):
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({"modem_password": "test", "modem_type": "fritzbox", "isp_name": "Vodafone"})
    return mgr


@pytest.fixture
def client(config_mgr):
    init_config(config_mgr)
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def sample_analysis():
    return {
        "summary": {
            "ds_total": 33,
            "us_total": 4,
            "ds_power_min": -1.0,
            "ds_power_max": 5.0,
            "ds_power_avg": 2.5,
            "us_power_min": 40.0,
            "us_power_max": 45.0,
            "us_power_avg": 42.5,
            "ds_snr_min": 35.0,
            "ds_snr_avg": 37.0,
            "ds_correctable_errors": 1234,
            "ds_uncorrectable_errors": 56,
            "health": "good",
            "health_issues": [],
            "us_capacity_mbps": 50.0,
        },
        "ds_channels": [{
            "channel_id": 1,
            "frequency": "602 MHz",
            "power": 3.0,
            "snr": 35.0,
            "modulation": "256QAM",
            "correctable_errors": 100,
            "uncorrectable_errors": 5,
            "docsis_version": "3.0",
            "health": "good",
            "health_detail": "",
        }],
        "us_channels": [{
            "channel_id": 1,
            "frequency": "37 MHz",
            "power": 42.0,
            "modulation": "64QAM",
            "multiplex": "ATDMA",
            "docsis_version": "3.0",
            "health": "good",
            "health_detail": "",
        }],
    }


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
def storage_client(tmp_path, config_mgr):
    db_path = str(tmp_path / "test_web.db")
    storage = SnapshotStorage(db_path, max_days=7)
    bnetz_st = BnetzStorage(db_path)
    init_config(config_mgr)
    init_storage(storage)
    import app.modules.bnetz.routes as bnetz_routes
    bnetz_routes._storage = None
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, storage, bnetz_st
    init_storage(None)
    bnetz_routes._storage = None
