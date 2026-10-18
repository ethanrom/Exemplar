// Web Worker entry of the Lab (SPEC 7.5). All the logic is lib/synth's LabSession: the exhaustive solver, the run state
// and replay loop, request ids and cancellation. This file only makes it a bundler entry:
//   new Worker(new URL('../_worker/lab.worker.ts', import.meta.url), { type: 'module' })
// The worker never imports the grid, the comparator or any recorded run (SPEC 6.5); the page does the comparing.
import '../../../lib/synth/lab.worker.ts'
