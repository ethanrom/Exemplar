"""Perception (stream B): clip -> frames -> Claude on Bedrock -> symbolic `Trace` (PLAN.md §2.1).

    from exemplar.perception import perceive, sample_frames, PROMPT_VERSION
    trace = perceive("clip.mp4", clip_id="evt123", source="ring", mode="fast")

CLI: ``uv run --project engine python -m exemplar.perception CLIP [--strong] [--n 16] [--start S --dur L] [--roi x,y,w,h]``
"""
from .extract import PerceptionBackendError
from .merge import merge_traces
from .pipeline import PerceptionReport, PerceptionResult, perceive, perceive_detailed
from .prompt import PROMPT_VERSION, build_system_prompt, emit_trace_schema
from .sampling import SampledFrame, SamplingError, probe, sample_frames, sample_window

__all__ = ["PROMPT_VERSION", "PerceptionBackendError", "PerceptionReport", "PerceptionResult", "SampledFrame", "SamplingError", "build_system_prompt",
           "emit_trace_schema", "merge_traces", "perceive", "perceive_detailed", "probe", "sample_frames",
           "sample_window"]
