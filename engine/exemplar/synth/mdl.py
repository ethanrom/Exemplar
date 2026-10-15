"""Minimum-description-length score used to rank candidate rules (PLAN.md section 2.3)."""
from __future__ import annotations

import math

from ..contracts.dsl_ast import Always, Eventually, HoldsFor, HourIn, Rule, Then, children, holes as ast_holes, node_count
from ..contracts.ontology import PREDICATES

# |ops| = size of the alphabet a node is drawn from: 7 formula operators (not, and, or, eventually, always,
# then, holds_for) + the 11 ontology predicates + 3 context atoms (hour, subtype, device) = 21.
# Every AST node (see `contracts.dsl_ast.node_count`) therefore costs log2(21) ~ 4.39 bits.
OPS_ALPHABET = 7 + len(PREDICATES) + 3
BITS_PER_NODE = math.log2(OPS_ALPHABET)
BITS_PER_HOLE = 8.0


def _numeric_slots(node) -> int:
    """Number of numeric bound slots (window bounds, durations, hours) in a closed rule."""
    n = 0
    if isinstance(node, (Eventually, Always, Then)):
        n += 2
    elif isinstance(node, HoldsFor):
        n += 1
    elif isinstance(node, HourIn):
        n += 2
    return n + sum(_numeric_slots(c) for c in children(node))


def n_parameters(rule: Rule) -> int:
    """Free parameters of ``rule``: its distinct holes if it is a sketch, else its numeric bound slots
    (a solved rule carries the same fitted numbers its sketch had as holes)."""
    hs = ast_holes(rule)
    return len(hs) if hs else _numeric_slots(rule)


def mdl(rule: Rule, violations: int, *, lam: float = 4.0) -> float:
    """``nodes * log2(|ops|) + 8 * #holes + lam * violations`` (bits).

    Pass the *sketch* (holes) or the solved rule: a closed rule is charged for its numeric bound slots, so both
    give the same value for the usual one-hole-per-slot sketch.  ``violations`` is the number of violated
    examples (perception-suspect clips).  Lower is better.
    """
    return node_count(rule) * BITS_PER_NODE + BITS_PER_HOLE * n_parameters(rule) + lam * violations
