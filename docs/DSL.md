# Exemplar DSL — semantics

**Owner:** stream C (Phase 1) completed this document. It is normative: `engine/exemplar/contracts/dsl_ast.py` (AST + grammar) and `engine/tests/test_contracts.py` must agree with it, and PLAN.md §2.2 is the source it elaborates. The sections below were fixed in Phase 0 because the contracts depend on them.

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

## Hole placement: temporal slack (decided 2026-10-15, replaces "prefer tighter windows")
Spike 6: with "prefer tighter windows" as the third objective, positives with gaps of 6 s and 7 s solve to exactly `[6, 7]`, and a rule taught from one clip matches only that exact timing. Instead, after minimising violations and maximising `m`, each hole is moved away from the edges of its feasible interval `[lo_h, hi_h]` (computed by Z3 min/max with the satisfied set and `m*` fixed):
- lower window bounds `a`: `0` if feasible, else the centre of the interval;
- all other holes (`b`, `d`, `h1`, `h2`): the centre of the interval;
- snap to a 0.5 s grid (hours: integers), then re-verify with the NumPy evaluator. If that fails, step back from the Z3 model point towards the snapped point until it passes.

Example: one positive with gap 7 s in a 24 s clip gives `then[0, 15.5]`, not `then[7, 7]`. Owned by stream D (`synth/`), and tested there.

## Semantics

Everything below is implemented in `engine/exemplar/dsl/` and pinned by `engine/tests/dsl/`. A rule is evaluated on a `Trace` with frames `0 … T−1` at times `t_i` (integer ms). Write `Δ(i,j) = (t_j − t_i) / 1000` (one division, see "Time is integer milliseconds") and

    W(i; a, b) = { j : a ≤ Δ(i,j) ≤ b }          the frames in the window [t_i + a, t_i + b], both ends inclusive
    C = 0.5                                       CLAMP; ρ always lies in [−C, C]

`s_P(args)(i)` is the signal of Phase 0 ("Signals"). Atoms are the only place the trace enters.

### Robustness ρ(φ, i) and boolean truth ⟦φ⟧(i), operator by operator

| Operator | Robustness `ρ(φ, i)` | Boolean `⟦φ⟧(i)` |
|---|---|---|
| `P(args)` | `s_P(args)(i) − 0.5` | `s_P(args)(i) > 0.5` |
| `not φ` | `−ρ(φ, i)` | `¬⟦φ⟧(i)` |
| `φ1 and … and φn` | `min_k ρ(φk, i)` | all `⟦φk⟧(i)` |
| `φ1 or … or φn` | `max_k ρ(φk, i)` | any `⟦φk⟧(i)` |
| `eventually[a,b] φ` | `max_{j ∈ W(i;a,b)} ρ(φ, j)`; **`−C` if `W` is empty** | some `j ∈ W` with `⟦φ⟧(j)`; false if `W` is empty |
| `always[a,b] φ` | `min_{j ∈ W(i;a,b)} ρ(φ, j)`; **`−C` if `W` is empty** | `W` non-empty and every `j ∈ W` has `⟦φ⟧(j)` (**false if `W` is empty**) |
| `φ then[a,b] ψ` | `max_{i1 ≥ i} min( ρ(φ, i1), E(i1) )`, `E(i1) = max_{j ∈ W(i1;a,b)} ρ(ψ, j)` or `−C` if that window is empty | some `i1 ≥ i` with `⟦φ⟧(i1)` and some `j ∈ W(i1;a,b)` with `⟦ψ⟧(j)` |
| `holds_for >= d φ` | `max over i1 ≥ i with Δ(i1, T−1) ≥ d of ( min_{j ∈ W(i1;0,d)} ρ(φ, j) )`; **`−C` if no such `i1`** | some `i1 ≥ i` with `Δ(i1, T−1) ≥ d` (i.e. `t_i1 + d ≤ t_end`) and `⟦φ⟧(j)` for every `j ∈ W(i1;0,d)` (and that window non-empty) |

`t_end` is the **last frame's time** (not `Trace.duration_ms`). Bounds `a, b, d` are in seconds; the typechecker guarantees `0 ≤ a ≤ b` and `d ≥ 0` (the evaluators do not re-check, and an inverted or negative window simply behaves as the formulas above say).

### Rules, bindings, context, score

    rule   = exists v1:T1, …, vn:Tn : body  [when ctx1 and … and ctxm]

* **Bindings.** `Trace.bindings(types)`: every assignment of *distinct* entities, each of a type admitted by its variable's declared type (`ontology.VAR_TYPES`). Atom arguments that are variable names are replaced by the bound entity id; zones and labels stay literal.
* **Context atoms** are crisp: `+C` if true, `−C` if false, combined with `and` (min). `hour in [h1,h2]` is inclusive and wraps past midnight when `h1 > h2` (`[22, 6]` = 22,23,0,…,6). `subtype = S` compares `Trace.context.sub_type` for equality (ingest is responsible for filling `sub_type`, including the extras `motion`, `ding`, `on_demand` when Ring supplied no smart sub-type). `device = D` compares `context.device_id`. **A missing context value (`None`) makes the atom false** (`−C`).
* **Score.** `robustness(rule, trace) = max over bindings β of max over frames i of min( ρ(body[β], i), κ )`, where `κ = −C` if some context atom is false and `+C` otherwise. Since `κ` is constant this equals `min(max_β max_i ρ(body[β], i), κ)`; a false context therefore pins the score at exactly `−C`.
* **No bindings, a trace with no frames, or `status = perception_failed` → `−C`.**
* **Match.** `score > 0`. `evaluate_bool(rule, trace)` is the boolean counterpart, computed independently (pure Python, different code path): `∃β ∃i ⟦body[β]⟧(i)` and all context atoms true. For every trace and rule, `evaluate_bool == (robustness > 0)`; ρ is never exactly 0 for signals produced by `Trace.signal` (atoms are ±0.05…0.45 away from 0 and `C ≠ 0`), and the property test only requires agreement where `ρ ≠ 0` so the claim survives other signal sources.

### Edge-case conventions (all deliberate, all tested)

1. **Empty windows are `−C` for both `eventually` and `always`.** "No evidence" is never vacuous truth. Consequences: `not always[a,b] φ` over an empty window is `+C` (true), and widening an `always` window is monotone *only where the narrower window already contained a frame* (the property test is stated that way; `test_always_widening_exception_is_the_empty_window_convention` shows the exception). `eventually` widening is monotone everywhere.
2. **Windows are clipped to the clip.** Offsets beyond the last frame have no frames, so `always[0, 1000] φ` on a 30 s clip is the min over all remaining frames. Use `holds_for` when "for at least d seconds" must be proven by evidence that long.
3. **`then` and `holds_for` search forward over every start `i1 ≥ i`**, exactly as PLAN §2.2 defines them. Nested inside a bounded operator (`eventually[0,5] (a then[0,3] b)`) the start `i1` is therefore *not* confined to the enclosing window. At the top of a rule it makes no difference, because the score already maximises over `i`.
4. **`holds_for` is evidence-based.** "Continuously" means every *sampled* frame in `[t1, t1+d]` holds. With frame spacing larger than `d` a single true frame is enough; the run must also fit inside the clip (`t1 + d ≤ t_end`, equality allowed). The dock fixture is sampled every 6 s from 6 s to 126 s plus 156 s, so `holds_for >= 150` holds and `holds_for >= 151` does not.
5. **Start-time semantics of absence.** The score maximises over the start time, so `A and not eventually[0,w] B` means "there is a start time at which A holds and B does not occur in the next `w` seconds", **not** "B never occurs in the clip" (a start after the last B qualifies). Rules that must exclude an event anywhere in a clip cannot be expressed this way; teach them with a positive formulation or with a context/attribute atom.
6. **Existential bindings.** `exists` ranges over entities that exist in the trace, so "nobody is around" cannot be said as an absence of persons; `unattended_package` (no person entity at all) is matched by `exists k: Package: always[0, 24] in_zone(k, steps)` or `holds_for >= 20 in_zone(k, steps)` instead. A variable that has no admissible entity makes the score `−C`.
7. **Plateau at `−C`.** Many different failures (no bindings, false context, empty windows) give exactly `−0.5`; do not read structure into differences inside that plateau. Differences between scores in `(−C, C)` are meaningful.
8. **Determinism.** Everything is a pure function of `(rule, trace, holes)`. Ties in witnesses resolve to the first binding (in `Trace.bindings` order) and the earliest frame.

### Differential testing hooks
The encoder (stream D) must agree with this evaluator: it uses the same `Δ`, the same `−C` conventions (including empty `always`, which is why `m ≤ C`), and `t_end = last frame`. `tests/dsl/dsl_reference.py` is a third, literal implementation of the table above (scalar recursion over Python lists) used to cross-check the vectorised code.

## Typechecker (`typecheck(rule) -> list[str]`)
Returns every problem found, in tree order; empty means well-typed. Messages are written for the LLM sketch loop (they name the predicate, argument position, expected kind and what was found):

| Check | Message (shape) |
|---|---|
| duplicate variable | `variable 'p' is declared more than once; every variable needs a unique name` |
| variable named like a zone | `variable name 'door' clashes with the zone 'door'; rename the variable` |
| unknown predicate | `unknown predicate 'rings_doorbell'; known: present, in_zone, near, carrying, picks_up, puts_down, rings_bell, enters, leaves, facing_camera, attr` |
| arity | `rings_bell takes 1 argument (rings_bell(Person)), got 2: rings_bell(p, p)` |
| variable type does not fit slot | `argument 1 of rings_bell must be a Person variable (rings_bell(Person)), but 'p' is declared Entity` |
| zone slot | `argument 2 of in_zone: 'garage' is not a zone; zones are: door, porch, …` or `… must be a zone literal (…), not the variable 'p'` |
| label slot | `argument 2 of attr must be a label literal such as hoodie or delivery_uniform, not the variable 'k'` |
| entity slot given a literal | `argument 1 of in_zone must be an entity variable (any type), not the zone 'porch' (in_zone(Entity, Zone))` |
| undeclared variable | `undeclared variable 'q' in near(p, q); declared variables: p: Person` |
| bad window | `eventually[5, 2]: the lower bound must be <= the upper bound (needs 0 <= a <= b)`; `…: bounds are seconds and must be >= 0, got -1`; non-finite numbers rejected |
| `holds_for` | `holds_for: bounds are seconds and must be >= 0, got -3` |
| hours | `hour in [...]: hours must be whole numbers between 0 and 23, got 24` |
| unused variable | `variable 'k' is declared but never used in the formula` |
| device id | `device id 'bad id!' may only contain letters, digits, '.', '_' and '-'` |

A variable of type `T` fits a slot of kind `K` iff `VAR_TYPES[T] ⊆ VAR_TYPES[K]` (so `Package` and `Object` fit `Carryable`, everything fits `Entity`, `Entity` fits only `Entity`). Holes are accepted wherever a number may appear and are not range-checked until they are filled; an unknown or mis-arity atom does not cascade into "unused variable" errors.

## Printers

### Canonical DSL text (`to_text`)
Minimal parentheses by precedence (`or` < `and` < `then` < prefix operators; `then` left-associative, so only a right-nested `then` is parenthesised). Windows print as `eventually[0, 20]`, holds_for as `holds_for >= 120 …`, holes as `?b`, a context clause as ` when hour in [6, 22] and subtype = human`. Numbers: integers without `.0`; other values with up to 3 decimals; **if 3 decimals would change the value, the shortest exact repr is used instead**, so the round trip never loses information (solver output is on a 0.5 s grid, so this only matters for hand-built values). For every well-typed rule in normal form, `parse(to_text(r)) == r`. "Normal form" = nested `and`/`or` flattened, which is all `parse` ever produces; use `normalize(rule)` on hand-built trees first.

### Parser notes
* `parse` accepts exactly `contracts.dsl_ast.GRAMMAR`; numbers become floats, hour bounds ints (a non-integral hour is a syntax error), nested `and`/`or` are flattened, `a then b then c` folds left.
* Errors are `DSLSyntaxError(message, line, column)` with `str(e) == "line L, column C: message"` and `e.context` = the source line with a caret. "Expected" sets come from the parser's exact accept set, e.g. `line 1, column 35: unexpected 'present'; expected '['`.
* Known grammar defect, worked around in the parser (no contract change): `PRED.2` is "a name followed by `(`", which also matches the keyword in `not (…)` / `not(…)`; the parser re-tags a `PRED` token whose text is `not` as the `NOT` keyword (`lexer_callbacks`). Suggested contract fix: give the keyword priority or exclude it in the `PRED` regex (`(?!not\b)`).

### English (`to_english`)
Deterministic templates; no LLM ever paraphrases a rule. A rule is `There is <vars> such that <body>[, when <context>].`

| Piece | Template |
|---|---|
| variable | `a person p`, `an entity e`, `a package k`, `a vehicle v`, `an animal a`, `an object o`, `a package or object k` (Carryable); several: `a person p, a package k and a vehicle v` |
| `present(x)` | `x is present` / negated `x is not present` |
| `in_zone(x, Z)` | `x is <zone phrase>` / `x is not <zone phrase>`; door `at the door`, porch `on the porch`, steps `on the steps`, yard `in the yard`, driveway `in the driveway`, sidewalk `on the sidewalk`, street `in the street`, dock `at the dock` |
| `near(x, y)` | `x is near y` / `x is not near y` |
| `carrying(p, k)` | `p is carrying k` / `p is not carrying k` |
| `picks_up(p, k)` | `p picks up k` / `p does not pick up k` |
| `puts_down(p, k)` | `p puts down k` / `p does not put down k` |
| `rings_bell(p)` | `p rings the doorbell` / `p does not ring the doorbell` |
| `enters(x, Z)` / `leaves(x, Z)` | `x enters the porch` / `x leaves the porch` (negated: `does not enter` / `does not leave`) |
| `facing_camera(p)` | `p faces the camera` / `p does not face the camera` |
| `attr(x, L)` | `x has the attribute "<L with spaces>"` / `x does not have the attribute "…"` |
| `not φ` (atom) | the negated atom template |
| `not eventually[a,b] φ` | `at no point within a to b s, φ` |
| `not φ` (other) | `it is not the case that φ` |
| `φ and ψ` / `φ or ψ` | `φ and ψ` / `φ or ψ` |
| `eventually[a,b] φ` | `at some point within a to b s, φ` |
| `always[a,b] φ` | `at every moment within a to b s, φ` |
| `φ then[a,b] ψ` | `φ, and then within a to b s ψ` |
| `holds_for >= d φ` | `φ continuously for at least d s` |
| `hour in [h1,h2]` | `the local hour is between h1 and h2 inclusive`; wrapping: `the local hour is 22 or later, or 6 or earlier`; with holes: `the local hour is in [?h1, 6] (inclusive; wraps past midnight if the first is larger)` |
| `subtype = S` | `the event sub-type is S` (underscores become spaces) |
| `device = D` | `the device is D` |
| hole | `?name` |

Scope is made explicit with parentheses: a phrase that runs to the right (`at some point…, X`, `X, and then within … Y`, `it is not the case that X`) is parenthesised unless it is the last thing in its clause; `and`/`or`/`then` children of `and`/`or`/unary operators are parenthesised; a left-nested `then` is parenthesised. Numbers use up to 3 decimals.

Example: `exists p: Person, k: Package: picks_up(p, k) then[0, 20] leaves(p, porch)` →
*There is a person p and a package k such that p picks up k, and then within 0 to 20 s p leaves the porch.*

## Python API (`exemplar.dsl`)

```python
parse(text: str) -> Rule                                   # DSLSyntaxError(line, column, message, context)
typecheck(rule: Rule) -> list[str]
to_text(node: Rule | Phi | Ctx | VarDecl) -> str
to_english(node: Rule | Phi | Ctx | VarDecl) -> str
normalize(node) -> node                                    # flatten nested and/or
fmt_num(x: float, exact: bool = False) -> str

robustness(rule, trace, holes=None) -> float               # trace: Trace | PreparedTrace; holes: {name: value}
evaluate(rule, trace, holes=None) -> float                 # = robustness(fill_holes(rule, holes), trace)
evaluate_bool(rule, trace, holes=None) -> bool             # independent implementation
rho(phi, trace, binding: dict[str, str], holes=None) -> np.ndarray   # shape (T,), per-frame rho for one binding
truth_series(phi, trace, binding) -> list[bool]            # boolean counterpart of rho
witness(rule, trace, holes=None) -> dict                   # see below
prepare(trace) -> PreparedTrace                            # cached offsets / signals; reuse across many calls
compile_rule(rule) -> CompiledRule                         # .score(trace, holes=None) -> float; .scores(traces, holes); .holes
```

Unfilled holes raise `UnboundHoleError(names)`. For hole sweeps (synthesis, committee sampling) use `compile_rule(sketch)` and `prepare(trace)` once, then `cr.score(prepared, {"a": 0.5, "b": 8.0})` per point: no pydantic copies, hour holes round with `int(round(x))` exactly like `fill_holes`.

### Witness (`witness(rule, trace)`)
api.yaml `Witness` minus `rule_id`, `tau`, `margin`:

    {"clip_id", "score", "bindings": {var: entity_id}, "entities": [{id, type, attrs}], "english",
     "spans": [{"path", "op", "text", "t_start_ms", "t_end_ms", "rho"}, …]}

The binding and start frame are the argmax of the score (first binding, earliest frame on ties); `spans` (pre-order) explain the descent from there. `path` is an AST path (`body`, `body.left`, `body.args[1]`, `body.arg`); `text` is the DSL text of that subformula; `rho` its robustness at the chosen frame. Spans exist for every temporal node reached, every atom reached (evidence facts), every `not` reached (point span, positive ρ of the absence, no descent), and the root when it is an `and`/`or` (covering its evidence). Times: `eventually` → the chosen frame (earliest best in the window); `always` → first..last frame of the window, descending into the weakest frame; `then` → chosen `t1` to chosen `t2`; `holds_for` → `t1` to the last frame in `[t1, t1+d]`, descending into the weakest frame; `or` → descends into the best branch only; `and` → all branches. A non-matching clip still gets a witness (the closest attempt, score ≤ 0); with no bindings or a failed trace the witness is `score = −C` with empty `bindings`/`spans`.

## Worked examples (fixtures)

Rules (all typecheck):

    theft       exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k) and not attr(p, delivery_uniform)
    dwell       exists v: Vehicle: holds_for >= 120 in_zone(v, dock)
    unattended  exists k: Package: always[0, 24] in_zone(k, steps)
    rings       exists p: Person: eventually[0, 5] rings_bell(p)

Scores (`robustness`; match iff `> 0`):

| fixture | theft | dwell | unattended | rings |
|---|---|---|---|---|
| theft_a | **+0.45** | −0.50 | −0.45 | −0.45 |
| theft_b | **+0.30** | −0.50 | −0.45 | −0.45 |
| delivery_a | −0.45 | −0.50 | −0.45 | −0.45 |
| delivery_b | −0.45 | −0.50 | −0.45 | **+0.45** |
| unattended_package | −0.50 | −0.50 | **+0.45** | −0.50 |
| vehicle_dwell_dock | −0.50 | **+0.45** | −0.50 | −0.45 |
| visitor_rings | −0.50 | −0.50 | −0.50 | **+0.45** |
| visitor_no_ring, vehicle_passby, birds_feeder, empty_scene, perception_failed | ≤ −0.45 | −0.50 | ≤ −0.45 | ≤ −0.45 |

(`−0.50` = no admissible binding, e.g. no vehicle in the clip.) `theft_b` scores 0.30 because its `picks_up` is only `med` confidence (0.8 − 0.5): the weakest link bounds a conjunction.

`theft` on `theft_a` (frames at 0,2,4,6,8,10,12,16,20 s; binding `p→p1, k→k1`):

    ρ picks_up(p,k)                 −.45 −.45 −.45 +.45 −.45 −.45 −.45 −.45 −.45   (high at 6 s)
    ρ carrying(p,k)                 −.45 −.45 −.45 −.45 +.45 +.30 −.45 −.45 −.45   (high 8 s, med 10 s)
    ρ picks_up then[0,10] carrying  +.45 +.45 +.45 +.45 −.45 −.45 −.45 −.45 −.45   (max over t1 ≥ t: only t1 = 6 s works, with ψ at 8 s)
    ρ not attr(p, delivery_uniform) +.45 at every frame                             (p1 is only "hoodie")
    ρ body = min of the last two    +.45 +.45 +.45 +.45 −.45 −.45 −.45 −.45 −.45

so the score is +0.45, first reached at t = 0 (earliest tie). Its witness: `then` span 6000 → 8000 ms (`picks_up(p, k)` at 6000, `carrying(p, k)` at 8000), a `not` span for the attribute, and the `and` root covering 0 → 8000 ms. On `delivery_a` there is no `picks_up` fact, so the `then` is −0.45 and the rule does not match even though the same person leaves the porch.

`dwell` on `vehicle_dwell_dock`: `in_zone(v1, dock)` is `high` at 6, 12, …, 126 s and `med` at 156 s. `holds_for >= 120` is witnessed by `t1 = 6 s` (window 6..126 s, offset exactly 120 s, equality counts), ρ = +0.45, span 6000 → 126000 ms. `holds_for >= 150` needs the 156 s frame (ρ = +0.30); `holds_for >= 151` has no valid start among the true frames (from 6 s only 150 s remain), and the one start that still fits, 0 s, would have to cover the frame at 0 s where the vehicle is not yet in the zone, so the score is −0.45; `holds_for >= 157` exceeds the clip and gives −0.50.

Integer-ms boundary: frames at 100 ms and 300 ms with `picks_up then[0.2, 0.2] leaves` match (`(300−100)/1000 = 0.2` equals the literal); float seconds would give `0.3 − 0.1 = 0.19999999999999998` and miss.

## Property tests (`engine/tests/dsl/test_dsl_properties.py`, Hypothesis)
Strategies (`dsl_strategies.py`) draw random valid traces (1–5 entities of the fixture types, 1–24 frames, integer-ms gaps including awkward ones, random facts and confidences, optional context) and random well-typed rules over them (1–3 variables, every predicate, all operators nested up to 6 leaves, window bounds drawn from the trace's own frame gaps so boundary equality is exercised, optional holes and context atoms).

1. **sign(ρ) agrees with the boolean evaluator** whenever `ρ ≠ 0`, at rule level and pointwise for every frame of random formulas.
2. **Negation duality**: `ρ(¬φ) = −ρ(φ)` exactly, and `¬¬φ` round-trips.
3. **Widening `eventually`** (lower `a`, raise `b`) never decreases ρ. **Widening `always`** never increases ρ where the narrower window is non-empty (see convention 1). **Widening a `then` window** never decreases ρ.
4. `parse(to_text(r)) == r` and `to_text` is a fixed point of parse∘print (with holes and context).
5. `typecheck` accepts every generated well-typed rule; `to_english` is total and deterministic.
6. The vectorised ρ equals the literal reference semantics (`dsl_reference.py`) bit for bit; `robustness` equals the reference score and lies in `[−C, C]`.
7. Hole-filling paths agree: `evaluate`, `compile_rule(...).score`, `robustness(fill_holes(...))`, `evaluate_bool` for random hole values (hours round like `fill_holes`).
8. The one-pass signal index equals `Trace.signal` for every candidate atom.
9. Witnesses are deterministic, consistent with the score, and every span's text/op/ρ/time is a real value of that subformula.

Plus example tests: the three concept rules above on all 12 fixtures, hand-computed ρ series per operator, integer-ms boundary cases, context atoms (hour wrap, missing context), hole errors, and the api.yaml `Witness` JSON schema.

## Performance
`tests/dsl/test_dsl_perf.py` (T = 24 frames, 3 persons × 2 packages = 6 bindings, a 4-node sketch with 3 holes and a context atom): ≈ 0.05–0.10 ms per `(rule, trace)` through `CompiledRule.score` on a `PreparedTrace` (also with every window distinct), ≈ 0.08 ms through `evaluate(sketch, trace, holes)`, ≈ 0.6 ms for a first call on a fresh `Trace` (includes `prepare`), `evaluate_bool` ≈ 0.6 ms, `witness` ≈ 0.2 ms. A 200-point × 40-clip sweep is therefore about 0.5 s. The evaluator batches all bindings into `(B, T, T)` NumPy arrays, caches window masks and atom matrices per prepared trace, and builds the signal index in one pass over the facts.

## Perception conventions the evaluators rely on (integrator, from stream B)
- `near(a, b)` is symmetric in traces: perception adds the mirrored fact, so rules may use either argument order.
- `present(e)` may be omitted by perception whenever another fact mentions `e` (`Trace.signal` implies it).
- Sampled frames sit at the midpoints of equal sub-windows, so the first frame is at `t > 0` and the last is before the clip end. `holds_for` and window edges are evaluated on these sampled frames only.
- `context.sub_type` must be filled at ingest (`human`, `vehicle`, `package_delivery`, `other_motion`, or the extras `motion`, `ding`, `on_demand`). `subtype = S` is strict equality, and a missing value makes the atom false.
- `exists` ranges only over entities that appear in the trace, so "nobody is around" isn't expressible as such. Write the positive form instead, e.g. `exists k: Package: holds_for >= 20 in_zone(k, steps)`.
