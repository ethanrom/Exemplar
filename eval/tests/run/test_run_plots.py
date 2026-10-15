"""Charts: well-formed accessible SVG from synthetic results, no NaN, safe with partial results, table twin."""
import random
import xml.etree.ElementTree as ET

import pytest

from eval.plots import charts
from eval.plots.__main__ import main as plots_main

CONCEPTS = ("vehicle_stop", "person_exits_vehicle", "door_crossing", "vehicle_loading")


def synthetic_rows(seeds=3, with_zero_shot=True, ks=(1, 3), qs=(0, 3, 5)):
    rng = random.Random(0)
    rows = []
    for ci, c in enumerate(CONCEPTS):
        for k in ks:
            for q in qs:
                for s in range(seeds):
                    f1 = min(0.95, 0.35 + 0.1 * k + 0.03 * q + 0.05 * ci + rng.uniform(-0.06, 0.06))
                    rows.append({"concept": c, "method": "exemplar", "k": k, "q": q, "seed": s, "f1": f1, "precision": f1, "recall": f1,
                                 "false_alarm_rate": rng.uniform(0.0, 0.12), "tokens_per_event": 9500.0, "usd_per_event": 0.0021,
                                 "p50_latency_ms": 14000.0, "escalated_fraction": 0.12, "n_test_neg": 60, "guarantee": True})
        if with_zero_shot:
            rows.append({"concept": c, "method": "zero_shot_vlm", "k": 0, "q": 0, "seed": 0, "f1": 0.45 + 0.04 * ci, "precision": 0.5,
                         "recall": 0.6, "false_alarm_rate": 0.1, "tokens_per_event": 5900.0, "usd_per_event": 0.0134,
                         "p50_latency_ms": 7000.0, "escalated_fraction": 0.0, "n_test_neg": 60, "native_f1": 0.5, "native_precision": 0.5,
                         "native_recall": 0.5, "native_false_alarm_rate": 0.3, "guarantee": True})
    return rows


def parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


@pytest.mark.parametrize("fn", [charts.f1_chart, charts.validity_chart, charts.cost_chart])
def test_each_chart_is_wellformed_titled_and_free_of_nan(fn):
    svg = fn(synthetic_rows())
    root = parse(svg)
    assert root.tag.endswith("svg") and root.get("role") == "img"
    assert "nan" not in svg.lower() and "inf" not in svg.lower().replace("info", "")
    ns = {"s": "http://www.w3.org/2000/svg"}
    assert root.find("s:title", ns).text and root.find("s:desc", ns).text
    assert "prefers-color-scheme: dark" in svg                                 # dark palette is selected, not an automatic flip


def test_f1_chart_has_one_panel_per_concept_a_legend_and_direct_labels():
    svg = charts.f1_chart(synthetic_rows())
    for title in CONCEPTS:
        assert title in svg or charts.concept_titles().get(title, "") in svg
    assert "Exemplar, k=3" in svg and "Exemplar, k=1" in svg and "Zero-shot" in svg
    assert svg.count("<circle") >= 3 * 4 and svg.count("<polygon") >= 4 + 1          # shapes, not colour only: circles + diamonds
    assert svg.count("<rect") > 4                                                    # squares for the second series


def test_validity_chart_marks_the_alpha_line_and_flags_rates_above_it():
    rows = synthetic_rows()
    for r in rows:
        if r["method"] == "zero_shot_vlm":
            r["native_false_alarm_rate"] = 0.4
    svg = charts.validity_chart(rows, alpha=0.1)
    assert "α = 0.1" in svg and "0.40 &gt; α" in svg
    assert "0.10 &gt; α" not in svg                                                 # a calibrated rate inside the CI is not flagged


def test_far_interval_uses_clopper_pearson_on_the_mean_rate():
    far, lo, hi = charts.far_interval([{"false_alarm_rate": 0.1, "n_test_neg": 60}, {"false_alarm_rate": 0.1, "n_test_neg": 60}])
    assert far == pytest.approx(0.1) and 0.03 < lo < 0.1 < hi < 0.22


def test_charts_survive_zero_shot_only_and_exemplar_only_results():
    for rows in (synthetic_rows(with_zero_shot=True, ks=(), qs=()), synthetic_rows(with_zero_shot=False)):
        for fn in (charts.f1_chart, charts.validity_chart, charts.cost_chart):
            parse(fn(rows))


def test_single_seed_rows_and_single_k():
    rows = synthetic_rows(seeds=1, ks=(3,), qs=(3,))
    for fn in (charts.f1_chart, charts.validity_chart, charts.cost_chart):
        parse(fn(rows))
    assert "Exemplar, k=1" not in charts.f1_chart(rows)


def test_headline_config_is_largest_k_then_largest_q():
    assert charts.headline_config(synthetic_rows()) == (3, 5)
    assert charts.headline_config([]) == (None, None)


def test_nice_ticks_cover_the_range():
    t = charts.nice_ticks(0.0134)
    assert t[0] == 0 and t[-1] >= 0.0134 and len(t) <= 8


def test_table_twin_lists_every_group_and_the_native_zero_shot_point():
    md = charts.results_table(synthetic_rows())
    assert md.count("| Exemplar |") == 4 * 2 * 3 and md.count("| zero-shot |") == 4 and md.count("zero-shot, own yes/no") == 4
    assert "nan" not in md.lower()


def test_cli_writes_all_files(tmp_path):
    from eval.harness import results
    p = tmp_path / "results.json"
    results.merge_rows(synthetic_rows(seeds=2), alpha=0.1, path=p)
    out = tmp_path / "plots"
    assert plots_main(["--results", str(p), "--out", str(out)]) == 0
    assert sorted(f.name for f in out.iterdir()) == ["cost_latency.svg", "f1_by_concept.svg", "results_table.md", "validity.svg"]
    assert plots_main(["--results", str(tmp_path / "none.json"), "--out", str(out)]) == 2
