"""Shared state of one CEGIS run: every sketch seen so far, its typecheck / solve outcome, and the event stream.

Both the orchestrator (`cegis.run_cegis`) and the agent's tools (`tools.py`) go through `RunState`, so a sketch the
agent tries by hand is solved once, appears in the timeline once, and can become a candidate.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from ..contracts.dsl_ast import Rule
from ..contracts.trace import Trace
from ..dsl import DSLError, parse, to_text, typecheck
from ..synth import Candidate, EncoderMismatch, Example, SketchError, SolveResult, mdl, render_trace_text, solve_sketch

log = logging.getLogger(__name__)


@dataclass
class SketchRecord:
    text: str                                  # canonical DSL text of the sketch
    sketch: Optional[Rule]
    round: int
    error: Optional[str] = None                # parse / typecheck problem (the sketch was rejected)
    result: Optional[SolveResult] = None
    candidate: Optional[Candidate] = None
    solved_by: str = "orchestrator"            # or "agent" when the LLM tried it through a tool

    @property
    def consistent(self) -> bool:
        return self.candidate is not None and not self.candidate.violated_clip_ids


class Cancelled(Exception):
    """The caller set the cancel event."""


class RunState:
    def __init__(self, examples: list[Example], emit: Callable[[dict], None], *, k: int,
                 cancel: Optional[threading.Event] = None, solve_timeout_s: float = 10.0,
                 max_agent_solves_per_round: int = 12) -> None:
        self.examples = list(examples)
        self.by_id = {e.clip_id: e for e in self.examples}
        if len(self.by_id) != len(self.examples):
            raise ValueError("example clip ids must be unique")
        self._emit = emit
        self.k = k
        self.cancel = cancel
        self.solve_timeout_s = solve_timeout_s
        self.max_agent_solves = max_agent_solves_per_round
        self.round = 0
        self.records: dict[str, SketchRecord] = {}
        self.accepted_this_round: list[str] = []         # canonical texts, in submission order
        self.agent_solves_this_round = 0
        self.lock = threading.RLock()
        self.cancel_hooks: list[Callable[[], None]] = []

    # ------------------------------------------------------------------ plumbing
    def emit(self, event: dict) -> None:
        try:
            self._emit(event)
        except Exception:                                  # a broken listener must not kill the run
            log.exception("emit callback failed for %s event", event.get("type"))

    def check_cancel(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            for hook in list(self.cancel_hooks):           # e.g. Strands `Agent.cancel`: stop the model loop now
                try:
                    hook()
                except Exception:                           # pragma: no cover
                    log.exception("cancel hook failed")
            raise Cancelled()

    def start_round(self, r: int) -> None:
        with self.lock:
            self.round = r
            self.accepted_this_round = []
            self.agent_solves_this_round = 0

    # ------------------------------------------------------------------ parse / typecheck / submit
    def parse_sketch(self, text: str) -> tuple[Optional[Rule], list[str]]:
        """(rule, errors).  Errors are written for the LLM."""
        try:
            rule = parse(text.strip())
        except DSLError as e:
            return None, [f"syntax error: {e}" + (f"\n{e.context}" if getattr(e, 'context', None) else "")]
        except Exception as e:                              # lark raised something unexpected
            return None, [f"could not parse the sketch: {type(e).__name__}: {e}"]
        errs = typecheck(rule)
        if not errs:
            try:
                from ..synth.z3enc import hole_kinds
                hole_kinds(rule)
            except SketchError as e:
                errs = [str(e)]
        return (rule if not errs else None), errs

    def check(self, text: str) -> list[str]:
        """Typecheck only (no events, no state)."""
        return self.parse_sketch(text)[1]

    def submit(self, text: str) -> tuple[bool, list[str], str]:
        """Register a proposed sketch for this round: (accepted, errors, canonical text)."""
        self.check_cancel()
        rule, errs = self.parse_sketch(text)
        if rule is None:
            with self.lock:
                self.emit({"type": "typecheck_failed", "round": self.round, "sketch": text.strip(),
                           "error": "; ".join(errs)})
            return False, errs, text.strip()
        canon = to_text(rule)
        with self.lock:
            rec = self.records.get(canon)
            if rec is None:
                self.records[canon] = SketchRecord(canon, rule, self.round)
                self.emit({"type": "sketch_proposed", "round": self.round, "sketch": canon})
            if canon not in self.accepted_this_round:
                self.accepted_this_round.append(canon)
        return True, [], canon

    # ------------------------------------------------------------------ solve
    def weighted_violations(self, violated: tuple[str, ...]) -> float:
        return sum(self.by_id[c].weight for c in violated)

    def solve(self, canon: str, *, by: str = "orchestrator") -> SketchRecord:
        """Solve a registered sketch (cached): emits solve_started / solve_result / differential_check /
        counterexample.  `EncoderMismatch` is an encoder bug: it is reported as an `error` event and re-raised."""
        self.check_cancel()
        with self.lock:
            rec = self.records[canon]
            if rec.result is not None:
                return rec
        self.emit({"type": "solve_started", "round": self.round, "sketch": canon})
        t0 = time.perf_counter()
        try:
            res = solve_sketch(rec.sketch, self.examples, timeout_s=self.solve_timeout_s)
        except EncoderMismatch as e:
            self.emit({"type": "error", "round": self.round, "sketch": canon, "error": f"encoder mismatch: {e}"})
            raise
        except SketchError as e:
            rec.error = str(e)
            self.emit({"type": "typecheck_failed", "round": self.round, "sketch": canon, "error": str(e)})
            return rec
        rec.result, rec.solved_by = res, by
        if res.rule is not None:
            rec.candidate = Candidate.from_result(res, mdl(res.sketch, self.weighted_violations(res.violated)))
        self.emit({"type": "solve_result", "round": self.round, "sketch": canon, "result": res.status,
                   "holes": dict(res.holes) if res.rule is not None else None,
                   "margin": res.margin if res.rule is not None else None,
                   "violated_clip_ids": list(res.violated),
                   "message": f"{res.solve_ms} ms; {res.note}" if res.note else f"{res.solve_ms} ms"})
        if res.rule is not None and res.diff_check_ok:
            self.emit({"type": "differential_check", "round": self.round, "sketch": canon,
                       "message": f"NumPy evaluator agrees with Z3 on {len(self.examples)} examples "
                                  f"(margin {res.margin:.2f})"})
        if res.rule is not None and res.violated:
            self.emit({"type": "counterexample", "round": self.round, "sketch": canon,
                       "violated_clip_ids": list(res.violated),
                       "message": f"{len(res.violated)} labelled example(s) violated: perception suspect?"})   # ids stay in violated_clip_ids
        log.debug("solved %s in %.0f ms: %s", canon, (time.perf_counter() - t0) * 1000, res.status)
        return rec

    # ------------------------------------------------------------------ views
    def solved(self) -> list[SketchRecord]:
        return [r for r in self.records.values() if r.result is not None]

    def candidates(self) -> list[Candidate]:
        ranked = sorted((r.candidate for r in self.solved() if r.candidate is not None),
                        key=lambda c: (c.mdl, -c.margin, c.dsl_text))
        out: dict[str, Candidate] = {}
        for c in ranked:                                   # the same closed rule from two sketches counts once
            out.setdefault(c.dsl_text, c)
        return list(out.values())

    def n_consistent(self) -> int:
        return len({r.candidate.dsl_text for r in self.solved() if r.consistent})

    def trace_of(self, clip_id: str) -> Trace:
        t = self.by_id[clip_id].trace
        return t.trace if hasattr(t, "trace") else t

    def render_clip(self, clip_id: str) -> str:
        e = self.by_id[clip_id]
        return f"clip_id={clip_id} label={'POSITIVE' if e.positive else 'NEGATIVE'} weight={e.weight:g}\n" \
               f"{render_trace_text(self.trace_of(clip_id))}"

    def outcome_line(self, rec: SketchRecord) -> str:
        if rec.error:
            return f"REJECTED {rec.text}  -> {rec.error}"
        res = rec.result
        if res is None:
            return f"(not solved) {rec.text}"
        if res.rule is None:
            return f"{res.status.upper()} {rec.text}  -> {res.note or 'no rule found'}"
        c = rec.candidate
        fit = "fits every example" if not res.violated else "VIOLATES " + ", ".join(
            f"{cid}({'pos' if self.by_id[cid].positive else 'neg'})" for cid in res.violated)
        return f"SAT {rec.text}\n    solved: {c.dsl_text}\n    margin {res.margin:.2f}, mdl {c.mdl:.1f}; {fit}"

    def counterexample_text(self, *, max_clips: int = 4, only_round: Optional[int] = None) -> str:
        """Rendered traces of the clips the solved sketches violate most (the CEGIS counterexamples)."""
        count: dict[str, int] = {}
        for r in self.solved():
            if only_round is not None and r.round != only_round:
                continue
            if r.result is not None and r.result.rule is not None:
                for c in r.result.violated:
                    count[c] = count.get(c, 0) + 1
        if not count:
            return "No sketch has any counterexample yet."
        top = sorted(count, key=lambda c: (-count[c], c))[:max_clips]
        return "\n\n".join(f"[violated by {count[c]} sketch(es)] " + self.render_clip(c) for c in top)
