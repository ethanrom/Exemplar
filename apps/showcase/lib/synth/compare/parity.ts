// Slot-level parity: the TypeScript free-play pipeline against the grid (SPEC 6.4, 7.2). Comparator side.

import { parse } from "../../dsl/index.ts";
import { freePlay, statesOf } from "../session.ts";
import type { LabData } from "../session.ts";
import { categorize } from "./categorize.ts";
import type { Category, EngineEntry } from "./categorize.ts";
import type { Grid } from "./grid.ts";

export interface SlotReport {
  slot: number;
  categories: Record<Category, number>;
  /** Per sketch id: the category (or "rejected" / "missing"). */
  perSketch: string[];
  /** same: identical list; explained: differs but some entry is not identical; mismatch: differs with all identical. */
  top6: "same" | "explained" | "mismatch" | "missing";
  mdlChecked: number;
  mdlMismatch: number;
  altChecked: number;
  altMismatch: number;
  problems: string[];
  /** Sum of solver time (ms) and the largest class count seen. */
  ms: number;
  maxClasses: number;
}

const STATUS = ["sat", "unsat", "rejected", "timeout", "grid_fallback", "error"] as const;

export function checkSlot(grid: Grid, data: LabData, slot: number): SlotReport {
  const states = statesOf(slot, data.curated.length);
  const t0 = performance.now();
  const r = freePlay(data, states);
  const ms = performance.now() - t0;
  const cats: Record<Category, number> = { identical: 0, tie_verified: 0, engine_supplied: 0, mismatch: 0 };
  const per: string[] = [];
  const problems: string[] = [];
  let mdlChecked = 0;
  let mdlMismatch = 0;
  let altChecked = 0;
  let altMismatch = 0;
  let maxClasses = 0;
  let allIdentical = true;
  for (const o of r.outcomes) {
    const g = grid.entry(o.sketch_id, slot);
    if (g === null) {
      per.push("missing");
      allIdentical = false;
      continue;
    }
    if (o.result === null) {
      per.push(g.status === 2 ? "rejected" : "mismatch");
      if (g.status !== 2) {
        cats.mismatch += 1;
        problems.push(`sketch ${o.sketch_id}: rejected by the solver, engine status ${STATUS[g.status]}`);
      }
      continue;
    }
    const names = grid.holeNames(o.sketch_id);
    const engine: EngineEntry = {
      status: STATUS[g.status] as EngineEntry["status"],
      holes: g.holes === null ? null : Object.fromEntries(names.map((n, i) => [n, g.holes![i] as number])),
      margin: g.margin,
      violated: g.violated === null ? null : grid.violatedIds(g.violated),
      placement: g.placement,
    };
    const sketch = o.result.sketch;
    const v = categorize(sketch, r.state.ctx, o.result, engine);
    cats[v.category] += 1;
    per.push(v.category);
    if (v.category !== "identical") allIdentical = false;
    if (v.category === "mismatch") problems.push(`sketch ${o.sketch_id}: ${v.reason}`);
    if (o.result.status !== "budget_exceeded" && g.alternatives !== null && g.alternatives !== -1 && g.status <= 1) {
      altChecked += 1;
      if (o.result.alternatives !== g.alternatives) {
        altMismatch += 1;
        problems.push(`sketch ${o.sketch_id}: alternatives ${o.result.alternatives} vs engine-side count ${g.alternatives}`);
      }
    }
    if (v.category === "identical" && o.result.status === "sat" && g.mdl !== null) {
      const rec = r.state.records.get((data.sketches[o.sketch_id] as { text: string }).text);
      const cand = rec?.candidate;
      if (cand) {
        mdlChecked += 1;
        if (Math.abs(cand.mdl - g.mdl) > 1e-12 * Math.max(1, Math.abs(g.mdl))) {
          mdlMismatch += 1;
          problems.push(`sketch ${o.sketch_id}: mdl ${cand.mdl} vs ${g.mdl}`);
        }
      }
    }
    maxClasses = Math.max(maxClasses, o.result.classes);
  }
  const gridTop = grid.top6(slot);
  let top6: SlotReport["top6"] = "missing";
  if (gridTop !== null) {
    const mine = r.items.map((i) => i.sketch_id);
    if (JSON.stringify(mine) === JSON.stringify(gridTop)) top6 = "same";
    else if (!allIdentical) top6 = "explained";
    else {
      top6 = "mismatch";
      problems.push(`top6 ${JSON.stringify(mine)} vs engine ${JSON.stringify(gridTop)}`);
    }
  }
  return { slot, categories: cats, perSketch: per, top6, mdlChecked, mdlMismatch, altChecked, altMismatch, problems, ms, maxClasses };
}

export { parse };
