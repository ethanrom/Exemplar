"""Ontology v1 (PLAN.md §2.1). Frozen contract — changes go through the integrator.

Shared by perception (what the model may assert), the trace validator, and the DSL typechecker.
"""
from __future__ import annotations

from typing import Literal

EntityType = Literal["person", "vehicle", "package", "animal", "object"]
ENTITY_TYPES: tuple[str, ...] = ("person", "vehicle", "package", "animal", "object")

Zone = Literal["door", "porch", "steps", "yard", "driveway", "sidewalk", "street", "dock"]
ZONES: tuple[str, ...] = ("door", "porch", "steps", "yard", "driveway", "sidewalk", "street", "dock")

Conf = Literal["low", "med", "high"]
CONF_VALUE: dict[str, float] = {"low": 0.6, "med": 0.8, "high": 0.95}
ABSENT_VALUE = 0.05          # signal value when a predicate is not asserted in a frame (§2.1.5)
THRESHOLD = 0.5              # ρ(atom, t) = s(t) − THRESHOLD (§2.2)
CLAMP = 0.5                  # C: robustness of empty windows / crisp context atoms is ±CLAMP (§2.2)

# Ring smart-alert subtypes (webhook `data.subType`, history filter `motion.<sub>`) + our two extras.
SubType = Literal["human", "vehicle", "package_delivery", "other_motion", "motion", "ding", "on_demand"]
SUB_TYPES: tuple[str, ...] = ("human", "vehicle", "package_delivery", "other_motion", "motion", "ding", "on_demand")

# Argument kinds. A DSL variable type is one of the capitalised entity types.
#   "Entity"   any entity             "Person" / "Vehicle" / "Package" / "Animal" / "Object"  that type
#   "Carryable" package | object      "Zone"   a Zone literal              "Label"  an open-vocab attr label
ArgKind = Literal["Entity", "Person", "Vehicle", "Package", "Animal", "Object", "Carryable", "Zone", "Label"]

PREDICATES: dict[str, tuple[ArgKind, ...]] = {
    "present": ("Entity",),
    "in_zone": ("Entity", "Zone"),
    "near": ("Entity", "Entity"),
    "carrying": ("Person", "Carryable"),
    "picks_up": ("Person", "Carryable"),
    "puts_down": ("Person", "Carryable"),
    "rings_bell": ("Person",),
    "enters": ("Entity", "Zone"),
    "leaves": ("Entity", "Zone"),
    "facing_camera": ("Person",),
    "attr": ("Entity", "Label"),
}

# DSL variable types (`exists p: Person`) and the entity types each admits.
VAR_TYPES: dict[str, tuple[str, ...]] = {
    "Entity": ENTITY_TYPES,
    "Person": ("person",),
    "Vehicle": ("vehicle",),
    "Package": ("package",),
    "Animal": ("animal",),
    "Object": ("object",),
    "Carryable": ("package", "object"),
}


def kind_admits(kind: str, entity_type: str) -> bool:
    """True if an entity of `entity_type` may fill an argument slot of `kind` (entity kinds only)."""
    return entity_type in VAR_TYPES.get(kind, ())

