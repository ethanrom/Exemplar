"""Counterexample-guided synthesis loop (PLAN.md section 2.3): propose sketches, typecheck, solve, feed counterexamples back.

    for round in 1..max_rounds:
        proposer -> up to K sketches        (LLM agent, or a deterministic proposer)
        typecheck each  (rejects go back to the proposer with the error, event `typecheck_failed`)
        solve each      (Z3 MaxSMT + max-margin + differential check; events `solve_started` / `solve_result` /
                         `differential_check` / `counterexample`)
        stop when K consistent candidates exist or the round added nothing new
    rank by MDL ascending, then margin descending; emit `candidates`, `done`.

The proposer is replaceable (`model=` argument): None builds the Strands/Bedrock agent from settings and falls back to
the template library when Bedrock is unusable; an object with ``propose(ctx)`` (or a plain function) is used as is.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from ..synth import Candidate, Example
from .llm import ProposerUnavailable, StrandsProposer, _scrub
from .state import Cancelled, RunState, SketchRecord
from .templates import TemplateProposer

log = logging.getLogger(__name__)


@dataclass
class RoundContext:
    """What a proposer sees in one round."""
    round: int
    k: int
    examples: list[Example]
    nl_hint: Optional[str]
    state: RunState

    @property
    def history(self) -> list[SketchRecord]:
        return [r for r in self.state.records.values() if r.round < self.round or r.error]

    def feedback(self) -> str:
        """The message the LLM gets for round >= 2: what each earlier sketch did and the counterexamples."""
        s = self.state
        recs = [r for r in s.records.values() if r.round == self.round - 1 or r.solved_by == "agent"]
        lines = [f"Round {self.round}. Results of the sketches from the previous round (solver output):"]
        lines += [s.outcome_line(r) for r in recs if r.result is not None or r.error] or ["(none)"]
        lines.append(f"\nConsistent sketches so far: {s.n_consistent()} of {self.k} wanted.")
        lines.append("Counterexamples (clips the solved sketches get wrong):\n" + s.counterexample_text(only_round=None))
        lines.append(
            f"\nRevise or add sketches (up to {self.k}), different from those already tried, and call `submit_sketches`. "
            "If a violated clip looks mislabelled or badly perceived, say so and leave the sketches that fit the rest.")
        return "\n".join(lines)


class Proposer(Protocol):
    def propose(self, ctx: RoundContext) -> list[str]: ...


class _FunctionProposer:
    name = "function"

    def __init__(self, fn: Callable[[RoundContext], list[str]]) -> None:
        self.fn = fn

    def propose(self, ctx: RoundContext) -> list[str]:
        return list(self.fn(ctx) or [])


def make_proposer(model) -> Proposer:
    if model is None:
        return StrandsProposer()
    if hasattr(model, "propose"):
        return model
    try:
        from strands.models import Model
        if isinstance(model, Model):
            return StrandsProposer(model)
    except Exception:  # pragma: no cover
        pass
    if callable(model):
        return _FunctionProposer(model)
    raise TypeError(f"model must be None, a proposer, a function or a strands Model, got {type(model).__name__}")


def run_cegis(examples: list[Example], *, nl_hint: Optional[str], emit: Callable[[dict], None], k: int = 6,
              max_rounds: int = 4, model=None, cancel: Optional[threading.Event] = None,
              solve_timeout_s: float = 10.0, backfill: bool = True) -> list[Candidate]:
    """Synthesise ranked candidate rules for the labelled ``examples``.

    ``emit`` receives RunEvent dicts (api.yaml ``RunEvent`` without ``seq`` / ``at_ms``): round_started,
    sketch_proposed, typecheck_failed, solve_started, solve_result, differential_check, counterexample, candidates, done,
    error (an `EncoderMismatch`, which is re-raised).  Candidates are ranked by MDL ascending, then margin descending.
    ``backfill`` tops up with template-library sketches when fewer than K consistent candidates were found, which gives
    the active-learning committee more hypotheses to disagree about.
    """
    if not any(e.positive for e in examples):
        emit({"type": "done", "message": "need at least one positive example"})
        return []
    state = RunState(examples, emit, k=k, cancel=cancel, solve_timeout_s=solve_timeout_s)
    proposer = make_proposer(model)
    fallback = TemplateProposer()
    try:
        for r in range(1, max_rounds + 1):
            state.check_cancel()
            state.start_round(r)
            ctx = RoundContext(r, k, list(examples), nl_hint, state)
            before = len(state.records)
            proposals: list[str] = []
            emit({"type": "round_started", "round": r, "message": f"proposer: {getattr(proposer, 'name', 'custom')}"})
            try:
                proposals = proposer.propose(ctx)
            except Cancelled:
                raise
            except ProposerUnavailable as e:
                log.warning("LLM proposer unavailable: %s", e)
                emit({"type": "round_started", "round": r,
                      "message": f"LLM proposer unavailable ({_scrub(str(e))}); using the template library"})
                proposer = fallback
                proposals = proposer.propose(ctx)
            for text in proposals[: max(k * 2, 1)]:
                state.submit(text)
            todo = state.accepted_this_round[:k]
            for canon in todo:
                state.solve(canon)
            if state.n_consistent() >= k:
                break
            if len(state.records) == before and not todo:
                emit({"type": "round_started", "round": r, "message": "no new sketches proposed; stopping"})
                break
        if backfill and state.n_consistent() < k and not isinstance(proposer, TemplateProposer):
            state.check_cancel()
            state.start_round(state.round)
            extra = fallback.propose(RoundContext(state.round, k, list(examples), nl_hint, state))
            if extra:
                emit({"type": "round_started", "round": state.round, "message": "template-library back-fill"})
                for text in extra:
                    state.submit(text)
                for canon in state.accepted_this_round[:k]:
                    state.solve(canon)
    except Cancelled:
        emit({"type": "done", "message": "cancelled"})
        return _top(state, k)
    out = _top(state, k)
    emit({"type": "candidates", "round": state.round, "rule_ids": [],
          "message": f"{len(out)} candidate(s), {sum(1 for c in out if not c.violated_clip_ids)} consistent with every example"})
    usage = getattr(proposer, "usage", None)
    emit({"type": "done", "round": state.round,
          "message": (f"{len(state.solved())} sketches solved"
                      + (f"; LLM tokens in/out {usage['inputTokens']}/{usage['outputTokens']}"
                         if usage and usage.get("calls") else ""))})
    return out


def _top(state: RunState, k: int) -> list[Candidate]:
    return state.candidates()[:k]
