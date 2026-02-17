"""Compal CH7465 modem driver for DOCSight.

The CH7465 is a DOCSIS 3.0 cable modem and router used by some ISPs.
The modem is rebranded e.g. as "Connect Box" or "Wireless Voice Gateway" by Unitymedia/Vodafone.

It provides channel data via XML APIs that require a session id and a session token which changes
after every HTTP request.
"""

import hashlib
import logging
import xml.etree.ElementTree as ET
import requests
import re
import weakref
from enum import Enum
from typing import Optional

from .base import ModemDriver

log = logging.getLogger("docsis.driver.ch7465")

class Query(Enum):
    """Query function codes usable with `_get_data()`"""
    GLOBAL_SETTINGS = 1
    SYSTEM_INFO = 2
    DOWNSTREAM_TABLE = 10
    UPSTREAM_TABLE = 11
    LOGIN_FAIL_COUNT = 22
    CONNECTION_STATUS = 144

class Action(Enum):
    """Action function codes usable with `_set_data()`"""
    LOGIN = 15
    LOGOUT = 16

def _node_text(node: Optional[ET.Element], default: str = "") -> str:
    """Helper function: Extract the text from one XML element (with fallback to `default` if the node does not exist)."""
    if node is not None and node.text is not None:
        return node.text
    else:
        return default

class CH7465Driver(ModemDriver):
    """Driver for Compal CH7465 cable modems.

    Manages authentication based on cookies for a SID and a session token changing after each request.
    DOCSIS data is fetched via XML API endpoints.
    """

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        session = requests.Session()
        self._session: requests.Session = session
        # Without a valid Referer, all API requests fail.
        session.headers["Referer"] = url.rstrip("/")+"/"
        session.headers["X-Requested-With"] = "XMLHttpRequest"
        # IP address + User-Agent are used to lock access to other users while logged in.
        # Thus the User-Agent must not change while a login session is in progress.
        session.headers["User-Agent"] = "docsight/2"
        # Workaround: finalizer to log out of the UI once the driver instance is dropped or
        # the application is exited.
        self._finalizer = weakref.finalize(self, CH7465Driver._cleanup, url, session)
        self._finalizer.atexit = True

    @staticmethod
    def _cleanup(url: str, session: requests.Session):
        """Close session on exit to allow other users to connect to the Web-UI."""
        if 'SID' in session.cookies:
            session.post(
                f"{url}/xml/setter.xml",
                data = { "fun": str(Action.LOGOUT.value) },
                timeout=10,
            )
            del session.cookies["SID"]

    def login(self) -> None:
        """Authenticate with username and SHA256-hashed password."""
        pw_hash = hashlib.sha256(self._password.encode()).hexdigest()

        r = self._session.get(
            f"{self._url}",
            timeout=10,
        )
        r.raise_for_status()
        r.close()

        response_text = self._set_data(Action.LOGIN, {
            "Username": self._user,
            "Password": pw_hash
        })

        if response_text.startswith("success") and 'SID=' in response_text:
            sid = response_text.split('SID=', 1)[1]
        else:
            error_msg = response_text[:32]
            # Readable error messages for the common cases documented in the Web-UI javascript code
            if "KDGloginincorrect" in error_msg:
                try:
                    retry = self._get_login_fail_count()
                except Exception:
                    retry = '???'
                error_msg = f"password incorrect - try again in {retry} seconds"
            elif "idloginrightincorrect" in error_msg:
                error_msg = "user not allowed to login"
            elif "KDGsuperUserPwEmpty" in error_msg:
                error_msg = "please set a password before login"
            elif "KDGsuperUserPwTimeout" in error_msg:
                error_msg = "login timeout"
            elif "KDGchangePW" in error_msg or 'passwordneedstochange' in error_msg:
                error_msg = "password must be changed"
            raise RuntimeError(f"Modem authentication failed: {error_msg}")

        self._session.cookies.set("SID", sid)
        log.info("Auth OK (SID: %s)", sid)

    def get_docsis_data(self) -> dict:
        """Query DOCSIS channel data."""
        result = {
            "docsis": "3.0",
            "downstream": [],
            "upstream": [],
        }

        # Downstream channels
        xml = self._get_data(Query.DOWNSTREAM_TABLE)
        root = ET.fromstring(xml)
        for channel in root.findall("downstream"):
            # Map to FritzBox-compatible format for analyzer
            item = {
                "channelID": int(channel.find("chid").text),
                "frequency": _node_text(channel.find("freq")),
                "powerLevel": float(_node_text(channel.find("pow"), "0")),
            }
            mer = _node_text(channel.find("RxMER"))
            modulation = self._normalize_modulation(_node_text(channel.find("mod")))
            pre_rs = _node_text(channel.find("PreRs"))
            post_rs = _node_text(channel.find("PostRs"))
            if mer:
                item["mer"] = float(mer)
                item["mse"] = -float(mer)
            if modulation:
                item["modulation"] = modulation
            if pre_rs:
                item["corrErrors"] = int(pre_rs)
            if post_rs:
                item["nonCorrErrors"] = int(post_rs)
            result["downstream"].append(item)

        # Upstream channels
        xml = self._get_data(Query.UPSTREAM_TABLE)
        root = ET.fromstring(xml)
        for channel in root.findall("upstream"):
            # Map to FritzBox-compatible format for analyzer
            item = {
                "channelID": int(channel.find("usid").text),
                "frequency": _node_text(channel.find("freq")),
                "powerLevel": float(_node_text(channel.find("power"), "0")),
            }
            modulation = self._normalize_modulation(_node_text(channel.find("mod")))
            messageType = _node_text(channel.find("messageType"))
            multiplex = {
                "2": "tdma", # "1.0"
                "29": "atdma", # "2.0"
                "35": "atdma", # "3.0"
            }.get(messageType, messageType)
            if modulation:
                item["modulation"] = modulation
            if multiplex:
                item["multiplex"] = multiplex
            # TODO: estimate "latency" from modulation, "srate", "t1Timeouts", .., "t4Timeouts"
            result["upstream"].append(item)

        return result

    def get_device_info(self) -> dict:
        """Try to get CH7465 model info."""
        try:
            xml = self._get_data(Query.GLOBAL_SETTINGS)
            root = ET.fromstring(xml)
            model = _node_text(root.find("ConfigVenderModel"))
            if model == "":
                model = _node_text(root.find("title"), "CH7465")
            name = _node_text(root.find("model_name"))
            model_name = f"{name} ({model})" if name != "" else model

            result = {
                "manufacturer": "Compal",
                "model": model_name,
                "sw_version": _node_text(root.find("SwVersion")),
            }
            
            xml2 = self._get_data(Query.SYSTEM_INFO)
            root2 = ET.fromstring(xml2)

            uptime = _node_text(root2.find("cm_system_uptime"))
            if uptime:
                m = re.match(r"(\d+)d[^\d]*(\d+)h?:(\d+)m?:(\d+)s?", uptime)
                if m:
                    try:
                        result["uptime_seconds"] = int(m.group(1)) * 86400 + int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4))
                    except (ValueError, TypeError):
                        pass

            return result
        except Exception:
            return {"manufacturer": "Compal", "model": "CH7465", "sw_version": ""}

    def get_connection_info(self) -> dict:
        """Get internet connection info."""
        try:
            xml = self._get_data(Query.CONNECTION_STATUS)
            root = ET.fromstring(xml)
            mode = _node_text(root.find("cm_docsis_mode"))
            flows = root.findall("serviceflow")

            downstream_bps = 0
            upstream_bps = 0

            for flow in flows:
                direction = _node_text(flow.find("direction"))
                rate = _node_text(flow.find("pMaxTrafficRate"))
                if not rate:
                    continue

                # Can't distinguish different service flow types (internet/phone),
                # so assume that the flow with the highest bps is internet.
                if direction == "1":
                    downstream_bps = max(int(rate), downstream_bps)
                elif direction == "2":
                    upstream_bps = max(int(rate), upstream_bps)

            return {
                "max_downstream_kbps": downstream_bps // 1000,
                "max_upstream_kbps": upstream_bps // 1000,
                "connection_type": mode,
            }
        except Exception as e:
            log.warning("Failed to get connection info: %s", e)
            return {}


    def _get_data(self, function: Query) -> str:
        """Query one information set from the modem."""
        r = self._session.post(
            f"{self._url}/xml/getter.xml",
            data = {
                "fun": str(function.value),
            },
            timeout=10,
            allow_redirects=False,
        )
        log.debug("Auth cookies: SID=%s; sessionToken=%s", self._session.cookies.get("SID", ""), self._session.cookies.get("sessionToken", ""))
        r.raise_for_status()
        return r.text

    def _set_data(self, function: Action, data: dict) -> str:
        """Execute an action on the modem."""
        if 'fun' in data:
            raise ValueError("invalid data key in CH7465VF command")
        r = self._session.post(
            f"{self._url}/xml/setter.xml",
            data = {
                "fun": str(function.value),
            } | data,
            timeout=10,
            allow_redirects=False,
        )
        log.debug("Auth cookies: SID=%s; sessionToken=%s", self._session.cookies.get("SID", ""), self._session.cookies.get("sessionToken", ""))
        r.raise_for_status()
        return r.text

    def _get_login_fail_count(self) -> int:
        """Query how many seconds the login is locked because of invalid login attempts."""
        xml = self._get_data(Query.LOGIN_FAIL_COUNT)
        root = ET.fromstring(xml)
        return int(root.find('FailCount').text)

    @staticmethod
    def _normalize_modulation(modulation: str) -> str:
        """Normalize modulation string to analyzer format.

        Input: "256qam", "64qam", "qpsk", ..
        Output: "qam_256", "qam_64", "qpsk", ..
        """
        if not modulation:
            return ""
        mod = modulation.lower().replace("-", "")
        if "qpsk" in mod:
            return "qpsk"
        if "qam" in mod:
            num = mod.replace("qam", "").strip()
            return f"qam_{num}" if num else "qam"
        return modulation
