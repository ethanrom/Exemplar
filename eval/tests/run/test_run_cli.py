"""`python -m eval.run` end to end with fake D / E: results.json rows, resume, trace cache access without a client."""
import json
import sys
from types import SimpleNamespace

import pytest

import eval.run as run
from eval.harness import results, traces
from eval.harness.dataset import load_windows
from exemplar.perception import cache as pcache
from fakes import CONCEPT, fake_services, make_world


@pytest.fixture
def world(monkeypatch, data_dir):
    w = make_world()
    monkeypatch.setattr(run, "concept_ids", lambda: [CONCEPT])
    monkeypatch.setattr(run, "load_windows", lambda concepts=None, splits=None: w.all)
    monkeypatch.setattr(run, "load_traces", lambda ws: (dict(w.traces), []))
    monkeypatch.setattr("eval.data.config.load_concepts", lambda: {CONCEPT: SimpleNamespace(hint="a person at the door")})
    return w


def rows_of(path):
    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def test_run_writes_validated_rows_for_every_seed_and_q(world, tmp_path):
    out, (svc, rec) = tmp_path / "results.json", fake_services()
    code = run.main(["--concept", CONCEPT, "--k", "1", "3", "--q", "0", "2", "--seeds", "2"], services=svc, results_path=out)
    assert code == 0
    rows = rows_of(out)
    assert len(rows) == 2 * 2 * 2                                                # k x q x seeds
    assert {(r["k"], r["q"], r["seed"]) for r in rows} == {(k, q, s) for k in (1, 3) for q in (0, 2) for s in (0, 1)}
    results.validate(json.loads(out.read_text(encoding="utf-8")))
    assert {r["method"] for r in rows} == {"exemplar"} and json.loads(out.read_text(encoding="utf-8"))["alpha"] == 0.1


def test_second_run_is_a_noop_force_recomputes(world, tmp_path):
    out = tmp_path / "results.json"
    svc, rec = fake_services()
    run.main(["--concept", CONCEPT, "--k", "1", "--q", "0", "--seeds", "2"], services=svc, results_path=out)
    n = len(rec.cegis_ids)
    run.main(["--concept", CONCEPT, "--k", "1", "--q", "0", "--seeds", "2"], services=svc, results_path=out)
    assert len(rec.cegis_ids) == n                                               # resumed: nothing recomputed
    run.main(["--concept", CONCEPT, "--k", "1", "--q", "0", "--seeds", "2", "--force"], services=svc, results_path=out)
    assert len(rec.cegis_ids) == 2 * n


def test_partial_resume_only_computes_the_missing_q(world, tmp_path):
    out = tmp_path / "results.json"
    svc, rec = fake_services()
    run.main(["--concept", CONCEPT, "--k", "1", "--q", "0", "--seeds", "1"], services=svc, results_path=out)
    before = len(rec.cegis_ids)
    run.main(["--concept", CONCEPT, "--k", "1", "--q", "0", "2", "--seeds", "1"], services=svc, results_path=out)
    assert len(rec.cegis_ids) - before == 3                                      # q=2 needs its own 3 synthesis runs; q=0 was kept
    assert sorted(r["q"] for r in rows_of(out)) == [0, 2]


def test_zero_shot_rows_in_the_same_file_are_kept(world, tmp_path):
    out = tmp_path / "results.json"
    results.merge_rows([{"concept": CONCEPT, "method": "zero_shot_vlm", "k": 0, "q": 0, "seed": 0, "f1": 0.5}], path=out)
    run.main(["--concept", CONCEPT, "--k", "1", "--q", "0", "--seeds", "1"], services=fake_services()[0], results_path=out)
    assert {r["method"] for r in rows_of(out)} == {"exemplar", "zero_shot_vlm"}


def test_explicit_seed_list_and_no_write(world, tmp_path):
    out = tmp_path / "results.json"
    run.main(["--concept", CONCEPT, "--k", "1", "--q", "0", "--seed-list", "7", "9"], services=fake_services()[0], results_path=out)
    assert sorted(r["seed"] for r in rows_of(out)) == [7, 9]
    out2 = tmp_path / "other.json"
    run.main(["--concept", CONCEPT, "--k", "1", "--q", "0", "--seeds", "1", "--no-write"], services=fake_services()[0], results_path=out2)
    assert not out2.exists()


def test_missing_traces_stop_the_run_unless_allowed(monkeypatch, data_dir, tmp_path, capsys):
    w = make_world()
    monkeypatch.setattr(run, "concept_ids", lambda: [CONCEPT])
    monkeypatch.setattr(run, "load_windows", lambda concepts=None, splits=None: w.all)
    monkeypatch.setattr(run, "load_traces", lambda ws: ({k: v for k, v in w.traces.items() if k != w.test[0].id}, [w.test[0].id]))
    monkeypatch.setattr("eval.data.config.load_concepts", lambda: {CONCEPT: SimpleNamespace(hint="h")})
    svc, rec = fake_services()
    assert run.main(["--concept", CONCEPT, "--seeds", "1"], services=svc, results_path=tmp_path / "r.json") == 2
    assert "no cached fast trace" in capsys.readouterr().err and rec.cegis_ids == []
    assert run.main(["--concept", CONCEPT, "--k", "1", "--q", "0", "--seeds", "1", "--allow-missing"], services=svc,
                    results_path=tmp_path / "r.json") == 0


def test_dry_run_and_unknown_concept(world, tmp_path):
    svc, rec = fake_services()
    assert run.main(["--concept", CONCEPT, "--dry-run"], services=svc, results_path=tmp_path / "r.json") == 0 and rec.cegis_ids == []
    with pytest.raises(SystemExit):
        run.main(["--concept", "nope"], services=svc)


def test_real_trace_loading_reads_the_cache_without_any_client(data_dir):
    ws = load_windows(concepts=["vehicle_stop"], splits=["test"])[:3]
    cached = traces.load_cached(ws[0])
    assert cached is None                                                         # a miss is reported, never silently filled
    tr = pytest.importorskip("fakes").make_trace(ws[0].id, "pos")
    pcache.store(data_dir, traces.key_for(ws[0].id), tr, {})
    found, missing = run.load_traces(ws)
    assert set(found) == {ws[0].id} and missing == [ws[1].id, ws[2].id]
    assert found[ws[0].id].source == "meva" and found[ws[0].id].context.sub_type is None


def test_trace_cache_key_matches_what_perceive_detailed_uses(data_dir):
    from exemplar.perception.pipeline import perceive_detailed
    w = load_windows(concepts=["vehicle_stop"], splits=["test"])[0]

    class Boom:                                                                    # a miss would have to call the model
        def converse(self, **kw):
            raise AssertionError("model called")

    from fakes import make_trace
    tr = make_trace(w.id, "pos")
    pcache.store(data_dir, traces.key_for(w.id), tr, {})
    res = perceive_detailed(w.path(), clip_id=w.id, source="meva", mode="fast", n_frames=16, client=Boom())
    assert res.cached and res.trace.clip_id == w.id


def test_make_services_explains_what_is_missing_when_d_or_e_are_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "exemplar.active", None)                      # simulate "stream E not merged"
    with pytest.raises(SystemExit) as e:
        run.make_services("offline")
    assert "streams D" in str(e.value) and "merged" in str(e.value)
