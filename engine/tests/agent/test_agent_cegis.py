"""The CEGIS loop with deterministic proposers (no Bedrock): events, ranking, counterexample feedback, cancellation."""
from __future__ import annotations

import threading

import pytest

from exemplar.agent import run_cegis
from exemplar.agent.templates import TemplateProposer, build_templates
from exemplar.dsl import parse, to_text
from exemplar.synth import Candidate, EncoderMismatch, Example, mdl
from dsl_helpers import load


def _theft():
    return [Example(load("theft_a"), True, 3, "theft_a"), Example(load("theft_b"), True, 3, "theft_b"),
            Example(load("delivery_a"), False, 3, "delivery_a"), Example(load("delivery_b"), False, 3, "delivery_b"),
            Example(load("unattended_package"), False, 1, "unattended_package"),
            Example(load("visitor_no_ring"), False, 1, "visitor_no_ring")]


class Script:
    """Proposer returning scripted sketches per round; records the contexts it was given."""
    name = "script"

    def __init__(self, rounds):
        self.rounds, self.seen = rounds, []

    def propose(self, ctx):
        self.seen.append((ctx.round, ctx.feedback() if ctx.round > 1 else ""))
        return self.rounds[ctx.round - 1] if ctx.round <= len(self.rounds) else []


def _run(examples, proposer, **kw):
    events: list[dict] = []
    out = run_cegis(examples, nl_hint="package theft", emit=events.append, model=proposer, **kw)
    return out, events


def test_events_ranking_and_candidates():
    good = "exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)"
    complex_ = ("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k) "
                "and not attr(p, delivery_uniform)")
    bad_type = "exists p: Person: rings_bell(p, p)"
    bad_syntax = "exists p Person picks_up(p"
    out, ev = _run(_theft(), Script([[bad_type, bad_syntax, complex_, good]]), k=3, max_rounds=1, backfill=False)
    types = [e["type"] for e in ev]
    assert types[0] == "round_started" and types[-2:] == ["candidates", "done"]
    assert types.count("typecheck_failed") == 2
    assert types.count("sketch_proposed") == 2
    assert types.count("solve_started") == 2 and types.count("solve_result") == 2
    assert types.count("differential_check") == 2
    err = next(e for e in ev if e["type"] == "typecheck_failed")
    assert "rings_bell" in err["error"] and "argument" in err["error"] or "takes 1 argument" in err["error"]
    res = [e for e in ev if e["type"] == "solve_result"]
    assert all(e["result"] == "sat" and e["violated_clip_ids"] == [] and e["margin"] > 0 for e in res)
    assert all(set(e["holes"]) == {"a", "b"} for e in res)
    # ranked by MDL ascending: the simpler sketch first
    assert len(out) == 2 and all(isinstance(c, Candidate) for c in out)
    assert out[0].mdl < out[1].mdl
    assert out[0].dsl_text.startswith("exists p: Person, k: Package: picks_up(p, k) then[0, ")
    assert out[0].english.startswith("There is a person p and a package k")
    assert out[0].sketch is not None and to_text(out[0].sketch) == out[0].sketch_text
    assert "?a" in out[0].sketch_text and "?" not in out[0].dsl_text
    assert out[0].mdl == pytest.approx(mdl(out[0].sketch, 0))


def test_candidate_to_api_matches_rule_summary_shape():
    out, _ = _run(_theft(), Script([["exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)"]]),
                  k=1, max_rounds=1, backfill=False)
    api = out[0].to_api(id="r1", concept_id="c1")
    for key in ("id", "concept_id", "dsl_text", "english", "margin", "mdl", "status"):
        assert key in api
    assert api["status"] == "candidate" and api["holes"] == out[0].holes
    assert parse(api["dsl_text"]) == out[0].rule


def test_counterexamples_reach_the_proposer_and_are_emitted():
    # delivery_a-style: this sketch accepts any pick-up, then fits the positives but also a negative? no - use one that fails a positive
    misses_b = "exists p: Person, k: Package: eventually[?a, ?b] (picks_up(p, k) and carrying(p, k))"   # never co-occur
    ok = "exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)"
    script = Script([[misses_b], [ok]])
    out, ev = _run(_theft(), script, k=2, max_rounds=2, backfill=False)
    first = next(e for e in ev if e["type"] == "solve_result")
    assert first["result"] == "unsat"
    # round 2 feedback names the sketch and why it failed
    r2 = dict(script.seen)[2]
    assert "UNSAT" in r2 and "eventually" in r2
    assert out and out[0].violated_clip_ids == ()


def test_noisy_example_gives_counterexample_event_and_a_ranked_candidate():
    ex = _theft() + [Example(load("delivery_a"), True, 1, "mislabelled")]
    out, ev = _run(ex, Script([["exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)"]]),
                   k=1, max_rounds=1, backfill=False)
    cx = [e for e in ev if e["type"] == "counterexample"]
    assert len(cx) == 1 and cx[0]["violated_clip_ids"] == ["mislabelled"]
    assert "mislabelled" not in cx[0]["message"] and "perception suspect" in cx[0]["message"]    # the UI shows the message: no raw ids
    assert out[0].violated_clip_ids == ("mislabelled",)
    assert out[0].mdl == pytest.approx(mdl(out[0].sketch, 1.0))          # one violated bulk example (weight 1)


def test_stops_when_k_consistent_found():
    sketches = ["exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)",
                "exists p: Person, k: Package: eventually[?a, ?b] picks_up(p, k)"]
    script = Script([sketches, ["exists p: Person: eventually[?a, ?b] in_zone(p, steps)"]])
    out, ev = _run(_theft(), script, k=2, max_rounds=4, backfill=False)
    assert len([e for e in ev if e["type"] == "round_started"]) == 1       # K = 2 consistent after round 1
    assert len(out) == 2


def test_template_proposer_finds_theft_rules_offline():
    out, ev = _run(_theft(), TemplateProposer(), k=4, max_rounds=3)
    assert len(out) >= 3 and all(not c.violated_clip_ids for c in out[:3])
    assert [c.mdl for c in out] == sorted(c.mdl for c in out)
    assert any(e["type"] == "differential_check" for e in ev)


def test_templates_are_deterministic_and_use_only_positive_facts():
    a, b = build_templates(_theft()), build_templates(_theft())
    assert a == b and a
    assert all("rings_bell" not in t for t in a)        # never seen in the positives
    assert all(not parse(t) is None for t in a)


def test_cancel_before_start_returns_immediately():
    cancel = threading.Event()
    cancel.set()
    out, ev = _run(_theft(), TemplateProposer(), cancel=cancel)
    assert out == [] and ev[-1] == {"type": "done", "message": "cancelled"}


def test_cancel_between_rounds():
    cancel = threading.Event()

    def proposer(ctx):
        if ctx.round == 1:
            cancel.set()                                   # the user hits stop while round 1 is thinking
            return ["exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)"]
        raise AssertionError("must not be asked again")

    out, ev = _run(_theft(), proposer, cancel=cancel, max_rounds=4)
    assert ev[-1]["message"] == "cancelled"
    assert not any(e["type"] == "solve_result" for e in ev)


def test_function_proposer_and_dedupe():
    s = "exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)"
    out, ev = _run(_theft(), lambda ctx: [s, s.replace("[?a, ?b]", "[ ?a ,?b ]")], k=2, max_rounds=1, backfill=False)
    assert sum(e["type"] == "solve_started" for e in ev) == 1 and len(out) == 1


def test_needs_a_positive():
    out, ev = _run([Example(load("delivery_a"), False, 1)], TemplateProposer())
    assert out == [] and ev[-1]["type"] == "done"


def test_encoder_mismatch_is_not_swallowed(monkeypatch):
    import exemplar.synth.solve as S
    real = S._score_all
    monkeypatch.setattr(S, "_score_all", lambda cr, preps, pt: [-s for s in real(cr, preps, pt)])
    events: list[dict] = []
    with pytest.raises(EncoderMismatch):
        run_cegis(_theft(), nl_hint=None, emit=events.append,
                  model=Script([["exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)"]]))
    assert any(e["type"] == "error" for e in events)


def test_llm_unavailable_falls_back_to_templates(monkeypatch):
    from exemplar.agent import llm

    def boom(*a, **k):
        raise llm.ProposerUnavailable("Bedrock settings are missing")

    monkeypatch.setattr(llm, "build_bedrock_model", boom)
    out, ev = _run(_theft(), llm.StrandsProposer(), k=3, max_rounds=2)
    assert out and any("template library" in (e.get("message") or "") for e in ev)


def test_events_and_rule_summary_validate_against_api_yaml():
    import json
    from pathlib import Path

    import yaml
    from jsonschema import Draft202012Validator

    contracts = Path(__file__).parents[2] / "exemplar" / "contracts"
    spec = yaml.safe_load((contracts / "api.yaml").read_text(encoding="utf-8"))
    run_event = Draft202012Validator(spec["components"]["schemas"]["RunEvent"])
    summary = dict(spec["components"]["schemas"]["RuleSummary"])
    summary["properties"] = {k: v for k, v in summary["properties"].items() if k not in ("ast", "calibration")}
    summary_v = Draft202012Validator(summary)
    rule_v = Draft202012Validator(json.loads((contracts / "schemas" / "Rule.json").read_text(encoding="utf-8")))

    ex = _theft() + [Example(load("delivery_a"), True, 1, "mislabelled")]
    script = Script([["exists p: Person: rings_bell(p, p)",
                      "exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)"]])
    out, events = _run(ex, script, k=2, max_rounds=1, backfill=False)
    assert {"round_started", "typecheck_failed", "sketch_proposed", "solve_started", "solve_result",
            "differential_check", "counterexample", "candidates", "done"} <= {e["type"] for e in events}
    for i, e in enumerate(events):
        run_event.validate({**e, "seq": i, "at_ms": i})
    for c in out:
        api = c.to_api(id="r1", concept_id="c1")
        summary_v.validate({k: v for k, v in api.items() if k not in ("ast", "calibration")})
        rule_v.validate(api["ast"])
