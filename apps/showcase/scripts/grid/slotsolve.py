"""One Lab-grid slot through the real engine (SPEC 4.5): `RunState` (k = 6) -> `submit` every sketch of the bank in
order -> `solve` every accepted sketch with `solve_timeout_s = 60` -> `candidates()[:6]`.  No proposer, no rounds, no
back-fill.  Workers call `init()` once, then `solve_slot(slot)`."""
from __future__ import annotations

import time
from typing import Optional

import gridlib as G

STATUS_CODE = {"sat": 0, "unsat": 1, "rejected": 2, "timeout": 3, "grid_fallback": 4, "error": 5}

_ctx: dict = {}


def init() -> None:
    """Load traces and the sketch bank once per process and spy on the placement step (to capture the Z3 model point
    when the engine had to step back from the slack centre)."""
    import exemplar.synth.solve as S
    lib = G.library()
    cur = G.curated(lib)
    bank = G.sketch_bank()
    _ctx.update(cur=cur, bank=bank, text_to_id={b["text"]: b["id"] for b in bank})
    orig = S._place
    cap: dict = {}

    def spy(enc, cr, p0, m_star, sat_idx, timeout_s):
        holes, how = orig(enc, cr, p0, m_star, sat_idx, timeout_s)
        cap["how"], cap["p0"], cap["holes"] = how, dict(p0), dict(holes)
        return holes, how

    S._place = spy
    _ctx["cap"] = cap


def _examples(slot: int):
    from exemplar.synth import Example
    states = G.decode_slot(slot)
    return [Example(c.trace, st == 1, G.WEIGHT, c.alias) for c, st in zip(_ctx["cur"], states) if st != 0]


def solve_slot(slot: int) -> dict:
    """Returns {"slot", "entries": [per sketch id dict], "top6": [sketch ids], "ms"}."""
    from exemplar.synth import EncoderMismatch
    from exemplar.agent.state import RunState
    cur, bank, cap = _ctx["cur"], _ctx["bank"], _ctx["cap"]
    alias_bit = {c.alias: i for i, c in enumerate(cur)}
    examples = _examples(slot)
    t0 = time.perf_counter()
    st = RunState(examples, lambda e: None, k=G.K_TOP, solve_timeout_s=G.SOLVE_TIMEOUT_S)
    entries: list[Optional[dict]] = []
    for b in bank:
        ok, errs, canon = st.submit(b["text"])
        if not ok:
            entries.append({"status": STATUS_CODE["rejected"], "note": "; ".join(errs)[:200]})
            continue
        if canon != b["text"]:
            raise AssertionError(f"sketch {b['id']} is not canonical")
        cap.clear()
        try:
            rec = st.solve(canon)
        except EncoderMismatch as e:
            entries.append({"status": STATUS_CODE["error"], "note": str(e)[:300]})
            continue
        if rec.error:                                     # SketchError at solve time
            entries.append({"status": STATUS_CODE["rejected"], "note": rec.error[:200]})
            continue
        res = rec.result
        e = {"status": STATUS_CODE[res.status], "solve_ms": res.solve_ms}
        if res.rule is not None:
            e["holes"] = [res.holes[h] for h in b["holes"]]
            e["margin"] = res.margin
            e["mdl"] = rec.candidate.mdl
        e["violated"] = sum(1 << alias_bit[c] for c in res.violated)
        e["satisfied"] = sum(1 << alias_bit[c] for c in res.satisfied)
        e["note"] = res.note
        if res.status == "sat" and b["holes"]:
            e["how"] = cap.get("how")
            if cap.get("how") != "slack-centre":
                e["p0"] = [cap["p0"][h] for h in b["holes"]]
        entries.append(e)
    top = [_ctx["text_to_id"][c.sketch_text] for c in st.candidates()[: G.K_TOP]]
    return {"slot": slot, "entries": entries, "top6": top, "ms": int((time.perf_counter() - t0) * 1000)}
