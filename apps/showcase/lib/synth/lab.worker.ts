// Web Worker entry of the Lab: a thin wrapper around `LabSession` (session.ts), which holds all the logic.
//
//   new Worker(new URL("./lab.worker.ts", import.meta.url), { type: "module" })
//
// Messages in:  { type: "init", data, cancelFlag? } | { type: "free", request_id, states } |
//               { type: "preset", request_id, run } | { type: "cancel", request_id }
// Messages out: { type: "event" | "candidates" | "outcomes" | "done" | "error", request_id, ... }
// Every message out carries the request_id it belongs to; the page drops anything from an older request.

import { LabSession } from "./session.ts";
import type { WorkerMessage, WorkerRequest } from "./session.ts";

const scope = globalThis as unknown as {
  postMessage(m: WorkerMessage): void;
  onmessage: ((ev: { data: WorkerRequest }) => void) | null;
};
const session = new LabSession((m) => scope.postMessage(m));
scope.onmessage = (ev) => {
  void session.handle(ev.data);
};
