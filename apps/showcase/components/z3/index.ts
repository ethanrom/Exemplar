// The opt-in "Check with real Z3" (SPEC 8): provider, panel and per-candidate badge. See lib/synth/z3 for the solver.
export { Z3Provider, useZ3, useZ3Inputs } from './Z3Provider.tsx'
export type { Z3Ctl, Z3Run } from './Z3Provider.tsx'
export { Z3Panel, statusText } from './Z3Panel.tsx'
export { Z3Badge } from './Z3Badge.tsx'
export { Z3_SHIPPED, Z3_TRANSFER_MB, Z3_WORKER_URL } from './assets.ts'
export type { ItemResult, Z3Inputs, Z3Item } from './types.ts'
