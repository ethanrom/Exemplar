"""The Exemplar trial: teach from k examples, ask q active questions, calibrate, score the held-out test split (PLAN.md section 3).

Everything stream D (synthesis) and E (active learning, calibration) provide is reached through `Services`, so the protocol
is testable with fakes and `eval.run` can wire in the real modules lazily.  The protocol, per (concept, k, seed):

1. Examples: k positives and `n_neg` negatives drawn (seeded, nested in k) from the concept's TRAIN windows, label provenance `example`.
2. `run_cegis` -> candidates.  For round r = 1..q: `build_committee` + `select_query` over the remaining unlabelled TRAIN windows,
   the oracle answers with the ground-truth label (provenance `active`), `run_cegis` again.  Checkpoints at every requested q.
3. Top candidate -> `calibrate` on the CALIB windows as provenance `random` labels -> tau, delta, guarantee.
4. Score the TEST windows with `robustness`; precision / recall / F1 / false-alarm rate at tau, cost, latency, escalation band.

Leakage is asserted, not assumed: every clip id handed to synthesis or active learning must be a train window of the concept and
the three id sets must be pairwise disjoint (`assert_no_leak`).
"""
from __future__ import annotations

import inspect
import random
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from exemplar.contracts.trace import Trace

from . import metrics
from .budget import usd
from .dataset import Window

WEIGHT_CONFIRMED = 3.0          # contracts.labels.WEIGHT_CONFIRMED: the user looked at the clip and chose the label
METHOD = "exemplar"
STRONG_PERCEPTION_USD_ESTIMATE = 0.028     # Phase 0 spike 5, 16 frames; used only when no strong trace was executed
FAILED_SCORE = -0.5                         # robustness of a perception_failed trace (-C)


class LeakError(AssertionError):
    """A calibration or test clip reached synthesis / active learning (or the splits overlap)."""


# ------------------------------------------------------------------ services (D and E, injected)
@dataclass
class Services:
    run_cegis: Callable[..., list]                   # D: agent.run_cegis(examples, nl_hint=, emit=, k=, max_rounds=, model=)
    build_committee: Callable[..., Any]              # E: active.build_committee(candidates, examples, ...)
    select_query: Callable[..., list]                # E: active.select_query(committee, unlabelled, ...)
    calibrate: Callable[..., Any]                    # E: calibrate.calibrate(rule, [(trace, label)], alpha)
    make_example: Callable[..., Any]                 # D: synth.Example(trace=, positive=, weight=, clip_id=)
    make_label: Callable[..., Any]                   # contracts.labels.Label(...)
    robustness: Callable[[Any, Trace], float]        # C: dsl.robustness(rule, trace)
    new_proposer: Callable[[], Any] = lambda: None   # fresh proposer per trial (None: D's default LLM proposer)
    proposer_name: str = "custom"


def call_supported(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call `fn` with the keyword arguments it accepts (the interface sheet is a floor: D and E may add parameters, and
    their real signatures may lack optional ones)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(*args, **kwargs)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kwargs)
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


# ------------------------------------------------------------------ sampling and leakage
def sample_examples(train: Sequence[Window], k: int, n_neg: int, seed: int, concept: str,
                    usable: Optional[Callable[[Window], bool]] = None) -> tuple[list[Window], list[Window]]:
    """(examples, pool).  Positives and negatives are shuffled with independent seeded RNGs and a prefix is taken, so the k=1
    example is the first of the k=3 examples and the negatives do not depend on k.  The pool is every other usable train window."""
    ok = [w for w in sorted(train, key=lambda w: w.id) if usable is None or usable(w)]
    pos = [w for w in ok if w.positive]
    neg = [w for w in ok if not w.positive]
    random.Random(f"exemplar|{concept}|{seed}|pos").shuffle(pos)
    random.Random(f"exemplar|{concept}|{seed}|neg").shuffle(neg)
    if len(pos) < k:
        raise ValueError(f"{concept}: only {len(pos)} usable train positives, need k={k}")
    examples = pos[:k] + neg[:n_neg]
    chosen = {w.id for w in examples}
    return examples, [w for w in ok if w.id not in chosen]


def assert_no_leak(*, train_ids: Iterable[str], calib_ids: Iterable[str], test_ids: Iterable[str], synth_ids: Iterable[str],
                   where: str = "") -> None:
    train, calib, test, synth = set(train_ids), set(calib_ids), set(test_ids), set(synth_ids)
    if (train & calib) or (train & test) or (calib & test):
        raise LeakError(f"splits overlap ({where}): train&calib={sorted(train & calib)[:3]} train&test={sorted(train & test)[:3]} "
                        f"calib&test={sorted(calib & test)[:3]}")
    bad = synth - train
    if bad:
        raise LeakError(f"{where}: non-train clips reached synthesis / active learning: {sorted(bad)[:5]}")


# ------------------------------------------------------------------ one trial
@dataclass
class TrialConfig:
    concept: str
    hint: Optional[str]
    alpha: float
    train: list[Window]
    calib: list[Window]
    test: list[Window]
    traces: Mapping[str, Trace]                      # window id -> fast trace (missing ids are dropped from the splits)
    n_neg: int = 2
    cand_k: int = 6
    max_rounds: int = 4
    committee_samples: int = 200
    solve_timeout_s: float = 10.0
    strong_fn: Optional[Callable[[Window], tuple[Trace, float, int]]] = None    # window -> (strong trace, usd paid now, latency ms)
    proposer_label: str = ""


@dataclass
class TrialOutput:
    rows: list[dict[str, Any]] = field(default_factory=list)
    log: dict[str, Any] = field(default_factory=dict)


def _ok(trace: Optional[Trace]) -> bool:
    return trace is not None and trace.status == "ok"


def _synth_usage(proposer: Any, events: Sequence[dict]) -> tuple[int, int]:
    """Cumulative LLM tokens (in, out) the synthesis used: the proposer's own counter, else D's `done` event message."""
    u = getattr(proposer, "usage", None)
    if isinstance(u, Mapping) and ("inputTokens" in u or "input_tokens" in u):
        return int(u.get("inputTokens", u.get("input_tokens", 0))), int(u.get("outputTokens", u.get("output_tokens", 0)))
    best = (0, 0)
    for ev in events:
        m = re.search(r"LLM tokens in/out (\d+)/(\d+)", str(ev.get("message", "")))
        if m:
            best = (max(best[0], int(m.group(1))), max(best[1], int(m.group(2))))
    return best


def run_trial(cfg: TrialConfig, k: int, seed: int, qs: Sequence[int], svc: Services) -> TrialOutput:
    """One (concept, k, seed) with checkpoints at every q in `qs`; returns one row per q."""
    qs = sorted(set(qs))
    q_max = qs[-1]
    traces = cfg.traces
    has = lambda w: _ok(traces.get(w.id))                       # noqa: E731
    train = [w for w in cfg.train if w.id in traces]
    calib = [w for w in cfg.calib if w.id in traces]
    test = [w for w in cfg.test if w.id in traces]
    train_ids, calib_ids, test_ids = ({w.id for w in ws} for ws in (cfg.train, cfg.calib, cfg.test))
    examples_w, pool = sample_examples(train, k, cfg.n_neg, seed, cfg.concept, usable=has)
    by_id = {w.id: w for w in train}

    labelled: list[tuple[Window, str]] = [(w, "example") for w in examples_w]       # (window, provenance)
    exs = [svc.make_example(trace=traces[w.id], positive=w.positive, weight=WEIGHT_CONFIRMED, clip_id=w.id) for w in examples_w]
    synth_in = synth_out = n_events_total = 0                  # cumulative synthesis LLM tokens over the rounds
    queried: list[dict[str, Any]] = []
    out = TrialOutput()
    cands: list[Any] = []
    stopped_at: Optional[int] = None
    evaluated: dict[int, dict[str, Any]] = {}

    def row_for(r: int, q: int) -> dict[str, Any]:
        if r not in evaluated:
            evaluated[r] = _evaluate(cfg, svc, cands, k=k, seed=seed, n_labelled=len(labelled), calib=calib, test=test,
                                     synth=(synth_in, synth_out))
        return {**evaluated[r], "q": q, "q_effective": r}

    for r in range(q_max + 1):
        assert_no_leak(train_ids=train_ids, calib_ids=calib_ids, test_ids=test_ids, synth_ids=[w.id for w, _ in labelled],
                       where=f"{cfg.concept} k={k} seed={seed} round={r}")
        proposer, events = svc.new_proposer(), []              # fresh proposer per synthesis run: template libraries depend on the examples
        cands = call_supported(svc.run_cegis, exs, nl_hint=cfg.hint, emit=events.append, k=cfg.cand_k, max_rounds=cfg.max_rounds,
                               model=proposer, solve_timeout_s=cfg.solve_timeout_s) or []
        t_in, t_out = _synth_usage(proposer, events)
        synth_in, synth_out, n_events_total = synth_in + t_in, synth_out + t_out, n_events_total + len(events)
        if r in qs:
            out.rows.append(row_for(r, r))
        if r == q_max:
            break
        if not cands or not pool:
            stopped_at = r
            break
        committee = call_supported(svc.build_committee, cands, exs, seed=seed, n_samples=cfg.committee_samples)
        unl = [traces[w.id] for w in pool]
        lab_tr = [traces[w.id] for w, _ in labelled]
        asked = call_supported(svc.select_query, committee, unl, k=1, labelled=lab_tr)
        if not asked:
            stopped_at = r
            break
        cid = asked[0].clip_id
        assert_no_leak(train_ids=train_ids, calib_ids=calib_ids, test_ids=test_ids, synth_ids=[cid],
                       where=f"{cfg.concept} query {r + 1}")
        w = by_id[cid]
        queried.append({"round": r + 1, "clip_id": cid, "p": float(getattr(asked[0], "p", float("nan"))), "answer": w.label})
        labelled.append((w, "active"))                           # the oracle answers with the ground-truth label
        exs.append(svc.make_example(trace=traces[cid], positive=w.positive, weight=WEIGHT_CONFIRMED, clip_id=cid))
        pool = [p for p in pool if p.id != cid]

    if stopped_at is not None:                                   # no more questions possible: later checkpoints = last state
        out.rows += [row_for(stopped_at, q) for q in qs if q > stopped_at]
    out.log = {"concept": cfg.concept, "k": k, "seed": seed, "qs": list(qs), "examples": [w.id for w in examples_w],
               "queried": queried, "stopped_at": stopped_at, "n_events": n_events_total, "proposer": cfg.proposer_label,
               "provenance": {p: sum(1 for _, pr in labelled if pr == p) for p in ("example", "active")}}
    return out


# ------------------------------------------------------------------ scoring one candidate
def _scores(svc: Services, rule: Any, ws: Sequence[Window], traces: Mapping[str, Trace]) -> list[float]:
    return [float(svc.robustness(rule, traces[w.id])) for w in ws]


def _evaluate(cfg: TrialConfig, svc: Services, cands: Sequence[Any], *, k: int, seed: int, n_labelled: int,
              calib: Sequence[Window], test: Sequence[Window], synth: tuple[int, int]) -> dict[str, Any]:
    traces = cfg.traces
    assert_no_leak(train_ids={w.id for w in cfg.train}, calib_ids={w.id for w in calib}, test_ids={w.id for w in test},
                   synth_ids=(), where="evaluate")
    pos_t = [w.positive for w in test]
    base: dict[str, Any] = {"concept": cfg.concept, "method": METHOD, "k": k, "seed": seed,
                            "alpha": cfg.alpha, "proposer": cfg.proposer_label, "n_labelled": n_labelled,
                            "n_test_pos": sum(pos_t), "n_test_neg": len(pos_t) - sum(pos_t),
                            "n_missing_traces": (len(cfg.calib) - len(calib)) + (len(cfg.test) - len(test)),
                            "synth_tokens_in": synth[0], "synth_tokens_out": synth[1]}
    synth_usd = usd("strong", *synth)
    n_events = max(1, len(test))
    metas = [traces[w.id].perception for w in test]
    p_tokens = [m.tokens_in + m.tokens_out for m in metas if m]
    p_usd = [usd("fast", m.tokens_in, m.tokens_out) for m in metas if m]
    lat = [float(m.latency_ms) if m else 0.0 for m in metas]            # per test event, aligned with `test`
    if not cands:
        # no rule could be synthesised: the monitor never fires (precision/recall/F1 = 0, no false alarms)
        base.update(no_rule=True, f1=0.0, precision=0.0, recall=0.0, false_alarm_rate=0.0, tau=0.0, guarantee=False,
                    escalated_fraction=0.0)
    else:
        top = cands[0]
        rule = top.rule
        labels = [(traces[w.id], svc.make_label(concept_id=cfg.concept, clip_id=w.id, value="pos" if w.positive else "neg",
                                                provenance="random")) for w in calib]
        cal = svc.calibrate(rule, labels, cfg.alpha)
        tau, delta = float(cal.tau), float(getattr(cal, "delta", 0.1))
        scores = _scores(svc, rule, test, traces)
        c = metrics.confusion(scores, pos_t, tau)
        m = metrics.prf(c)
        lo, hi = metrics.clopper_pearson(c.fp, c.n_neg)
        band = [i for i, s in enumerate(scores) if abs(s - tau) <= delta + 1e-12]
        base.update(m, no_rule=False, tau=tau, delta=delta, guarantee=bool(cal.guarantee), n_calib_neg=int(cal.n_random_neg),
                    n_calib_pos=int(cal.n_random_pos), false_alarm_ci95_low=lo, false_alarm_ci95_high=hi,
                    escalated_fraction=len(band) / n_events, margin=float(top.margin), mdl=float(top.mdl),
                    rule_dsl=top.dsl_text, rule_english=top.english, calib_recall=getattr(cal, "recall", None))
        rci = getattr(cal, "recall_ci95", None)
        if rci:
            base.update(calib_recall_ci95_low=float(rci[0]), calib_recall_ci95_high=float(rci[1]))
        esc_usd_each = STRONG_PERCEPTION_USD_ESTIMATE
        if cfg.strong_fn is not None and band:
            new_scores, paid, strong_usd = list(scores), 0.0, []
            for i in band:
                st, p, ms = cfg.strong_fn(test[i])
                new_scores[i] = float(svc.robustness(rule, st)) if st.status == "ok" else scores[i]
                paid += p
                if st.perception:
                    strong_usd.append(usd("strong", st.perception.tokens_in, st.perception.tokens_out))
                lat[i] += float(st.perception.latency_ms if st.perception else ms)     # band events also wait for the strong call
            ce = metrics.prf(metrics.confusion(new_scores, pos_t, tau))
            base.update({f"{k_}_escalated": v for k_, v in ce.items()}, escalation_executed=True, escalation_usd_paid=paid)
            if strong_usd:
                esc_usd_each = sum(strong_usd) / len(strong_usd)
        base["usd_escalation_expected"] = base["escalated_fraction"] * esc_usd_each
    base["tokens_per_event"] = (sum(p_tokens) / len(p_tokens) if p_tokens else 0.0) + (synth[0] + synth[1]) / n_events
    base["usd_perception"] = sum(p_usd) / len(p_usd) if p_usd else 0.0
    base["usd_synthesis_amortised"] = synth_usd / n_events
    base["usd_per_event"] = base["usd_perception"] + base["usd_synthesis_amortised"] + base.get("usd_escalation_expected", 0.0)
    base["p50_latency_ms"] = metrics.percentile(lat, 0.5)
    return base
