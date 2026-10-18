// Node helpers for the Z3 tests (not imported by library code): start z3-solver's Node build and hand the solver a
// context. One long-lived context, like the worker's (see solve.ts, Z3Api).
import { createRequire } from "node:module";
import type { Z3Api } from "./solve.ts";

const require = createRequire(import.meta.url);

export interface NodeZ3 {
  readonly api: Z3Api;
  /** Stop z3-solver's pthread workers so the process can exit. */
  close(): Promise<void>;
}

export async function startNodeZ3(): Promise<NodeZ3> {
  const { init, killThreads } = require("z3-solver") as { init: () => Promise<any>; killThreads: (em: unknown) => Promise<void> };
  const z3 = await init();
  const ctx = new z3.Context("main");
  return { api: { context: () => ctx }, close: () => killThreads(z3.em) };
}
