"""The Exemplar trial protocol against fake D / E: leakage assertions, determinism, checkpoints, metrics, escalation."""
import pytest

from eval.harness import experiment as ex
from eval.harness.experiment import LeakError, TrialConfig, assert_no_leak, call_supported, run_trial, sample_examples
from fakes import CONCEPT, fake_services, make_trace, make_world


def cfg_for(world, **kw):
    return TrialConfig(concept=CONCEPT, hint="a person at the door", alpha=0.1, train=world.train, calib=world.calib, test=world.test,
                       traces=world.traces, **kw)


# ------------------------------------------------------------------ sampling
def test_sampling_is_deterministic_and_seed_dependent():
    w = make_world()
    a = sample_examples(w.train, 3, 2, 7, CONCEPT)
    b = sample_examples(list(reversed(w.train)), 3, 2, 7, CONCEPT)          # input order does not matter
    assert [x.id for x in a[0]] == [x.id for x in b[0]]
    others = {tuple(x.id for x in sample_examples(w.train, 3, 2, s, CONCEPT)[0]) for s in range(6)}
    assert len(others) > 1


def test_k1_example_is_the_first_of_the_k3_examples_and_negatives_do_not_depend_on_k():
    w = make_world()
    e1, _ = sample_examples(w.train, 1, 2, 0, CONCEPT)
    e3, _ = sample_examples(w.train, 3, 2, 0, CONCEPT)
    assert e3[0].id == e1[0].id
    assert [x.id for x in e1 if not x.positive] == [x.id for x in e3 if not x.positive]
    assert [x.positive for x in e3] == [True] * 3 + [False] * 2


def test_pool_is_the_rest_of_train_only():
    w = make_world()
    examples, pool = sample_examples(w.train, 1, 2, 0, CONCEPT)
    assert len(examples) + len(pool) == len(w.train)
    assert not {x.id for x in examples} & {x.id for x in pool}
    assert all(x.split == "train" for x in examples + pool)


def test_sampling_skips_unusable_windows_and_complains_without_enough_positives():
    w = make_world(n_train=(2, 5))
    failed = w.train[0]
    ex_, pool = sample_examples(w.train, 1, 2, 0, CONCEPT, usable=lambda x: x.id != failed.id)
    assert failed.id not in {x.id for x in ex_ + pool}
    with pytest.raises(ValueError):
        sample_examples(w.train, 3, 2, 0, CONCEPT)


# ------------------------------------------------------------------ leakage
def test_assert_no_leak_catches_foreign_clips_and_overlapping_splits():
    assert_no_leak(train_ids={"a"}, calib_ids={"b"}, test_ids={"c"}, synth_ids=["a"])
    with pytest.raises(LeakError):
        assert_no_leak(train_ids={"a"}, calib_ids={"b"}, test_ids={"c"}, synth_ids=["a", "b"])        # calib clip in synthesis
    with pytest.raises(LeakError):
        assert_no_leak(train_ids={"a"}, calib_ids={"b"}, test_ids={"c"}, synth_ids=["c"])             # test clip in synthesis
    with pytest.raises(LeakError):
        assert_no_leak(train_ids={"a", "b"}, calib_ids={"b"}, test_ids={"c"}, synth_ids=[])           # split overlap


def test_synthesis_and_active_learning_only_ever_see_train_clips():
    w = make_world()
    svc, rec = fake_services()
    run_trial(cfg_for(w), 3, 0, [0, 3], svc)
    train, held_out = {x.id for x in w.train}, {x.id for x in w.calib + w.test}
    seen = {c for call in rec.cegis_ids + rec.committee_ids + rec.query_pool_ids for c in call}
    assert seen and seen <= train and not seen & held_out
    assert rec.query_pool_ids and all(set(p) <= train for p in rec.query_pool_ids)


def test_calibration_gets_calib_clips_only_as_random_labels_and_test_is_never_a_label():
    w = make_world()
    svc, rec = fake_services()
    run_trial(cfg_for(w), 1, 0, [0], svc)
    labels = rec.calibrate_labels[0]
    assert {c for c, _ in labels} == {x.id for x in w.calib}
    assert {p for _, p in labels} == {"random"}
    assert not {c for c, _ in labels} & {x.id for x in w.test}


def test_a_query_for_a_calib_or_test_clip_is_refused():
    w = make_world()
    svc, _ = fake_services(question_ids=[w.test[0].id])
    with pytest.raises(LeakError):
        run_trial(cfg_for(w), 1, 0, [1], svc)
    svc, _ = fake_services(question_ids=[w.calib[0].id])
    with pytest.raises(LeakError):
        run_trial(cfg_for(w), 1, 0, [1], svc)


def test_overlapping_splits_in_the_config_are_refused_before_synthesis():
    w = make_world()
    bad = cfg_for(w)
    bad.test = w.test + [w.train[0]]
    svc, rec = fake_services()
    with pytest.raises(LeakError):
        run_trial(bad, 1, 0, [0], svc)
    assert rec.cegis_ids == []


# ------------------------------------------------------------------ protocol
def test_checkpoints_share_one_active_run_and_provenance_counts():
    w = make_world()
    svc, rec = fake_services()
    out = run_trial(cfg_for(w), 1, 0, [0, 2], svc)
    assert [len(c) for c in rec.cegis_ids] == [3, 4, 5]            # k=1 pos + 2 neg, then +1 answer per round (3 runs, not 1 + 3)
    assert [r["q"] for r in out.rows] == [0, 2] and [r["q_effective"] for r in out.rows] == [0, 2]
    assert out.log["provenance"] == {"example": 3, "active": 2}
    assert [q["round"] for q in out.log["queried"]] == [1, 2]
    assert all(w_ == ex.WEIGHT_CONFIRMED for w_ in rec.example_weights)
    assert rec.proposers_made == 3                                  # a fresh proposer per synthesis run


def test_active_answers_come_from_the_ground_truth_labels():
    w = make_world()
    svc, rec = fake_services()
    out = run_trial(cfg_for(w), 1, 0, [2], svc)
    by_id = {x.id: x.label for x in w.train}
    assert all(q["answer"] == by_id[q["clip_id"]] for q in out.log["queried"])


def test_metrics_on_the_fixture_world_match_hand_computation():
    w = make_world()
    svc, _ = fake_services()
    [row] = run_trial(cfg_for(w), 3, 0, [0], svc).rows
    # 17 of 20 calibration negatives score -0.45 and 3 score +0.10: n=20, k=19 -> tau = 0.10; test positives (+0.45) fire,
    # the 2 weak test negatives (+0.10) do not fire (strictly above tau), so TP=4 FP=0.
    assert row["tau"] == pytest.approx(0.1) and row["guarantee"] is True and row["n_calib_neg"] == 20
    assert (row["precision"], row["recall"], row["f1"], row["false_alarm_rate"]) == (1.0, 1.0, 1.0, 0.0)
    assert row["n_test_pos"] == 4 and row["n_test_neg"] == 10
    assert row["escalated_fraction"] == pytest.approx(2 / 14)        # the 2 weak negatives sit exactly on tau
    assert row["tokens_per_event"] == 9500 and row["p50_latency_ms"] == 14000
    assert row["usd_perception"] == pytest.approx(0.00155) and row["usd_synthesis_amortised"] == 0.0
    assert row["usd_per_event"] == pytest.approx(0.00155 + (2 / 14) * ex.STRONG_PERCEPTION_USD_ESTIMATE)
    assert row["method"] == "exemplar" and row["rule_dsl"] and row["false_alarm_ci95_high"] > row["false_alarm_ci95_low"] == 0.0


def test_with_few_calibration_negatives_there_is_no_guarantee_and_tau_falls_back_to_zero():
    w = make_world(n_calib=(5, 6))
    svc, _ = fake_services()
    [row] = run_trial(cfg_for(w), 1, 0, [0], svc).rows
    assert row["guarantee"] is False and row["tau"] == 0.0
    assert row["false_alarm_rate"] == pytest.approx(2 / 10)            # fires on score > 0: the 2 weak test negatives now fire


def test_trial_is_deterministic():
    w = make_world()
    a = run_trial(cfg_for(w), 3, 4, [0, 3], fake_services()[0])
    b = run_trial(cfg_for(w), 3, 4, [0, 3], fake_services()[0])
    assert a.rows == b.rows and a.log == b.log


def test_pool_exhaustion_stops_asking_and_reuses_the_last_state():
    w = make_world(n_train=(2, 2))
    svc, rec = fake_services()
    out = run_trial(cfg_for(w), 1, 0, [0, 3], svc)
    assert out.log["stopped_at"] == 1 and len(rec.cegis_ids) == 2
    assert [(r["q"], r["q_effective"]) for r in out.rows] == [(0, 0), (3, 1)]


def test_no_candidate_gives_a_zero_row_flagged_no_rule_and_no_query():
    w = make_world()
    svc, rec = fake_services(candidates=False)
    out = run_trial(cfg_for(w), 1, 0, [0, 1], svc)
    assert rec.query_pool_ids == [] and len(out.rows) == 2
    assert all(r["no_rule"] and r["f1"] == 0.0 and r["false_alarm_rate"] == 0.0 for r in out.rows)


def test_perception_failed_traces_never_become_examples_but_score_as_misses_on_test():
    w = make_world()
    failed_train = w.train[0]                                           # a positive
    failed_test = w.test[0]                                             # a positive
    w.traces[failed_train.id] = make_trace(failed_train.id, "failed")
    w.traces[failed_test.id] = make_trace(failed_test.id, "failed")
    svc, rec = fake_services()
    [row] = run_trial(cfg_for(w), 3, 0, [0], svc).rows
    assert failed_train.id not in {c for call in rec.cegis_ids for c in call}
    assert row["recall"] == pytest.approx(3 / 4)                        # the failed test positive is a miss


def test_windows_without_a_cached_trace_are_dropped_and_counted():
    w = make_world()
    del w.traces[w.test[-1].id]
    svc, _ = fake_services()
    [row] = run_trial(cfg_for(w), 1, 0, [0], svc).rows
    assert row["n_missing_traces"] == 1 and row["n_test_pos"] + row["n_test_neg"] == len(w.test) - 1


def test_executed_escalation_rescores_only_band_events():
    w = make_world()
    svc, _ = fake_services()
    asked = []

    def strong(win):
        asked.append(win.id)
        return make_trace(win.id, "pos", tokens=(20000, 3000), latency_ms=30000), 0.05, 31000      # the strong model "sees" the door

    [row] = run_trial(cfg_for(w, strong_fn=strong), 1, 0, [0], svc).rows
    assert set(asked) == {x.id for x in w.test if x.id.startswith("test-neg-0") and x.id[-1] in "01"}     # the 2 weak negatives
    assert row["escalation_executed"] is True and row["escalation_usd_paid"] == pytest.approx(0.10)
    assert row["false_alarm_rate_escalated"] == pytest.approx(0.2) and row["precision_escalated"] == pytest.approx(4 / 6)
    assert row["false_alarm_rate"] == 0.0                                  # the headline numbers stay the fast-model ones
    assert row["usd_escalation_expected"] == pytest.approx((2 / 14) * (20000 * 2 + 3000 * 10) / 1e6)


def test_call_supported_filters_unknown_keywords():
    def f(a, *, x=1):
        return a, x

    assert call_supported(f, 5, x=2, y=3) == (5, 2)
    assert call_supported(lambda a, **kw: (a, kw), 1, z=2) == (1, {"z": 2})
