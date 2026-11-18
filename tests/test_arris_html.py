"""Tests for the shared Arris HTML channel-table parser."""


from app.drivers.arris_html import (
    parse_arris_channel_tables,
    _find_channel_tables,
    _is_header_row,
    _parse_downstream,
    _parse_upstream,
    _parse_freq_hz,
    _parse_value,
)
from bs4 import BeautifulSoup


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


# ---------------------------------------------------------------------------
# _parse_freq_hz
# ---------------------------------------------------------------------------

class TestParseFreqHz:
    def test_integer_mhz(self):
        assert _parse_freq_hz("705000000 Hz") == "705 MHz"

    def test_fractional_mhz(self):
        assert _parse_freq_hz("706500000 Hz") == "706.5 MHz"

    def test_empty_string(self):
        assert _parse_freq_hz("") == ""

    def test_none_like(self):
        # Should not crash on unusual input
        assert _parse_freq_hz("not a number") == "not a number"

    def test_whitespace(self):
        assert _parse_freq_hz("  795000000 Hz  ") == "795 MHz"


# ---------------------------------------------------------------------------
# _parse_value
# ---------------------------------------------------------------------------

class TestParseValue:
    def test_dbmv(self):
        assert _parse_value("8.2 dBmV") == 8.2

    def test_db(self):
        assert _parse_value("43.0 dB") == 43.0

    def test_negative(self):
        assert _parse_value("-1.5 dBmV") == -1.5

    def test_empty(self):
        assert _parse_value("") is None

    def test_none(self):
        assert _parse_value(None) is None

    def test_garbage(self):
        assert _parse_value("N/A") is None

    def test_integer(self):
        assert _parse_value("10 dBmV") == 10.0


# ---------------------------------------------------------------------------
# _is_header_row
# ---------------------------------------------------------------------------

class TestIsHeaderRow:
    def test_th_row(self):
        soup = BeautifulSoup("<tr><th>Header</th></tr>", "html.parser")
        assert _is_header_row(soup.find("tr")) is True

    def test_strong_row(self):
        soup = BeautifulSoup("<tr><td><strong>Title</strong></td></tr>", "html.parser")
        assert _is_header_row(soup.find("tr")) is True

    def test_data_row(self):
        soup = BeautifulSoup("<tr><td>1</td><td>Locked</td></tr>", "html.parser")
        assert _is_header_row(soup.find("tr")) is False


# ---------------------------------------------------------------------------
# _find_channel_tables
# ---------------------------------------------------------------------------

class TestFindChannelTables:
    def test_both_tables_found(self):
        html = _full_page(
            _wrap_ds_table(),
            _wrap_us_table(),
        )
        soup = BeautifulSoup(html, "html.parser")
        ds, us = _find_channel_tables(soup)
        assert ds is not None
        assert us is not None

    def test_no_tables(self):
        soup = BeautifulSoup("<html><body></body></html>", "html.parser")
        ds, us = _find_channel_tables(soup)
        assert ds is None
        assert us is None

    def test_only_downstream(self):
        html = _full_page(_wrap_ds_table())
        soup = BeautifulSoup(html, "html.parser")
        ds, us = _find_channel_tables(soup)
        assert ds is not None
        assert us is None


# ---------------------------------------------------------------------------
# _parse_downstream
# ---------------------------------------------------------------------------

class TestParseDownstream:
    def test_scqam_channel(self):
        row = _make_ds_row(
            "1", "Locked", "256QAM", "705000000 Hz",
            "8.2 dBmV", "43.0 dB", "100", "5",
        )
        table = BeautifulSoup(_wrap_ds_table(row), "html.parser").find("table")
        ds30, ds31 = _parse_downstream(table)
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
        ds30, ds31 = _parse_downstream(table)
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
        ds30, ds31 = _parse_downstream(table)
        assert len(ds30) == 0
        assert len(ds31) == 0

    def test_none_table(self):
        ds30, ds31 = _parse_downstream(None)
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
        ds30, ds31 = _parse_downstream(table)
        assert len(ds30) == 2
        assert len(ds31) == 1
        assert ds30[0]["channelID"] == 1
        assert ds30[1]["channelID"] == 2
        assert ds31[0]["channelID"] == 33

    def test_short_row_skipped(self):
        """Rows with fewer than 8 columns are ignored."""
        short_row = "<tr><td>1</td><td>Locked</td><td>256QAM</td></tr>"
        table = BeautifulSoup(_wrap_ds_table(short_row), "html.parser").find("table")
        ds30, ds31 = _parse_downstream(table)
        assert len(ds30) == 0
        assert len(ds31) == 0


# ---------------------------------------------------------------------------
# _parse_upstream
# ---------------------------------------------------------------------------

class TestParseUpstream:
    def test_scqam_channel(self):
        row = _make_us_row(
            "1", "5", "Locked", "SC-QAM Upstream",
            "38596000 Hz", "6400000 Hz", "45.0 dBmV",
        )
        table = BeautifulSoup(_wrap_us_table(row), "html.parser").find("table")
        us30, us31 = _parse_upstream(table)
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
        us30, us31 = _parse_upstream(table)
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
        us30, us31 = _parse_upstream(table)
        assert len(us30) == 0
        assert len(us31) == 0

    def test_none_table(self):
        us30, us31 = _parse_upstream(None)
        assert us30 == []
        assert us31 == []

    def test_mixed_channels(self):
        rows = [
            _make_us_row("1", "5", "Locked", "SC-QAM Upstream", "38596000 Hz", "6400000 Hz", "45.0 dBmV"),
            _make_us_row("2", "6", "Locked", "SC-QAM Upstream", "30596000 Hz", "6400000 Hz", "44.0 dBmV"),
            _make_us_row("5", "9", "Locked", "OFDM Upstream", "27600000 Hz", "47200000 Hz", "40.0 dBmV"),
        ]
        table = BeautifulSoup(_wrap_us_table(*rows), "html.parser").find("table")
        us30, us31 = _parse_upstream(table)
        assert len(us30) == 2
        assert len(us31) == 1

    def test_short_row_skipped(self):
        short_row = "<tr><td>1</td><td>5</td><td>Locked</td></tr>"
        table = BeautifulSoup(_wrap_us_table(short_row), "html.parser").find("table")
        us30, us31 = _parse_upstream(table)
        assert len(us30) == 0
        assert len(us31) == 0


# ---------------------------------------------------------------------------
# parse_arris_channel_tables (full integration)
# ---------------------------------------------------------------------------

class TestParseArrisChannelTables:
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
        result = parse_arris_channel_tables(html)

        assert "channelDs" in result
        assert "channelUs" in result
        assert len(result["channelDs"]["docsis30"]) == 1
        assert len(result["channelDs"]["docsis31"]) == 1
        assert len(result["channelUs"]["docsis30"]) == 1
        assert len(result["channelUs"]["docsis31"]) == 1

    def test_empty_html(self):
        result = parse_arris_channel_tables("")
        assert result == {
            "channelDs": {"docsis30": [], "docsis31": []},
            "channelUs": {"docsis30": [], "docsis31": []},
        }

    def test_no_channel_tables(self):
        html = "<html><body><table><tr><td>Other data</td></tr></table></body></html>"
        result = parse_arris_channel_tables(html)
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
        result = parse_arris_channel_tables(html)
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
        result = parse_arris_channel_tables(html)
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
        result = parse_arris_channel_tables(html)
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
        result = parse_arris_channel_tables(html)
        assert len(result["channelDs"]["docsis30"]) == 32
        assert len(result["channelDs"]["docsis31"]) == 1
        assert len(result["channelUs"]["docsis30"]) == 4
        assert len(result["channelUs"]["docsis31"]) == 1
