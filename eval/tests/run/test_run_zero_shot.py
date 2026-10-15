"""Zero-shot baseline: tool-use validation and retry, request shape, cache, budget, seeded stratified subset, scoring."""
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from eval.baselines import zero_shot as zs
from eval.harness.budget import BudgetGuard, usd
from eval.harness.dataset import Window
from fakes import window

DESC = "A vehicle that was driving comes to a stop."


def tool_resp(match=True, conf=0.8, tin=5000, tout=100, name=zs.TOOL_NAME, payload=None):
    inp = payload if payload is not None else {"match": match, "confidence": conf}
    return {"output": {"message": {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t1", "name": name, "input": inp}}]}},
            "usage": {"inputTokens": tin, "outputTokens": tout}, "stopReason": "tool_use"}


class FakeClient:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def converse(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def frames(n=16):
    return [SimpleNamespace(t_ms=500 + 1000 * i, jpeg=b"\xff\xd8jpeg") for i in range(n)]


def run(client, w=None):
    w = w or window("w1", "pos", "test", "vehicle_stop")
    return zs.classify(client, model_id="arn:secret-model-id", alias="alias", window=w, frames=frames(), window_ms=16000, description=DESC)


# ------------------------------------------------------------------ validation
@pytest.mark.parametrize("payload,ok", [
    ({"match": True, "confidence": 0.7}, True), ({"match": False, "confidence": 0}, True), ('{"match": true, "confidence": 1}', True),
    ({"match": "yes", "confidence": 0.5}, False), ({"match": True, "confidence": 1.5}, False), ({"match": True, "confidence": True}, False),
    ({"match": True}, False), ("not json", False), (None, False), ({"match": True, "confidence": float("nan")}, False)])
def test_validate(payload, ok):
    match, conf, errs = zs.validate(payload)
    assert (not errs) == ok
    assert (match is not None) == ok


# ------------------------------------------------------------------ the model call
def test_request_shape_uses_the_strong_model_recipe_and_the_same_frames():
    c = FakeClient(tool_resp())
    r = run(c)
    kw = c.calls[0]
    assert kw["toolConfig"]["toolChoice"] == {"auto": {}}                           # forced tool choice is rejected by the strong model
    assert kw["additionalModelRequestFields"] == {"thinking": {"type": "between_tools"}}
    assert "temperature" not in kw and "temperature" not in kw["inferenceConfig"]
    texts = [b["text"] for b in kw["messages"][0]["content"] if "text" in b]
    images = [b for b in kw["messages"][0]["content"] if "image" in b]
    assert len(images) == 16 and texts[1] == "Frame 0 (t=0.5s)" and texts[16] == "Frame 15 (t=15.5s)"     # B's caption format
    assert DESC in texts[-1] and zs.TOOL_NAME in texts[-1]
    assert (r.match, r.confidence, r.status, r.attempts) == (True, 0.8, "ok", 1)
    assert r.usd == pytest.approx(usd("strong", 5000, 100)) and r.model_alias == "alias"


def test_invalid_answer_is_retried_once_with_the_error_fed_back_and_tokens_add_up():
    c = FakeClient(tool_resp(payload={"match": "maybe", "confidence": 0.5}, tin=5000, tout=50), tool_resp(False, 0.2, tin=5200, tout=60))
    r = run(c)
    assert r.status == "ok" and r.attempts == 2 and (r.match, r.confidence) == (False, 0.2)
    assert (r.tokens_in, r.tokens_out) == (10200, 110)
    follow = c.calls[1]["messages"][-1]["content"][0]["toolResult"]
    assert follow["status"] == "error" and "`match` must be a boolean" in follow["content"][0]["text"]


def test_two_invalid_answers_give_an_invalid_result_scored_as_no_match():
    bad = tool_resp(payload={"confidence": 2})
    r = run(FakeClient(bad, bad))
    assert r.status == "invalid" and r.match is False and r.confidence == 0.0 and r.attempts == 2


def test_plain_text_answer_without_the_tool_is_retried():
    text = {"output": {"message": {"role": "assistant", "content": [{"text": "yes"}]}}, "usage": {"inputTokens": 1, "outputTokens": 1}}
    r = run(FakeClient(text, tool_resp(True, 0.9)))
    assert r.status == "ok" and r.attempts == 2


def test_backend_errors_are_wrapped_and_scrub_the_model_id():
    err = ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down arn:secret-model-id"}}, "Converse")
    with pytest.raises(zs.ZeroShotBackendError) as e:
        run(FakeClient(err))
    assert "ThrottlingException" in str(e.value) and "arn:secret-model-id" not in str(e.value)


# ------------------------------------------------------------------ cache, budget, sampling
class FakeSample:
    def __init__(self):
        self.calls = []

    def __call__(self, path, n, **kw):
        self.calls.append((n, kw))
        return SimpleNamespace(frames=tuple(frames(n)), duration_ms=16000)


def test_run_window_samples_exactly_like_perception_caches_and_charges_the_ledger(data_dir):
    w = window("vehicle_stop-x-pos", "pos", "test", "vehicle_stop")
    guard = BudgetGuard(1.0, data_dir / "eval" / "costs.jsonl")
    sample, client = FakeSample(), FakeClient(tool_resp(True, 0.9))
    status, res, err = zs.run_window(w, client=client, model_id="m", alias="a", descriptions={"vehicle_stop": DESC}, guard=guard, sample=sample)
    n, kw = sample.calls[0]
    assert (status, err) == ("ok", "") and n == 16 and kw["width"] == 640 and kw["min_gap_s"] == 0.5 and kw["roi"] is None
    loaded = zs.load_result(w.id)
    assert loaded == res and guard.spent == pytest.approx(res.usd)
    ledger = (data_dir / "eval" / "costs.jsonl").read_text(encoding="utf-8")
    assert '"phase":"zero_shot"' in ledger and '"model_alias":"a"' in ledger and "arn" not in ledger


def test_a_cached_result_with_another_prompt_version_is_ignored(data_dir):
    w = window("w", "neg", "calib", "vehicle_stop")
    guard = BudgetGuard(1.0, data_dir / "c.jsonl")
    _, res, _ = zs.run_window(w, client=FakeClient(tool_resp()), model_id="m", alias="a", descriptions={"vehicle_stop": DESC}, guard=guard,
                              sample=FakeSample())
    assert zs.load_result(w.id) is not None
    p = zs.cache_dir() / f"{w.id}.json"
    p.write_text(p.read_text(encoding="utf-8").replace(zs.PROMPT_VERSION, "old"), encoding="utf-8")
    assert zs.load_result(w.id) is None


def test_budget_guard_stops_before_any_call(data_dir):
    w = window("w", "pos", "test", "vehicle_stop")
    guard = BudgetGuard(0.01, data_dir / "c.jsonl")                    # < the per-call reservation
    client = FakeClient(tool_resp())
    status, res, err = zs.run_window(w, client=client, model_id="m", alias="a", descriptions={"vehicle_stop": DESC}, guard=guard,
                                     sample=FakeSample())
    assert status == "budget_stop" and res is None and client.calls == [] and guard.spent == 0 and guard.in_flight == 0


def test_backend_error_is_retried_then_reported_and_the_reservation_is_released(data_dir):
    w = window("w", "pos", "test", "vehicle_stop")
    guard = BudgetGuard(1.0, data_dir / "c.jsonl")
    err = ClientError({"Error": {"Code": "ServiceUnavailableException", "Message": "x"}}, "Converse")
    slept = []
    status, res, msg = zs.run_window(w, client=FakeClient(err, err, err), model_id="m", alias="a", descriptions={"vehicle_stop": DESC},
                                     guard=guard, sample=FakeSample(), sleep=slept.append)
    assert status == "backend_error" and res is None and "ServiceUnavailable" in msg and len(slept) == 2 and guard.in_flight == 0


# ------------------------------------------------------------------ subset
def many_windows():
    ws = []
    for c in ("a", "b"):
        for split, npos, nneg in (("calib", 6, 30), ("test", 10, 40)):
            ws += [window(f"{c}-{split}-pos-{i}", "pos", split, c) for i in range(npos)]
            ws += [window(f"{c}-{split}-neg-{i}", "neg", split, c) for i in range(nneg)]
    return ws


def test_subset_is_seeded_stratified_and_nested():
    ws = many_windows()
    s30 = zs.stratified_subset(ws, 0.3, seed=0)
    assert [w.id for w in s30] == [w.id for w in zs.stratified_subset(list(reversed(ws)), 0.3, seed=0)]
    assert [w.id for w in s30] != [w.id for w in zs.stratified_subset(ws, 0.3, seed=1)]
    s60 = zs.stratified_subset(ws, 0.6, seed=0)
    assert {w.id for w in s30} <= {w.id for w in s60}                                     # nested across fractions
    cells = {zs.cell_of(w) for w in ws}
    assert {zs.cell_of(w) for w in s30} == cells                                          # every concept x split x label is present
    assert len(zs.stratified_subset(ws, 1.0)) == len(ws)


def test_subset_keeps_enough_calibration_negatives_for_the_guarantee():
    ws = many_windows()
    s = zs.stratified_subset(ws, 0.1, seed=0)
    for c in ("a", "b"):
        assert sum(1 for w in s if w.concept == c and w.split == "calib" and not w.positive) >= 10      # >= ceil(1/0.1)-1 = 9


def test_subset_order_is_round_robin_so_stopping_early_stays_stratified():
    ws = many_windows()
    s = zs.stratified_subset(ws, 0.5, seed=0)
    n_cells = len({zs.cell_of(w) for w in ws})
    assert len({zs.cell_of(w) for w in s[:n_cells]}) == n_cells


def test_fit_fraction_picks_the_largest_fraction_that_fits_and_cached_windows_are_free():
    ws = many_windows()
    full = zs.fit_fraction(ws, cached=set(), est_usd=0.01, remaining=1e9)
    assert full == 1.0
    f = zs.fit_fraction(ws, cached=set(), est_usd=0.01, remaining=0.01 * 1.25 * len(ws) * 0.5)
    assert 0.3 <= f <= 0.5
    assert zs.fit_fraction(ws, cached={w.id for w in ws}, est_usd=0.01, remaining=0.0) == 1.0


# ------------------------------------------------------------------ scoring
def result(w: Window, match, conf, tin=5000, tout=100, lat=7000):
    return zs.ZeroShotResult(id=w.id, concept=w.concept, split=w.split, label=w.label, match=match, confidence=conf, status="ok",
                             tokens_in=tin, tokens_out=tout, latency_ms=lat, attempts=1, usd=usd("strong", tin, tout), model_alias="a")


def test_build_row_calibrates_on_calib_negatives_and_scores_test():
    calib = [window(f"cn{i}", "neg", "calib", "c") for i in range(20)] + [window(f"cp{i}", "pos", "calib", "c") for i in range(4)]
    test = [window(f"tp{i}", "pos", "test", "c") for i in range(4)] + [window(f"tn{i}", "neg", "test", "c") for i in range(6)]
    res = {}
    for i, w in enumerate(w for w in calib if not w.positive):          # 17 at 0.1, 3 at 0.6 -> k=19 -> tau = 0.6
        res[w.id] = result(w, i >= 17, 0.1 if i < 17 else 0.6)
    for w in (w for w in calib if w.positive):
        res[w.id] = result(w, True, 0.9)
    for i, w in enumerate(w for w in test if w.positive):               # confidences 0.9 0.9 0.7 0.5 -> fire iff > 0.6: 3 of 4
        res[w.id] = result(w, True, [0.9, 0.9, 0.7, 0.5][i])
    for i, w in enumerate(w for w in test if not w.positive):           # 0.1 0.1 0.2 0.6 0.7 0.95: > 0.6 fires for the last two
        res[w.id] = result(w, i >= 3, [0.1, 0.1, 0.2, 0.6, 0.7, 0.95][i])
    row = zs.build_row("c", res, calib + test, alpha=0.1, subset_fraction=0.5)
    assert row["tau"] == 0.6 and row["guarantee"] is True and row["n_calib_neg"] == 20 and row["subset_fraction"] == 0.5
    assert (row["precision"], row["recall"]) == (pytest.approx(3 / 5), pytest.approx(3 / 4))
    assert row["f1"] == pytest.approx(2 * 0.6 * 0.75 / (0.6 + 0.75)) and row["false_alarm_rate"] == pytest.approx(2 / 6)
    # native point: match flag; positives all match (4/4); negatives 3 of 6 match
    assert row["native_recall"] == 1.0 and row["native_false_alarm_rate"] == pytest.approx(3 / 6)
    assert (row["method"], row["k"], row["q"], row["seed"]) == ("zero_shot_vlm", 0, 0, 0)
    assert row["tokens_per_event"] == 5100 and row["p50_latency_ms"] == 7000 and row["escalated_fraction"] == 0.0
    assert row["usd_per_event"] == pytest.approx(usd("strong", 5000, 100))


def test_build_row_without_enough_negatives_flags_no_guarantee_and_uses_the_native_threshold():
    calib = [window(f"cn{i}", "neg", "calib", "c") for i in range(5)]
    test = [window("tp", "pos", "test", "c"), window("tn", "neg", "test", "c")]
    res = {w.id: result(w, False, 0.1) for w in calib}
    res["tp"], res["tn"] = result(test[0], True, 0.8), result(test[1], False, 0.3)
    row = zs.build_row("c", res, calib + test, alpha=0.1)
    assert row["guarantee"] is False and row["tau"] == 0.5 and row["f1"] == 1.0


def test_build_row_is_none_without_test_results():
    assert zs.build_row("c", {}, [window("tp", "pos", "test", "c")], alpha=0.1) is None


@pytest.mark.parametrize("match,conf,score", [
    (True, 0.9, 0.9), (False, 0.04, 0.04),                  # consistent: confidence is the event probability
    (False, 0.96, 0.04), (True, 0.2, 0.8),                  # confidence in the answer: flipped so that match fixes the direction
    (True, 0.5, 0.5), (False, 0.5, 0.5), (True, 1.0, 1.0), (False, 0.0, 0.0)])
def test_score_is_the_event_probability_with_the_sign_fixed_by_match(match, conf, score):
    r = result(window("w", "pos", "test", "c"), match, conf)
    assert r.score == pytest.approx(score)
    assert (r.score > 0.5) == (match and conf != 0.5) or conf == 0.5
