"""Immutable configuration for isolated E2E application processes."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

_INHERITED_ENVIRONMENT = {
    "HOME",
    "LANG",
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "TZ",
    "WINDIR",
    "DOCSIGHT_E2E_RUN_ID",
}


@dataclass(frozen=True)
class ServerProfile:
    """Pickle-safe behavior shared by one explicit server variant."""

    name: str
    configured: bool
    demo_mode: bool
    modem_type: str | None = None
    mount_path: str = ""
    base_path: str | None = None
    trusted_prefix_hops: int | None = None
    production_startup: bool = False
    post_seed_callback: Callable[[str], None] | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("server profile name must not be empty")
        if self.mount_path and not self.mount_path.startswith("/"):
            raise ValueError("mount_path must be empty or absolute")


@dataclass(frozen=True)
class ServerTarget:
    """Unique identity, data path, port, and profile for one app process."""

    identity: str
    data_dir: str
    port: int
    profile: ServerProfile
    admin_password: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.identity:
            raise ValueError("server target identity must not be empty")
        if not self.data_dir:
            raise ValueError("server target data_dir must not be empty")
        if not 0 < self.port < 65536:
            raise ValueError("server target port is outside the TCP range")

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}{self.profile.mount_path}"

    def environment(
        self, inherited: Mapping[str, str] | None = None
    ) -> dict[str, str]:
        """Return a clean child environment for exactly this target."""

        source = os.environ if inherited is None else inherited
        environment = {
            key: value
            for key, value in source.items()
            if key in _INHERITED_ENVIRONMENT or key.startswith("LC_")
        }
        environment.update(
            {
                "DATA_DIR": self.data_dir,
                "LOG_LEVEL": "WARNING",
            }
        )
        if self.profile.demo_mode:
            environment["DEMO_MODE"] = "1"
        if self.profile.base_path is not None:
            environment["BASE_PATH"] = self.profile.base_path
        if self.profile.trusted_prefix_hops is not None:
            environment["REVERSE_PROXY_PREFIX"] = str(
                self.profile.trusted_prefix_hops
            )
        if self.profile.production_startup:
            environment.update(
                {
                    "WEB_HOST": "127.0.0.1",
                    "WEB_PORT": str(self.port),
                }
            )
        return environment

    def apply_environment(self) -> None:
        environment = self.environment()
        os.environ.clear()
        os.environ.update(environment)
