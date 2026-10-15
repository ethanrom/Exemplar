"""Hand-written fixture traces + signed webhook payloads (PLAN.md §4 Phase 0). Part of the contract.

    uv run --project engine python tests/fixtures/make_fixtures.py

Writes traces/*.json and webhooks/*.json next to this file. The JSON files are committed; this
script is the readable source of truth for them.

Webhook fixtures are signed with WEBHOOK_TEST_KEY (not a secret). Each file stores the raw body as
a string so verifiers test the exact bytes:  {"headers": {...}, "body": "<raw json text>"}.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from exemplar.contracts.trace import Entity, Fact, Frame, PerceptionMeta, Trace, TraceContext

HERE = Path(__file__).parent
WEBHOOK_TEST_KEY = "exemplar-test-signing-key"
DEVICE = "ava1.ring.device.FIXTUREDEVICE0001"


def fr(t_s: float, *facts: tuple) -> Frame:
    return Frame(t_ms=int(round(t_s * 1000)), facts=tuple(Fact(pred=p, args=tuple(a), conf=c) for p, a, c in facts))


def trace(clip_id, duration_s, entities, frames, summary, **ctx) -> Trace:
    return Trace(clip_id=clip_id, source="fixture", duration_ms=int(duration_s * 1000),
                 entities=tuple(entities), frames=tuple(frames), summary=summary,
                 context=TraceContext(device_id=DEVICE, **ctx),
                 perception=PerceptionMeta(mode="fixture", n_frames=len(frames)))


P = lambda i, *attrs: Entity(id=f"p{i}", type="person", attrs=attrs)
K = lambda i, *attrs: Entity(id=f"k{i}", type="package", attrs=attrs)
V = lambda i, *attrs: Entity(id=f"v{i}", type="vehicle", attrs=attrs)
A = lambda i, *attrs: Entity(id=f"a{i}", type="animal", attrs=attrs)

H, M, L = "high", "med", "low"


def traces() -> list[Trace]:
    out = []
    # 1-2. package theft: a non-uniformed person picks up the waiting package and leaves with it.
    out.append(trace("theft_a", 20, [P(1, "hoodie"), K(1, "box")], [
        fr(0, ("in_zone", ["k1", "porch"], H)),
        fr(2, ("in_zone", ["k1", "porch"], H), ("enters", ["p1", "porch"], M)),
        fr(4, ("in_zone", ["p1", "porch"], H), ("near", ["p1", "k1"], H), ("in_zone", ["k1", "porch"], H)),
        fr(6, ("picks_up", ["p1", "k1"], H), ("in_zone", ["p1", "porch"], H)),
        fr(8, ("carrying", ["p1", "k1"], H), ("in_zone", ["p1", "steps"], M)),
        fr(10, ("carrying", ["p1", "k1"], M), ("leaves", ["p1", "porch"], H)),
        fr(12, ("in_zone", ["p1", "sidewalk"], M)),
        fr(16),
        fr(20),
    ], "A person in a hoodie walks up, picks up the package on the porch and leaves carrying it.",
        sub_type="human", event_kind="motion", local_hour=14, weekday=2))
    out.append(trace("theft_b", 24, [P(1, "dark_jacket"), K(1, "box")], [
        fr(0, ("in_zone", ["k1", "steps"], H)),
        fr(3, ("in_zone", ["k1", "steps"], H)),
        fr(6, ("enters", ["p1", "steps"], M), ("in_zone", ["k1", "steps"], H)),
        fr(9, ("near", ["p1", "k1"], H), ("in_zone", ["p1", "steps"], H)),
        fr(12, ("picks_up", ["p1", "k1"], M), ("facing_camera", ["p1"], L)),
        fr(15, ("carrying", ["p1", "k1"], H)),
        fr(18, ("carrying", ["p1", "k1"], H), ("leaves", ["p1", "steps"], M)),
        fr(21, ("in_zone", ["p1", "street"], L)),
        fr(24),
    ], "Someone in a dark jacket takes the box from the steps and walks off with it.",
        sub_type="human", event_kind="motion", local_hour=10, weekday=5))
    # 3-4. deliveries: uniformed person puts the package down and leaves without it (hard negatives for theft).
    out.append(trace("delivery_a", 20, [P(1, "delivery_uniform", "hi_vis"), K(1, "box")], [
        fr(0, ("enters", ["p1", "porch"], H), ("carrying", ["p1", "k1"], H)),
        fr(3, ("carrying", ["p1", "k1"], H), ("in_zone", ["p1", "porch"], H)),
        fr(6, ("puts_down", ["p1", "k1"], H), ("in_zone", ["p1", "porch"], H)),
        fr(9, ("in_zone", ["k1", "porch"], H), ("in_zone", ["p1", "porch"], M)),
        fr(12, ("leaves", ["p1", "porch"], H), ("in_zone", ["k1", "porch"], H)),
        fr(16, ("in_zone", ["k1", "porch"], H)),
        fr(20, ("in_zone", ["k1", "porch"], H)),
    ], "A courier in a uniform drops a box on the porch and leaves.",
        sub_type="package_delivery", event_kind="motion", local_hour=11, weekday=1))
    out.append(trace("delivery_b", 18, [P(1, "delivery_uniform"), K(1, "envelope")], [
        fr(0, ("carrying", ["p1", "k1"], M), ("in_zone", ["p1", "steps"], M)),
        fr(3, ("in_zone", ["p1", "door"], H), ("rings_bell", ["p1"], H)),
        fr(6, ("puts_down", ["p1", "k1"], M), ("in_zone", ["p1", "door"], H)),
        fr(9, ("in_zone", ["k1", "door"], H), ("leaves", ["p1", "door"], M)),
        fr(13, ("in_zone", ["k1", "door"], H)),
        fr(18, ("in_zone", ["k1", "door"], H)),
    ], "A delivery driver rings the bell, leaves an envelope at the door and goes.",
        sub_type="package_delivery", event_kind="ding", local_hour=16, weekday=3))
    # 5. unattended package, nobody around (mirrors the Playground package clip).
    out.append(trace("unattended_package", 30, [K(1, "box")], [
        fr(t, ("in_zone", ["k1", "steps"], H)) for t in range(0, 31, 3)
    ], "A cardboard package sits on snowy porch steps; nobody appears.",
        event_kind="on_demand", local_hour=9, weekday=0))
    # 6. vehicle drives past in the street (mirrors the Playground vehicle clip).
    out.append(trace("vehicle_passby", 20, [V(1, "sedan")], [
        fr(0), fr(2, ("in_zone", ["v1", "street"], M)), fr(4, ("in_zone", ["v1", "street"], H)),
        fr(6, ("in_zone", ["v1", "street"], H)), fr(8, ("present", ["v1"], L)), fr(12), fr(16), fr(20),
    ], "A grey sedan drives through the lot and out of view.",
        sub_type="vehicle", event_kind="on_demand", local_hour=9, weekday=0))
    # 7. vehicle dwelling at the loading dock for > 2 minutes.
    out.append(trace("vehicle_dwell_dock", 156, [V(1, "box_truck"), P(1, "hi_vis")], [
        fr(0, ("enters", ["v1", "dock"], H)),
        *[fr(t, ("in_zone", ["v1", "dock"], H)) for t in range(6, 151, 6)][:21],
        fr(156, ("in_zone", ["v1", "dock"], M), ("near", ["p1", "v1"], L)),
    ], "A box truck pulls into the loading dock and stays there for over two minutes.",
        sub_type="vehicle", event_kind="motion", local_hour=6, weekday=4))
    # 8. visitor rings the bell.
    out.append(trace("visitor_rings", 15, [P(1, "backpack")], [
        fr(0, ("enters", ["p1", "steps"], M)), fr(2, ("in_zone", ["p1", "door"], H)),
        fr(4, ("rings_bell", ["p1"], H), ("facing_camera", ["p1"], M)), fr(7, ("in_zone", ["p1", "door"], H)),
        fr(10, ("in_zone", ["p1", "door"], H)), fr(13, ("leaves", ["p1", "door"], M)), fr(15),
    ], "A visitor with a backpack walks up and rings the doorbell.",
        sub_type="human", event_kind="ding", local_hour=18, weekday=6))
    # 9. someone comes to the door but doesn't ring.
    out.append(trace("visitor_no_ring", 15, [P(1, "hoodie")], [
        fr(0, ("enters", ["p1", "porch"], M)), fr(2, ("in_zone", ["p1", "door"], H)),
        fr(4, ("in_zone", ["p1", "door"], H), ("facing_camera", ["p1"], H)), fr(7, ("in_zone", ["p1", "door"], M)),
        fr(10, ("leaves", ["p1", "porch"], H)), fr(13, ("in_zone", ["p1", "sidewalk"], L)), fr(15),
    ], "A person in a hoodie comes to the door, looks at the camera and leaves without ringing.",
        sub_type="human", event_kind="motion", local_hour=23, weekday=4))
    # 10. empty scene.
    out.append(trace("empty_scene", 12, [], [fr(t) for t in range(0, 13, 2)],
                     "An empty porch; nothing happens.", sub_type="other_motion", event_kind="motion"))
    # 11. birds at the feeder (mirrors the Playground motion clip).
    out.append(trace("birds_feeder", 39, [A(1, "woodpecker"), A(2, "cardinal")], [
        fr(t, ("in_zone", ["a1", "yard"], H), *([("in_zone", ["a2", "yard"], M)] if t >= 21 else []))
        for t in range(0, 40, 3)
    ], "A woodpecker and a cardinal visit a snowy bird feeder.",
        sub_type="other_motion", event_kind="on_demand", local_hour=9, weekday=0))
    # 12. perception failed (no frames).
    out.append(Trace(clip_id="perception_failed", source="fixture", duration_ms=20000, status="perception_failed",
                     error="schema validation failed twice: frame 3: in_zone('p1', 'garage') is not a valid Zone",
                     context=TraceContext(device_id=DEVICE)))
    return out


def sign(body: str) -> str:
    return "sha256=" + hmac.new(WEBHOOK_TEST_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()


def webhooks() -> dict[str, dict]:
    def env(req, typ, **data):
        return {"meta": {"version": "1.1", "time": "2026-10-15T07:08:25Z", "request_id": req,
                         "account_id": "ava1.ring.account.FIXTUREACCOUNT"},
                "data": {"id": f"evt-{req}", "type": typ, **data}}
    motion = env("req-0001", "motion_detected", subType="human",
                 attributes={"source": DEVICE, "source_type": "devices", "timestamp": 1792048059034},
                 relationships={"devices": {"links": {"self": f"/v1/devices/{DEVICE}"}}})
    vehicle = env("req-0002", "motion_detected", subType="vehicle",
                  attributes={"source": DEVICE, "source_type": "devices", "timestamp": 1792048103109},
                  relationships={"devices": {"links": {"self": f"/v1/devices/{DEVICE}"}}})
    ding = env("req-0003", "button_press",
               attributes={"source": DEVICE, "source_type": "devices", "timestamp": 1792048133868},
               relationships={"devices": {"links": {"self": f"/v1/devices/{DEVICE}"}}})
    added = env("req-0004", "app_integration_added",
                attributes={"source": "ava1.ring.account.FIXTUREACCOUNT", "source_type": "users", "timestamp": 1792045683000})
    removed = env("req-0005", "app_integration_removed",
                  attributes={"source": "ava1.ring.account.FIXTUREACCOUNT", "source_type": "users", "timestamp": 1792049999000})
    out = {}
    for name, payload in [("motion_human", motion), ("motion_vehicle", vehicle), ("button_press", ding),
                          ("app_integration_added", added), ("app_integration_removed", removed)]:
        body = json.dumps(payload, separators=(",", ":"))
        out[name] = {"expect": "accept", "headers": {"X-Signature": sign(body), "Content-Type": "application/json"},
                     "body": body}
    good = out["motion_human"]
    # body changed after signing → reject (401)
    out["tampered"] = {"expect": "reject", "headers": good["headers"],
                       "body": good["body"].replace('"subType":"human"', '"subType":"vehicle"')}
    # re-serialised JSON (whitespace) breaks the raw-body signature → reject; verifiers must not re-serialise
    out["reserialised"] = {"expect": "reject", "headers": good["headers"],
                           "body": json.dumps(json.loads(good["body"]), indent=1)}
    out["missing_signature"] = {"expect": "reject", "headers": {"Content-Type": "application/json"}, "body": good["body"]}
    # same request_id delivered again → 200, processed once
    out["duplicate"] = {"expect": "duplicate", "headers": good["headers"], "body": good["body"]}
    return out


def main() -> None:
    td, wd = HERE / "traces", HERE / "webhooks"
    td.mkdir(exist_ok=True)
    wd.mkdir(exist_ok=True)
    for t in traces():
        (td / f"{t.clip_id}.json").write_text(t.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8")
    for name, w in webhooks().items():
        (wd / f"{name}.json").write_text(json.dumps(w, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(list(td.glob('*.json')))} traces, {len(list(wd.glob('*.json')))} webhooks")


if __name__ == "__main__":
    main()
