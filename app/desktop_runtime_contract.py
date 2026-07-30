"""Shared schema and environment contract for the desktop runtime."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

DESKTOP_MODE_ENV = "DOCSIGHT_DESKTOP_MODE"
INSTANCE_TOKEN_ENV = "DOCSIGHT_DESKTOP_INSTANCE_TOKEN"
INSTANCE_PID_ENV = "DOCSIGHT_DESKTOP_INSTANCE_PID"
INSTANCE_START_TIME_ENV = "DOCSIGHT_DESKTOP_PROCESS_START_TIME"
INSTANCE_VERSION_ENV = "DOCSIGHT_DESKTOP_APP_VERSION"
WEB_PORT_ENV = "WEB_PORT"

DESKTOP_RUNTIME_ENV_NAMES = (
    INSTANCE_TOKEN_ENV,
    INSTANCE_PID_ENV,
    INSTANCE_START_TIME_ENV,
    INSTANCE_VERSION_ENV,
)
RUNTIME_SCHEMA_VERSION = 1
RUNTIME_STATE_FIELDS = frozenset(
    {
        "schema_version",
        "pid",
        "port",
        "application_version",
        "process_start_time",
        "instance_token",
    }
)

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_VERSION_PATTERN = re.compile(r"^[^\x00-\x1f\x7f]{1,128}$")


@dataclass(frozen=True)
class RuntimeState:
    """Strict versioned identity for one running desktop server."""

    schema_version: int
    pid: int
    port: int
    application_version: str
    process_start_time: int
    instance_token: str

    @classmethod
    def create(
        cls,
        *,
        pid: int,
        port: int,
        application_version: str,
        process_start_time: int,
        instance_token: str,
    ) -> RuntimeState:
        return cls.from_mapping(
            {
                "schema_version": RUNTIME_SCHEMA_VERSION,
                "pid": pid,
                "port": port,
                "application_version": application_version,
                "process_start_time": process_start_time,
                "instance_token": instance_token,
            }
        )

    @classmethod
    def from_mapping(cls, value: object) -> RuntimeState:
        if not isinstance(value, dict) or set(value) != RUNTIME_STATE_FIELDS:
            raise ValueError("runtime state fields are invalid")

        schema_version = _strict_int(value["schema_version"])
        pid = _strict_int(value["pid"])
        port = _strict_int(value["port"])
        process_start_time = _strict_int(value["process_start_time"])
        application_version = value["application_version"]
        instance_token = value["instance_token"]

        if schema_version != RUNTIME_SCHEMA_VERSION:
            raise ValueError("runtime schema version is unsupported")
        if not 1 <= pid <= 0xFFFFFFFF:
            raise ValueError("runtime PID is out of range")
        if not 1 <= port <= 65535:
            raise ValueError("runtime port is out of range")
        if not 1 <= process_start_time <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("runtime process start time is out of range")
        if not is_valid_application_version(application_version):
            raise ValueError("runtime application version is invalid")
        if not is_valid_instance_token(instance_token):
            raise ValueError("runtime instance token is invalid")

        return cls(
            schema_version=schema_version,
            pid=pid,
            port=port,
            application_version=application_version,
            process_start_time=process_start_time,
            instance_token=instance_token,
        )

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> RuntimeState:
        """Build and validate the exact runtime identity exported by the launcher."""
        return cls.create(
            pid=_strict_environment_int(env.get(INSTANCE_PID_ENV)),
            port=_strict_environment_int(env.get(WEB_PORT_ENV)),
            application_version=env.get(INSTANCE_VERSION_ENV, ""),
            process_start_time=_strict_environment_int(
                env.get(INSTANCE_START_TIME_ENV)
            ),
            instance_token=env.get(INSTANCE_TOKEN_ENV, ""),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "pid": self.pid,
            "port": self.port,
            "application_version": self.application_version,
            "process_start_time": self.process_start_time,
            "instance_token": self.instance_token,
        }

    def export_environment(self) -> dict[str, str]:
        return {
            INSTANCE_TOKEN_ENV: self.instance_token,
            INSTANCE_PID_ENV: str(self.pid),
            INSTANCE_START_TIME_ENV: str(self.process_start_time),
            INSTANCE_VERSION_ENV: self.application_version,
            WEB_PORT_ENV: str(self.port),
        }


def is_valid_instance_token(value: object) -> bool:
    return isinstance(value, str) and _TOKEN_PATTERN.fullmatch(value) is not None


def is_valid_application_version(value: object) -> bool:
    return isinstance(value, str) and _VERSION_PATTERN.fullmatch(value) is not None


def _strict_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("runtime integer field is invalid")
    return value


def _strict_environment_int(value: str | None) -> int:
    if value is None or not value.isdecimal():
        raise ValueError("invalid desktop runtime integer")
    return int(value)
