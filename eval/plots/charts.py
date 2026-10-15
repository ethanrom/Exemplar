"""The three evaluation charts (static SVG) and their table twin, from `results.json`.

(a) `f1_chart`       F1 at the alpha false-alarm target per concept: Exemplar (k, q) vs zero-shot, mean with min-max over seeds.
(b) `validity_chart` measured test false-alarm rate vs alpha per concept and method, with a Clopper-Pearson 95 % interval.
(c) `cost_chart`      cost per event (USD) and p50 latency per concept, Exemplar vs zero-shot.
`results_table`      markdown twin of all three (every plotted number, so no chart gates a value).
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from eval.harness import metrics

from .svg import SERIES, Svg, fmt, legend, text_width

Row = dict[str, Any]
ZS = "zero_shot_vlm"
EX = "exemplar"


# ------------------------------------------------------------------ aggregation
def concept_titles() -> dict[str, str]:
    try:
        from eval.data.config import load_concepts
        return {cid: c.title for cid, c in load_concepts().items()}
    except Exception:                                                         # noqa: BLE001  (plots must work without the repo data)
        return {}


def select(rows: Iterable[Row], **kw: Any) -> list[Row]:
    return [r for r in rows if all(r.get(k) == v for k, v in kw.items())]


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def spread(rs: Sequence[Row], field: str) -> tuple[float, float, float]:
    xs = [r[field] for r in rs if field in r]
    return (mean(xs), min(xs), max(xs)) if xs else (float("nan"),) * 3


def std(xs: Sequence[float]) -> float:
    return metrics.mean_std(xs)[1]


def concepts_in(rows: Sequence[Row]) -> list[str]:
    """Concepts present in the rows, in the order of concepts.yaml (then alphabetical for unknown ids)."""
    order = {cid: i for i, cid in enumerate(concept_titles())}
    return sorted({r["concept"] for r in rows}, key=lambda c: (order.get(c, len(order)), c))


def headline_config(rows: Sequence[Row]) -> tuple[Optional[int], Optional[int]]:
    """(k, q) of the Exemplar rows to show in the single-config charts: the largest k, then the largest q."""
    ex = select(rows, method=EX)
    if not ex:
        return None, None
    k = max(r["k"] for r in ex)
    return k, max(r["q"] for r in ex if r["k"] == k)


def nice_ticks(vmax: float, n: int = 4) -> list[float]:
    if vmax <= 0:
        return [0.0, 1.0]
    raw = vmax / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    out, v = [], 0.0
    while v <= vmax + step * 0.999:
        out.append(round(v, 10))
        v += step
        if len(out) > 12:
            break
    return out


def n_seeds(rows: Sequence[Row]) -> int:
    return len({r["seed"] for r in rows if r["method"] == EX}) or 1


# ------------------------------------------------------------------ (a) F1
def f1_chart(rows: Sequence[Row], *, alpha: float = 0.1) -> str:
    concepts, titles = concepts_in(rows), concept_titles()
    ex_k = sorted({r["k"] for r in rows if r["method"] == EX})[-2:]
    qs = sorted({r["q"] for r in rows if r["method"] == EX})
    cols: list[tuple[str, str, Optional[int], Optional[int], str]] = []       # (group, series, k, q, label)
    if select(rows, method=ZS):
        cols.append(("zero-shot", "zero_shot", None, None, "zero-shot"))
    for k in ex_k:
        series = "exemplar_a" if k == ex_k[-1] else "exemplar_b"
        for q in qs:
            cols.append((f"Exemplar, k={k}", series, k, q, f"q={q}"))
    pw, ph, pad_l, plot_h = 470, 240, 46, 150
    ncols = max(1, len(concepts))
    per_row = 2 if ncols > 1 else 1
    nrows = math.ceil(ncols / per_row)
    W, H = 24 + per_row * pw + 10, 108 + nrows * ph + 16
    svg = Svg(W, H, title=f"F1 at the {alpha:.0%} false-alarm target, per concept",
              desc="Dot plot per MEVA concept. Each dot is the mean F1 over seeds on the held-out test split; the vertical line spans "
                   "the minimum to maximum over seeds. Exemplar rules taught from k examples with q active questions are compared "
                   "with a zero-shot vision language model prompted with the concept description.")
    svg.text(24, 28, f"F1 at a {alpha:.0%} false-alarm target: few-shot rules vs. zero-shot vision LLM", cls="title")
    svg.text(24, 46, f"MEVA test split; the threshold tau is calibrated on held-out calibration clips. Dot = mean over {n_seeds(rows)} seed(s), "
                     "line = min to max over seeds", cls="sub")
    svg.text(24, 62, "(zero-shot: one deterministic run). k = positive examples given, q = active questions answered.", cls="sub")
    items = []
    if ex_k:
        items.append((f"Exemplar, k={ex_k[-1]}", "s1", "circle", False))
    if len(ex_k) > 1:
        items.append((f"Exemplar, k={ex_k[0]}", "s2", "square", False))
    if any(c[1] == "zero_shot" for c in cols):
        items.append(("Zero-shot Claude, same 16 frames", "s3", "diamond", False))
    legend(svg, 24, 86, items)
    for ci, cid in enumerate(concepts):
        px, py = 24 + (ci % per_row) * pw, 112 + (ci // per_row) * ph
        x0, x1, y0, y1 = px + pad_l, px + pw - 14, py + 22, py + 22 + plot_h
        svg.text(px, py + 8, titles.get(cid, cid), cls="strong")
        for v in (0, 0.25, 0.5, 0.75, 1.0):
            y = y1 - v * plot_h
            svg.line(x0, y, x1, y, "axis" if v == 0 else "grid")
            svg.text(x0 - 8, y + 4, f"{v:.2f}".rstrip("0").rstrip(".") or "0", anchor="end", cls="muted")
        # column x positions: unit spacing, extra half-unit gap between groups
        xs, cur, last_group = [], 0.0, None
        for g, *_ in cols:
            if last_group is not None and g != last_group:
                cur += 0.7
            xs.append(cur)
            cur += 1.0
            last_group = g
        scale = (x1 - x0 - 24) / max(cur - 1, 1)
        cx = [x0 + 12 + u * scale for u in xs]
        groups: dict[str, list[int]] = defaultdict(list)
        for i, c in enumerate(cols):
            groups[c[0]].append(i)
        for i, (g, series, k, q, label) in enumerate(cols):
            rs = select(rows, concept=cid, method=ZS) if k is None else select(rows, concept=cid, method=EX, k=k, q=q)
            svg.text(cx[i], y1 + 16, label if k is not None else "", anchor="middle", cls="muted")
            if not rs:
                continue
            m, lo, hi = spread(rs, "f1")
            meta = SERIES[series]
            if hi > lo:
                svg.line(cx[i], y1 - hi * plot_h, cx[i], y1 - lo * plot_h, f"span l{meta['var'][-1]}")
            svg.marker(meta["shape"], cx[i], y1 - m * plot_h, meta["var"])
            if i == groups[g][-1]:                                                # label the last point of each group
                svg.text(cx[i], y1 - m * plot_h - 11, f"{m:.2f}", anchor="middle", cls="ink")
        for g, idx in groups.items():
            gx = (cx[idx[0]] + cx[idx[-1]]) / 2
            svg.text(gx, y1 + 34, g, anchor="middle", cls="ink")
            if len(idx) > 1:
                svg.line(cx[idx[0]] - 8, y1 + 22, cx[idx[-1]] + 8, y1 + 22, "grid")
    return svg.render()


# ------------------------------------------------------------------ (b) validity
def far_interval(rs: Sequence[Row]) -> tuple[float, float, float]:
    """(mean false-alarm rate over seeds, CP 95 % low, high) with n = the test negatives of one run."""
    far = mean([r["false_alarm_rate"] for r in rs])
    n = int(rs[0].get("n_test_neg") or 0)
    if n <= 0:
        return far, float("nan"), float("nan")
    lo, hi = metrics.clopper_pearson(int(round(far * n)), n)
    return far, lo, hi


def validity_chart(rows: Sequence[Row], *, alpha: float = 0.1, k: Optional[int] = None, q: Optional[int] = None) -> str:
    concepts, titles = concepts_in(rows), concept_titles()
    hk, hq = headline_config(rows)
    k, q = (k if k is not None else hk), (q if q is not None else hq)
    entries: list[tuple[str, list[Row], str, str, bool, str]] = []        # (concept, rows, series var, shape, hollow, label)
    items: dict[str, list[tuple[str, list[Row], str, str, bool]]] = {}
    for cid in concepts:
        its = []
        ex = select(rows, concept=cid, method=EX, k=k, q=q)
        if ex:
            its.append((f"Exemplar, k={k}, q={q}  ({len(ex)} seeds)", ex, "s1", "circle", False))
        zs = select(rows, concept=cid, method=ZS)
        if zs:
            its.append(("Zero-shot, calibrated at the same α", zs, "s3", "diamond", False))
            nat = [{**r, "false_alarm_rate": r["native_false_alarm_rate"]} for r in zs if "native_false_alarm_rate" in r]
            if nat:
                its.append(("Zero-shot, its own yes/no (uncalibrated)", nat, "s3", "diamond", True))
        items[cid] = its
    pts = [far_interval(rs) for its in items.values() for _, rs, *_ in its]
    top = max([p[2] for p in pts if math.isfinite(p[2])] + [alpha * 2.5])
    xmax = min(1.0, math.ceil(top * 10) / 10)
    row_h, grp_gap, label_w = 28, 26, 280
    n_rows = sum(len(v) for v in items.values())
    H = 118 + n_rows * row_h + len(items) * (grp_gap + 6) + 40
    W = 980
    x0, x1 = label_w + 30, W - 40
    svg = Svg(W, H, title="Measured false-alarm rate on the test split versus the target alpha",
              desc="For each MEVA concept the measured false-alarm rate on held-out negative test clips with its 95 percent "
                   "Clopper-Pearson interval, for Exemplar, the calibrated zero-shot baseline and the uncalibrated zero-shot answer. "
                   "A vertical line marks the target alpha.")
    svg.text(24, 28, f"Does the false-alarm guarantee hold? Measured rate vs. target α = {alpha:g}", cls="title")
    svg.text(24, 48, "Held-out test negatives. Dot = rate (Exemplar: mean over seeds, small dots = single seeds), bar = 95 % Clopper-Pearson "
                     "interval. Left of the line = within target.", cls="sub")
    legend(svg, 24, 76, [("Exemplar (calibrated)", "s1", "circle", False), ("Zero-shot, calibrated", "s3", "diamond", False),
                         ("Zero-shot, uncalibrated", "s3", "diamond", True)])
    y_top = 96
    plot_top, y = y_top + 14, y_top + 30
    ticks = [i / 20 for i in range(0, int(xmax * 20) + 1)] if xmax <= 0.3 else [i / 10 for i in range(0, int(xmax * 10) + 1)]
    sx = lambda v: x0 + (x1 - x0) * v / xmax                                # noqa: E731
    body_y0 = y
    for cid, its in items.items():
        svg.text(24, y + 4, titles.get(cid, cid), cls="strong")
        y += grp_gap - 6
        for label, rs, var, shape, hollow in its:
            far, lo, hi = far_interval(rs)
            cy = y + 10
            svg.text(40, cy + 4, label, cls="ink" if not hollow else "")
            if math.isfinite(lo):
                svg.line(sx(lo), cy, sx(hi), cy, f"span l{var[-1]}")
            if rs[0]["method"] == EX and len(rs) > 1:
                for r in rs:
                    svg.marker(shape, sx(r["false_alarm_rate"]), cy, var, r=2.5, faint=True)
            svg.marker(shape, sx(far), cy, var, hollow=hollow)
            if math.isfinite(lo) and lo > alpha:                              # statistically above the target: say so
                svg.text(sx(hi) + 8, cy + 4, f"{far:.2f} > α", cls="strong")
            y += row_h
        y += 12
    body_y1 = y - 6
    for v in ticks:
        svg.line(sx(v), body_y0 - 6, sx(v), body_y1, "grid" if v else "axis")
        svg.text(sx(v), body_y1 + 16, f"{v:g}", anchor="middle", cls="muted")
    svg.line(sx(alpha), plot_top, sx(alpha), body_y1, "rule")
    svg.text(sx(alpha) + 6, plot_top + 6, f"α = {alpha:g}", cls="strong")
    svg.text((x0 + x1) / 2, body_y1 + 34, "false-alarm rate on test negatives", anchor="middle", cls="muted")
    return svg.render()


# ------------------------------------------------------------------ (c) cost and latency
def cost_chart(rows: Sequence[Row], *, k: Optional[int] = None, q: Optional[int] = None) -> str:
    concepts, titles = concepts_in(rows), concept_titles()
    hk, hq = headline_config(rows)
    k, q = (k if k is not None else hk), (q if q is not None else hq)
    panels = [("usd_per_event", "Model cost per event (USD)", lambda v: f"${v:.4f}", 1.0),
              ("p50_latency_ms", "Median latency per event (s)", lambda v: f"{v:.1f} s", 1 / 1000)]
    bar_h, bar_gap, grp_gap = 14, 4, 22
    W = 980
    n = len(concepts)
    H = 116 + n * (2 * bar_h + bar_gap + grp_gap) + 52
    svg = Svg(W, H, title="Cost and latency per event, Exemplar versus zero-shot",
              desc="Horizontal bars per MEVA concept comparing the model cost per event in US dollars and the median latency per event "
                   "for an Exemplar rule (fast perception plus amortised synthesis plus expected escalation) with the zero-shot "
                   "vision language model call.")
    svg.text(24, 28, "What a decision costs: Exemplar rule vs. one strong-model call per event", cls="title")
    svg.text(24, 48, f"Exemplar (k={k}, q={q}): fast-model perception + synthesis amortised over the test events + expected escalation. "
                     "Zero-shot: one strong-model call on the same 16 frames.", cls="sub")
    legend(svg, 24, 76, [(f"Exemplar, k={k}, q={q}", "s1", "circle", False), ("Zero-shot Claude, same 16 frames", "s3", "diamond", False)])
    label_w = 210
    pw = (W - 24 - 24 - label_w - 40) / 2
    for pi, (field, title, fmt_v, scale) in enumerate(panels):
        px = 24 + label_w + pi * (pw + 40)
        vals = [r[field] * scale for r in rows if field in r and (r["method"] == ZS or (r["method"] == EX and r["k"] == k and r["q"] == q))]
        vmax = max(vals) if vals else 1.0
        ticks = nice_ticks(vmax * 1.25, 4)
        xmax = ticks[-1] or 1.0
        sx = lambda v: px + (pw - 70) * v / xmax                                # noqa: E731
        top, bottom = 112, 112 + n * (2 * bar_h + bar_gap + grp_gap) - 8
        svg.text(px, 100, title, cls="strong")
        for t in ticks:
            svg.line(sx(t), top - 6, sx(t), bottom, "grid" if t else "axis")
            svg.text(sx(t), bottom + 16, f"{t:g}", anchor="middle", cls="muted")
        y = top
        for cid in concepts:
            if pi == 0:
                svg.text(24, y + bar_h + 2, titles.get(cid, cid), cls="strong")
            for rs, var in ((select(rows, concept=cid, method=EX, k=k, q=q), "s1"), (select(rows, concept=cid, method=ZS), "s3")):
                if rs and all(field in r for r in rs):
                    v = mean([r[field] for r in rs]) * scale
                    w = max(2.0, sx(v) - px)
                    svg.hbar(px, y, w, bar_h, var)
                    svg.text(px + w + 6, y + bar_h - 3, fmt_v(v), cls="ink")
                y += bar_h + bar_gap
            y += grp_gap - bar_gap
    return svg.render()


# ------------------------------------------------------------------ table twin
def results_table(rows: Sequence[Row], *, alpha: float = 0.1) -> str:
    titles = concept_titles()
    lines = [f"# Evaluation results (alpha = {alpha:g}, MEVA test split)", "",
             "Mean over seeds (std in brackets). FA = measured false-alarm rate on test negatives; its 95 % Clopper-Pearson interval is "
             "computed from the mean rate and the number of test negatives. usd = model cost per event.", "",
             "| concept | method | k | q | seeds | F1 | precision | recall | FA [95 % CI] | guarantee | tokens/ev | usd/ev | p50 s | escalated |",
             "|---|---|---:|---:|---:|---|---|---|---|---|---:|---:|---:|---:|"]
    groups: dict[tuple, list[Row]] = defaultdict(list)
    for r in rows:
        groups[(r["concept"], r["method"], r["k"], r["q"])].append(r)
    for key in sorted(groups, key=lambda t: (t[0], t[1] != ZS, t[2], t[3])):
        rs = groups[key]
        cid, method, k, q = key
        f = lambda fld: (mean([r[fld] for r in rs if fld in r]), std([r[fld] for r in rs if fld in r]))       # noqa: E731
        f1, p, rc = f("f1"), f("precision"), f("recall")
        far, lo, hi = far_interval(rs)
        g = [r.get("guarantee") for r in rs]
        gtxt = "yes" if all(g) and g else ("no" if not any(g) else "some")
        fmt3 = lambda t: f"{t[0]:.3f} ({t[1]:.3f})" if len(rs) > 1 else f"{t[0]:.3f}"                       # noqa: E731
        lines.append(f"| {titles.get(cid, cid)} | {'zero-shot' if method == ZS else 'Exemplar'} | {k if method == EX else '-'} | "
                     f"{q if method == EX else '-'} | {len(rs)} | {fmt3(f1)} | {fmt3(p)} | {fmt3(rc)} | {far:.3f} [{lo:.3f}, {hi:.3f}] | "
                     f"{gtxt} | {mean([r.get('tokens_per_event', float('nan')) for r in rs]):.0f} | "
                     f"{mean([r.get('usd_per_event', float('nan')) for r in rs]):.4f} | "
                     f"{mean([r.get('p50_latency_ms', float('nan')) for r in rs]) / 1000:.1f} | "
                     f"{mean([r.get('escalated_fraction', float('nan')) for r in rs]):.2f} |")
        if method == ZS and "native_f1" in rs[0]:
            lines.append(f"| {titles.get(cid, cid)} | zero-shot, own yes/no | - | - | 1 | {rs[0]['native_f1']:.3f} | "
                         f"{rs[0]['native_precision']:.3f} | {rs[0]['native_recall']:.3f} | {rs[0]['native_false_alarm_rate']:.3f} | no | | | | |")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ driver
def write_all(rows: Sequence[Row], out_dir: Path, *, alpha: float = 0.1, k: Optional[int] = None, q: Optional[int] = None) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {"f1_by_concept.svg": f1_chart(rows, alpha=alpha), "validity.svg": validity_chart(rows, alpha=alpha, k=k, q=q),
             "cost_latency.svg": cost_chart(rows, k=k, q=q), "results_table.md": results_table(rows, alpha=alpha)}
    paths = []
    for name, body in files.items():
        p = out_dir / name
        p.write_text(body, encoding="utf-8", newline="\n")
        paths.append(p)
    return paths
