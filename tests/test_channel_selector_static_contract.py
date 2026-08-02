from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHANNELS_JS = ROOT / "app" / "static" / "js" / "channels.js"


def test_channel_frontend_has_one_selector_reference_decoder():
    source = CHANNELS_JS.read_text(encoding="utf-8")

    assert source.count("function _readChannelSelection(") == 1
    assert "selector=" in source
    assert "selectors=" in source
    assert "dataset.selector" in source


def test_compare_identity_is_not_deduplicated_by_modem_channel_id():
    source = CHANNELS_JS.read_text(encoding="utf-8")

    assert "c.key === ref.key" in source
    assert "removeCompareChannel(ch.key)" in source
