// lib/synth: the learning half of Exemplar in TypeScript - exhaustive hole solver, run state and replay loop,
// MDL ranking and conformal calibration. Pure and deterministic; the only dependency is lib/dsl.

export { betainc, betaincinv, calibrateScores, clopperPearson, conformalRank, conformalThreshold, escalationDelta,
  minNegatives, pyRound3, recallCi } from "./conformal.ts";
export type { Calibration } from "./conformal.ts";
export { BITS_PER_HOLE, BITS_PER_NODE, mdl, nParameters } from "./mdl.ts";
export { EPS, InfeasibleBox, MARGIN_LEVELS, MAX_CLASSES, holeBox, makeExampleContext, solveForSatisfiedSet,
  solveSketchExhaustive } from "./exhaustive.ts";
export type { ExampleContext, SolveOptions } from "./exhaustive.ts";
export { RunState } from "./state.ts";
export type { RunEvent, RunStateOptions, SketchRecord } from "./state.ts";
export { runReplay } from "./replay.ts";
export type { RecordedRound, ReplayOptions, ReplayResult } from "./replay.ts";
export { Cancelled, SketchError, makeExample } from "./types.ts";
export type { Candidate, Example, SolveResult, SolveStatus } from "./types.ts";
export { K, LabSession, WEIGHT, examplesOf, freePlay, freePlayGen, isValid, runPreset, slotOf, statesOf } from "./session.ts";
export type { CandidateItem, FreePlayResult, LabData, PresetRun, PresetResult, SketchOutcome, States, WorkerMessage,
  WorkerRequest } from "./session.ts";
export { calibrate } from "./calibrate.ts";
export type { RandomLabelled } from "./calibrate.ts";
