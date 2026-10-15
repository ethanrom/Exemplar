"""Concepts, labels (provenance rules), random sampling, teach runs (+ SSE), rules listing, questions."""
from __future__ import annotations

import json
import threading
from collections import Counter

import pytest

from exemplar.contracts.dsl_ast import Rule
from exemplar.dsl import parse, to_english, to_text

from . import helpers as H
from .conftest import validate_component

ALL = H.ALL_FIXTURES
run_teach, parse_sse = H.run_teach, H.parse_sse


@pytest.fixture
def tenv(env):
    env.seed_fixture_events(*ALL)
    env.seed_fixture_events("perception_failed")
    env.cid = env.new_concept()
    return env


# ------------------------------------------------------------------------------------------ concepts
def test_create_and_list_concepts(env):
    r = env.client.post("/concepts", json={"name": "  vehicle in lot  "})
    assert r.status_code == 201
    c = r.json()
    assert c["name"] == "vehicle in lot" and c["alpha"] == 0.1 and c["nl_hint"] is None
    assert c["deployed_rule_id"] is None
    assert c["counts"] == {f"{p}_{v}": 0 for p in ("example", "active", "random") for v in ("pos", "neg")}
    c2 = env.client.post("/concepts", json={"name": "theft", "nl_hint": "takes the box", "alpha": 0.2}).json()
    assert [x["id"] for x in env.client.get("/concepts").json()] == [c["id"], c2["id"]]
    assert c2["nl_hint"] == "takes the box" and c2["alpha"] == 0.2


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "x", "alpha": 0}, {"name": "x", "alpha": 1}])
def test_create_concept_validation(env, body):
    assert env.client.post("/concepts", json=body).status_code == 400


# ------------------------------------------------------------------------------------------ labels
def test_put_label_replaces_and_deletes(tenv):
    cid = tenv.cid
    r = tenv.label(cid, "theft_a", "pos")
    assert r.json() == {"concept_id": cid, "clip_id": "theft_a", "value": "pos", "provenance": "example", "weight": 3.0}
    assert tenv.label(cid, "theft_a", "neg", "active").json()["weight"] == 3.0                    # replaces, one per clip
    labels = tenv.client.get(f"/concepts/{cid}/labels").json()
    assert len(labels) == 1 and labels[0]["value"] == "neg" and labels[0]["provenance"] == "active"
    gone = tenv.label(cid, "theft_a", None).json()
    assert gone["value"] is None and gone["clip_id"] == "theft_a"
    assert tenv.client.get(f"/concepts/{cid}/labels").json() == []


def test_concept_counts_follow_labels(tenv):
    cid = tenv.cid
    tenv.label(cid, "theft_a", "pos")
    tenv.label(cid, "theft_b", "pos")
    tenv.label(cid, "delivery_a", "neg", "active")
    counts = [c for c in tenv.client.get("/concepts").json() if c["id"] == cid][0]["counts"]
    assert counts["example_pos"] == 2 and counts["active_neg"] == 1 and counts["random_neg"] == 0


def test_label_errors(tenv):
    cid = tenv.cid
    assert tenv.label("cn_nope", "theft_a", "pos").status_code == 404
    assert tenv.label(cid, "nope", "pos").status_code == 404
    assert tenv.client.put(f"/concepts/{cid}/labels", json={"clip_id": "theft_a", "value": "maybe", "provenance": "example"}).status_code == 400
    assert tenv.client.put(f"/concepts/{cid}/labels", json={"clip_id": "theft_a", "value": "pos", "provenance": "magic"}).status_code == 400
    assert tenv.client.get("/concepts/cn_nope/labels").status_code == 404


def test_random_provenance_only_for_clips_drawn_by_random_sample(tenv):
    cid = tenv.cid
    r = tenv.label(cid, "theft_a", "neg", "random")
    assert r.status_code == 400 and r.json()["code"] == "INVALID_PROVENANCE"
    drawn = tenv.client.post(f"/concepts/{cid}/random-sample?n=3&seed=1").json()
    ok = tenv.label(cid, drawn[0]["clip_id"], "neg", "random")
    assert ok.status_code == 200 and ok.json()["weight"] == 1.0 and ok.json()["provenance"] == "random"
    undrawn = next(c for c in ALL if c not in {d["clip_id"] for d in drawn})
    assert tenv.label(cid, undrawn, "neg", "random").status_code == 400
    # deleting a label does not need the pool check
    assert tenv.label(cid, undrawn, None, "random").status_code == 200


def test_bulk_negative(tenv):
    cid = tenv.cid
    r = tenv.client.post(f"/concepts/{cid}/labels/bulk-negative",
                         json={"clip_ids": ["delivery_a", "delivery_b", "delivery_a"], "provenance": "example"})
    assert r.status_code == 200 and r.json()["value"] == "neg" and r.json()["weight"] == 1.0
    labels = {l["clip_id"]: l for l in tenv.client.get(f"/concepts/{cid}/labels").json()}
    assert set(labels) == {"delivery_a", "delivery_b"} and all(l["weight"] == 1.0 and l["value"] == "neg" for l in labels.values())


def test_bulk_negative_validation_and_random_rule(tenv):
    cid = tenv.cid
    url = f"/concepts/{cid}/labels/bulk-negative"
    assert tenv.client.post(url, json={"clip_ids": [], "provenance": "example"}).status_code == 400
    assert tenv.client.post(url, json={"clip_ids": ["theft_a"], "provenance": "active"}).status_code == 400
    assert tenv.client.post(url, json={"clip_ids": ["nope"], "provenance": "example"}).status_code == 404
    r = tenv.client.post(url, json={"clip_ids": ["theft_a"], "provenance": "random"})
    assert r.status_code == 400 and r.json()["code"] == "INVALID_PROVENANCE"
    drawn = [d["clip_id"] for d in tenv.client.post(f"/concepts/{cid}/random-sample?n=4&seed=2").json()]
    assert tenv.client.post(url, json={"clip_ids": drawn, "provenance": "random"}).status_code == 200
    assert {l["provenance"] for l in tenv.client.get(f"/concepts/{cid}/labels").json()} == {"random"}
    assert tenv.client.post("/concepts/cn_nope/labels/bulk-negative", json={"clip_ids": ["a"], "provenance": "example"}).status_code == 404


# ------------------------------------------------------------------------------------------ random sample
def test_random_sample_is_seeded_unlabelled_and_traced(tenv):
    cid = tenv.cid
    tenv.label(cid, "theft_a", "pos")
    a = tenv.client.post(f"/concepts/{cid}/random-sample?n=5&seed=7").json()
    b = tenv.client.post(f"/concepts/{cid}/random-sample?n=5&seed=7").json()
    c = tenv.client.post(f"/concepts/{cid}/random-sample?n=5&seed=8").json()
    ids = lambda xs: [x["clip_id"] for x in xs]          # noqa: E731
    assert ids(a) == ids(b) and ids(a) != ids(c) and len(a) == 5 == len(set(ids(a)))
    assert "theft_a" not in ids(a) + ids(c)                                  # labelled clips are not sampled
    assert "perception_failed" not in ids(a) + ids(c)                        # nor clips without an ok trace
    assert all(x["label"] is None and x["trace_status"] == "ok" for x in a)


def test_random_sample_is_uniform_over_the_pool(tenv):
    cid = tenv.cid
    pool = set(ALL)
    hits = Counter(tenv.client.post(f"/concepts/{cid}/random-sample?n=1&seed={s}").json()[0]["clip_id"] for s in range(300))
    assert set(hits) == pool
    assert min(hits.values()) > 300 / len(pool) / 2 and max(hits.values()) < 300 / len(pool) * 2


def test_random_sample_edges(tenv):
    cid = tenv.cid
    assert len(tenv.client.post(f"/concepts/{cid}/random-sample?n=50&seed=1").json()) == len(ALL)       # pool smaller than n
    assert tenv.client.post(f"/concepts/{cid}/random-sample?n=0").status_code == 400
    assert tenv.client.post(f"/concepts/{cid}/random-sample?n=51").status_code == 400
    assert tenv.client.post("/concepts/cn_nope/random-sample").status_code == 404
    assert len(tenv.client.post(f"/concepts/{cid}/random-sample").json()) == 10                            # default n


def test_random_sample_empty_pool(env):
    cid = env.new_concept()
    assert env.client.post(f"/concepts/{cid}/random-sample").json() == []


# ------------------------------------------------------------------------------------------ teach
def _label_for_teach(env):
    cid = env.cid
    env.label(cid, "theft_a", "pos")
    env.label(cid, "theft_b", "pos")
    env.label(cid, "delivery_a", "neg")
    env.label(cid, "unattended_package", "neg", "active")
    return cid


def test_teach_run_uses_only_example_and_active_labels(tenv):
    cid = _label_for_teach(tenv)
    drawn = tenv.client.post(f"/concepts/{cid}/random-sample?n=2&seed=3").json()
    for d in drawn:
        assert tenv.label(cid, d["clip_id"], "pos", "random").status_code == 200
    tenv.label(cid, "perception_failed", "pos")                              # no ok trace -> cannot be an example
    run = run_teach(tenv, cid)
    assert run["status"] == "done" and run["error"] is None and run["finished_at_ms"] >= run["started_at_ms"]
    call = tenv.cegis.calls[0]
    got = {e.clip_id: (e.positive, e.weight) for e in call["examples"]}
    assert got == {"theft_a": (True, 3.0), "theft_b": (True, 3.0), "delivery_a": (False, 3.0),
                   "unattended_package": (False, 3.0)}
    assert call["nl_hint"] == "someone takes a package" and call["k"] == 6 and call["max_rounds"] == 4
    assert all(e.trace.status == "ok" for e in call["examples"])


def test_teach_events_are_sequenced_stored_and_valid(tenv):
    cid = _label_for_teach(tenv)
    run = run_teach(tenv, cid)
    stored = tenv.state.store.runs.events(run["id"])
    assert [e["seq"] for e in stored] == list(range(1, len(stored) + 1))
    types = [e["type"] for e in stored]
    assert types[:4] == ["round_started", "sketch_proposed", "typecheck_failed", "solve_result"]
    assert types[-3:] == ["candidates", "question_ready", "done"] and types.count("done") == 1     # the proposer's own `done` is dropped
    assert all(isinstance(e["at_ms"], int) and e["at_ms"] > 0 for e in stored)
    for e in stored:
        validate_component("RunEvent", e)
    solve = next(e for e in stored if e["type"] == "solve_result")
    assert solve["holes"] == {"b": 6.0} and solve["margin"] == 0.3                # numpy scalars serialised
    rules = tenv.client.get(f"/concepts/{cid}/rules").json()
    cand = next(e for e in stored if e["type"] == "candidates")
    assert cand["rule_ids"] == [r["id"] for r in rules]


def test_teach_creates_ranked_rules_with_printer_text(tenv):
    cid = _label_for_teach(tenv)
    run_teach(tenv, cid)
    rules = tenv.client.get(f"/concepts/{cid}/rules").json()
    assert [r["mdl"] for r in rules] == [21.0, 24.0]
    r0 = rules[0]
    assert r0["dsl_text"] == to_text(parse(H.THEFT_DSL)) and r0["english"] == to_english(parse(H.THEFT_DSL))
    assert r0["sketch_text"] == H.THEFT_SKETCH and r0["holes"] == {"b": 6.0} and r0["margin"] == 0.3
    assert r0["status"] == "candidate" and r0["actions"] == ["ui"] and r0["calibration"] is None
    assert Rule.model_validate(r0["ast"]) == parse(H.THEFT_DSL)
    assert tenv.client.get(f"/rules/{r0['id']}").json() == r0


def test_teach_stream_replays_and_resumes_from_last_event_id(tenv):
    cid = _label_for_teach(tenv)
    run = run_teach(tenv, cid)
    with tenv.client.stream("GET", f"/runs/{run['id']}/stream") as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        frames = parse_sse(r.iter_lines())
    stored = tenv.state.store.runs.events(run["id"])
    assert [f["id"] for f in frames] == [str(e["seq"]) for e in stored]
    assert [f["event"] for f in frames] == [e["type"] for e in stored]
    assert json.loads(frames[0]["data"]) == stored[0]
    with tenv.client.stream("GET", f"/runs/{run['id']}/stream", headers={"Last-Event-ID": "4"}) as r:
        later = parse_sse(r.iter_lines())
    assert [f["id"] for f in later] == [str(e["seq"]) for e in stored if e["seq"] > 4]


def test_teach_stream_follows_a_live_run(make_env):
    tenv = make_env(serve=True)
    tenv.seed_fixture_events(*ALL)
    tenv.cid = tenv.new_concept()
    cid = _label_for_teach(tenv)
    tenv.cegis.gate = threading.Event()
    run = tenv.client.post(f"/concepts/{cid}/teach").json()
    assert run["status"] == "running" and run["finished_at_ms"] is None
    got: list[dict] = []
    started = threading.Event()

    def reader():
        with tenv.client.stream("GET", f"/runs/{run['id']}/stream") as r:
            buf = []
            for line in r.iter_lines():
                buf.append(line)
                if line == "":
                    got[:] = parse_sse(buf)
                    if got:
                        started.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    assert started.wait(10), "no event arrived while the run was still going"
    assert tenv.client.get(f"/runs/{run['id']}").json()["status"] == "running"
    assert "candidates" not in [f["event"] for f in got]
    tenv.cegis.gate.set()
    t.join(15)
    assert not t.is_alive(), "stream did not close after the run finished"
    assert [f["event"] for f in got][-3:] == ["candidates", "question_ready", "done"]


def test_second_teach_while_running_is_409(tenv):
    cid = _label_for_teach(tenv)
    tenv.cegis.gate = threading.Event()
    first = tenv.client.post(f"/concepts/{cid}/teach")
    assert first.status_code == 202
    second = tenv.client.post(f"/concepts/{cid}/teach")
    assert second.status_code == 409 and second.json()["code"] == "RUN_IN_PROGRESS"
    other = tenv.new_concept("other")
    tenv.label(other, "theft_a", "pos")
    assert tenv.client.post(f"/concepts/{other}/teach").status_code == 202           # per concept, not global
    tenv.cegis.gate.set()
    H.wait_until(lambda: tenv.client.get(f"/runs/{first.json()['id']}").json()["status"] == "done")
    H.wait_until(lambda: tenv.client.post(f"/concepts/{cid}/teach").status_code == 202, what="new run once the first ended")


def test_teach_failure_is_reported_on_the_run_and_stream(tenv):
    cid = _label_for_teach(tenv)
    tenv.cegis.error = RuntimeError("Bedrock throttled")
    run = run_teach(tenv, cid)
    assert run["status"] == "failed" and "Bedrock throttled" in run["error"]
    stored = tenv.state.store.runs.events(run["id"])
    assert stored[-1]["type"] == "error" and "Bedrock throttled" in stored[-1]["message"]
    assert "done" not in [e["type"] for e in stored] and tenv.client.get(f"/concepts/{cid}/rules").json() == []
    validate_component("RunEvent", stored[-1])


def test_teach_without_a_positive_example_fails_the_run_clearly(tenv):
    cid = tenv.cid
    tenv.label(cid, "delivery_a", "neg")
    run = run_teach(tenv, cid)
    assert run["status"] == "failed" and "positive" in run["error"]
    assert tenv.cegis.calls == []


def test_teach_unknown_concept_and_run(env):
    assert env.client.post("/concepts/cn_nope/teach").status_code == 404
    assert env.client.get("/runs/run_nope").status_code == 404
    assert env.client.get("/runs/run_nope/stream").status_code == 404


def test_teach_503_when_synthesis_is_unavailable(make_env):
    env = make_env(disable=("run_cegis",))
    env.seed_fixture_events("theft_a")
    cid = env.new_concept()
    env.label(cid, "theft_a", "pos")
    r = env.client.post(f"/concepts/{cid}/teach")
    assert r.status_code == 503 and r.json()["error"].endswith("not available yet")
    assert env.state.store.runs.latest_for_concept(cid) is None                  # nothing half-created


def test_missing_modules_surface_as_503_by_default(make_env):
    """Without injected fakes the real `exemplar.synth` / `exemplar.agent` are imported lazily: 503 if they cannot be imported."""
    from exemplar.api import Services
    env = make_env()
    env.state.services = Services(perceive=env.perceive)       # no overrides: resolved by import
    env.seed_fixture_events("theft_a")
    cid = env.new_concept()
    env.label(cid, "theft_a", "pos")
    import importlib
    try:
        importlib.import_module("exemplar.agent").run_cegis
        available = True
    except (ImportError, AttributeError):
        available = False
    r = env.client.post(f"/concepts/{cid}/teach")
    assert (r.status_code == 202) if available else (r.status_code == 503)


def test_retraining_reuses_identical_rules_and_retires_stale_candidates(tenv):
    cid = _label_for_teach(tenv)
    run_teach(tenv, cid)
    first = tenv.client.get(f"/concepts/{cid}/rules").json()
    run_teach(tenv, cid)
    again = tenv.client.get(f"/concepts/{cid}/rules").json()
    assert [r["id"] for r in again] == [r["id"] for r in first]
    tenv.cegis.candidates = [H.make_candidate("exists p: Person: eventually[0, 10] in_zone(p, steps)",
                                              "exists p: Person: eventually[0, ?b] in_zone(p, steps)",
                                              mdl=18.0, margin=0.4, holes={"b": 10.0})]
    run_teach(tenv, cid)
    now = tenv.client.get(f"/concepts/{cid}/rules").json()
    assert len(now) == 1 and now[0]["mdl"] == 18.0                               # earlier candidates superseded
    assert tenv.state.store.rules.get(first[0]["id"]).status == "retired"


def test_teach_run_cost_ledger_picks_up_reported_sketch_tokens(tenv):
    cid = _label_for_teach(tenv)
    tenv.cegis.extra_events = [{"type": "sketch_proposed", "round": 2, "sketch": H.THEFT_SKETCH, "tokens_in": 900, "tokens_out": 120}]
    run_teach(tenv, cid)
    assert tenv.state.store.cost.totals()["sketch"] == {"calls": 1, "tokens_in": 900, "tokens_out": 120}


# ------------------------------------------------------------------------------------------ question
def test_question_is_the_committee_disagreement_clip(tenv):
    cid = tenv.cid
    tenv.label(cid, "theft_a", "pos")
    tenv.label(cid, "delivery_a", "neg")
    run_teach(tenv, cid)
    q = tenv.client.get(f"/concepts/{cid}/question")
    assert q.status_code == 200
    body = q.json()
    assert body["clip_id"] == "theft_b" and body["p"] == 0.5 and body["committee_size"] == 2
    assert body["event"]["id"] == "fx_theft_b" and body["event"]["trace_status"] == "ok"
    labelled_clips = tenv.active.query_calls[-1]
    assert "theft_a" not in labelled_clips and "delivery_a" not in labelled_clips     # only unlabelled clips are candidates
    call = tenv.active.committee_calls[-1]
    assert [c.dsl_text for c in call["candidates"]] == [to_text(parse(H.THEFT_DSL)), to_text(parse(H.SITTING_DSL))]
    assert {e.clip_id for e in call["examples"]} == {"theft_a", "delivery_a"}
    assert call["mdl_temperature"] == 8.0                                               # gentler than exp(-MDL): keeps real disagreement visible
    assert tenv.active.query_kwargs[-1] == {"labelled": ["delivery_a", "theft_a"], "exclude": []}     # diversity reference set
    n_calls = len(tenv.active.committee_calls)
    assert tenv.client.get(f"/concepts/{cid}/question").json() == body
    assert len(tenv.active.committee_calls) == n_calls                                # cached until labels change
    tenv.label(cid, "theft_b", "pos", "active")
    tenv.client.get(f"/concepts/{cid}/question")
    assert len(tenv.active.committee_calls) == n_calls + 1


def test_question_skips_clips_waiting_to_be_random_labelled(tenv):
    cid = tenv.cid
    tenv.label(cid, "theft_a", "pos")
    run_teach(tenv, cid)
    tenv.state.store.random_samples.add(cid, ["theft_b"])                               # drawn, not yet labelled
    body = tenv.client.get(f"/concepts/{cid}/question").json()
    assert body["clip_id"] != "theft_b" and "theft_b" not in tenv.active.query_calls[-1]
    assert tenv.active.query_kwargs[-1]["exclude"] == ["theft_b"]


def test_question_204_when_nothing_is_informative_or_no_rules(tenv):
    cid = tenv.cid
    assert tenv.client.get(f"/concepts/{cid}/question").status_code == 204             # no candidate rules yet
    tenv.label(cid, "theft_a", "pos")
    run_teach(tenv, cid)
    tenv.active.none = True
    tenv.state.question_cache.clear()
    assert tenv.client.get(f"/concepts/{cid}/question").status_code == 204
    assert tenv.client.get("/concepts/cn_nope/question").status_code == 404


@pytest.mark.parametrize("p, expect", [(0.0, 204), (1.0, 204), (0.04, 204), (0.96, 204), (0.05, 200), (0.95, 200), (0.3, 200)])
def test_question_204_when_the_committee_is_unanimous(tenv, p, expect):
    """select_query still returns its closest-to-0.5 clip when everyone agrees; the endpoint must not call that a question."""
    cid = tenv.cid
    tenv.label(cid, "theft_a", "pos")
    run_teach(tenv, cid)
    tenv.active.p = p
    tenv.state.question_cache.clear()
    r = tenv.client.get(f"/concepts/{cid}/question")
    assert r.status_code == expect
    if expect == 200:
        assert r.json()["p"] == p


def test_question_ready_event_only_when_there_is_a_question(tenv):
    cid = tenv.cid
    tenv.label(cid, "theft_a", "pos")
    tenv.active.none = True
    run = run_teach(tenv, cid)
    assert "question_ready" not in [e["type"] for e in tenv.state.store.runs.events(run["id"])]


def test_question_503_without_active_learning(make_env):
    env = make_env(disable=("build_committee",))
    env.seed_fixture_events("theft_a", "theft_b")
    cid = env.new_concept()
    env.label(cid, "theft_a", "pos")
    run = run_teach(env, cid)
    assert run["status"] == "done"                                       # the run itself does not need E
    assert "question_ready" not in [e["type"] for e in env.state.store.runs.events(run["id"])]
    assert env.client.get(f"/concepts/{cid}/rules").json()
    r = env.client.get(f"/concepts/{cid}/question")
    assert r.status_code == 503 and "not available yet" in r.json()["error"]
