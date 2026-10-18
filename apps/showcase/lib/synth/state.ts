// Shared state of one synthesis run: every sketch seen so far, its typecheck / solve outcome and the event stream.
// Port of engine/exemplar/agent/state.py (the `RunState` the CEGIS loop and the agent tools both go through).
//
// Canonical key (state.py `submit`, line "canon = to_text(rule)" and `self.records.get(canon)`): a sketch is identified
// by the printer's text of its parse, so a sketch proposed twice - or in two spellings - is solved and listed once.
// Candidate order (state.py `candidates`): sorted by (mdl, -margin, dsl_text), the same closed rule reached from two
// sketches counts once (the first in that order wins; ties keep submission order because the sort is stable).

import type { Rule } from "../dsl/index.ts";
import { DSLError, DSLSyntaxError, parse, toEnglish, toText, typecheck } from "../dsl/index.ts";
import { holeKinds } from "./classes.ts";
import { makeExampleContext, solveSketchExhaustive } from "./exhaustive.ts";
import type { ExampleContext, SolveOptions } from "./exhaustive.ts";
import { mdl } from "./mdl.ts";
import { Cancelled, SketchError } from "./types.ts";
import type { Candidate, Example, SolveResult } from "./types.ts";

/** api.yaml RunEvent without seq / at_ms. */
export interface RunEvent {
  type: string;
  round?: number;
  sketch?: string;
  error?: string;
  result?: string;
  holes?: Record<string, number> | null;
  margin?: number | null;
  violated_clip_ids?: string[];
  rule_ids?: string[];
  message?: string;
}

export interface SketchRecord {
  /** Canonical DSL text of the sketch. */
  readonly text: string;
  readonly sketch: Rule | null;
  readonly round: number;
  error: string | null;
  result: SolveResult | null;
  candidate: Candidate | null;
}

export interface RunStateOptions {
  k: number;
  /** Polled at every check-point (submit, solve and inside the solver); true abandons the run. */
  isCancelled?: () => boolean;
  /** Passed to the solver (budget). */
  maxClasses?: number;
}

export class RunState {
  readonly examples: readonly Example[];
  readonly byId: Map<string, Example>;
  readonly k: number;
  readonly ctx: ExampleContext;
  round = 0;
  readonly records = new Map<string, SketchRecord>();
  acceptedThisRound: string[] = [];
  private readonly emitFn: (e: RunEvent) => void;
  private readonly opts: RunStateOptions;

  constructor(examples: readonly Example[], emit: (e: RunEvent) => void, opts: RunStateOptions) {
    this.examples = [...examples];
    this.byId = new Map(this.examples.map((e) => [e.clip_id, e] as const));
    if (this.byId.size !== this.examples.length) throw new Error("example clip ids must be unique");
    this.emitFn = emit;
    this.k = opts.k;
    this.opts = opts;
    this.ctx = makeExampleContext(this.examples);
  }

  // ------------------------------------------------------------------ plumbing
  emit(e: RunEvent): void {
    this.emitFn(e);
  }

  checkCancel(): void {
    if (this.opts.isCancelled?.()) throw new Cancelled();
  }

  startRound(r: number): void {
    this.round = r;
    this.acceptedThisRound = [];
  }

  // ------------------------------------------------------------------ parse / typecheck / submit
  /** (rule, errors). Errors are written for the LLM. */
  parseSketch(text: string): { rule: Rule | null; errors: string[] } {
    let rule: Rule;
    try {
      rule = parse(text.trim());
    } catch (e) {
      if (e instanceof DSLSyntaxError) {
        return { rule: null, errors: [`syntax error: ${e.message}` + (e.context ? `\n${e.context}` : "")] };
      }
      if (e instanceof DSLError) return { rule: null, errors: [`syntax error: ${e.message}`] };
      return { rule: null, errors: [`could not parse the sketch: ${(e as Error).name}: ${(e as Error).message}`] };
    }
    let errs = typecheck(rule);
    if (errs.length === 0) {
      try {
        holeKinds(rule);
      } catch (e) {
        if (!(e instanceof SketchError)) throw e;
        errs = [e.message];
      }
    }
    return { rule: errs.length === 0 ? rule : null, errors: errs };
  }

  /** Register a proposed sketch for this round: (accepted, errors, canonical text). */
  submit(text: string): { accepted: boolean; errors: string[]; canon: string } {
    this.checkCancel();
    const { rule, errors } = this.parseSketch(text);
    if (rule === null) {
      this.emit({ type: "typecheck_failed", round: this.round, sketch: text.trim(), error: errors.join("; ") });
      return { accepted: false, errors, canon: text.trim() };
    }
    const canon = toText(rule);
    if (!this.records.has(canon)) {
      this.records.set(canon, { text: canon, sketch: rule, round: this.round, error: null, result: null, candidate: null });
      this.emit({ type: "sketch_proposed", round: this.round, sketch: canon });
    }
    if (!this.acceptedThisRound.includes(canon)) this.acceptedThisRound.push(canon);
    return { accepted: true, errors: [], canon };
  }

  // ------------------------------------------------------------------ solve
  weightedViolations(violated: readonly string[]): number {
    let w = 0;
    for (const c of violated) w += (this.byId.get(c) as Example).weight;
    return w;
  }

  /** Solve a registered sketch (cached): emits solve_started / solve_result / differential_check / counterexample. */
  solve(canon: string): SketchRecord {
    this.checkCancel();
    const rec = this.records.get(canon) as SketchRecord;
    if (rec.result !== null) return rec;
    this.emit({ type: "solve_started", round: this.round, sketch: canon });
    const so: SolveOptions = { maxClasses: this.opts.maxClasses, isCancelled: this.opts.isCancelled };
    let res: SolveResult;
    try {
      res = solveSketchExhaustive(rec.sketch as Rule, this.ctx, so);
    } catch (e) {
      if (e instanceof SketchError) {
        rec.error = e.message;
        this.emit({ type: "typecheck_failed", round: this.round, sketch: canon, error: e.message });
        return rec;
      }
      throw e;
    }
    rec.result = res;
    if (res.rule !== null) {
      const { sketch, rule } = res;
      rec.candidate = {
        sketch_text: toText(sketch), dsl_text: toText(rule), english: toEnglish(rule), rule, holes: { ...res.holes },
        margin: res.margin, mdl: mdl(sketch, this.weightedViolations(res.violated)),
        violated_clip_ids: [...res.violated], sketch,
      };
    }
    this.emit({
      type: "solve_result", round: this.round, sketch: canon, result: res.status,
      holes: res.rule !== null ? { ...res.holes } : null, margin: res.rule !== null ? res.margin : null,
      violated_clip_ids: [...res.violated],
      message: res.note ? `${res.solveMs} ms; ${res.note}` : `${res.solveMs} ms`,
    });
    if (res.rule !== null) {
      this.emit({
        type: "differential_check", round: this.round, sketch: canon,
        message: `placed rule re-checked with the evaluator on ${this.examples.length} examples (margin ${res.margin.toFixed(2)})`,
      });
    }
    if (res.rule !== null && res.violated.length > 0) {
      this.emit({
        type: "counterexample", round: this.round, sketch: canon, violated_clip_ids: [...res.violated],
        message: `${res.violated.length} labelled example(s) violated: perception suspect?`,
      });
    }
    return rec;
  }

  // ------------------------------------------------------------------ views
  solved(): SketchRecord[] {
    return [...this.records.values()].filter((r) => r.result !== null);
  }

  candidates(): Candidate[] {
    const withCand = this.solved().filter((r) => r.candidate !== null).map((r) => r.candidate as Candidate);
    const ranked = withCand.sort((x, y) => {
      if (x.mdl !== y.mdl) return x.mdl < y.mdl ? -1 : 1;
      if (x.margin !== y.margin) return x.margin > y.margin ? -1 : 1; // -margin ascending
      return x.dsl_text < y.dsl_text ? -1 : x.dsl_text > y.dsl_text ? 1 : 0;
    });
    const out = new Map<string, Candidate>();
    for (const c of ranked) if (!out.has(c.dsl_text)) out.set(c.dsl_text, c);
    return [...out.values()];
  }

  nConsistent(): number {
    const s = new Set<string>();
    for (const r of this.solved()) if (r.candidate !== null && r.candidate.violated_clip_ids.length === 0) s.add(r.candidate.dsl_text);
    return s.size;
  }
}
