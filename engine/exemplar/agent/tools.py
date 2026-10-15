"""The Strands tools the CEGIS agent calls: typecheck, solve_sketch, evaluate, fetch_counterexamples, submit_sketches.

Each tool is a closure over the run's `RunState`, returns plain text (the model reads it), and never raises on bad
input: a mistake is reported back so the model can fix it.
"""
from __future__ import annotations

from typing import Callable

from strands import tool

from ..dsl import DSLError, parse, robustness, to_english, to_text, typecheck, witness
from ..contracts.dsl_ast import holes as ast_holes
from .state import Cancelled, RunState


def _cancelled() -> str:
    return "The run was cancelled by the user. Stop now; do not call any more tools."


def build_tools(state: RunState) -> list[Callable]:
    @tool
    def typecheck_sketch(sketch: str) -> str:
        """Check that a rule sketch parses and type-checks against the ontology. Returns 'ok' or the list of problems.

        Args:
            sketch: DSL text, e.g. "exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] leaves(p, porch)"
        """
        try:
            state.check_cancel()
        except Cancelled:
            return _cancelled()
        errs = state.check(sketch)
        return "ok" if not errs else "problems:\n- " + "\n- ".join(errs)

    @tool
    def solve_sketch(sketch: str) -> str:
        """Fill the holes of a sketch with the exact solver (Z3) against ALL labelled examples and report the result:
        sat/unsat, the solved rule (English + DSL), the margin and which clips it gets wrong (violated clip ids).

        Args:
            sketch: DSL text with holes, e.g. "exists k: Package: holds_for >= ?d in_zone(k, steps)"
        """
        try:
            state.check_cancel()
        except Cancelled:
            return _cancelled()
        with state.lock:
            if state.agent_solves_this_round >= state.max_agent_solves:
                return ("Solve budget for this round is used up. Call submit_sketches with your best sketches; they "
                        "will be solved and reported back.")
            state.agent_solves_this_round += 1
        ok, errs, canon = state.submit(sketch)
        if not ok:
            return "REJECTED (does not typecheck):\n- " + "\n- ".join(errs)
        try:
            rec = state.solve(canon, by="agent")
        except Cancelled:
            return _cancelled()
        return state.outcome_line(rec) + (
            ("\n    English: " + rec.candidate.english) if rec.candidate is not None else "")

    @tool
    def evaluate(rule_text: str, clip_id: str) -> str:
        """Score a CLOSED rule (no holes) on one labelled clip: robustness (> 0 means the rule matches), the label, and
        the witness (the evidence the rule used) or the closest failed attempt.

        Args:
            rule_text: a closed rule, e.g. "exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k)"
            clip_id: the id of a labelled clip, as shown in the task
        """
        try:
            state.check_cancel()
        except Cancelled:
            return _cancelled()
        if clip_id not in state.by_id:
            return f"unknown clip_id {clip_id!r}; known: {', '.join(state.by_id)}"
        try:
            rule = parse(rule_text.strip())
        except DSLError as e:
            return f"syntax error: {e}"
        errs = typecheck(rule)
        if errs:
            return "problems:\n- " + "\n- ".join(errs)
        if ast_holes(rule):
            return "evaluate needs a closed rule (no ?holes); use solve_sketch for sketches"
        tr = state.trace_of(clip_id)
        score = robustness(rule, tr)
        ex = state.by_id[clip_id]
        w = witness(rule, tr)
        spans = "; ".join(f"{s['op']} {s['text']} @ {s['t_start_ms'] / 1000:g}-{s['t_end_ms'] / 1000:g}s (rho {s['rho']:+.2f})"
                          for s in w["spans"][:6])
        verdict = "MATCH" if score > 0 else "no match"
        agree = "agrees with" if (score > 0) == ex.positive else "CONTRADICTS"
        return (f"{to_text(rule)}\n{to_english(rule)}\nscore {score:+.2f} -> {verdict}; label is "
                f"{'POSITIVE' if ex.positive else 'NEGATIVE'} ({agree} the label)\nbindings {w['bindings']}; {spans}")

    @tool
    def fetch_counterexamples() -> str:
        """Show the traces of the clips that your solved sketches get wrong (violated examples), most-violated first.
        Use them to see which fact or ordering separates a violated clip from the rest."""
        try:
            state.check_cancel()
        except Cancelled:
            return _cancelled()
        return state.counterexample_text()

    @tool
    def submit_sketches(sketches: list[str]) -> str:
        """Submit your final sketches for this round (up to K, simplest first). Each is typechecked now; rejected ones
        come back with the error so you can fix and resubmit. Accepted ones are solved against all examples after you
        finish, and the counterexamples are sent back to you.

        Args:
            sketches: list of DSL sketches with holes (?a ?b ?d ...)
        """
        try:
            state.check_cancel()
        except Cancelled:
            return _cancelled()
        lines = []
        for text in sketches[: max(state.k, 1) * 2]:
            ok, errs, canon = state.submit(text)
            lines.append(f"ACCEPTED {canon}" if ok else f"REJECTED {text.strip()}\n    " + "\n    ".join(errs))
        if len(sketches) > state.k * 2:
            lines.append(f"(ignored {len(sketches) - state.k * 2} extra sketches)")
        bad = sum(1 for l in lines if l.startswith("REJECTED"))
        lines.append(f"{len(state.accepted_this_round)} sketch(es) accepted this round"
                     + (f"; {bad} rejected: fix them and call submit_sketches again with the corrected ones." if bad else
                        ". Reply with one short sentence; do not call more tools."))
        return "\n".join(lines)

    return [typecheck_sketch, solve_sketch, evaluate, fetch_counterexamples, submit_sketches]
