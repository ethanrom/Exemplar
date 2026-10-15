"""Prompt, tool schema and request construction for the Bedrock Converse call.

The ontology listing in the system prompt and the `emit_trace` JSON schema are *generated* from
`exemplar.contracts.ontology`, so they cannot drift from what `trace_errors` accepts.  Only the natural-
language hints below are hand-written; `tests/perception/test_perception_prompt.py` fails if a predicate
or zone is added to the ontology without a hint here.

Bump PROMPT_VERSION whenever the system prompt, the schema, the caption format or the parameter rules
change — it is part of the trace cache key.
"""
from __future__ import annotations

from typing import Any, Sequence

from exemplar.contracts.ontology import ENTITY_TYPES, PREDICATES, ZONES

from .sampling import SampledFrame

PROMPT_VERSION = "v2"
TOOL_NAME = "emit_trace"

# Display names for argument kinds (the ontology's "Carryable" is spelled out for the model).
_KIND_TEXT = {"Carryable": "Package|Object"}

# Hand-written semantics.  The key set must equal ontology.PREDICATES (tested).
PREDICATE_HINTS: dict[str, str] = {
    "present": "the entity is visible in this frame. It is IMPLIED by any other fact that names the entity in the same "
               "frame, so assert present(e) only for a visible entity that has no other fact in that frame (this keeps "
               "the output short).",
    "in_zone": "the entity is located in that zone in this frame (a package lying on the steps: in_zone(k1, steps)). "
               "Give every visible person, vehicle and package a zone in every frame in which one of the zones "
               "plausibly fits (cars parked in a lot or on a driveway: driveway; cars on a road: street). Use the "
               "most specific zone; two zones only when clearly overlapping.",
    "near": "the two entities are within about arm's reach / two body-widths of each other in the scene. "
            "Symmetric: assert it once per pair.",
    "carrying": "the person holds or carries the item (in hands or arms) in this frame. Assert it in EVERY frame "
                "in which the item is held, including the frame in which it is picked up. Once a person has picked an item up "
                "and has not set it down, keep asserting carrying (conf low if the item is hard to see) in every "
                "frame in which that person is visible.",
    "picks_up": "the transition frame in which the person's hands take the item off a surface (ground, steps, porch, "
                "car) and lift it, OR the first frame in which the person holds an item that lay on a surface in "
                "earlier frames. Assert it ONLY in that transition frame(s), not while the item is merely held. "
                "A person who just walks past an item without taking it does NOT pick it up.",
    "puts_down": "the transition frame in which the person sets a held item down on a surface, or the first frame "
                 "in which an item that was being carried now rests on a surface. Only in that frame(s).",
    "rings_bell": "the person is pressing the doorbell button (finger on the bell) in this frame.",
    "enters": "the first frame in which the entity is inside that zone after not being there (arrived from outside "
              "the zone or from outside the view, e.g. a car driving into the lot or a person walking onto the steps). "
              "Not asserted for entities already in the zone in frame 0.",
    "leaves": "the last frame in which the entity is still inside that zone when it is gone from the zone in the "
              "following frames (walking/driving out of it or out of view). You see all frames at once, so look "
              "ahead to decide.",
    "facing_camera": "the person's face/front of the head is turned towards the camera in this frame (this is "
                     "NOT identification).",
    "attr": "a label that is true of the entity only in this frame (e.g. holding_umbrella). Clip-level labels go in "
            "the entity's `attrs` instead.",
}

ZONE_HINTS: dict[str, str] = {
    "door": "the entrance door itself / directly in front of it",
    "porch": "the landing or covered area at the door",
    "steps": "stairs or stoop leading up to the door",
    "yard": "lawn, garden or open ground around the house",
    "driveway": "the driveway, parking pad or parking lot",
    "sidewalk": "the public footpath",
    "street": "the road (also a road seen in the distance)",
    "dock": "a loading dock / bay or parking-lot loading area",
}

_CONF_TEXT = "high = clearly visible; med = probably; low = a guess (small, blurry, partly hidden)"


def _sig(pred: str) -> str:
    return f"{pred}({', '.join(_KIND_TEXT.get(k, k) for k in PREDICATES[pred])})"


def build_system_prompt() -> str:
    preds = "\n".join(f"- {_sig(p)}: {PREDICATE_HINTS[p]}" for p in PREDICATES)
    zones = "\n".join(f"- {z}: {ZONE_HINTS[z]}" for z in ZONES)
    etypes = ", ".join(ENTITY_TYPES)
    return f"""You convert frames from a home / business security camera clip into a compact symbolic trace by calling the {TOOL_NAME} tool exactly once.

You receive N frames, each preceded by a caption "Frame i (t=…s)" (i = 0..N-1, t = seconds from the start of the clip window). You see ALL frames at once, so use later frames to decide what is happening in earlier ones.

ENTITIES
- Declare every distinct thing that matters once, with a stable id that is the SAME in every frame it appears in and never reused for something else. Ids: lowercase letter then letters/digits/underscore. Use p1, p2 for people; v1.. vehicles; k1.. packages (boxes, parcels, envelopes, bags delivered or left); a1.. animals; o1.. other objects.
- type is one of: {etypes}.
- attrs are short snake_case open-vocabulary labels that hold for the whole clip (delivery_uniform, hi_vis, hoodie, backpack, suv, cardboard_box, woodpecker). Describe clothing and objects only: do not name anyone and do not try to recognise anyone (no face identification).
- Do not declare an entity that you never assert a fact about. Do not invent entities that are not visible.

FACTS (per frame, only what is visible or happening in THAT frame)
{preds}

ZONES (the Zone argument must be exactly one of these)
{zones}

CONFIDENCE: {_CONF_TEXT}.

RULES
- Every frame index 0..N-1 must appear in `frames`, with an empty `facts` list when nothing is visible.
- Use only the predicates above, with exactly the argument types shown. Entity arguments must be ids you declared.
- Prefer a few correct facts over many speculative ones; do not assert what you cannot see. If no person is visible, declare no person.
- The camera is a Ring device: IGNORE the Ring watermark overlay (logo top-left; device id, app name and timestamp text top-right). It is not part of the scene and must never produce entities or facts.
- Do not identify anyone and do not describe faces. Facts describe positions, actions and objects only.
- `summary` is ONE plain sentence about what happens in the clip.

EXAMPLE (abbreviated, for the format of action facts): a person walks up to a box lying on the steps, lifts it and walks away.
frame 3: in_zone(p1, steps) in_zone(k1, steps) near(p1, k1)
frame 4: in_zone(p1, steps) in_zone(k1, steps) picks_up(p1, k1) carrying(p1, k1)
frame 5: in_zone(p1, steps) carrying(p1, k1) leaves(p1, steps)"""


def emit_trace_schema() -> dict[str, Any]:
    """JSON schema of the `emit_trace` tool input (generated from the ontology)."""
    return {
        "type": "object",
        "required": ["entities", "frames", "summary"],
        "properties": {
            "entities": {"type": "array", "items": {
                "type": "object", "required": ["id", "type", "attrs"],
                "properties": {"id": {"type": "string", "description": "stable across frames, e.g. p1, k1, v1"},
                               "type": {"type": "string", "enum": list(ENTITY_TYPES)},
                               "attrs": {"type": "array", "items": {"type": "string"}}}}},
            "frames": {"type": "array", "items": {
                "type": "object", "required": ["i", "facts"],
                "properties": {"i": {"type": "integer", "description": "frame index 0..N-1"},
                               "facts": {"type": "array", "items": {
                                   "type": "object", "required": ["pred", "args", "conf"],
                                   "properties": {"pred": {"type": "string", "enum": list(PREDICATES)},
                                                  "args": {"type": "array", "items": {"type": "string"}},
                                                  "conf": {"type": "string", "enum": ["low", "med", "high"]}}}}}}},
            "summary": {"type": "string"},
        },
    }


def tool_config(strong: bool) -> dict[str, Any]:
    cfg: dict[str, Any] = {"tools": [{"toolSpec": {"name": TOOL_NAME, "description": "Emit the symbolic trace.",
                                                   "inputSchema": {"json": emit_trace_schema()}}}]}
    # Strong model: forced tool choice ("tool"/"any") is rejected -> auto + explicit instruction.
    cfg["toolChoice"] = {"auto": {}} if strong else {"tool": {"name": TOOL_NAME}}
    return cfg


def model_fields(strong: bool) -> dict[str, Any]:
    # Fast: forced toolChoice needs thinking disabled.  Strong: "disabled" is rejected, use "between_tools".
    # Never send `temperature` (deprecated for these models).
    return {"thinking": {"type": "between_tools" if strong else "disabled"}}


def caption(i: int, t_ms: int) -> str:
    return f"Frame {i} (t={t_ms / 1000:.1f}s)"


def user_content(frames: Sequence[SampledFrame], window_ms: int, strong: bool) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {"text": f"Clip window: {window_ms / 1000:.1f} s, {len(frames)} frames (indices 0..{len(frames) - 1})."}]
    for i, fr in enumerate(frames):
        content.append({"text": caption(i, fr.t_ms)})
        content.append({"image": {"format": "jpeg", "source": {"bytes": fr.jpeg}}})
    final = f"Call {TOOL_NAME} now with the entities, the facts of every frame, and a one-sentence summary."
    if strong:
        final += f" You MUST respond by calling the {TOOL_NAME} tool exactly once; do not answer in plain text."
    content.append({"text": final})
    return content


def retry_text(errors: Sequence[str]) -> str:
    shown = list(errors[:25])
    more = f"\n(+{len(errors) - 25} more)" if len(errors) > 25 else ""
    return ("Validation failed. Fix every problem below and call "
            f"{TOOL_NAME} again with the complete corrected trace:\n" + "\n".join(f"- {e}" for e in shown) + more)
