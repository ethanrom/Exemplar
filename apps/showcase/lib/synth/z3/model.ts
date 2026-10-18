// View models of the opt-in Z3 check: what a finished Z3 answer becomes on the page. Pure (no React, no DOM), so Node
// tests cover the wording and the rules - when a badge shows, what it says, how a run is summed up.
//
//   - "Z3 agrees" is shown only for a verdict `agree` of a completed answer; every other verdict says exactly what is
//     different (agree_outcome, equal_optimum, differs) or that the rule was not checked;
//   - an error removes the badge (the run summary still says one rule failed);
//   - results the engine supplied are compared like the others, and the badge says what it was compared with.

import type { Trace } from "../../dsl/index.ts";
import type { WireExample, Z3Outcome } from "./protocol.ts";
import { compareWithReference } from "./verdict.ts";
import type { Reference, Verdict } from "./verdict.ts";

/** One sketch to check, with the result the page shows for it. */
export interface Z3Item {
  /** Identifies the item for the page (the candidate's closed-rule text). */
  readonly key: string;
  /** DSL text of the sketch; empty when the page has none (then the item is "not checked by Z3"). */
  readonly sketch: string;
  readonly reference: Reference;
}

/** What the page hands the Z3 check for the result set it currently shows. */
export interface Z3Inputs {
  /** Changes whenever the shown result changes (the Lab's request); a Z3 answer counts only for the key it was asked for. */
  readonly requestKey: string;
  /** The page has finished computing and comparing what it shows for `requestKey`. */
  readonly ready: boolean;
  readonly examples: readonly WireExample[] | null;
  /** The selected rule first, then the top candidates. */
  readonly items: readonly Z3Item[];
}

/** What came of one item. */
export type ItemResult =
  | { readonly kind: "verdict"; readonly verdict: Verdict; readonly against: Reference["source"] }
  | { readonly kind: "unsupported"; readonly reason: string }
  | { readonly kind: "error"; readonly message: string };

/** The selected rule and the top candidates, never more than `limit` solves (default 7). */
export function pickItems<T extends { readonly key: string }>(views: readonly T[], selectedKey: string | null, limit = 7): T[] {
  const out: T[] = [];
  const seen = new Set<string>();
  const add = (v: T | undefined): void => {
    if (v !== undefined && !seen.has(v.key) && out.length < limit) {
      seen.add(v.key);
      out.push(v);
    }
  };
  add(views.find((v) => v.key === selectedKey));
  for (const v of views) add(v);
  return out;
}

/** Examples for the worker from the page's labelled clips. */
export function wireExamples(list: readonly { readonly alias: string; readonly positive: boolean; readonly weight: number; readonly trace: Trace }[]): WireExample[] {
  return list.map((e) => ({ clip_id: e.alias, positive: e.positive, weight: e.weight, trace: e.trace }));
}

/** The worker's outcome for one item, judged against the result shown for it. */
export function itemResult(outcome: Z3Outcome, ref: Reference): ItemResult {
  if (outcome.kind === "unsupported") return { kind: "unsupported", reason: outcome.reason };
  if (outcome.kind === "error") return { kind: "error", message: outcome.message };
  if (outcome.result.status === "timeout") return { kind: "unsupported", reason: "Z3 did not finish within its time budget for this rule" };
  const verdict = compareWithReference(outcome.result, ref);
  if (verdict.kind === "not_comparable") return { kind: "unsupported", reason: verdict.summary };
  return { kind: "verdict", verdict, against: ref.source };
}

export type BadgeTone = "pos" | "info" | "neg" | "neutral";

export interface BadgeModel {
  readonly tone: BadgeTone;
  readonly icon: "check" | "cross" | "info" | "clock" | "dot";
  /** The badge text. "Z3 agrees" appears only for an `agree` verdict. */
  readonly label: string;
  /** Plain lines under the badge: the exact differences. */
  readonly lines: readonly string[];
  readonly title: string;
}

const COMPARED: Record<Reference["source"], string> = {
  browser: "compared with the result computed in your browser",
  engine: "compared with the engine's result",
};

/**
 * The badge for one item, or null when there is nothing to show (not asked yet, or an error). `pending` shows a quiet
 * "checking" tag while the run for the current request is still going.
 */
export function badgeModel(r: ItemResult | undefined, pending: boolean): BadgeModel | null {
  if (r === undefined) {
    return pending ? { tone: "neutral", icon: "clock", label: "Z3 checking", lines: [], title: "Z3 is solving this rule" } : null;
  }
  if (r.kind === "error") return null; // the badge disappears on any error
  if (r.kind === "unsupported") {
    return { tone: "neutral", icon: "dot", label: "Not checked by Z3", lines: [r.reason], title: r.reason };
  }
  const v = r.verdict;
  const how = COMPARED[r.against];
  switch (v.kind) {
    case "agree":
      return { tone: "pos", icon: "check", label: "Z3 agrees", lines: [], title: `Z3 solved this rule and its answer is identical: ${how}` };
    case "agree_outcome":
      return { tone: "info", icon: "info", label: "Z3 agrees on the outcome", lines: v.differences, title: `${v.summary}; ${how}` };
    case "equal_optimum":
      return { tone: "info", icon: "info", label: "Z3: equally optimal choice", lines: v.differences, title: `${v.summary}; ${how}` };
    case "differs":
      return { tone: "neg", icon: "cross", label: "Z3 differs", lines: v.differences, title: `${v.summary}; ${how}` };
    case "not_comparable":
      return { tone: "neutral", icon: "dot", label: "Not checked by Z3", lines: [v.summary], title: v.summary };
  }
}

export interface RunSummary {
  readonly checked: number;
  readonly agree: number;
  readonly agreeOutcome: number;
  readonly equalOptimum: number;
  readonly differs: number;
  readonly unchecked: number;
  readonly failed: number;
  /** First failure message, if any. */
  readonly firstFailure: string | null;
}

export function summarize(results: readonly ItemResult[]): RunSummary {
  let agree = 0;
  let agreeOutcome = 0;
  let equalOptimum = 0;
  let differs = 0;
  let unchecked = 0;
  let failed = 0;
  let firstFailure: string | null = null;
  for (const r of results) {
    if (r.kind === "error") {
      failed += 1;
      firstFailure ??= r.message;
    } else if (r.kind === "unsupported") unchecked += 1;
    else if (r.verdict.kind === "agree") agree += 1;
    else if (r.verdict.kind === "agree_outcome") agreeOutcome += 1;
    else if (r.verdict.kind === "equal_optimum") equalOptimum += 1;
    else if (r.verdict.kind === "differs") differs += 1;
    else unchecked += 1;
  }
  return { checked: results.length, agree, agreeOutcome, equalOptimum, differs, unchecked, failed, firstFailure };
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/** One sentence for the status line and the live region once a run has finished. */
export function summaryText(s: RunSummary): string {
  if (s.checked === 0) return "Nothing to check yet.";
  if (s.agree === s.checked) return s.checked === 1 ? "Z3 agrees on the checked rule." : `Z3 agrees on all ${s.checked} checked rules.`;
  const parts: string[] = [];
  if (s.agree > 0) parts.push(`${s.agree} agree`);
  if (s.agreeOutcome > 0) parts.push(`${s.agreeOutcome} agree on the outcome (hole values differ)`);
  if (s.equalOptimum > 0) parts.push(`${s.equalOptimum} chose another equally optimal rule`);
  if (s.differs > 0) parts.push(`${s.differs} differ`);
  if (s.unchecked > 0) parts.push(`${s.unchecked} not checked`);
  if (s.failed > 0) parts.push(`${s.failed} failed${s.firstFailure ? ` (${s.firstFailure})` : ""}`);
  return `Z3 checked ${plural(s.checked, "rule", "rules")}: ${parts.join(", ")}.`;
}
