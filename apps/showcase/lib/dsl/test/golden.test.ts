// Parity of the TypeScript DSL with the Python engine on the DSL golden families (SPEC 6.2 F1-F5).
// Run: node --test lib/dsl/test/   (from apps/showcase). Bar: 0 mismatches in every family.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { TestContext } from "node:test";
import { PARSER_TABLES } from "../parser-tables.ts";
import {
  DSLSyntaxError, evaluate, fillHoles, parse, rho, robustness, toEnglish, toText, typecheck, witness,
} from "../index.ts";
import type { Rule, Trace } from "../index.ts";
import { diff, readJsonGz, readJsonlGz } from "./golden-util.ts";
import type { GoldenRow } from "./golden-util.ts";

interface Tables {
  traces: Record<string, Trace>;
  rules?: Record<string, { ast: Rule; kind: string }>;
}

let tablesCache: Tables | null = null;
function tables(): Tables {
  tablesCache ??= readJsonGz<Tables>("dsl.tables.json.gz");
  return tablesCache;
}

/** Run `check` on every row; it returns the first difference or null. Reports counts, fails on any mismatch. */
function runFamily(t: TestContext, name: string, rows: GoldenRow[], check: (row: GoldenRow) => string | null): void {
  const bad: string[] = [];
  let ok = 0;
  for (const row of rows) {
    let d: string | null;
    try {
      d = check(row);
    } catch (e) {
      d = `threw ${(e as Error).name}: ${(e as Error).message}`;
    }
    if (d === null) ok += 1;
    else bad.push(`${row.id}: ${d}`);
  }
  const line = `${name}: ${rows.length} cases, ${ok} identical, ${bad.length} mismatches`;
  t.diagnostic(line);
  console.log(`# golden ${line}`);
  assert.equal(bad.length, 0, `${line}\n${bad.slice(0, 8).join("\n")}`);
}

function ruleExpect(rule: Rule, trace: Trace, holes: Record<string, number> | undefined, want: Record<string, unknown>): string | null {
  const got: Record<string, unknown> = {};
  if ("typecheck" in want) got.typecheck = typecheck(rule);
  if ("to_text" in want) got.to_text = toText(rule);
  if ("to_english" in want) got.to_english = toEnglish(rule);
  if ("roundtrip" in want) {
    let rt = false;
    try {
      rt = diff(parse(toText(rule)), rule) === null;
    } catch {
      rt = false;
    }
    got.roundtrip = rt;
  }
  if ("robustness" in want) got.robustness = holes ? evaluate(rule, trace, holes) : robustness(rule, trace);
  if ("witness" in want) got.witness = witness(rule, trace, holes);
  if ("filled_text" in want || "filled_english" in want) {
    const filled = fillHoles(rule, holes ?? {});
    got.filled_text = toText(filled);
    got.filled_english = toEnglish(filled);
  }
  const d = diff(got, Object.fromEntries(Object.entries(want).filter(([k]) => k in got)));
  return d;
}

test("parser tables were generated from the grammar the goldens were produced with", () => {
  const { meta } = readJsonlGz("dsl.text.jsonl.gz");
  assert.equal(meta.grammar_sha256, PARSER_TABLES.grammar_sha256);
  assert.equal(meta.lark_version, PARSER_TABLES.lark_version);
});

test("F1 dsl.random: Hypothesis rule/trace pairs, holes and rho series", (t) => {
  const { rows } = readJsonlGz("dsl.random.jsonl.gz");
  runFamily(t, "F1 dsl.random", rows, (row) => {
    const { input, expect } = row;
    if (row.id.startsWith("f1.rho.")) {
      const got = {
        rho: rho(input.phi, input.trace, input.binding), text: toText(input.phi), english: toEnglish(input.phi),
      };
      return diff(got, expect);
    }
    return ruleExpect(input.rule, input.trace, input.holes, expect);
  });
});

test("F2 dsl.real: recorded rules and filled sketches x recorded traces", (t) => {
  const { rows } = readJsonlGz("dsl.real.jsonl.gz");
  const tb = tables();
  runFamily(t, "F2 dsl.real", rows, (row) => {
    const rule = (tb.rules as NonNullable<Tables["rules"]>)[row.input.rule].ast;
    const trace = tb.traces[row.input.trace];
    const got: Record<string, unknown> = { score: robustness(rule, trace) };
    if ("witness" in row.expect) got.witness = witness(rule, trace);
    return diff(got, row.expect);
  });
});

test("F3 dsl.sweep: d sweeps on recorded traces", (t) => {
  const { meta, rows } = readJsonlGz("dsl.sweep.jsonl.gz");
  const tb = tables();
  const sketches = meta.sketches as Record<string, string>;
  const parsed = new Map<string, Rule>();
  runFamily(t, "F3 dsl.sweep", rows, (row) => {
    let sk = parsed.get(row.input.sketch);
    if (sk === undefined) {
      sk = parse(sketches[row.input.sketch]);
      parsed.set(row.input.sketch, sk);
    }
    const trace = tb.traces[row.input.trace];
    const holes = row.input.holes as Record<string, number>;
    return diff({ score: evaluate(sk, trace, holes), witness: witness(sk, trace, holes) }, row.expect);
  });
});

test("F4 dsl.edge: hand-written boundary cases", (t) => {
  const { rows } = readJsonlGz("dsl.edge.jsonl.gz");
  runFamily(t, "F4 dsl.edge", rows, (row) => {
    const { input, expect } = row;
    const rule = parse(input.text);
    const d0 = diff(rule, expect.parse);
    if (d0 !== null) return `parse: ${d0}`;
    const want = { ...expect };
    delete want.parse;
    return ruleExpect(rule, input.trace, input.holes, want);
  });
});

function textOutcome(text: string): Record<string, unknown> {
  let rule: Rule;
  try {
    rule = parse(text);
  } catch (e) {
    if (e instanceof DSLSyntaxError) {
      return {
        parse: {
          ok: false,
          error: { class: "DSLSyntaxError", reason: e.reason, line: e.line, column: e.column, context: e.context, str: e.message },
        },
      };
    }
    const m = /^(\w+Error):/.exec((e as Error).message);
    return { parse: { ok: false, error: { class: m ? m[1] : (e as Error).name } } };
  }
  const out: Record<string, unknown> = { parse: { ok: true, ast: rule } };
  out.typecheck = typecheck(rule);
  out.to_text = toText(rule);
  out.to_english = toEnglish(rule);
  let rt = false;
  try {
    rt = diff(parse(toText(rule)), rule) === null;
  } catch {
    rt = false;
  }
  out.roundtrip = rt;
  out.body_text = toText(rule.body);
  out.body_english = toEnglish(rule.body);
  out.vars_text = rule.vars.map((v) => toText(v));
  out.vars_english = rule.vars.map((v) => toEnglish(v));
  out.when_text = rule.when.map((c) => toText(c));
  out.when_english = rule.when.map((c) => toEnglish(c));
  return out;
}

test("F5 dsl.text: recorded and fuzzed texts (parse / typecheck / print / English / errors)", (t) => {
  const { rows } = readJsonlGz("dsl.text.jsonl.gz");
  runFamily(t, "F5 dsl.text", rows, (row) => diff(textOutcome(row.input.text), row.expect));
});
