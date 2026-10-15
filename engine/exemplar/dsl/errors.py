"""Exceptions raised by the DSL package."""
from __future__ import annotations


class DSLError(Exception):
    """Base class for DSL errors."""


class DSLSyntaxError(DSLError, ValueError):
    """Text could not be parsed. `line`/`column` are 1-based; `message` is short and LLM-readable.

    `str(err)` is "line L, column C: message"; `err.context` is the offending source line with a
    caret under the column (for logs and UIs).
    """

    def __init__(self, message: str, line: int = 1, column: int = 1, context: str = "") -> None:
        self.message = message
        self.line = line
        self.column = column
        self.context = context
        super().__init__(f"line {line}, column {column}: {message}")


class UnboundHoleError(DSLError, ValueError):
    """An evaluator was given a rule that still has holes (`?name`) and no value for them."""

    def __init__(self, names: list[str]) -> None:
        self.names = list(names)
        super().__init__("rule has unfilled holes: " + ", ".join("?" + n for n in self.names)
                         + " (pass holes={...} or fill_holes() first)")
