"""DOCSight driver for Technicolor CGM4981COM (Cox Panoramic Gateway PM8 / XB8).

Supported hardware
------------------
- Technicolor / Vantiva CGM4981COM
- Branded as Cox Panoramic Gateway "PM8" or "XB8"
- Firmware series: CGM4981COM_8.x / Prod_23.2 (RDK-B platform)

Authentication
--------------
Standard form POST to ``/check.jst``; session maintained via ``DUKSID`` cookie.

Channel data
------------
All DOCSIS data is embedded in columnar HTML tables on ``/network_setup.jst``.
The page contains three tables parsed by this driver:

  1. **Downstream** – 32× SC-QAM (DOCSIS 3.0) + 2× OFDM (DOCSIS 3.1)
  2. **Upstream**   – 4× SC-QAM ATDMA (DOCSIS 3.0) + 1× OFDMA (DOCSIS 3.1)
  3. **CM Error Codewords** – per-channel correctable / uncorrectable counts
     (aligned to the same 34 downstream channel IDs)

Implementation notes
--------------------
- The three tables share row labels (e.g. "Channel ID" appears in all three).
  This driver parses them by HTML section to avoid label-collision issues.
- OFDM / OFDMA upstream channel power thresholds differ from SC-QAM.
  Cox provisions OFDMA upstream at lower per-channel power (~37 dBmV is normal).
  Adjust ``thresholds_vfkd/thresholds.json`` if DOCSight flags these as critical:
      ``upstream_power.ofdma.critical: [35.0, 50.0]``
      ``upstream_power.ofdma.good:     [37.0, 47.0]``
"""

import logging
import re

import requests

from .base import ModemDriver

log = logging.getLogger("docsis.driver.cgm4981")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOGIN_PATH  = "/check.jst"
_STATUS_PATH = "/network_setup.jst"

# The login-redirect page is always ~8 640 bytes; anything larger is real data.
_MIN_STATUS_PAGE_BYTES = 9_000

# Cookie name that confirms a valid session.
_SESSION_COOKIE = "DUKSID"

# HTML markers used to split the page into three sections.
_MARKER_DS  = ">Downstream<"
_MARKER_US  = ">Upstream<"
_MARKER_ERR = "CM Error Codewords"

# Compiled patterns used throughout parsing.
_RE_TR        = re.compile(r"<tr[^>]*>(.*?)</tr>",               re.DOTALL | re.IGNORECASE)
_RE_TH        = re.compile(r"<th[^>]*>(.*?)</(?:th|td)>",        re.DOTALL | re.IGNORECASE)
_RE_NETWIDTH  = re.compile(r'<div[^>]*class="netWidth"[^>]*>(.*?)</div>', re.DOTALL)
_RE_STRIP     = re.compile(r"<[^>]+>")
_RE_NUMBER    = re.compile(r"-?\d+\.?\d*")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _text(html: str) -> str:
    """Strip HTML tags and return plain text."""
    return _RE_STRIP.sub("", html).strip()


def _float(raw: str) -> float:
    """Return first float found in a string, e.g. '44.1 dB' → 44.1."""
    m = _RE_NUMBER.search(raw.strip())
    return float(m.group()) if m else 0.0


def _freq_mhz(raw: str) -> str:
    """Normalise a frequency string to 'NNN MHz'.

    Handles:
      - '189 MHz'       → '189 MHz'
      - '300000000'     → '300 MHz'   (raw Hz integer from OFDM row)
      - '950000000'     → '950 MHz'
      - '17  MHz'       → '17 MHz'    (extra whitespace)
    """
    raw = raw.strip()
    if re.search(r"[Mm][Hh][Zz]", raw):
        num = _RE_NUMBER.search(raw)
        if num:
            mhz = float(num.group())
            return f"{int(mhz) if mhz == int(mhz) else mhz} MHz"
    m = _RE_NUMBER.search(raw)
    if m:
        val = float(m.group())
        if val > 1_000_000:
            mhz = val / 1_000_000
            return f"{int(mhz) if mhz == int(mhz) else mhz} MHz"
        return f"{int(val) if val == int(val) else val} MHz"
    return raw


def _modulation(raw: str) -> str:
    """Normalise modulation string for DOCSight's analyser.

    Maps common CGM4981 values:
      '256 QAM' → 'QAM256'
      'OFDM'    → 'OFDM'
      'OFDMA'   → 'OFDMA'
      'QAM'     → 'QAM'   (upstream SC-QAM without order)
    """
    up = raw.strip().upper()
    if "OFDMA" in up:
        return "OFDMA"
    if "OFDM" in up:
        return "OFDM"
    # '256 QAM' → 'QAM256', '64 QAM' → 'QAM64', etc.
    m = re.search(r"(\d+)\s*QAM", up)
    if m:
        return f"QAM{m.group(1)}"
    if "QAM" in up:
        return "QAM"
    return raw.strip()


def _section_rows(html: str) -> dict[str, list[str]]:
    """Parse all ``<tr>`` rows in an HTML *section* into {label: [values]}.

    Each data row is expected to have:
      - A ``<th>`` element whose text is the row label.
      - One or more ``<td>`` cells each containing a
        ``<div class="netWidth">VALUE</div>`` element.

    Labels are unique within a section (the caller is responsible for
    passing only one table's HTML, not the whole page).
    """
    rows: dict[str, list[str]] = {}
    for tr_m in _RE_TR.finditer(html):
        tr = tr_m.group(1)
        th_m = _RE_TH.search(tr)
        if not th_m:
            continue
        label = _text(th_m.group(1))
        if not label:
            continue
        values = [_text(v) for v in _RE_NETWIDTH.findall(tr)]
        if values:
            rows[label] = values
    return rows


def _split_sections(html: str) -> tuple[str, str, str]:
    """Return (ds_html, us_html, err_html) by finding section markers."""
    ds_idx  = html.find(_MARKER_DS)
    us_idx  = html.find(_MARKER_US)
    err_idx = html.find(_MARKER_ERR)

    ds_html  = html[ds_idx:us_idx]          if ds_idx  >= 0 and us_idx  > ds_idx  else ""
    us_html  = html[us_idx:err_idx]         if us_idx  >= 0 and err_idx > us_idx  else ""
    err_html = html[err_idx:]               if err_idx >= 0                        else ""

    return ds_html, us_html, err_html


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class CGM4981Driver(ModemDriver):
    """Driver for Technicolor CGM4981COM (Cox Panoramic Gateway PM8 / XB8).

    Parses downstream and upstream DOCSIS channel data from the columnar
    HTML tables on ``/network_setup.jst``.  Error counts (correctable and
    uncorrectable codewords) are read from the separate "CM Error Codewords"
    table on the same page.
    """

    def __init__(self, url: str, user: str, password: str) -> None:
        super().__init__(url, user, password)
        self._session: requests.Session = requests.Session()
        self._status_html: str | None = None

    # ------------------------------------------------------------------
    # ModemDriver interface
    # ------------------------------------------------------------------

    def login(self) -> None:
        """POST credentials to ``/check.jst`` and verify the session cookie."""
        self._status_html = None
        self._session = requests.Session()
        try:
            self._session.post(
                f"{self._url}{_LOGIN_PATH}",
                data={"username": self._user, "password": self._password},
                allow_redirects=True,
                timeout=15,
            ).raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"CGM4981 login request failed: {exc}") from exc

        if _SESSION_COOKIE not in self._session.cookies:
            raise RuntimeError(
                "CGM4981 authentication failed: session cookie not received. "
                "Check username and password."
            )
        log.info(
            "CGM4981 auth OK (DUKSID=%s…)",
            str(self._session.cookies.get(_SESSION_COOKIE, ""))[:8],
        )

    def get_docsis_data(self) -> dict:
        """Return parsed downstream and upstream channel data."""
        html = self._fetch_status_page()
        ds_html, us_html, err_html = _split_sections(html)

        if not ds_html:
            log.warning("CGM4981: Downstream section not found in status page")
        if not us_html:
            log.warning("CGM4981: Upstream section not found in status page")

        ds_rows  = _section_rows(ds_html)
        us_rows  = _section_rows(us_html)
        err_rows = _section_rows(err_html)

        ds_channels = self._build_ds_channels(ds_rows, err_rows)
        us_channels = self._build_us_channels(us_rows)

        ds30 = [ch for ch in ds_channels if ch.get("modulation") != "OFDM"]
        ds31 = [ch for ch in ds_channels if ch.get("modulation") == "OFDM"]
        us30 = [ch for ch in us_channels if ch.get("modulation") != "OFDMA"]
        us31 = [ch for ch in us_channels if ch.get("modulation") == "OFDMA"]

        log.debug(
            "CGM4981 parsed: DS SC-QAM=%d OFDM=%d | US SC-QAM=%d OFDMA=%d",
            len(ds30), len(ds31), len(us30), len(us31),
        )
        return {
            "channelDs": {"docsis30": ds30, "docsis31": ds31},
            "channelUs": {"docsis30": us30, "docsis31": us31},
        }

    def get_device_info(self) -> dict:
        """Return model, firmware version, and uptime from the status page."""
        info: dict = {
            "manufacturer": "Technicolor",
            "model":        "CGM4981COM",
            "sw_version":   "",
        }
        try:
            html = self._fetch_status_page()

            m = re.search(r"Model:</span>\s*<span[^>]*>\s*(CGM\w+)", html)
            if m:
                info["model"] = m.group(1).strip()

            m = re.search(r"Download Version:</span>\s*<span[^>]*>\s*([^\s<]+)", html)
            if m:
                info["sw_version"] = m.group(1).strip()

            # "0 days 2h: 1m: 11s"
            m = re.search(
                r"System Uptime:</span>\s*<span[^>]*>\s*"
                r"(\d+)\s*days?\s*(\d+)h:\s*(\d+)m:\s*(\d+)s",
                html,
            )
            if m:
                info["uptime_seconds"] = (
                    int(m.group(1)) * 86400
                    + int(m.group(2)) * 3600
                    + int(m.group(3)) * 60
                    + int(m.group(4))
                )
        except Exception:
            pass
        return info

    def get_connection_info(self) -> dict:
        """Return WAN IP and connection status from the status page."""
        info: dict = {}
        try:
            html = self._fetch_status_page()
            m = re.search(
                r"WAN IP Address \(IPv4\):</span>\s*<span[^>]*>\s*([0-9.]+)", html
            )
            if m:
                info["wan_ip"] = m.group(1)
            m = re.search(r"Internet:</span>\s*<span[^>]*>\s*(\w+)", html)
            if m:
                info["status"] = m.group(1)
        except Exception:
            pass
        return info

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_status_page(self) -> str:
        """Fetch and cache ``/network_setup.jst``.  Re-authenticates on expiry."""
        if self._status_html is not None:
            return self._status_html

        for attempt in range(2):
            try:
                r = self._session.get(f"{self._url}{_STATUS_PATH}", timeout=40)
                r.raise_for_status()
            except requests.RequestException as exc:
                if attempt == 0:
                    log.warning("CGM4981 status page fetch failed, retrying: %s", exc)
                    self._session = requests.Session()
                    self.login()
                    continue
                raise RuntimeError(
                    f"CGM4981 status page retrieval failed: {exc}"
                ) from exc

            if len(r.text) < _MIN_STATUS_PAGE_BYTES:
                # Session expired — redirect to login page.
                if attempt == 0:
                    log.warning("CGM4981 session expired, re-authenticating")
                    self._session = requests.Session()
                    self.login()
                    continue
                raise RuntimeError(
                    "CGM4981 status page returned login redirect after re-auth"
                )

            self._status_html = r.text
            return self._status_html

        raise RuntimeError("CGM4981 failed to fetch status page after 2 attempts")

    # ------------------------------------------------------------------
    # Channel builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_ds_channels(
        ds_rows: dict[str, list[str]],
        err_rows: dict[str, list[str]],
    ) -> list[dict]:
        """Build downstream channel list from the DS section and error table.

        Error counts from the "CM Error Codewords" table are indexed by
        channel ID to ensure correct alignment even if row order varies.
        """
        ch_ids  = ds_rows.get("Channel ID",  [])
        locks   = ds_rows.get("Lock Status", [])
        freqs   = ds_rows.get("Frequency",   [])
        snrs    = ds_rows.get("SNR",         [])
        powers  = ds_rows.get("Power Level", [])
        mods    = ds_rows.get("Modulation",  [])

        if not ch_ids:
            log.warning("CGM4981: no DS Channel ID row found")
            return []

        # Build a {channel_id: (corr, uncorr)} map from the error table.
        err_ch_ids = err_rows.get("Channel ID",              [])
        err_corr   = err_rows.get("Correctable Codewords",   [])
        err_uncorr = err_rows.get("Uncorrectable Codewords", [])
        err_map: dict[str, tuple[int, int]] = {}
        for i, cid in enumerate(err_ch_ids):
            corr   = int(err_corr[i])   if i < len(err_corr)   and err_corr[i].lstrip("-").isdigit()   else 0
            uncorr = int(err_uncorr[i]) if i < len(err_uncorr) and err_uncorr[i].lstrip("-").isdigit() else 0
            err_map[cid] = (corr, uncorr)

        channels = []
        for i, cid in enumerate(ch_ids):
            lock = locks[i] if i < len(locks) else ""
            if lock.lower() != "locked":
                continue
            try:
                mod  = _modulation(mods[i]  if i < len(mods)   else "")
                freq = _freq_mhz(freqs[i]   if i < len(freqs)  else "")
                snr  = _float(snrs[i]       if i < len(snrs)   else "")
                pwr  = _float(powers[i]     if i < len(powers) else "")
                corr, uncorr = err_map.get(cid, (0, 0))

                ch: dict = {
                    "channelID":      int(cid),
                    "frequency":      freq,
                    "powerLevel":     pwr,
                    "mer":            snr,
                    "mse":            -snr if snr else None,
                    "modulation":     mod,
                    "corrErrors":     corr,
                    "nonCorrErrors":  uncorr,
                }
                if mod == "OFDM":
                    ch["type"] = "OFDM"

                channels.append(ch)
            except (ValueError, IndexError) as exc:
                log.warning("CGM4981 DS channel %s parse error: %s", cid, exc)

        return channels

    @staticmethod
    def _build_us_channels(us_rows: dict[str, list[str]]) -> list[dict]:
        """Build upstream channel list from the US section only."""
        ch_ids = us_rows.get("Channel ID",  [])
        locks  = us_rows.get("Lock Status", [])
        freqs  = us_rows.get("Frequency",   [])
        powers = us_rows.get("Power Level", [])
        mods   = us_rows.get("Modulation",  [])
        types  = us_rows.get("Channel Type",[])

        if not ch_ids:
            log.warning("CGM4981: no US Channel ID row found")
            return []

        channels = []
        for i, cid in enumerate(ch_ids):
            lock = locks[i] if i < len(locks) else ""
            if lock.lower() != "locked":
                continue
            try:
                raw_mod = mods[i] if i < len(mods) else ""
                raw_type = types[i] if i < len(types) else ""
                mod = _modulation(raw_mod)
                # OFDMA upstream: modulation field says 'OFDMA' directly.
                # ATDMA SC-QAM: modulation field says 'QAM' (no order on this device).
                freq = _freq_mhz(freqs[i]   if i < len(freqs)  else "")
                pwr  = _float(powers[i]     if i < len(powers) else "")

                ch: dict = {
                    "channelID":   int(cid),
                    "frequency":   freq,
                    "powerLevel":  pwr,
                    "modulation":  mod,
                    "multiplex":   raw_type.upper() or mod,
                }
                if mod == "OFDMA":
                    ch["type"] = "OFDMA"

                channels.append(ch)
            except (ValueError, IndexError) as exc:
                log.warning("CGM4981 US channel %s parse error: %s", cid, exc)

        return channels
