"""The Strands plumbing (agent, tools, rounds, feedback) driven by a scripted fake model: no Bedrock, no cost.

The fake `strands.models.Model` answers each model call with the next scripted turn: either a tool call or plain text.
This checks what the live run depends on: tool schemas build, tool results flow back, `submit_sketches` rejects bad
sketches with the typechecker's message, round 2 sees the counterexamples, and token usage is accounted.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from strands.models import Model

from exemplar.agent import StrandsProposer, run_cegis
from exemplar.synth import Example
from dsl_helpers import load


class FakeModel(Model):
    def __init__(self, turns: list):
        self.turns = list(turns)
        self.calls: list[list[dict]] = []

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> Any:
        return {}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):  # pragma: no cover
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, *, tool_choice=None, **kwargs):
        self.calls.append(json.loads(json.dumps(messages, default=str)))
        assert tool_choice is None or "auto" in str(tool_choice), "forced tool choice is rejected by the strong model"
        turn = self.turns.pop(0)
        yield {"messageStart": {"role": "assistant"}}
        if turn[0] == "tool":
            _, name, args = turn
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{len(self.calls)}", "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": turn[1]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 100, "outputTokens": 10, "totalTokens": 110},
                            "metrics": {"latencyMs": 1}}}


def _theft():
    return [Example(load("theft_a"), True, 3, "theft_a"), Example(load("theft_b"), True, 3, "theft_b"),
            Example(load("delivery_a"), False, 3, "delivery_a"), Example(load("delivery_b"), False, 3, "delivery_b"),
            Example(load("unattended_package"), False, 1, "unattended_package"),
            Example(load("visitor_no_ring"), False, 1, "visitor_no_ring")]


GOOD = "exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)"
WEAK = "exists p: Person, k: Package: eventually[?a, ?b] (picks_up(p, k) and carrying(p, k))"


def _texts(messages) -> str:
    return json.dumps(messages)


def test_agent_round_trip_with_tools_and_feedback():
    model = FakeModel([
        # round 1: typecheck, one bad sketch rejected by submit_sketches, then a corrected one and a weak one
        ("tool", "typecheck_sketch", {"sketch": "exists p: Person: rings_bell(p, p)"}),
        ("tool", "solve_sketch", {"sketch": GOOD}),
        ("tool", "submit_sketches", {"sketches": ["exists p: Person: rings_bell(p, p)", GOOD, WEAK]}),
        ("text", "Submitted two sketches."),
        # round 2: look at the counterexamples, then resubmit a variation
        ("tool", "fetch_counterexamples", {}),
        ("tool", "evaluate", {"rule_text": "exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k)",
                              "clip_id": "theft_a"}),
        ("tool", "submit_sketches", {"sketches": ["exists p: Person, k: Package: eventually[?a, ?b] picks_up(p, k)"]}),
        ("text", "Done."),
    ])
    prop = StrandsProposer(model)
    events: list[dict] = []
    out = run_cegis(_theft(), nl_hint="package theft", emit=events.append, model=prop, k=6, max_rounds=2,
                    backfill=False)
    types = [e["type"] for e in events]
    assert types.count("typecheck_failed") == 1           # the rings_bell(p, p) sketch
    assert types.count("sketch_proposed") == 3            # GOOD (tried by hand, then submitted), WEAK, round-2 sketch
    assert types.count("solve_result") == 3 and types.count("solve_started") == 3   # no sketch is solved twice
    results = {e["sketch"]: e for e in events if e["type"] == "solve_result"}
    assert results[next(s for s in results if "carrying" in s and "eventually" not in s)]["result"] == "sat"
    assert any(e["result"] == "unsat" for e in results.values())                     # WEAK never fits a positive
    # round-2 prompt carries the solver output and the counterexample section
    round2_prompt = model.calls[4][-1]["content"][0]["text"] if "text" in model.calls[4][-1]["content"][0] else ""
    assert "Round 2" in round2_prompt and "UNSAT" in round2_prompt
    # the first model call is the task: it contains the rendered positive and negative traces and the system prompt knows the ontology
    first = _texts(model.calls[0])
    assert "clip_id=theft_a" in first and "POSITIVE" in first and "NEGATIVE" in first
    # tool results reached the model
    assert "problems" in _texts(model.calls[1]) and "argument" in _texts(model.calls[1])
    assert "REJECTED" in _texts(model.calls[3])
    assert "MATCH" in _texts(model.calls[6]) or "match" in _texts(model.calls[6])
    assert len(out) == 2 and all(c.violated_clip_ids == () for c in out)
    assert prop.usage["calls"] == 2 and prop.usage["inputTokens"] > 0
    assert not model.turns, "every scripted turn was used"


def test_prose_answer_is_salvaged():
    model = FakeModel([("text", f"Here is my sketch:\n{GOOD}\nthat is all")])
    out = run_cegis(_theft(), nl_hint=None, emit=lambda e: None, model=StrandsProposer(model), k=1, max_rounds=1,
                    backfill=False)
    assert len(out) == 1


def test_solve_budget_per_round():
    from exemplar.agent.state import RunState
    from exemplar.agent.tools import build_tools
    st = RunState(_theft(), lambda e: None, k=2, max_agent_solves_per_round=1)
    st.start_round(1)
    tools = {t.tool_name: t for t in build_tools(st)}
    r1 = tools["solve_sketch"](sketch=GOOD)
    r2 = tools["solve_sketch"](sketch="exists p: Person: eventually[?a, ?b] rings_bell(p)")
    assert "SAT" in r1.upper() and "budget" in r2
