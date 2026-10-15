# Friction notes — stream C (DSL)

Per-stream notes; combined into `docs/FRICTION_LOG.md` in Phase 3. Format per entry: task, steps, expected vs actual, severity, workaround, suggestion. Stream C touches no Ring/AWS API, so these are tooling and contract findings.

## C-1 Contract grammar mis-lexes `not (` / `not(` as a predicate name
- **Task:** parse `exists p: Person: not (present(p) or facing_camera(p))` with `Lark(GRAMMAR, parser="lalr")`.
- **Steps:** build the parser from `contracts.dsl_ast.GRAMMAR`; parse any formula where `not` is followed by `(`.
- **Expected:** `not` is the negation keyword, the parenthesised formula is its operand (the contract's own examples use `not eventually[…]`, which works).
- **Actual:** `UnexpectedToken: Token('LPAR', '(') … Expected one of: RPAR, COMMA`. `PRED.2` is `/[a-z][a-z0-9_]*(?=\s*\()/`, i.e. any name followed by `(`, with priority 2, so it beats the `NOT` keyword in the contextual lexer's state where both are acceptable. `and (` / `or (` are fine because `PRED` is not acceptable in those parser states.
- **Severity:** medium. LLM sketches very commonly write `not (a or b)`; the printer also needs `not (…)` for negated compound formulas.
- **Workaround (in `dsl/parser.py`, no contract change):** `lexer_callbacks={"PRED": …}` re-tags a PRED token whose text is `not` as `NOT`. Covered by `test_not_followed_by_parenthesis`.
- **Suggestion for the integrator:** fix the grammar (`PRED.2: /(?!not\b)[a-z][a-z0-9_]*(?=\s*\()/` or give the keyword a higher priority) and then drop the callback.

## C-2 Lark's `expected` set after an LALR reduction is an over-approximation
- **Task:** short, correct "expected …" hints in `DSLSyntaxError` for the LLM feedback loop.
- **Actual:** `eventually[0 5] present(p)` reported "expected a formula, ',' or ']'" (terminals valid after the default reduction), which is wrong and noisy.
- **Workaround:** use `exc.interactive_parser.accepts()` (exact accept set for the current state) when available. Now: `unexpected '5'; expected ','`.
- **Severity:** low.

## C-3 Windows text-mode writes CRLF into LF-normalised repos
- **Task:** scripted edits of repo files from Python on Windows.
- **Actual:** `open(p, "w")` writes CRLF; `.gitattributes` (`* text=auto eol=lf`) only normalises at `git add`, so every commit prints "CRLF will be replaced by LF" warnings and `git diff --stat` shows phantom changes.
- **Workaround:** `open(p, "w", encoding="utf-8", newline="\n")`, or `sed -i 's/\r$//'`.
- **Severity:** low.

## Spec findings (semantics) worth a decision before D/E depend on them
These follow PLAN §2.2 literally; none blocks D or E, but D's encoder and E's explanations must share them (all are documented in `docs/DSL.md`, "Edge-case conventions").
1. **`then` / `holds_for` look forward over every start `t1 ≥ t`**, so nested inside a bounded operator (`eventually[0,5] (a then[0,3] b)`) the start is not confined to the enclosing window. Only the rule root is unaffected (the score maximises over `t`). If the intent is "anchored at `t`", the encoder and evaluator would both change `max over t1 ≥ t` to `t1 = t`.
2. **Absence is "from some start time"**: `A and not eventually[0,w] B` holds if some start has no B in the next `w` s, not "B never occurs in the clip" (the score maximises over the start time; `visitor_rings` still matches "door and no ring in the next 30 s" from a start after the ring). Negating a clip-level `attr` is unaffected (`attr` is constant over the clip).
3. **"Nobody is around" is not expressible**: `exists` only ranges over entities in the trace; a clip with no person entity gives no binding for a `Person` variable. The Playground package clip is matched by `exists k: Package: always[0, 24] in_zone(k, steps)` / `holds_for >= 20 in_zone(k, steps)`, not by a rule that mentions a person.
4. **`always` widening is not monotone across the empty-window convention** (`−C`): the property test is stated for non-empty narrow windows, as the plan's "deliberately non-vacuous" convention implies.
