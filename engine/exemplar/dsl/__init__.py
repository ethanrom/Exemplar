"""Exemplar DSL: parser, typechecker, printers and evaluators (see docs/DSL.md)."""
from .boolean import evaluate_bool, truth_series
from .english import to_english
from .errors import DSLError, DSLSyntaxError, UnboundHoleError
from .evaluator import CompiledRule, PreparedTrace, compile_rule, evaluate, prepare, rho, robustness
from .parser import parse
from .printer import to_text
from .typecheck import typecheck
from .util import fmt_num, normalize
from .witness import witness

__all__ = [
    "parse", "typecheck", "to_text", "to_english", "normalize", "fmt_num",
    "rho", "robustness", "evaluate", "evaluate_bool", "truth_series", "witness",
    "prepare", "PreparedTrace", "compile_rule", "CompiledRule",
    "DSLError", "DSLSyntaxError", "UnboundHoleError",
]
