"""Immutable result contract for pure modem payload parsers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
from typing import Any, Generic, TypeVar

from ...types import DocsisDataFritz, RawChannel
T = TypeVar("T")
# A cell holds one number, optionally followed by the unit the captured pages use.
_UNITS = ([], ["dB"], ["dBmV"])
# Counters must fit the SQLite INTEGER range the history stores them in.
_COUNTER_MAX = 2**63 - 1


@dataclass(frozen=True, slots=True)
class ParseDiagnostic:
    """Stable parser metadata that cannot contain payload or transport data."""

    family: str
    profile: str
    code: str
    direction: str | None = None
    row: int | None = None
    index: int | None = None
    field: str | None = None


@dataclass(frozen=True, slots=True)
class ParseResult(Generic[T]):
    """A normalized value plus immutable, payload-safe diagnostics."""

    value: T
    diagnostics: tuple[ParseDiagnostic, ...] = ()


def docsis_split(
    ds30: list[RawChannel],
    ds31: list[RawChannel],
    us30: list[RawChannel],
    us31: list[RawChannel],
) -> DocsisDataFritz:
    """Build the common four-lane result without hiding lane semantics."""
    return {
        "channelDs": {"docsis30": ds30, "docsis31": ds31},
        "channelUs": {"docsis30": us30, "docsis31": us31},
    }


def ofdm_downstream(channel_id, frequency, power, mer, corrected, uncorrected) -> RawChannel:
    """A DOCSIS 3.1 OFDM downstream channel without a modulation profile."""
    return {
        "channelID": channel_id, "type": "OFDM", "frequency": frequency,
        "powerLevel": power, "mer": mer, "mse": None,
        "corrErrors": corrected, "nonCorrErrors": uncorrected,
    }


def docsis_result(
    ds30: ParseResult[list[RawChannel]],
    ds31: ParseResult[list[RawChannel]],
    us30: ParseResult[list[RawChannel]],
    us31: ParseResult[list[RawChannel]],
) -> ParseResult[DocsisDataFritz]:
    """Combine four explicit lane results and their safe diagnostics."""
    results = (ds30, ds31, us30, us31)
    return ParseResult(
        docsis_split(ds30.value, ds31.value, us30.value, us31.value),
        tuple(issue for result in results for issue in result.diagnostics),
    )


def diagnostic(
    profile: str,
    code: str,
    *,
    family: str,
    direction: str | None = None,
    row: int | None = None,
    index: int | None = None,
    field: str | None = None,
) -> ParseDiagnostic:
    """Construct a diagnostic while keeping its finite schema explicit."""
    return ParseDiagnostic(
        family=family,
        profile=profile,
        code=code,
        direction=direction,
        row=row,
        index=index,
        field=field,
    )


def number_reader(diagnostics: list[ParseDiagnostic], profile: str, **where: Any) -> Callable[..., Any]:
    """Read one row's numeric cells or JSON values; a finite JSON number keeps its type.

    Text must be one number, optionally with a dB or dBmV unit. An ``int`` field (a counter) must be a
    non-negative integer up to ``_COUNTER_MAX``. A missing or empty value is reported as unavailable;
    anything else that does not qualify as invalid.
    """
    def read(value: object, field: str, kind: type = float) -> Any:
        text = "" if value is None else str(value).strip()
        token, *unit = text.split() or [""]
        try:
            if type(value) in (int, float):
                number = value
            else:
                number = (int if kind is int else float)(token) if unit in _UNITS else None
            if number is not None and not (math.isfinite(number) and (
                kind is not int or (number == int(number) and 0 <= number <= _COUNTER_MAX)
            )):
                number = None
        except (ValueError, OverflowError):
            number = None
        if number is None:
            diagnostics.append(diagnostic(
                profile, "invalid_field" if text else "unavailable_field", field=field, **where,
            ))
        return number
    return read
