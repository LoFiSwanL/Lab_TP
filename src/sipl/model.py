"""Shared source positions and diagnostics."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Position:
    offset: int
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start: Position
    end: Position


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    span: SourceSpan | None = None
    expected: tuple[str, ...] = ()


class SIPLError(Exception):
    def __init__(self, diagnostic: Diagnostic):
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic
