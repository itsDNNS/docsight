"""Snapshot and channel factories owned by modulation engine tests."""


def make_snapshot(timestamp, us_channels=None, ds_channels=None):
    return {
        "timestamp": timestamp,
        "us_channels": us_channels or [],
        "ds_channels": ds_channels or [],
        "summary": {},
    }


def make_channels(modulations, docsis_version="3.0"):
    return [
        {"modulation": modulation, "channel_id": index, "docsis_version": docsis_version}
        for index, modulation in enumerate(modulations)
    ]
