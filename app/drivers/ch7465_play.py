"""Compal CH7465 modem driver for DOCSight — Play/UPC firmware variant.

Inherits from the main CH7465 driver, overriding only the differing parts:
- Login uses plaintext password (no SHA256 hashing)
- Login always sends Username="NULL"
- All API requests always include the session token

Everything else (DOCSIS data parsing, device info, connection info,
modulation normalisation, session cleanup) is identical and inherited.
"""

import logging

from .ch7465 import CH7465Driver, Action, Query

log = logging.getLogger("docsis.driver.ch7465_play")


class CH7465PlayDriver(CH7465Driver):
    """Driver for Compal CH7465 cable modems with Play/UPC firmware.

    Play firmware specifics (overrides from CH7465Driver):
    - Plaintext password authentication (no SHA256)
    - Username is always "NULL"
    - Session token is always included in API requests
    """

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        # Override: Play variant always uses Play mode (no auto-detection)
        self._is_play = True

    def login(self) -> None:
        """Authenticate with the modem using Play firmware protocol."""
        r = self._session.get(
            f"{self._url}",
            timeout=10,
        )
        r.raise_for_status()
        log.debug("Initial GET status=%d, cookies=%s", r.status_code, dict(self._session.cookies))
        r.close()

        payload = {"Username": "NULL", "Password": self._password}

        response_text = self._set_data(Action.LOGIN, payload)
        log.debug("Login response: %s", response_text)

        if response_text.startswith("success") and 'SID=' in response_text:
            sid = response_text.split('SID=', 1)[1]
        else:
            error_msg = response_text[:32]
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
