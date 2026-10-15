"""The prompt/schema are generated from the ontology; these tests fail if they drift."""
from __future__ import annotations

from exemplar.contracts.ontology import ENTITY_TYPES, PREDICATES, ZONES
from exemplar.perception import PROMPT_VERSION, build_system_prompt, emit_trace_schema
from exemplar.perception import prompt as P
from exemplar.perception.sampling import SampledFrame


def test_every_predicate_and_zone_is_in_the_prompt_with_its_signature():
    text = build_system_prompt()
    for pred, kinds in PREDICATES.items():
        shown = ", ".join("Package|Object" if k == "Carryable" else k for k in kinds)
        assert f"{pred}({shown})" in text
    for z in ZONES:
        assert f"- {z}:" in text
    for t in ENTITY_TYPES:
        assert t in text


def test_hand_written_hints_cover_the_whole_ontology():
    assert set(P.PREDICATE_HINTS) == set(PREDICATES)
    assert set(P.ZONE_HINTS) == set(ZONES)


def test_prompt_policy_lines():
    text = build_system_prompt()
    assert "IGNORE the Ring watermark" in text
    assert "do not try to recognise anyone" in text and "no face identification" in text


def test_schema_enums_follow_the_ontology():
    s = emit_trace_schema()
    ent = s["properties"]["entities"]["items"]["properties"]
    fact = s["properties"]["frames"]["items"]["properties"]["facts"]["items"]["properties"]
    assert ent["type"]["enum"] == list(ENTITY_TYPES)
    assert fact["pred"]["enum"] == list(PREDICATES)
    assert fact["conf"]["enum"] == ["low", "med", "high"]
    assert s["required"] == ["entities", "frames", "summary"]


def test_parameter_rules_per_model_class():
    fast, strong = P.tool_config(False), P.tool_config(True)
    assert fast["toolChoice"] == {"tool": {"name": "emit_trace"}}
    assert strong["toolChoice"] == {"auto": {}}
    assert P.model_fields(False) == {"thinking": {"type": "disabled"}}
    assert P.model_fields(True) == {"thinking": {"type": "between_tools"}}
    assert "temperature" not in str(P.model_fields(True)) + str(P.model_fields(False))


def test_user_content_captions_and_instruction():
    frames = [SampledFrame(625, b"\xff\xd8a"), SampledFrame(1875, b"\xff\xd8b")]
    c = P.user_content(frames, 2500, strong=False)
    texts = [b["text"] for b in c if "text" in b]
    assert "Frame 0 (t=0.6s)" in texts and "Frame 1 (t=1.9s)" in texts
    imgs = [b for b in c if "image" in b]
    assert len(imgs) == 2 and imgs[0]["image"]["format"] == "jpeg"
    # caption immediately precedes its image
    assert c.index({"text": "Frame 1 (t=1.9s)"}) + 1 == c.index(imgs[1])
    assert "MUST respond by calling" not in c[-1]["text"]
    assert "MUST respond by calling the emit_trace tool" in P.user_content(frames, 2500, strong=True)[-1]["text"]


def test_prompt_version_is_a_nonempty_string():
    assert isinstance(PROMPT_VERSION, str) and PROMPT_VERSION
