// Focused unit tests: the boundary and convention cases that docs/DSL.md calls out, ported from the engine's
// hand-written tests (engine/tests/dsl/test_dsl_{eval,witness,syntax}.py). Expected values are the documented ones.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  C, DSLSyntaxError, UnboundHoleError, compileRule, evaluate, fillHoles, fmtNum, holesOf, normalize, parse, prepare,
  robustness, toEnglish, toText, typecheck, witness,
} from "../index.ts";
import type { Rule, Trace } from "../index.ts";
import { formatFixed3, pyFloatRepr, pyReprStr, pyRound } from "../pycompat.ts";
import { readJsonGz } from "./golden-util.ts";

const near = (a: number, b: number): void => assert.ok(Math.abs(a - b) < 1e-9, `${a} !~ ${b}`);

interface Tables {
  traces: Record<string, Trace>;
}
const fx = (name: string): Trace => (readJsonGz<Tables>("dsl.tables.json.gz").traces[`fx-${name}`]);

type F = [number, [string, string[], "low" | "med" | "high"][]];
function mk(frames: F[], entities: [string, string][], ctx: Trace["context"] = {}): Trace {
  return {
    clip_id: "m", source: "fixture", duration_ms: frames[frames.length - 1][0] + 1000, status: "ok",
    entities: entities.map(([id, type]) => ({ id, type: type as "person", attrs: [] })),
    frames: frames.map(([t, fs]) => ({ t_ms: t, facts: fs.map(([pred, args, conf]) => ({ pred, args, conf })) })),
    context: ctx,
  };
}
const R = (text: string): Rule => {
  const r = parse(text);
  assert.deepEqual(typecheck(r).filter((m) => !m.includes("never used")), []);
  return r;
};
const THEFT = "exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k) and not attr(p, delivery_uniform)";
const DWELL = "exists v: Vehicle: holds_for >= 120 in_zone(v, dock)";
const UNATTENDED = "exists k: Package: always[0, 24] in_zone(k, steps)";
const RINGS = "exists p: Person: eventually[0, 5] rings_bell(p)";

test("docs/DSL.md worked-example score table (12 fixtures x 4 rules)", () => {
  const rules = [THEFT, DWELL, UNATTENDED, RINGS].map(R);
  const table: Record<string, (number | "le")[]> = {
    theft_a: [0.45, -0.5, -0.45, -0.45], theft_b: [0.3, -0.5, -0.45, -0.45], delivery_a: [-0.45, -0.5, -0.45, -0.45],
    delivery_b: [-0.45, -0.5, -0.45, 0.45], unattended_package: [-0.5, -0.5, 0.45, -0.5],
    vehicle_dwell_dock: [-0.5, 0.45, -0.5, -0.45], visitor_rings: [-0.5, -0.5, -0.5, 0.45],
  };
  for (const [name, want] of Object.entries(table)) {
    rules.forEach((r, i) => near(robustness(r, fx(name)), want[i] as number));
  }
  for (const name of ["visitor_no_ring", "vehicle_passby", "birds_feeder", "empty_scene", "perception_failed"]) {
    const s = rules.map((r) => robustness(r, fx(name)));
    assert.ok(s[0] <= -0.45 && s[1] === -0.5 && s[2] <= -0.45 && s[3] <= -0.45, `${name}: ${s}`);
  }
});

test("integer-ms boundary: frames at 100 and 300 ms match then[0.2, 0.2] (float seconds would miss)", () => {
  const tr = mk([[100, [["picks_up", ["p1", "k1"], "high"]]], [300, [["leaves", ["p1", "porch"], "high"]]]],
    [["p1", "person"], ["k1", "package"]]);
  assert.ok(robustness(R("exists p: Person, k: Package: picks_up(p, k) then[0.2, 0.2] leaves(p, porch)"), tr) > 0);
  assert.ok(0.3 - 0.1 < 0.2, "premise: float seconds differ"); // 0.19999999999999998
  assert.equal((300 - 100) / 1000, 0.2);
});

test("holds_for: equality counts, evidence-based on sampled frames, run must fit in the clip", () => {
  const dock = fx("vehicle_dwell_dock");
  const hf = (d: number): number => robustness(R(`exists v: Vehicle: holds_for >= ${d} in_zone(v, dock)`), dock);
  near(hf(120), 0.45); // window 6..126 s, offset exactly 120 s
  near(hf(150), 0.3); // needs the 156 s frame (med confidence)
  near(hf(151), -0.45); // only start 0 fits, and the vehicle is not in the zone at 0 s
  assert.equal(hf(157), -C); // exceeds the clip
  const w = witness(R(DWELL), dock);
  assert.deepEqual([w.spans[0].op, w.spans[0].t_start_ms, w.spans[0].t_end_ms], ["holds_for", 6000, 126000]);
});

test("holds_for d = 0 and a single frame", () => {
  const one = mk([[500, [["in_zone", ["k1", "steps"], "high"]]]], [["k1", "package"]]);
  near(robustness(R("exists k: Package: holds_for >= 0 in_zone(k, steps)"), one), 0.45);
  assert.equal(robustness(R("exists k: Package: holds_for >= 1 in_zone(k, steps)"), one), -C);
});

test("empty windows are -C for eventually AND always; not always over an empty window is +C", () => {
  const tr = mk([[0, [["present", ["p1"], "high"]]], [1000, []]], [["p1", "person"]]);
  assert.equal(robustness(R("exists p: Person: eventually[5, 6] present(p)"), tr), -C);
  assert.equal(robustness(R("exists p: Person: always[5, 6] present(p)"), tr), -C);
  assert.equal(robustness(R("exists p: Person: not always[5, 6] present(p)"), tr), C);
});

test("windows are clipped to the clip: always[0, 1000] is the min over the remaining frames", () => {
  const tr = mk([[0, [["present", ["p1"], "high"]]], [1000, [["present", ["p1"], "med"]]]], [["p1", "person"]]);
  near(robustness(R("exists p: Person: always[0, 1000] present(p)"), tr), 0.3);
});

test("no bindings / no frames / perception_failed all give -C", () => {
  assert.equal(robustness(R("exists v: Vehicle: present(v)"), fx("theft_a")), -C);
  assert.equal(robustness(R("exists p: Person: present(p)"), fx("perception_failed")), -C);
  const none = mk([[0, []]], [["p1", "person"]]);
  assert.equal(robustness(R("exists p: Person: present(p)"), { ...none, frames: [] }), -C);
});

test("context atoms: hour wraps past midnight, missing context is false, false context pins the score at -C", () => {
  const at = (h: number | null): Trace =>
    mk([[0, [["present", ["p1"], "high"]]]], [["p1", "person"]], h === null ? {} : { local_hour: h });
  const r = R("exists p: Person: present(p) when hour in [22, 6]");
  assert.ok(robustness(r, at(23)) > 0 && robustness(r, at(3)) > 0);
  assert.equal(robustness(r, at(12)), -C);
  assert.equal(robustness(r, at(null)), -C);
  assert.ok(robustness(R("exists p: Person: present(p) when hour in [6, 22]"), at(22)) > 0); // inclusive
  const sub = R("exists p: Person: present(p) when subtype = human");
  assert.equal(robustness(sub, mk([[0, [["present", ["p1"], "high"]]]], [["p1", "person"]], { sub_type: "vehicle" })), -C);
});

test("hole filling: hours round half to even, time holes stay numbers, unfilled holes throw", () => {
  const sketch = R("exists p: Person: present(p) when hour in [?h, 23]");
  const tr = mk([[0, [["present", ["p1"], "high"]]]], [["p1", "person"]], { local_hour: 2 });
  assert.ok(evaluate(sketch, tr, { h: 2.5 }) > 0); // round(2.5) = 2
  near(evaluate(sketch, { ...tr, context: { local_hour: 3 } }, { h: 2.5 }), 0.45); // hour 3 in [2, 23]
  assert.equal(evaluate(sketch, { ...tr, context: { local_hour: 3 } }, { h: 3.5 }), -C); // round(3.5) = 4 > 3: hour 3 is outside [4, 23]
  assert.ok(evaluate(sketch, { ...tr, context: { local_hour: 4 } }, { h: 3.5 }) > 0);
  assert.throws(() => robustness(sketch, tr), UnboundHoleError);
  assert.deepEqual(holesOf(sketch), ["h"]);
  const filled = fillHoles(R("exists p: Person: eventually[0, ?b] present(p)"), { b: 7 });
  assert.equal(toText(filled), "exists p: Person: eventually[0, 7] present(p)");
  const cr = compileRule(sketch);
  assert.deepEqual(cr.holes, ["h"]);
  assert.ok(cr.score(prepare(tr), { h: 2 }) > 0);
});

test("theft_a witness: then 6000-8000, not span, and-root hull 0-8000", () => {
  const w = witness(R(THEFT), fx("theft_a"));
  assert.deepEqual(w.bindings, { p: "p1", k: "k1" });
  near(w.score, 0.45);
  assert.deepEqual(w.spans.map((s) => s.path), ["body", "body.args[0]", "body.args[0].left", "body.args[0].right", "body.args[1]"]);
  const sp = Object.fromEntries(w.spans.map((s) => [s.path, s]));
  assert.deepEqual([sp["body.args[0]"].op, sp["body.args[0]"].t_start_ms, sp["body.args[0]"].t_end_ms], ["then", 6000, 8000]);
  assert.deepEqual([sp.body.t_start_ms, sp.body.t_end_ms], [0, 8000]);
  assert.equal(sp["body.args[1]"].op, "not");
  assert.equal(sp["body.args[0].left"].text, "picks_up(p, k)");
});

test("holds_for witness span is the required window [t1, t1 + d], not the last sampled frame", () => {
  const frames: F[] = [1000, 5000, 9000, 13900, 14900, 20000].map((t) => [t, t <= 14900 ? [["in_zone", ["k1", "steps"], "high"]] : []]);
  const tr = mk(frames, [["k1", "package"]]);
  const w = witness(R("exists k: Package: holds_for >= 15 in_zone(k, steps)"), tr);
  near(w.score, 0.45);
  assert.deepEqual([w.spans[0].op, w.spans[0].t_start_ms, w.spans[0].t_end_ms], ["holds_for", 1000, 16000]);
  assert.deepEqual([w.spans[1].op, w.spans[1].t_start_ms, w.spans[1].t_end_ms], ["atom", 1000, 1000]);
  // a hole resolves before the span is built
  const wh = witness(parse("exists k: Package: holds_for >= ?d in_zone(k, steps)"), tr, { d: 15 });
  assert.deepEqual([wh.spans[0].t_start_ms, wh.spans[0].t_end_ms], [1000, 16000]);
  // a 10 s clip cannot hold a 15 s run: window clipped to the last frame
  const short = mk([1000, 5000, 9000, 10000].map((t): F => [t, [["in_zone", ["k1", "steps"], "high"]]]), [["k1", "package"]]);
  const ws = witness(R("exists k: Package: holds_for >= 15 in_zone(k, steps)"), short);
  assert.equal(ws.score, -C);
  assert.deepEqual([ws.spans[0].t_start_ms, ws.spans[0].t_end_ms], [1000, 10000]);
});

test("eventually/always spans are the evaluated window, clipped at the last frame; empty window stays a point", () => {
  const tr = mk([500, 4000, 9000, 12500].map((t): F => [t, [["in_zone", ["k1", "steps"], "high"]]]), [["k1", "package"]]);
  let w = witness(R("exists k: Package: eventually[2, 6] in_zone(k, steps)"), tr);
  assert.deepEqual([w.spans[0].op, w.spans[0].t_start_ms, w.spans[0].t_end_ms], ["eventually", 2500, 6500]);
  assert.deepEqual([w.spans[1].t_start_ms, w.spans[1].t_end_ms], [4000, 4000]);
  w = witness(R("exists k: Package: always[1, 100] in_zone(k, steps)"), tr);
  assert.deepEqual([w.spans[0].op, w.spans[0].t_start_ms, w.spans[0].t_end_ms], ["always", 1500, 12500]);
  w = witness(R("exists k: Package: eventually[50, 60] in_zone(k, steps)"), tr);
  assert.equal(w.spans[0].t_start_ms, w.spans[0].t_end_ms);
  assert.equal(w.score, -C);
});

test("or takes the best branch (ties go to the first); and-root span is the hull of its evidence", () => {
  const tie = mk([[0, [["rings_bell", ["p1"], "high"], ["facing_camera", ["p1"], "high"]]]], [["p1", "person"]]);
  assert.deepEqual(witness(R("exists p: Person: facing_camera(p) or rings_bell(p)"), tie).spans.map((s) => s.path), ["body", "body.args[0]"]);
  const second = mk([[0, [["rings_bell", ["p1"], "high"], ["facing_camera", ["p1"], "low"]]]], [["p1", "person"]]);
  assert.deepEqual(witness(R("exists p: Person: facing_camera(p) or rings_bell(p)"), second).spans.map((s) => s.path), ["body", "body.args[1]"]);
  // frames at 0, 0.5 and 1.5 s: the window span [0, 1000] ends between frames, so the root hull ends there too
  const hull = mk([[0, [["present", ["p1"], "high"]]], [500, [["rings_bell", ["p1"], "high"]]], [1500, []]], [["p1", "person"]]);
  const w = witness(R("exists p: Person: present(p) and eventually[0, 1] rings_bell(p)"), hull);
  assert.deepEqual(w.spans.map((s) => [s.path, s.t_start_ms, s.t_end_ms]),
    [["body", 0, 1000], ["body.args[0]", 0, 0], ["body.args[1]", 0, 1000], ["body.args[1].arg", 500, 500]]);
});

test("first binding and earliest frame win ties", () => {
  const tr = mk([[0, []], [1000, [["in_zone", ["p1", "door"], "high"], ["in_zone", ["p2", "door"], "high"]]],
    [2000, [["in_zone", ["p1", "door"], "high"], ["in_zone", ["p2", "door"], "high"]]]], [["p1", "person"], ["p2", "person"]]);
  const w = witness(R("exists p: Person: in_zone(p, door)"), tr);
  assert.deepEqual(w.bindings, { p: "p1" });
  assert.equal(w.spans[0].t_start_ms, 1000);
});

test("witness with nothing to bind or a failed trace: score -C, empty bindings and spans", () => {
  const w = witness(R("exists p: Person: present(p)"), fx("perception_failed"));
  assert.deepEqual([w.score, w.bindings, w.entities, w.spans], [-C, {}, [], []]);
  assert.ok(w.english.startsWith("There is"));
  assert.throws(() => witness(parse("exists p: Person: eventually[0, ?b] present(p)"), fx("theft_a")), UnboundHoleError);
});

test("number formatting is Python's: half-even ties, exact repr, exponent spelling", () => {
  assert.deepEqual([20, 0, 0.5, 1.25, 0.333333, 7.0001, 1e-9, 120].map((x) => fmtNum(x)),
    ["20", "0", "0.5", "1.25", "0.333", "7", "0", "120"]);
  assert.equal(fmtNum(0.333333, true), "0.333333");
  assert.equal(fmtNum(1e-9, true), "1e-09");
  assert.equal(fmtNum(2, true), "2");
  assert.equal(fmtNum(0.0625), "0.062"); // exact tie -> even
  assert.equal(fmtNum(0.1875), "0.188");
  assert.equal(fmtNum(0.3125), "0.312");
  assert.equal(fmtNum(-0.0625), "-0.062");
  assert.equal(fmtNum(-0.0001), "-0");
  assert.equal(formatFixed3(2.0005), "2.001"); // 2.0005 is slightly above the tie in binary
  assert.equal(pyFloatRepr(1e16), "1e+16");
  assert.equal(pyFloatRepr(1e15), "1000000000000000.0");
  assert.equal(pyFloatRepr(0.0001), "0.0001");
  assert.equal(pyFloatRepr(0.00001), "1e-05");
  assert.equal(pyFloatRepr(123456789.125), "123456789.125");
  assert.equal(pyFloatRepr(-1.5e-7), "-1.5e-07");
  assert.deepEqual([0.5, 1.5, 2.5, -0.5, -1.5, -2.5, 2.4, 2.6].map(pyRound), [0, 2, 2, 0, -2, -2, 2, 3]);
  assert.equal(pyReprStr("a'b"), '"a\'b"');
  assert.equal(pyReprStr(" "), "'\\xa0'");
  assert.equal(pyReprStr("@"), "'@'");
});

test("printers: round trip, minimal parentheses, spec English example", () => {
  const cases: Record<string, string> = {
    "exists p: Person: (present(p) or rings_bell(p)) and facing_camera(p)": "exists p: Person: (present(p) or rings_bell(p)) and facing_camera(p)",
    "exists p: Person: (present(p) and rings_bell(p)) or facing_camera(p)": "exists p: Person: present(p) and rings_bell(p) or facing_camera(p)",
    "exists p: Person: not (not present(p))": "exists p: Person: not not present(p)",
    "exists p: Person: (present(p) then[0, 1] rings_bell(p)) then[0, 2] facing_camera(p)":
      "exists p: Person: present(p) then[0, 1] rings_bell(p) then[0, 2] facing_camera(p)",
    "exists p: Person: present(p) then[0, 1] (rings_bell(p) then[0, 2] facing_camera(p))":
      "exists p: Person: present(p) then[0, 1] (rings_bell(p) then[0, 2] facing_camera(p))",
    "exists p: Person: holds_for >= 2.50 (present(p) or rings_bell(p))": "exists p: Person: holds_for >= 2.5 (present(p) or rings_bell(p))",
  };
  for (const [src, want] of Object.entries(cases)) {
    const r = parse(src);
    assert.equal(toText(r), want, src);
    assert.deepEqual(parse(want), r);
  }
  assert.equal(
    toEnglish(parse("exists p: Person, k: Package: picks_up(p, k) then[0, 20] leaves(p, porch)")),
    "There is a person p and a package k such that p picks up k, and then within 0 to 20 s p leaves the porch.",
  );
  assert.equal(
    toEnglish(parse("exists p: Person: eventually[0, 30] in_zone(p, door) and not eventually[0, 30] rings_bell(p)")),
    "There is a person p such that (at some point within 0 to 30 s, p is at the door) and at no point within 0 to 30 s, p rings the doorbell.",
  );
  assert.equal(
    toEnglish(parse("exists v: Vehicle: present(v) when hour in [?h1, 6]")).endsWith("in [?h1, 6] (inclusive; wraps past midnight if the first is larger)."), true,
  );
  const nested: Rule = { vars: [{ name: "p", type: "Person" }], when: [], body: { op: "and", args: [
    { op: "and", args: [{ op: "atom", pred: "present", args: ["p"] }, { op: "atom", pred: "rings_bell", args: ["p"] }] },
    { op: "atom", pred: "facing_camera", args: ["p"] }] } };
  const flat = normalize(nested);
  assert.equal(flat.body.op === "and" && flat.body.args.length, 3);
});

test("parser: errors carry the engine's position and message", () => {
  const cases: [string, number, number, string][] = [
    ["", 1, 1, "expected 'exists'"],
    ["exists p Person: present(p)", 1, 10, "expected ':'"],
    ["exists p: Person: present(p", 1, 28, "expected ')' or ','"],
    ["exists p: Person: present(p) then present(p)", 1, 35, "expected '['"],
    ["exists p: Person: eventually[0 5] present(p)", 1, 32, "unexpected '5'; expected ','"],
    ["exists p: Person: Present(p)", 1, 19, "expected a formula"],
    ["exists p: Person: present(p) when hour in [6.5, 7]", 1, 44, "whole numbers"],
    ["exists p: Person: present(p) when subtype = foo", 1, 45, "unknown subtype 'foo'; known: human"],
    ["exists p: Person: present(p) and", 1, 33, "unexpected end of input"],
    ["exists p: Person: holds_for > 5 present(p)", 1, 29, "unexpected character '>'"],
    ["exists p: Person:" + "\n  present(p)\n  and 5", 3, 7, "unexpected '5'"],
    ["exists p: Person: present(p) when hour in [6, 7] and", 1, 53, "'hour'"],
    ["exists p: Person: present(p) @", 1, 30, "unexpected character '@'"],
  ];
  for (const [text, line, col, frag] of cases) {
    assert.throws(() => parse(text), (e: unknown) => {
      assert.ok(e instanceof DSLSyntaxError);
      assert.deepEqual([e.line, e.column], [line, col], text);
      assert.ok(e.reason.includes(frag), `${text}: ${e.reason}`);
      assert.ok(e.message.startsWith(`line ${line}, column ${col}: `));
      assert.ok(e.context.includes("^"));
      return true;
    });
  }
});

test("parser: structure (flattening, precedence, left-associative then, numbers and holes)", () => {
  const r = parse("exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch) when hour in [6, 22]");
  assert.deepEqual(r, {
    vars: [{ name: "p", type: "Person" }, { name: "k", type: "Package" }],
    body: { op: "then", a: 0, b: { op: "hole", name: "b" }, left: { op: "atom", pred: "picks_up", args: ["p", "k"] },
      right: { op: "atom", pred: "leaves", args: ["p", "porch"] } },
    when: [{ op: "hour_in", h1: 6, h2: 22 }],
  });
  const flat = parse("exists p: Person: present(p) and (facing_camera(p) and rings_bell(p)) and near(p, p)");
  assert.equal(flat.body.op === "and" && flat.body.args.length, 4);
  const th = parse("exists p: Person: present(p) then[0, 1] rings_bell(p) then[0, 2] facing_camera(p)");
  assert.ok(th.body.op === "then" && th.body.b === 2 && th.body.left.op === "then");
  const pr = parse("exists p: Person: present(p) or rings_bell(p) and facing_camera(p)");
  assert.ok(pr.body.op === "or" && pr.body.args[1].op === "and");
  assert.deepEqual(parse("exists p: Person: eventually[0.5, 1e1] present(p)").body, {
    op: "eventually", a: 0.5, b: 10, arg: { op: "atom", pred: "present", args: ["p"] },
  });
  // `not (` must lex as the keyword, not as a predicate named "not"
  assert.equal(toText(parse("exists p: Person: not (present(p) or rings_bell(p))")), "exists p: Person: not (present(p) or rings_bell(p))");
});

test("typechecker messages are the engine's", () => {
  const tc = (t: string): string[] => typecheck(parse(t));
  assert.deepEqual(tc("exists p: Person: rings_doorbell(p)"), [
    "unknown predicate 'rings_doorbell'; known: present, in_zone, near, carrying, picks_up, puts_down, rings_bell, enters, leaves, facing_camera, attr",
  ]);
  assert.deepEqual(tc("exists p: Person: rings_bell(p, p)"), ["rings_bell takes 1 argument (rings_bell(Person)), got 2: rings_bell(p, p)"]);
  assert.deepEqual(tc("exists p: Entity: rings_bell(p)"), ["argument 1 of rings_bell must be a Person variable (rings_bell(Person)), but 'p' is declared Entity"]);
  assert.deepEqual(tc("exists p: Person: in_zone(p, garage)"), [
    "argument 2 of in_zone: 'garage' is not a zone; zones are: door, porch, steps, yard, driveway, sidewalk, street, dock",
  ]);
  assert.deepEqual(tc("exists p: Person, p: Package: present(p)"), ["variable 'p' is declared more than once; every variable needs a unique name"]);
  assert.deepEqual(tc("exists p: Person, k: Package: present(p)"), ["variable 'k' is declared but never used in the formula"]);
  assert.deepEqual(tc("exists p: Person: eventually[5, 2] present(p)"), ["eventually[5, 2]: the lower bound must be <= the upper bound (needs 0 <= a <= b)"]);
  assert.deepEqual(tc("exists p: Person: present(p) when hour in [6, 24]"), ["hour in [...]: hours must be whole numbers between 0 and 23, got 24"]);
  assert.deepEqual(tc("exists p: Person: eventually[?a, 1] present(p) when hour in [?h, 3]"), []);
  assert.deepEqual(tc("exists p: Person: always[0, 1e999] present(p)"), ["always[0, inf]: bound must be a finite number, got inf"]);
});

test("scoring a 16-frame trace takes well under 0.2 ms (median)", (t) => {
  const frames: F[] = Array.from({ length: 16 }, (_, i): F => [
    (i + 1) * 1900, i % 3 === 0 ? [["in_zone", ["k1", "steps"], "high"], ["in_zone", ["p1", "porch"], "med"]] : [["in_zone", ["k1", "steps"], "high"]],
  ]);
  const tr = mk(frames, [["k1", "package"], ["p1", "person"]]);
  const cr = compileRule(parse("exists k: Package, p: Person: (in_zone(k, steps) or in_zone(p, porch)) then[0, ?b] in_zone(k, steps) and holds_for >= ?d in_zone(k, steps)"));
  const prep = prepare(tr);
  const times: number[] = [];
  for (let rep = 0; rep < 200; rep++) {
    const t0 = performance.now();
    for (let i = 0; i < 20; i++) cr.score(prep, { b: 3 + (i % 5) * 0.5, d: 4 + (i % 7) * 0.5 });
    times.push((performance.now() - t0) / 20);
  }
  times.sort((a, b) => a - b);
  const median = times[times.length >> 1];
  t.diagnostic(`16-frame score (3 holes-sketch, 2 bindings, fresh windows): median ${(median * 1000).toFixed(1)} us`);
  assert.ok(median < 0.2, `median ${median} ms`);
});
