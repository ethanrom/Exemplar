"""Frozen contracts shared by every workstream (PLAN.md §4). Change only via the integrator,
and update docs/DSL.md + engine/tests/test_contracts.py in the same change."""
from .dsl_ast import (Always, And, Atom, Bound, Ctx, DeviceEq, Eventually, Hole, HoldsFor, HourIn, Not, Or,
                      Phi, Rule, SubtypeEq, Then, VarDecl, fill_holes, holes, node_count)
from .labels import Label, for_calibration, for_synthesis
from .trace import Entity, Fact, Frame, PerceptionMeta, Trace, TraceContext, trace_errors

CONTRACTS_VERSION = "1.0.1"
