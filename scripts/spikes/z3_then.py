"""Exploratory probe used while designing the Z3 encoding: solve the holes of a toy `then[?a,?b]` sketch with
Z3, then differentially check the solution against an independent NumPy robustness evaluator.

Sketch:  exists p:Person, k:Package:  picks_up(p,k) then[?a,?b] leaves(p, porch)

Not used at runtime: the production encoder is `engine/exemplar/synth/z3enc.py`. Its `rho_then` is also
used by a test as an independent reference (engine/tests/dsl/test_dsl_eval.py).

    uv run --project engine python scripts/spikes/z3_then.py
"""
from __future__ import annotations

import time
from fractions import Fraction

import numpy as np
import z3

C = 0.5
CONF = {"low": 0.6, "med": 0.8, "high": 0.95}
ABSENT = 0.05


def trace(n: int, step_ms: int, facts: dict[tuple, dict[int, str]]) -> dict:
    """facts: atom -> {frame index: conf label}. Times are integer ms (see note at the bottom)."""
    t_ms = np.arange(n, dtype=np.int64) * step_ms
    sig = {}
    for atom, frames in facts.items():
        s = np.full(n, ABSENT)
        for i, c in frames.items():
            s[i] = CONF[c]
        sig[atom] = s
    return {"t_ms": t_ms, "sig": sig, "bindings": [{"p": "p1", "k": "k1"}]}


def atom_sig(tr, name, b):
    key = {"picks_up": ("picks_up", b["p"], b["k"]), "leaves": ("leaves", b["p"], "porch")}[name]
    return tr["sig"].get(key, np.full(len(tr["t_ms"]), ABSENT))


# ---------------------------------------------------------------- NumPy evaluator (independent)
def rho_then(phi: np.ndarray, psi: np.ndarray, t_ms: np.ndarray, a: float, b: float) -> np.ndarray:
    """ρ(φ then[a,b] ψ, t) = max_{t1≥t} min(ρφ(t1), max_{t2: a ≤ t2−t1 ≤ b} ρψ(t2)); empty window → −C."""
    T = len(t_ms)
    inner = np.full(T, -C)
    for i in range(T):
        d = (t_ms - t_ms[i]) / 1000.0          # Δ from integer ms: one rounding, monotone (see note)
        w = (d >= a) & (d <= b)
        if w.any():
            inner[i] = psi[w].max()
        inner[i] = min(phi[i], inner[i])
    return np.maximum.accumulate(inner[::-1])[::-1]   # max over t1 ≥ t


def score(tr, a, b) -> float:
    best = -C
    for bnd in tr["bindings"]:
        phi = atom_sig(tr, "picks_up", bnd) - 0.5
        psi = atom_sig(tr, "leaves", bnd) - 0.5
        best = max(best, rho_then(phi, psi, tr["t_ms"], a, b).max())
    return float(best)


# ---------------------------------------------------------------- Z3 encoding (see docs/DSL.md)
def encode(tr, A, B, m):
    T = len(tr["t_ms"])
    secs = [z3.RealVal(Fraction(int(x), 1000)) for x in tr["t_ms"]]
    ge_b, le_b = [], []
    for bnd in tr["bindings"]:
        phi = atom_sig(tr, "picks_up", bnd) - 0.5
        psi = atom_sig(tr, "leaves", bnd) - 0.5
        rv = lambda x: z3.RealVal(Fraction(float(x)).limit_denominator(10**6))
        # GE/LE of the `then` node at t1 (the top-level max over t of a max over t1≥t collapses to "some t1")
        ge_t1, le_t1 = [], []
        for i in range(T):
            win = [(z3.And(A <= secs[j] - secs[i], secs[j] - secs[i] <= B), j) for j in range(T)]
            ge_psi = z3.Or([z3.And(w, rv(psi[j]) >= m) for w, j in win])
            le_psi = z3.And([z3.Implies(w, rv(psi[j]) <= -m) for w, j in win])
            ge_t1.append(z3.And(rv(phi[i]) >= m, ge_psi))
            le_t1.append(z3.Or(rv(phi[i]) <= -m, le_psi))
        ge_b.append(z3.Or(ge_t1))
        le_b.append(z3.And(le_t1))
    return z3.Or(ge_b), z3.And(le_b)        # exists: OR over bindings for GE, AND for LE


def solve(examples, clip_len_s):
    A, B, m = z3.Reals("a b m")
    opt = z3.Optimize()
    opt.set(timeout=10_000)
    opt.add(0 <= A, A <= B, B <= clip_len_s, 0 <= m, m <= C)   # m ≤ C: empty windows give ρ = −C
    for tr, label, w in examples:
        ge, le = encode(tr, A, B, m)
        opt.add_soft(ge if label else le, w, id="lab")
    opt.maximize(m)            # lexicographic: soft-violations first, then margin, then tightness
    opt.minimize(B - A)
    t0 = time.perf_counter()
    res = opt.check()
    dt = time.perf_counter() - t0
    mod = opt.model()
    val = lambda v: float(Fraction(str(mod.eval(v, model_completion=True).as_fraction())))
    violated = [i for i, (tr, label, w) in enumerate(examples)
                if not z3.is_true(mod.eval(encode(tr, A, B, m)[0 if label else 1], model_completion=True))]
    return res, val(A), val(B), val(m), violated, dt


def main():
    n, step = 24, 1000                                   # 24 frames, 1 s apart
    pos1 = trace(n, step, {("picks_up", "p1", "k1"): {4: "high"}, ("leaves", "p1", "porch"): {10: "high"}})
    pos2 = trace(n, step, {("picks_up", "p1", "k1"): {2: "med"}, ("leaves", "p1", "porch"): {9: "high"}})
    neg = trace(n, step, {("picks_up", "p1", "k1"): {3: "high"}, ("leaves", "p1", "porch"): {22: "high"}})
    examples = [(pos1, True, 1), (pos2, True, 1), (neg, False, 3)]
    res, a, b, m, violated, dt = solve(examples, clip_len_s=(n - 1) * step / 1000)
    print(f"z3: {res}  a={a:.3f}s b={b:.3f}s m={m:.3f}  violated={violated}  solve={dt*1000:.0f} ms")

    ok = True
    for i, (tr, label, _) in enumerate(examples):
        s = score(tr, a, b)
        agree = (s > 0) == label
        margin_ok = (s >= m - 1e-9) if label else (s <= -m + 1e-9)
        ok &= (agree and margin_ok) or i in violated
        print(f"  ex{i} label={label} numpy score={s:+.3f} agree={agree} margin_ok={margin_ok}")
    print("differential check:", "PASS" if ok else "FAIL")
    print("under 1 s:", "PASS" if dt < 1 else "FAIL")
    assert ok

    # Why integer ms: the tightness tiebreak pushes holes exactly onto observed gaps (a = Δ),
    # so evaluators must agree at equality. Float seconds break that:
    print("float pitfall: 0.3-0.1 >= 0.2 ->", 0.3 - 0.1 >= 0.2, "| (300-100)/1000 >= 0.2 ->", (300 - 100) / 1000 >= 0.2)


if __name__ == "__main__":
    main()
