"""Stage 0 (free): drop rules that cannot match, from the Ring sub_type alone.

Ring's smart-alert sub_type says what the camera classified the motion as. A `vehicle` event has no person
and an `other_motion` event has neither person nor vehicle; `human`, `package_delivery`, `motion`, `ding`,
`on_demand` and an unknown (None) sub_type never prune, because they say nothing about what else is in frame.

A rule is impossible when some variable can only be bound to an entity type that is ruled out (``Person``
needs a person; ``Entity`` / ``Carryable`` can always bind something else). A ``when subtype = S`` context
atom that contradicts a known sub_type is pruned too: the evaluator would pin such a rule at -C anyway.
"""
from __future__ import annotations

from typing import Optional

from exemplar.contracts.dsl_ast import Rule, SubtypeEq
from exemplar.contracts.ontology import VAR_TYPES

IMPOSSIBLE_ENTITIES: dict[str, frozenset[str]] = {
    "vehicle": frozenset({"person"}),
    "other_motion": frozenset({"person", "vehicle"}),
}


def stage0_reason(rule: Rule, sub_type: Optional[str]) -> Optional[str]:
    """Why ``rule`` cannot match an event with this Ring ``sub_type`` (None: it might, so keep it)."""
    if sub_type is None:
        return None
    ruled_out = IMPOSSIBLE_ENTITIES.get(sub_type, frozenset())
    for v in rule.vars:
        if ruled_out and set(VAR_TYPES[v.type]) <= ruled_out:
            return f"rule needs a {v.type.lower()} ({v.name}) but a Ring '{sub_type}' event has none"
    for c in rule.when:
        if isinstance(c, SubtypeEq) and c.value != sub_type:
            return f"rule requires sub_type '{c.value}' but the event is '{sub_type}'"
    return None
