"""Immutable result contract for pure modem payload parsers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from ...types import DocsisDataFritz, RawChannel

T = TypeVar("T")


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
