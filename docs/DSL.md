# Exemplar DSL — semantics

**Owner:** stream C (Phase 1) completes this document. It is normative: `engine/exemplar/contracts/dsl_ast.py` (AST + grammar) and `engine/tests/test_contracts.py` must agree with it, and PLAN.md §2.2 is the source it elaborates. The sections below were fixed in Phase 0 because the contracts depend on them.

## Grammar
The Lark LALR grammar is `GRAMMAR` in `contracts/dsl_ast.py`. Precedence, loosest to tightest: `or` < `and` < `then` < prefix (`not`, `eventually[a,b]`, `always[a,b]`, `holds_for >= d`). `then` is left-associative. Any `name(` parses as an atom. Unknown predicates are rejected by the **typechecker** with a readable message, because the CEGIS agent feeds that message back to the LLM. Bounds are seconds; `hour` bounds are integers 0–23; `?name` is a hole.

## Time is integer milliseconds (Phase 0, spike 6)
`Frame.t_ms` is an integer offset from clip start. Evaluators compute a window offset as `(t_ms[j] - t_ms[i]) / 1000`, a single correctly-rounded division, and compare it with `a <= Δ <= b`. They never subtract float seconds. Why it matters: the solver's tightness tiebreak puts holes *exactly* on observed gaps, so evaluators must agree at equality. With float seconds, `0.3 - 0.1 >= 0.2` is `False`. With integer ms, if exact `Δ == b` then the rounded values are equal too, because rounding is monotone. The Z3 encoder uses the exact rationals `t_ms/1000`.

## Signals (`Trace.signal`)
- `s(t) = CONF_VALUE[conf]` when the fact is asserted in that frame (max over duplicates), otherwise `ABSENT_VALUE = 0.05`. `ρ(atom, t) = s(t) − 0.5`.
- `present(e)` is **implied** by any fact mentioning `e` in that frame, with the value of the strongest such fact.
- `attr(e, L)` is at least `CONF_VALUE["med"]` in every frame when `L ∈ e.attrs` (clip-level labels).

## Encoder bound
The margin variable is bounded `0 ≤ m ≤ C`. With the plan's empty-window convention (`ρ = −C`), an `LE` constraint over an empty window is `−C ≤ −m`, so `m ≤ C`.

## Label provenance and the conformal guarantee
| provenance | used by synthesis | used by calibration / recall CI |
|---|---|---|
| `example` | yes | no |
| `active` | yes | no (actively chosen, so not exchangeable with deployment events) |
| `random` | **no** | yes |

`random` labels are also kept **out of synthesis**. The conformal bound `P(false alarm) ≤ α` needs calibration scores from negatives the rule was not fitted on. If they were used for fitting, τ_α would be biased low and the guarantee would not hold. (PLAN.md §2.5 only says active labels never calibrate; this is the other half.)

## Open decision: window tiebreak (spike 6)
PLAN.md §2.3's third objective, "prefer tighter windows", solves `picks_up then[?a,?b] leaves` on positives with gaps 6 s and 7 s to exactly `[6, 7]`. A rule taught from one clip then only matches that clip's exact timing. Proposed replacement: maximise **temporal slack**, the distance from each positive's witness gap to the window edges and from each negative's gaps to the window. Clamp at `a ≥ 0`, then snap to a 0.5 s grid and re-verify. Pending the integrator's decision before stream D starts.

## To be written by stream C
Full robustness semantics per operator (PLAN §2.2), boolean semantics, the English printer's templates, worked examples on the fixtures, and the property-test list.
