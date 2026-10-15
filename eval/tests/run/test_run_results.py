"""results.json: EvalResults schema validation, merge by (concept, method, k, q, seed), NaN handling."""
import json
import math

import jsonschema
import pytest

from eval.harness import results


def row(**kw):
    base = {"concept": "vehicle_stop", "method": "exemplar", "k": 3, "q": 3, "seed": 0, "f1": 0.5, "precision": 0.5, "recall": 0.5,
            "false_alarm_rate": 0.05, "tokens_per_event": 9000.0, "usd_per_event": 0.002, "p50_latency_ms": 14000.0,
            "escalated_fraction": 0.1}
    base.update(kw)
    return base


def test_merge_replaces_equal_keys_and_keeps_others(tmp_path):
    p = tmp_path / "results.json"
    results.merge_rows([row(seed=0, f1=0.4), row(seed=1, f1=0.6)], alpha=0.1, path=p)
    doc = results.merge_rows([row(seed=1, f1=0.9), row(seed=2, f1=0.7)], alpha=0.1, path=p)
    by_seed = {r["seed"]: r["f1"] for r in doc["rows"]}
    assert by_seed == {0: 0.4, 1: 0.9, 2: 0.7}
    assert json.loads(p.read_text(encoding="utf-8")) == doc and doc["alpha"] == 0.1 and doc["generated_at"]


def test_rows_validate_against_the_api_yaml_schema(tmp_path):
    p = tmp_path / "results.json"
    doc = results.merge_rows([row(), row(method="zero_shot_vlm", k=0, q=0, extra_field="allowed")], alpha=0.1, path=p)
    results.validate(doc)


def test_schema_rejects_a_bad_method_and_missing_keys(tmp_path):
    p = tmp_path / "results.json"
    with pytest.raises(jsonschema.ValidationError):
        results.merge_rows([row(method="magic")], path=p)
    with pytest.raises(jsonschema.ValidationError):
        results.validate({"generated_at": "now", "rows": [{"concept": "c", "method": "exemplar", "k": 1, "q": 0}]})
    assert not p.exists()                                   # nothing written when validation fails


def test_nan_and_none_are_dropped_not_written(tmp_path):
    p = tmp_path / "results.json"
    doc = results.merge_rows([row(f1=float("nan"), recall=None, p50_latency_ms=math.inf)], path=p)
    r = doc["rows"][0]
    assert "f1" not in r and "recall" not in r and "p50_latency_ms" not in r
    json.loads(p.read_text(encoding="utf-8"))               # strict JSON parse works (no NaN literal)


def test_rows_are_sorted_deterministically(tmp_path):
    p = tmp_path / "results.json"
    doc = results.merge_rows([row(concept="b"), row(concept="a", seed=3), row(concept="a", seed=1)], path=p)
    assert [(r["concept"], r["seed"]) for r in doc["rows"]] == [("a", 1), ("a", 3), ("b", 0)]


def test_load_results_of_a_missing_file_is_empty(tmp_path):
    assert results.load_results(tmp_path / "none.json")["rows"] == []
