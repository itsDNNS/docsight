"""Tests for the shared Arris HTML channel-table parser."""


from app.drivers.formats.html_rows import (
    _arris_tables,
    _optional_value,
    parse_arris_downstream,
    parse_arris_html,
    parse_arris_upstream,
)
from bs4 import BeautifulSoup
import pytest


# ---------------------------------------------------------------------------
# Helpers to build HTML fragments
# ---------------------------------------------------------------------------

def _make_ds_row(channel_id, lock, modulation, freq, power, snr, corr, uncorr):
    return (
        f"<tr>"
        f"<td>{channel_id}</td><td>{lock}</td><td>{modulation}</td>"
        f"<td>{freq}</td><td>{power}</td><td>{snr}</td>"
        f"<td>{corr}</td><td>{uncorr}</td>"
        f"</tr>"
    )


def _make_us_row(channel, channel_id, lock, ch_type, freq, width, power):
    return (
        f"<tr>"
        f"<td>{channel}</td><td>{channel_id}</td><td>{lock}</td>"
        f"<td>{ch_type}</td><td>{freq}</td><td>{width}</td>"
        f"<td>{power}</td>"
        f"</tr>"
    )


def _wrap_ds_table(*rows):
    header = (
        '<tr><th colspan="8"><strong>Downstream Bonded Channels</strong></th></tr>'
        "<tr><th>Channel ID</th><th>Lock Status</th><th>Modulation</th>"
        "<th>Frequency</th><th>Power</th><th>SNR/MER</th>"
        "<th>Corrected</th><th>Uncorrectables</th></tr>"
    )
    return f"<table>{header}{''.join(rows)}</table>"


def _wrap_us_table(*rows):
    header = (
        '<tr><th colspan="7"><strong>Upstream Bonded Channels</strong></th></tr>'
        "<tr><th>Channel</th><th>Channel ID</th><th>Lock Status</th>"
        "<th>US Channel Type</th><th>Frequency</th><th>Width</th>"
        "<th>Power</th></tr>"
    )
    return f"<table>{header}{''.join(rows)}</table>"


def _full_page(*tables):
    return f"<html><body>{''.join(tables)}</body></html>"


SCQAM_DS_ROW = _make_ds_row("1", "Locked", "256QAM", "705000000 Hz", "8.2 dBmV", "43.0 dB", "100", "5")


# ---------------------------------------------------------------------------
# _optional_value
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8.2 dBmV", 8.2),
        ("43.0 dB", 43.0),
        ("-1.5 dBmV", -1.5),
        ("", None),
        (None, None),
        ("N/A", None),
        ("10 dBmV", 10.0),
    ],
)
def test_optional_value(raw, expected):
    assert _optional_value(raw) == expected


# ---------------------------------------------------------------------------
# _arris_tables
# ---------------------------------------------------------------------------

class TestFindChannelTables:
    def test_both_tables_found(self):
        html = _full_page(
            _wrap_ds_table(),
            _wrap_us_table(),
        )
        soup = BeautifulSoup(html, "html.parser")
        ds, us = _arris_tables(soup)
        assert ds is not None
        assert us is not None

    def test_no_tables(self):
        soup = BeautifulSoup("<html><body></body></html>", "html.parser")
        ds, us = _arris_tables(soup)
        assert ds is None
        assert us is None

    def test_only_downstream(self):
        html = _full_page(_wrap_ds_table())
        soup = BeautifulSoup(html, "html.parser")
        ds, us = _arris_tables(soup)
        assert ds is not None
        assert us is None


# ---------------------------------------------------------------------------
# parse_arris_downstream
# ---------------------------------------------------------------------------

class TestParseDownstream:
    def test_scqam_channel(self):
        table = BeautifulSoup(_wrap_ds_table(SCQAM_DS_ROW), "html.parser").find("table")
        ds30, ds31 = parse_arris_downstream(table).value
        assert len(ds30) == 1
        assert len(ds31) == 0
        ch = ds30[0]
        assert ch["channelID"] == 1
        assert ch["frequency"] == "705 MHz"
        assert ch["powerLevel"] == 8.2
        assert ch["modulation"] == "256QAM"
        assert ch["mer"] == 43.0
        assert ch["mse"] == -43.0
        assert ch["corrErrors"] == 100
        assert ch["nonCorrErrors"] == 5

    def test_ofdm_channel(self):
        row = _make_ds_row(
            "33", "Locked", "Other", "722000000 Hz",
            "10.0 dBmV", "38.5 dB", "200", "10",
        )
        table = BeautifulSoup(_wrap_ds_table(row), "html.parser").find("table")
        ds30, ds31 = parse_arris_downstream(table).value
        assert len(ds30) == 0
        assert len(ds31) == 1
        ch = ds31[0]
        assert ch["channelID"] == 33
        assert ch["type"] == "OFDM"
        assert ch["modulation"] == "Other"
        assert ch["mer"] == 38.5
        assert ch["mse"] is None

    def test_unlocked_skipped(self):
        row = _make_ds_row(
            "2", "Not Locked", "256QAM", "711000000 Hz",
            "0.0 dBmV", "0.0 dB", "0", "0",
        )
        table = BeautifulSoup(_wrap_ds_table(row), "html.parser").find("table")
        ds30, ds31 = parse_arris_downstream(table).value
        assert len(ds30) == 0
        assert len(ds31) == 0

    def test_none_table(self):
        ds30, ds31 = parse_arris_downstream(None).value
        assert ds30 == []
        assert ds31 == []

    def test_mixed_channels(self):
        rows = [
            _make_ds_row("1", "Locked", "256QAM", "705000000 Hz", "8.0 dBmV", "40.0 dB", "10", "1"),
            _make_ds_row("2", "Locked", "64QAM", "711000000 Hz", "7.0 dBmV", "39.0 dB", "20", "2"),
            _make_ds_row("33", "Locked", "Other", "722000000 Hz", "10.0 dBmV", "38.0 dB", "30", "3"),
            _make_ds_row("3", "Not Locked", "256QAM", "717000000 Hz", "0.0 dBmV", "0.0 dB", "0", "0"),
        ]
        table = BeautifulSoup(_wrap_ds_table(*rows), "html.parser").find("table")
        ds30, ds31 = parse_arris_downstream(table).value
        assert len(ds30) == 2
        assert len(ds31) == 1
        assert ds30[0]["channelID"] == 1
        assert ds30[1]["channelID"] == 2
        assert ds31[0]["channelID"] == 33

    def test_short_row_skipped(self):
        """Rows with fewer than 8 columns are ignored."""
        short_row = "<tr><td>1</td><td>Locked</td><td>256QAM</td></tr>"
        table = BeautifulSoup(_wrap_ds_table(short_row), "html.parser").find("table")
        ds30, ds31 = parse_arris_downstream(table).value
        assert len(ds30) == 0
        assert len(ds31) == 0

    @pytest.mark.parametrize("marker", ["<th>Header</th>", "<td><strong>Header</strong></td>"])
    def test_header_row_skipped(self, marker):
        """A full-width row marked as a header is not parsed as a channel."""
        table = BeautifulSoup(_wrap_ds_table(SCQAM_DS_ROW.replace("</tr>", f"{marker}</tr>")), "html.parser").find("table")
        assert parse_arris_downstream(table).value == ([], [])


# ---------------------------------------------------------------------------
# parse_arris_upstream
# ---------------------------------------------------------------------------

class TestParseUpstream:
    def test_scqam_channel(self):
        row = _make_us_row(
            "1", "5", "Locked", "SC-QAM Upstream",
            "38596000 Hz", "6400000 Hz", "45.0 dBmV",
        )
        table = BeautifulSoup(_wrap_us_table(row), "html.parser").find("table")
        us30, us31 = parse_arris_upstream(table).value
        assert len(us30) == 1
        assert len(us31) == 0
        ch = us30[0]
        assert ch["channelID"] == 5
        assert ch["frequency"] == "38.6 MHz"
        assert ch["powerLevel"] == 45.0
        assert ch["modulation"] == "SC-QAM Upstream"
        assert ch["multiplex"] == "SC-QAM"

    def test_ofdma_channel(self):
        row = _make_us_row(
            "5", "9", "Locked", "OFDM Upstream",
            "27600000 Hz", "47200000 Hz", "40.0 dBmV",
        )
        table = BeautifulSoup(_wrap_us_table(row), "html.parser").find("table")
        us30, us31 = parse_arris_upstream(table).value
        assert len(us30) == 0
        assert len(us31) == 1
        ch = us31[0]
        assert ch["channelID"] == 9
        assert ch["type"] == "OFDMA"
        assert ch["multiplex"] == ""

    def test_unlocked_skipped(self):
        row = _make_us_row(
            "2", "6", "Not Locked", "SC-QAM Upstream",
            "0 Hz", "0 Hz", "0.0 dBmV",
        )
        table = BeautifulSoup(_wrap_us_table(row), "html.parser").find("table")
        us30, us31 = parse_arris_upstream(table).value
        assert len(us30) == 0
        assert len(us31) == 0

    def test_none_table(self):
        us30, us31 = parse_arris_upstream(None).value
        assert us30 == []
        assert us31 == []

    def test_mixed_channels(self):
        rows = [
            _make_us_row("1", "5", "Locked", "SC-QAM Upstream", "38596000 Hz", "6400000 Hz", "45.0 dBmV"),
            _make_us_row("2", "6", "Locked", "SC-QAM Upstream", "30596000 Hz", "6400000 Hz", "44.0 dBmV"),
            _make_us_row("5", "9", "Locked", "OFDM Upstream", "27600000 Hz", "47200000 Hz", "40.0 dBmV"),
        ]
        table = BeautifulSoup(_wrap_us_table(*rows), "html.parser").find("table")
        us30, us31 = parse_arris_upstream(table).value
        assert len(us30) == 2
        assert len(us31) == 1

    def test_short_row_skipped(self):
        short_row = "<tr><td>1</td><td>5</td><td>Locked</td></tr>"
        table = BeautifulSoup(_wrap_us_table(short_row), "html.parser").find("table")
        us30, us31 = parse_arris_upstream(table).value
        assert len(us30) == 0
        assert len(us31) == 0


# ---------------------------------------------------------------------------
# parse_arris_html (full integration)
# ---------------------------------------------------------------------------

class TestParseArrisHtml:
    def test_full_page(self):
        ds_rows = [
            _make_ds_row("1", "Locked", "256QAM", "705000000 Hz", "8.2 dBmV", "43.0 dB", "100", "5"),
            _make_ds_row("33", "Locked", "Other", "722000000 Hz", "10.0 dBmV", "38.5 dB", "200", "10"),
        ]
        us_rows = [
            _make_us_row("1", "5", "Locked", "SC-QAM Upstream", "38596000 Hz", "6400000 Hz", "45.0 dBmV"),
            _make_us_row("5", "9", "Locked", "OFDM Upstream", "27600000 Hz", "47200000 Hz", "40.0 dBmV"),
        ]
        html = _full_page(
            _wrap_ds_table(*ds_rows),
            _wrap_us_table(*us_rows),
        )
        result = parse_arris_html(html).value

        assert "channelDs" in result
        assert "channelUs" in result
        assert len(result["channelDs"]["docsis30"]) == 1
        assert len(result["channelDs"]["docsis31"]) == 1
        assert len(result["channelUs"]["docsis30"]) == 1
        assert len(result["channelUs"]["docsis31"]) == 1

    def test_empty_html(self):
        result = parse_arris_html("").value
        assert result == {
            "channelDs": {"docsis30": [], "docsis31": []},
            "channelUs": {"docsis30": [], "docsis31": []},
        }

    def test_no_channel_tables(self):
        html = "<html><body><table><tr><td>Other data</td></tr></table></body></html>"
        result = parse_arris_html(html).value
        assert result == {
            "channelDs": {"docsis30": [], "docsis31": []},
            "channelUs": {"docsis30": [], "docsis31": []},
        }

    def test_all_unlocked(self):
        ds_rows = [
            _make_ds_row("1", "Not Locked", "256QAM", "705000000 Hz", "0.0 dBmV", "0.0 dB", "0", "0"),
        ]
        us_rows = [
            _make_us_row("1", "5", "Not Locked", "SC-QAM Upstream", "0 Hz", "0 Hz", "0.0 dBmV"),
        ]
        html = _full_page(_wrap_ds_table(*ds_rows), _wrap_us_table(*us_rows))
        result = parse_arris_html(html).value
        assert result["channelDs"]["docsis30"] == []
        assert result["channelDs"]["docsis31"] == []
        assert result["channelUs"]["docsis30"] == []
        assert result["channelUs"]["docsis31"] == []

    def test_ds_mse_negative_of_snr(self):
        """SC-QAM downstream channels have mse = -snr."""
        row = _make_ds_row(
            "1", "Locked", "256QAM", "705000000 Hz",
            "8.0 dBmV", "40.0 dB", "0", "0",
        )
        html = _full_page(_wrap_ds_table(row), _wrap_us_table())
        result = parse_arris_html(html).value
        ch = result["channelDs"]["docsis30"][0]
        assert ch["mer"] == 40.0
        assert ch["mse"] == -40.0

    def test_ds31_mse_is_none(self):
        """OFDM (3.1) downstream channels have mse = None."""
        row = _make_ds_row(
            "33", "Locked", "Other", "722000000 Hz",
            "10.0 dBmV", "38.0 dB", "0", "0",
        )
        html = _full_page(_wrap_ds_table(row), _wrap_us_table())
        result = parse_arris_html(html).value
        ch = result["channelDs"]["docsis31"][0]
        assert ch["mse"] is None

    def test_realistic_channel_count(self):
        """Parse a realistic page with 32 DS + 1 OFDM and 4 US + 1 OFDMA."""
        ds_rows = [
            _make_ds_row(str(i), "Locked", "256QAM",
                         f"{699000000 + i * 6000000} Hz",
                         f"{7.0 + i * 0.1:.1f} dBmV",
                         f"{38.0 + i * 0.1:.1f} dB",
                         str(i * 10), str(i))
            for i in range(1, 33)
        ] + [
            _make_ds_row("33", "Locked", "Other", "722000000 Hz",
                         "10.0 dBmV", "38.5 dB", "200", "10"),
        ]
        us_rows = [
            _make_us_row(str(i), str(i + 4), "Locked", "SC-QAM Upstream",
                         f"{38596000 + i * 6400000} Hz", "6400000 Hz",
                         f"{44.0 + i * 0.5:.1f} dBmV")
            for i in range(1, 5)
        ] + [
            _make_us_row("5", "9", "Locked", "OFDM Upstream",
                         "27600000 Hz", "47200000 Hz", "40.0 dBmV"),
        ]
        html = _full_page(_wrap_ds_table(*ds_rows), _wrap_us_table(*us_rows))
        result = parse_arris_html(html).value
        assert len(result["channelDs"]["docsis30"]) == 32
        assert len(result["channelDs"]["docsis31"]) == 1
        assert len(result["channelUs"]["docsis30"]) == 4
        assert len(result["channelUs"]["docsis31"]) == 1
