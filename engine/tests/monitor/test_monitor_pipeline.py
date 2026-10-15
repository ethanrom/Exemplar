"""calibrate -> deploy -> monitor, offline, as stream H wires it; plus an opt-in live smoke test on Bedrock."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from exemplar.calibrate import calibrate
from exemplar.contracts.labels import Label
from exemplar.contracts.trace import TraceContext
from exemplar.dsl import parse, to_english
from exemplar.monitor import DeployedRule, Monitor
from monitor_helpers import DWELL, THEFT, UNATTENDED, Perceiver, Sink, deployed, event, load

NEGATIVES = ["delivery_a", "delivery_b", "unattended_package", "vehicle_dwell_dock", "vehicle_passby", "birds_feeder",
             "empty_scene", "visitor_no_ring", "visitor_rings"]
ALL = ["theft_a", "theft_b", *NEGATIVES, "perception_failed"]


def random_label(name: str, value: str) -> Label:
    return Label(concept_id="theft", clip_id=name, value=value, provenance="random")


def test_calibrated_rule_deployed_fires_only_on_thefts():
    rule = parse(THEFT)
    cal = calibrate(rule, [(load(n), random_label(n, "neg")) for n in NEGATIVES]
                    + [(load(n), random_label(n, "pos")) for n in ("theft_a", "theft_b")], 0.1)
    assert cal.guarantee and cal.tau == 0.0
    perceive = Perceiver({n: load(n) for n in ALL})
    sink = Sink()
    mon = Monitor(perceive_fast=perceive, perceive_strong=Perceiver(), on_firing=sink.on_firing, on_event=sink.on_event)
    mon.deploy(DeployedRule(rule_id="theft", concept_id="theft", rule=rule, tau=cal.tau, delta=cal.delta,
                            actions=("ui",), english=to_english(rule)))
    fired, stages = {}, {}
    for name in ALL:
        t = load(name)
        (rec,) = mon.process(event(name, sub_type=t.context.sub_type, device_id=t.context.device_id, context=t.context))
        fired[name], stages[name] = rec.fired, rec.stage
    assert {n for n, f in fired.items() if f} == {"theft_a", "theft_b"}
    assert len(sink.firings) == len(ALL)                                   # dropped events are recorded too
    # the rule needs a person: Ring 'vehicle' / 'other_motion' events are pruned at stage 0, before any perception
    pruned = {n for n in ALL if load(n).context.sub_type in ("vehicle", "other_motion")}
    assert pruned >= {"vehicle_dwell_dock", "vehicle_passby"} and {n for n, st in stages.items() if st == 0} == pruned
    assert not pruned & set(perceive.calls)
    c = mon.cost()
    ok_traces = [n for n in ALL if n not in pruned and n != "perception_failed"]
    assert (c["events"], c["stage0_dropped"], c["stage1_scored"]) == (len(ALL), len(pruned), len(ok_traces))


def test_playground_demo_two_rules_package_and_vehicle():
    """Demo design (PLAN §5): package event fires the package rule, vehicle event fires the vehicle rule."""
    package_rule = parse(UNATTENDED)
    vehicle_rule = parse(DWELL)
    traces = {"pkg": load("unattended_package"), "veh": load("vehicle_dwell_dock"), "birds": load("birds_feeder")}
    mon = Monitor(perceive_fast=Perceiver({k: v for k, v in traces.items()}), perceive_strong=Perceiver(),
                  on_firing=lambda r: None)
    mon.deploy(deployed("package", UNATTENDED))
    mon.deploy(deployed("vehicle", DWELL))
    out = {k: {r.rule_id: (r.fired, r.stage) for r in mon.process(event(k, sub_type="on_demand"))} for k in traces}
    assert out["pkg"] == {"package": (True, 1), "vehicle": (False, 1)}
    assert out["veh"] == {"package": (False, 1), "vehicle": (True, 1)}
    assert out["birds"] == {"package": (False, 1), "vehicle": (False, 1)}
    # Playground events carry sub_type 'on_demand': stage 0 can never prune them
    assert mon.cost()["stage0_dropped"] == 0
    assert package_rule and vehicle_rule


# ------------------------------------------------------------------------------------------ live (opt-in)
DATA = Path(os.environ.get("EXEMPLAR_DATA_DIR") or Path(__file__).parents[3] / "data")
PKG = DATA / "spike" / "ring" / "CBDPSLBSIOVQ66XX" / "clip.mp4"


@pytest.mark.live
def test_live_monitor_on_the_playground_package_clip():
    """Real fast (and, if the score lands in the band, strong) perception through the monitor. About $0.002-$0.03."""
    if not PKG.is_file():
        pytest.skip(f"missing {PKG}")
    from exemplar.perception import perceive_detailed

    ctx = TraceContext(sub_type="on_demand", event_kind="on_demand", device_id="playground")

    def fast(ev):
        return perceive_detailed(PKG, clip_id="live_pg_package", source="ring", context=ev.context, mode="fast")

    def strong(ev):
        return perceive_detailed(PKG, clip_id="live_pg_package", source="ring", context=ev.context, mode="strong")

    sink = Sink()
    mon = Monitor(perceive_fast=fast, perceive_strong=strong, on_firing=sink.on_firing, on_event=sink.on_event)
    mon.deploy(deployed("package", "exists k: Package: holds_for >= 20 in_zone(k, steps)"))
    mon.deploy(deployed("theft", THEFT))
    mon.deploy(deployed("vehicle", DWELL))
    recs = {r.rule_id: r for r in mon.process(event("live1", sub_type="on_demand", device_id="playground", context=ctx))}
    print({k: (r.fired, r.stage, r.score, r.message) for k, r in recs.items()}, mon.cost())
    assert set(recs) == {"package", "theft", "vehicle"} and all(r.stage in (1, 2) for r in recs.values())
    assert not recs["vehicle"].fired                                      # no vehicle in the package clip
    assert not recs["theft"].fired                                        # no person, no theft in the Playground clip
    assert mon.cost()["stage1_scored"] == 3 and sink.types()[-1] == "cost_update"
