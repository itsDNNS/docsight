"""Explicit non-parser boundaries registered alongside DOCSIS profiles."""

from __future__ import annotations

from ...types import DocsisDataFritz
from .contract import ParseResult, docsis_split


def parse_generic_no_docsis() -> ParseResult[DocsisDataFritz]:
    return ParseResult(docsis_split([], [], [], []))
