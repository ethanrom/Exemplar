"""Model cost per event versus the number of deployed rules: `docs/eval/cost_vs_rules.svg` + `.md`.

    uv run --project engine python eval/plots/cost_vs_rules.py [--data-dir DIR] [--max-rules 10]
                                                                 [--svg PATH] [--md PATH]

Every number comes from a cost ledger written by the evaluation run, nothing is modelled:

* Exemplar: perception runs once per event, whatever the number of rules; scoring a rule on the cached trace is a
  NumPy evaluation (0.05-0.1 ms, no model call). Cost per event = mean `usd` of the fast-perception calls in
  `<data-dir>/eval/precompute.jsonl` (one row per clip; 1,005 clips).
* Zero-shot prompting: one strong-model call per rule per event (the baseline asks one concept per call, on the same 16
  frames). Cost per call = median `usd` of the `zero_shot` rows in `<data-dir>/eval/costs.jsonl` (527 calls; the mean is
  reported next to it in the table notes). The median is the lower of the two, so the baseline is not overstated.

The ledgers live in the gitignored `data/` directory. When they are not found the script falls back to the figures
recorded below (copied from those ledgers on 2026-10-15), so the chart can be regenerated from a fresh clone.
Chart conventions follow the dataviz reference palette (slots 1 and 2, validated with the palette validator in both modes):
2 px lines, markers >= 8 px with a 2 px surface ring, circle versus square as the non-colour identity channel,
direct labels plus a legend, light and dark selected through `prefers-color-scheme`.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Figures copied from data/eval/precompute.jsonl and data/eval/costs.jsonl (2026-10-15); used only if those are missing.
FALLBACK = {
    "exemplar_usd": 0.0017873, "exemplar_n": 1005, "exemplar_p50_latency_s": 15.6,
    "zero_shot_median_usd": 0.013328, "zero_shot_mean_usd": 0.013507, "zero_shot_n": 527,
}


@dataclass(frozen=True)
class Measured:
    exemplar_usd: float            # mean fast-perception USD per event
    exemplar_n: int
    exemplar_p50_latency_s: float
    zero_shot_usd: float           # median strong-model USD per call (= per rule per event)
    zero_shot_mean_usd: float
    zero_shot_n: int
    from_ledgers: bool


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_measured(data_dir: Path) -> Measured:
    pre, costs = data_dir / "eval" / "precompute.jsonl", data_dir / "eval" / "costs.jsonl"
    if not (pre.is_file() and costs.is_file()):
        print(f"note: {pre} / {costs} not found; using the recorded figures", file=sys.stderr)
        f = FALLBACK
        return Measured(f["exemplar_usd"], f["exemplar_n"], f["exemplar_p50_latency_s"], f["zero_shot_median_usd"],
                        f["zero_shot_mean_usd"], f["zero_shot_n"], False)
    rows = [r for r in _jsonl(pre) if r.get("status") == "ok" and not r.get("cached")]
    lat = [r["perception_latency_ms"] for r in rows if r.get("perception_latency_ms")]
    zs = [r["usd"] for r in _jsonl(costs) if r.get("phase") == "zero_shot"]
    return Measured(exemplar_usd=statistics.fmean(r["usd"] for r in rows), exemplar_n=len(rows),
                    exemplar_p50_latency_s=statistics.median(lat) / 1000, zero_shot_usd=statistics.median(zs),
                    zero_shot_mean_usd=statistics.fmean(zs), zero_shot_n=len(zs), from_ledgers=True)


def usd_fmt(x: float) -> str:
    """Dollar amounts as shown in the chart and the table: 4 decimals from $0.01, else 5 significant decimals."""
    return f"${x:.4f}" if x >= 0.01 else f"${x:.5f}"


# ------------------------------------------------------------------------------------------------------ the table
def table_rows(m: Measured, max_rules: int) -> list[tuple[int, float, float, float]]:
    ex, zs = round(m.exemplar_usd, 5), round(m.zero_shot_usd, 4)      # the rounded values are what the reader sees
    return [(n, ex, n * zs, n * zs / ex) for n in range(1, max_rules + 1)]


def markdown(m: Measured, max_rules: int) -> str:
    rows = table_rows(m, max_rules)
    ex, zs = rows[0][1], round(m.zero_shot_usd, 4)
    src = ("`data/eval/precompute.jsonl` and `data/eval/costs.jsonl` (gitignored; regenerate with the commands in `eval/README.md`)"
           if m.from_ledgers else "the recorded figures in `eval/plots/cost_vs_rules.py` (copied from those ledgers on 2026-10-15)")
    lines = [
        "# Model cost per event versus number of rules",
        "",
        f"![Cost per event as rules are added: Exemplar stays at {usd_fmt(ex)}; zero-shot prompting grows by {usd_fmt(zs)} per rule](cost_vs_rules.svg)",
        "",
        "Text twin of `cost_vs_rules.svg`. Dollar amounts are model spend per event while the rules are watching "
        "(one-time teaching cost is not included).",
        "",
        "| Rules deployed | Exemplar, $ per event | Zero-shot prompting, $ per event | Zero-shot / Exemplar |",
        "|---:|---:|---:|---:|",
    ]
    for n, e, z, ratio in rows:
        lines.append(f"| {n} | {usd_fmt(e)} | {usd_fmt(z)} | {ratio:.0f}x |")
    lines += [
        "",
        "## How the numbers are obtained",
        "",
        f"- **Exemplar, {usd_fmt(ex)} per event, flat.** Mean cost of the fast model's perception of one clip: "
        f"{m.exemplar_n:,} clips, 16 frames each, p50 perception latency {m.exemplar_p50_latency_s:.1f} s. "
        "The trace is cached, so adding a rule adds no model call: scoring a rule on a cached trace takes "
        "about 0.05 to 0.1 ms in the NumPy evaluator (`docs/DSL.md`, Performance).",
        f"- **Zero-shot prompting, {usd_fmt(zs)} per rule per event.** Median cost of one strong-model call on the same "
        f"16 frames ({m.zero_shot_n} calls, mean {usd_fmt(m.zero_shot_mean_usd)}). The baseline asks one concept per call, "
        "so n rules cost n calls per event and the line is exactly n x the single-call cost.",
        "- Both prices are computed from the token counts the model returned and the per-token prices in `eval/harness/budget.py`.",
        "- Events that land close to a rule's decision boundary can be re-checked by the strong model; that is billed on top and "
        "was not needed in the live Playground run, where the measured cost was about $0.0015 per watched event.",
        f"- Source: {src}.",
        "",
        "Regenerate: `uv run --project engine python eval/plots/cost_vs_rules.py`.",
        "",
    ]
    return "\n".join(lines)


# -------------------------------------------------------------------------------------------------------- the SVG
CSS = """
svg.cvr { --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
          --s1:#2a78d6; --s2:#eb6834; font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }
@media (prefers-color-scheme: dark) { svg.cvr { --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
          --grid:#2c2c2a; --axis:#383835; --s1:#3987e5; --s2:#d95926; } }
svg.cvr .bg { fill:var(--surface); }
svg.cvr text { fill:var(--ink2); font-size:12px; }
svg.cvr text.title { fill:var(--ink); font-size:17px; font-weight:600; }
svg.cvr text.ink { fill:var(--ink); }
svg.cvr text.strong { fill:var(--ink); font-weight:600; }
svg.cvr text.muted { fill:var(--muted); font-size:11px; }
svg.cvr .grid { stroke:var(--grid); stroke-width:1; fill:none; }
svg.cvr .axis { stroke:var(--axis); stroke-width:1; fill:none; }
svg.cvr .line { stroke-width:2; fill:none; stroke-linecap:round; stroke-linejoin:round; }
svg.cvr .l1 { stroke:var(--s1); } svg.cvr .l2 { stroke:var(--s2); }
svg.cvr .m1 { fill:var(--s1); stroke:var(--surface); stroke-width:2; }
svg.cvr .m2 { fill:var(--s2); stroke:var(--surface); stroke-width:2; }
"""


def f1(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def svg_chart(m: Measured, max_rules: int) -> str:
    rows = table_rows(m, max_rules)
    ex, zs = rows[0][1], round(m.zero_shot_usd, 4)
    top = max(r[2] for r in rows)
    ymax = next(t for t in (0.02, 0.04, 0.06, 0.08, 0.1, 0.12, 0.14, 0.16, 0.2, 0.3, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0) if t >= top * 1.04)
    ystep = next(s for s in (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5) if ymax / s <= 8)
    W, H = 800, 478
    L, R, T, B = 74, 214, 112, 92                      # plot margins (right: room for the direct labels)
    pw, ph = W - L - R, H - T - B
    px = lambda n: L + (n - 1) / (max_rules - 1) * pw   # noqa: E731
    py = lambda v: T + ph - v / ymax * ph                # noqa: E731
    o: list[str] = []
    a = o.append

    title = "Cost per event stays flat as you add rules"
    desc = (f"Line chart, 1 to {max_rules} deployed rules on the x axis and model cost in US dollars per event on the y axis. "
            f"Exemplar is flat at {usd_fmt(ex)} per event because it perceives each event once and scores every rule on the cached trace. "
            f"Zero-shot prompting costs {usd_fmt(zs)} per rule per event, rising in a straight line to {usd_fmt(rows[-1][2])} at "
            f"{max_rules} rules, about {rows[-1][3]:.0f} times more. Circle markers are Exemplar, square markers are zero-shot prompting. "
            "A table with every value is in cost_vs_rules.md.")
    a(f'<svg xmlns="http://www.w3.org/2000/svg" class="cvr" role="img" aria-labelledby="t d" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
    a(f"<title id=\"t\">{escape(title)}</title><desc id=\"d\">{escape(desc)}</desc>")
    a(f"<style>{CSS}</style>")
    a(f'<rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')
    a(f'<text class="title" x="{L}" y="30">{escape(title)}</text>')
    a(f'<text x="{L}" y="52">Model spend per event, US dollars, for 1 to {max_rules} deployed rules. '
      "Exemplar perceives an event once; prompting calls a model per rule.</text>")

    # legend (two series: always present), swatch = the same line + marker as in the plot
    ly = 80
    a(f'<line class="line l1" x1="{L}" y1="{ly}" x2="{L + 28}" y2="{ly}"/><circle class="m1" cx="{L + 14}" cy="{ly}" r="5"/>')
    a(f'<text class="ink" x="{L + 38}" y="{ly + 4}">Exemplar (perceive once, score every rule)</text>')
    lx2 = L + 330
    a(f'<line class="line l2" x1="{lx2}" y1="{ly}" x2="{lx2 + 28}" y2="{ly}"/>'
      f'<rect class="m2" x="{lx2 + 9}" y="{ly - 5}" width="10" height="10"/>')
    a(f'<text class="ink" x="{lx2 + 38}" y="{ly + 4}">Zero-shot prompting (one call per rule)</text>')

    # grid + y ticks
    t = 0.0
    while t <= ymax + 1e-9:
        y = py(t)
        a(f'<line class="{"axis" if t == 0 else "grid"}" x1="{L}" y1="{f1(y)}" x2="{L + pw}" y2="{f1(y)}"/>')
        a(f'<text x="{L - 10}" y="{f1(y + 4)}" text-anchor="end">${t:.2f}</text>')
        t = round(t + ystep, 10)
    for n in range(1, max_rules + 1):
        a(f'<text x="{f1(px(n))}" y="{T + ph + 20}" text-anchor="middle">{n}</text>')
    a(f'<text x="{L + pw / 2}" y="{T + ph + 44}" text-anchor="middle" class="ink">Rules deployed on the camera</text>')
    a(f'<text x="18" y="{T + ph / 2}" text-anchor="middle" class="ink" transform="rotate(-90 18 {T + ph / 2})">US dollars per event</text>')

    # series (zero-shot first so the flat Exemplar line and its ringed markers sit on top where they are close)
    zpts = " ".join(f"{f1(px(n))},{f1(py(z))}" for n, _, z, _ in rows)
    epts = " ".join(f"{f1(px(n))},{f1(py(e))}" for n, e, _, _ in rows)
    a(f'<polyline class="line l2" points="{zpts}"/>')
    a(f'<polyline class="line l1" points="{epts}"/>')
    for n, e, z, ratio in rows:
        s = (f"{n} rule{'s' if n > 1 else ''}: zero-shot prompting {usd_fmt(z)} per event, "
             f"Exemplar {usd_fmt(e)} per event ({ratio:.0f}x)")
        a(f'<rect class="m2" x="{f1(px(n) - 5)}" y="{f1(py(z) - 5)}" width="10" height="10"><title>{escape(s)}</title></rect>')
        a(f'<circle class="m1" cx="{f1(px(n))}" cy="{f1(py(e))}" r="5"><title>{escape(s)}</title></circle>')

    # direct labels at the line ends
    xe = px(max_rules) + 16
    a(f'<text class="strong" x="{f1(xe)}" y="{f1(py(rows[-1][2]) - 6)}">Zero-shot prompting</text>')
    a(f'<text x="{f1(xe)}" y="{f1(py(rows[-1][2]) + 10)}">{usd_fmt(rows[-1][2])} at {max_rules} rules</text>')
    a(f'<text x="{f1(xe)}" y="{f1(py(rows[-1][2]) + 26)}">({usd_fmt(zs)} per rule)</text>')
    a(f'<text class="strong" x="{f1(xe)}" y="{f1(py(rows[-1][2]) + 46)}">about {rows[-1][3]:.0f}x the cost of Exemplar</text>')
    a(f'<text class="strong" x="{f1(xe)}" y="{f1(py(ex) - 22)}">Exemplar</text>')
    a(f'<text x="{f1(xe)}" y="{f1(py(ex) - 6)}">{usd_fmt(ex)}, any number of rules</text>')
    # footnote with the provenance of both lines
    fy = T + ph + 68
    a(f'<text class="muted" x="{L}" y="{fy}">Measured, not modelled. Exemplar: mean fast-model perception cost over {m.exemplar_n:,} clips '
      "(16 frames each). Zero-shot:</text>")
    a(f'<text class="muted" x="{L}" y="{fy + 15}">median cost of {m.zero_shot_n} strong-model calls on the same frames. '
      "Teaching a rule is a one-time cost and is not included.</text>")
    a("</svg>")
    return "\n".join(o) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", type=Path, default=Path(os.environ.get("EXEMPLAR_DATA_DIR") or REPO / "data"))
    ap.add_argument("--max-rules", type=int, default=10)
    ap.add_argument("--svg", type=Path, default=REPO / "docs" / "eval" / "cost_vs_rules.svg")
    ap.add_argument("--md", type=Path, default=REPO / "docs" / "eval" / "cost_vs_rules.md")
    args = ap.parse_args(argv)
    m = load_measured(args.data_dir)
    args.svg.parent.mkdir(parents=True, exist_ok=True)
    args.svg.write_text(svg_chart(m, args.max_rules), encoding="utf-8", newline="\n")
    args.md.write_text(markdown(m, args.max_rules), encoding="utf-8", newline="\n")
    print(args.svg)
    print(args.md)
    print(f"exemplar {m.exemplar_usd:.6f} USD/event over {m.exemplar_n} clips; zero-shot median {m.zero_shot_usd:.6f} "
          f"(mean {m.zero_shot_mean_usd:.6f}) over {m.zero_shot_n} calls; ledgers={'yes' if m.from_ledgers else 'fallback'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
