"""Rule synthesis: Z3 hole solving (MaxSMT + max-margin), differential check, MDL ranking (PLAN.md section 2.3)."""
from .mdl import mdl
from .render import render_trace_text
from .solve import InfeasibleBox, hole_box, solve_sketch
from .types import Candidate, EncoderMismatch, Example, SketchError, SolveResult

__all__ = ["Example", "SolveResult", "Candidate", "solve_sketch", "hole_box", "mdl", "render_trace_text",
           "EncoderMismatch", "SketchError", "InfeasibleBox"]
