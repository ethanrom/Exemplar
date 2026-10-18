// Decoder of data/grid/grid.json (format "exemplar.lab-grid/1", written by scripts/grid/assemble.py).
// Comparator side: the solver never imports this (SPEC 6.5).

export interface GridProvenance {
  engine_commit: string;
  z3_version: string;
  solve_timeout_s: number;
  k: number;
  weight: number;
  sketch_bank_sha256: string;
  curated: { alias: string; trace_sha256: string }[];
  generated_on: string;
  wall_time_s: number;
  workers: number;
  [k: string]: unknown;
}

/** One engine answer for one sketch in one slot. */
export interface GridEntry {
  /** 0 sat, 1 unsat, 2 rejected, 3 timeout, 4 grid_fallback, 5 error */
  status: number;
  holes: number[] | null;
  margin: number | null;
  /** Bitmask over `clips` (bit i = clip i): the examples the engine's answer gets wrong. */
  violated: number | null;
  mdl: number | null;
  /** Distinct optimal satisfied sets; -1 beyond the brute-force budget; null for operational statuses. */
  alternatives: number | null;
  /** The engine's placement note when it stepped back from the slack centre, else null. */
  placement: string | null;
  /** The engine's Z3 model point (hole order) for those entries. */
  model_point: number[] | null;
}

export interface GridDoc {
  format: string;
  provenance: GridProvenance;
  clips: string[];
  slots: number;
  valid_slots: number;
  status_codes: string[];
  sketch_ids: number[];
  sketches: { id: number; holes: string[]; rows: any[][]; slot: (number | null)[] }[];
  top6: (number[] | null)[];
}

export class Grid {
  readonly doc: GridDoc;
  constructor(doc: GridDoc) {
    if (doc.format !== "exemplar.lab-grid/1") throw new Error(`unsupported grid format ${doc.format}`);
    this.doc = doc;
  }

  get clips(): readonly string[] {
    return this.doc.clips;
  }

  get sketchCount(): number {
    return this.doc.sketches.length;
  }

  holeNames(sketchId: number): readonly string[] {
    return (this.doc.sketches[sketchId] as GridDoc["sketches"][number]).holes;
  }

  /** The engine entry, or null for an invalid slot (or one missing from a partial grid). */
  entry(sketchId: number, slot: number): GridEntry | null {
    const sk = this.doc.sketches[sketchId] as GridDoc["sketches"][number];
    const ix = sk.slot[slot];
    if (ix === null || ix === undefined) return null;
    const r = sk.rows[ix] as any[];
    return {
      status: r[0], holes: r[1] ?? null, margin: r[2] ?? null, violated: r[3] ?? null, mdl: r[4] ?? null,
      alternatives: r[5] ?? null, placement: r[6] ?? null, model_point: r[7] ?? null,
    };
  }

  top6(slot: number): number[] | null {
    return this.doc.top6[slot] ?? null;
  }

  /** Clip aliases whose bit is set in a violated mask. */
  violatedIds(mask: number): string[] {
    return this.doc.clips.filter((_, i) => ((mask >> i) & 1) === 1);
  }
}
