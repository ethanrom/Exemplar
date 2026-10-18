// Parity of the Z3 path with the engine: F6 (49 recorded solves), F7 (random sketches) and the Lab grid.
//
//   node scripts/z3/parity.mjs                                    F6 + F7 (full) + a grid sample (every 150th valid slot)
//   node scripts/z3/parity.mjs --only grid --grid-stride 10 --grid-offset 5 --skip 60 --limit 60 --out part.json
//
// The grid slots are the valid label combinations in order; `--grid-stride S --grid-offset O` takes every S-th from O, and
// `--skip K --limit L` a window of that list (z3-solver's 2 GB heap is not returned between solves, so a long sweep runs in
// short processes). Prints a JSON report to stdout (and to --out). Z3 runs in Node here; the browser uses the same TypeScript.
import { writeFileSync } from 'node:fs'
import { parseArgs } from 'node:util'
import { loadGrid, runGrid, runRandom, runRecorded } from '../../lib/synth/z3/parity.ts'
import { startNodeZ3 } from '../../lib/synth/z3/testutil.ts'

const { values } = parseArgs({
  options: {
    only: { type: 'string', default: 'all' }, // all | recorded | random | grid
    'grid-stride': { type: 'string', default: '150' },
    'grid-offset': { type: 'string', default: '0' },
    skip: { type: 'string', default: '0' },
    limit: { type: 'string' },
    'random-stride': { type: 'string', default: '1' },
    out: { type: 'string' },
  },
})
const z3 = await startNodeZ3()
const report = { generated_on: new Date().toISOString().slice(0, 10), families: [] }
const want = (f) => values.only === 'all' || values.only === f
try {
  if (want('recorded')) report.families.push(await runRecorded(z3.api))
  if (want('random')) {
    for (const fam of ['synth.random', 'synth.random.sat']) report.families.push(await runRandom(z3.api, fam, { stride: Number(values['random-stride']) }))
  }
  if (want('grid')) {
    let done = 0
    let shown = 0
    const slots = []
    const t = await runGrid(z3.api, loadGrid(), {
      stride: Number(values['grid-stride']), offset: Number(values['grid-offset']), skip: Number(values.skip),
      limit: values.limit === undefined ? undefined : Number(values.limit),
      onSlot: (slot, tally) => {
        slots.push(slot)
        // a case that is neither identical nor an explained agreement is printed the moment it happens (the process may die later)
        for (; shown < tally.notes.length; shown++) if (!/: (agree_outcome|equal_optimum)/.test(tally.notes[shown])) console.error('NOTE ' + tally.notes[shown])
        if (++done % 10 === 0) console.error(`grid: ${done} slots, ${tally.cases} cases, differs ${tally.differs}, errors ${tally.errors}`)
      },
    })
    t.slots = slots
    report.families.push(t)
  }
} finally {
  await z3.close()
}
const text = JSON.stringify(report, null, 1)
if (values.out) writeFileSync(values.out, text)
console.log(text)
