"""Shared Arris HTML channel-table parser for DOCSight.

Parses the ``/cmconnectionstatus.html`` status page used by Arris cable
modems (CM8200A, SB8200 HTML fallback, and similar) into the standard
DOCSight channel data format.

The page contains two HTML tables:
- "Downstream Bonded Channels" (8 columns)
- "Upstream Bonded Channels" (7 columns)

DOCSIS version is inferred from modulation / channel type:
- DS: modulation "Other" = OFDM (3.1), anything else = SC-QAM (3.0)
- US: "OFDM" in type without "SC-QAM" = OFDMA (3.1), else SC-QAM (3.0)
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup, Tag

from ..types import DocsisDataFritz, RawChannel

log = logging.getLogger("docsis.arris_html")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_arris_channel_tables(html: str) -> DocsisDataFritz:
    """Parse Arris modem status page HTML into DOCSight channel format.

    Returns::

        {"channelDs": {"docsis30": [...], "docsis31": [...]},
         "channelUs": {"docsis30": [...], "docsis31": [...]}}
    """
    soup = BeautifulSoup(html, "html.parser")
    ds_table, us_table = _find_channel_tables(soup)

    ds30, ds31 = _parse_downstream(ds_table)
    us30, us31 = _parse_upstream(us_table)

    return {
        "channelDs": {"docsis30": ds30, "docsis31": ds31},
        "channelUs": {"docsis30": us30, "docsis31": us31},
    }


# ---------------------------------------------------------------------------
# Table discovery
# ---------------------------------------------------------------------------

def _find_channel_tables(soup: BeautifulSoup) -> tuple:
    """Find downstream and upstream channel tables by header text.

    Returns ``(ds_table, us_table)`` where either may be ``None``.
    """
    ds_table = None
    us_table = None

    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        text = header.get_text(strip=True).lower()
        if "downstream bonded" in text:
            ds_table = table
        elif "upstream bonded" in text:
            us_table = table

    return ds_table, us_table


# ---------------------------------------------------------------------------
# Row classification
# ---------------------------------------------------------------------------

def _is_header_row(row: Tag) -> bool:
    """True if *row* is a table title or column-header row (not data)."""
    if row.find("th"):
        return True
    if row.find("strong"):
        return True
    return False


# ---------------------------------------------------------------------------
# Downstream parser
# ---------------------------------------------------------------------------

def _parse_downstream(table) -> tuple:
    """Parse downstream table into ``(docsis30, docsis31)`` channel lists.

    Expected 8 columns per data row:
    Channel ID | Lock Status | Modulation | Frequency |
    Power | SNR/MER | Corrected | Uncorrectables
    """
    ds30: list[dict] = []
    ds31: list[dict] = []
    if not table:
        return ds30, ds31

    for row in table.find_all("tr"):
        if _is_header_row(row):
            continue
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 8:
            continue

        lock_status = cells[1]
        if lock_status != "Locked":
            continue

        try:
            channel_id = int(cells[0])
            modulation = cells[2]
            frequency = _parse_freq_hz(cells[3])
            power = _parse_value(cells[4])
            snr = _parse_value(cells[5])
            corrected = int(cells[6])
            uncorrectables = int(cells[7])

            channel: RawChannel = {
                "channelID": channel_id,
                "frequency": frequency,
                "powerLevel": power,
                "modulation": modulation,
                "corrErrors": corrected,
                "nonCorrErrors": uncorrectables,
            }

            if modulation == "Other":
                # OFDM channel (DOCSIS 3.1)
                channel["type"] = "OFDM"
                channel["mer"] = snr
                channel["mse"] = None
                ds31.append(channel)
            else:
                # SC-QAM channel (DOCSIS 3.0)
                channel["mer"] = snr
                channel["mse"] = -snr if snr is not None else None
                ds30.append(channel)
        except (ValueError, TypeError, IndexError) as e:
            log.warning("Failed to parse DS row: %s", e)

    return ds30, ds31


# ---------------------------------------------------------------------------
# Upstream parser
# ---------------------------------------------------------------------------

def _parse_upstream(table) -> tuple:
    """Parse upstream table into ``(docsis30, docsis31)`` channel lists.

    Expected 7 columns per data row:
    Channel | Channel ID | Lock Status | US Channel Type |
    Frequency | Width | Power
    """
    us30: list[dict] = []
    us31: list[dict] = []
    if not table:
        return us30, us31

    for row in table.find_all("tr"):
        if _is_header_row(row):
            continue
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 7:
            continue

        lock_status = cells[2]
        if lock_status != "Locked":
            continue

        try:
            channel_id = int(cells[1])
            channel_type = cells[3]
            frequency = _parse_freq_hz(cells[4])
            power = _parse_value(cells[6])

            channel: RawChannel = {
                "channelID": channel_id,
                "frequency": frequency,
                "powerLevel": power,
                "modulation": channel_type,
            }

            if "OFDM" in channel_type and "SC-QAM" not in channel_type:
                # OFDMA channel (DOCSIS 3.1)
                channel["type"] = "OFDMA"
                channel["multiplex"] = ""
                us31.append(channel)
            else:
                # SC-QAM channel (DOCSIS 3.0)
                channel["multiplex"] = "SC-QAM"
                us30.append(channel)
        except (ValueError, TypeError, IndexError) as e:
            log.warning("Failed to parse US row: %s", e)

    return us30, us31


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------

def _parse_freq_hz(freq_str: str) -> str:
    """Convert ``'795000000 Hz'`` to ``'795 MHz'``."""
    from .utils import hz_to_mhz
    return hz_to_mhz(freq_str)


def _parse_value(val_str: str):
    """Parse ``'8.2 dBmV'`` or ``'43.0 dB'`` to float.

    Note: Returns None (not 0.0) for empty/unparseable input, unlike
    parse_number(). This preserves arris_html's existing behaviour where
    None signals "value not present" vs 0.0 for "value is zero".
    """
    if not val_str:
        return None
    parts = val_str.strip().split()
    try:
        return float(parts[0])
    except (ValueError, IndexError):
        return None
