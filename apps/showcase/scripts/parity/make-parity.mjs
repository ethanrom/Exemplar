// Writes data/parity.json, the report the Evidence page renders ("This site's own check", components/evidence/ParitySlot.tsx).
//
//   node scripts/parity/make-parity.mjs        (from apps/showcase; takes about a minute)
//
// Nothing is typed in. The script runs the parity tests with `node --test`, parses the count lines they print, checks
// each count against the golden file's own meta record, and takes F8 (lab.grid) from data/grid/parity-report.json,
// which `lib/synth/compare/run-parity.ts` wrote over all 6,050 slots. It stops on any failing test, any mismatch, a
// count that disagrees with its golden file, or goldens made by different engine commits.
// Families are keyed by golden family name (dsl.random, ..., mdl), not by the spec's F1-F11 numbers: the site's copy rules
// keep "F1" off the page, where it would read as an F1 score.
import { spawnSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gunzipSync } from 'node:zlib'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const abs = (p) => join(root, p)
const fail = (msg) => { console.error(`make-parity: ${msg}`); process.exit(1) }

const TESTS = [
  'lib/dsl/test/golden.test.ts',
  'lib/synth/synth.test.ts',
  'lib/synth/random.test.ts',
  'lib/synth/calibrate.test.ts',
  'lib/synth/conformal.test.ts',
  'lib/synth/mdl.test.ts',
]
const run = spawnSync(process.execPath, ['--test', ...TESTS], { cwd: root, encoding: 'utf-8', maxBuffer: 1 << 28 })
const log = `${run.stdout}\n${run.stderr}`
if (run.status !== 0) fail(`the parity tests failed (exit ${run.status}):\n${log.split('\n').filter((l) => /^✖|not ok/.test(l)).join('\n')}`)

// --- golden files: meta record and event counts -------------------------------------------------------------------
const golden = (dir, name) => gunzipSync(readFileSync(abs(`${dir}/${name}.jsonl.gz`))).toString('utf-8').split('\n').filter(Boolean).map((l) => JSON.parse(l))
const meta = (dir, name) => golden(dir, name)[0]
const DSL = 'lib/dsl/test/golden'
const SYN = 'data/grid/golden'
const commits = new Set([
  ...['dsl.random', 'dsl.real', 'dsl.sweep', 'dsl.edge', 'dsl.text'].map((n) => meta(DSL, n).engine_commit),
  ...['synth.recorded', 'synth.random', 'synth.random.sat', 'cegis.presets', 'cal', 'cal.real', 'mdl'].map((n) => meta(SYN, n).engine_commit),
])
if (commits.size !== 1) fail(`goldens come from ${commits.size} engine commits: ${[...commits].join(', ')}`)
const engine_commit = [...commits][0]
const manifestCommit = JSON.parse(readFileSync(abs('data/manifest.json'), 'utf-8')).engine_commit
if (manifestCommit !== engine_commit) fail('data/manifest.json names a different engine commit than the goldens')

const families = {}
const add = (name, f, goldenCount) => {
  if (f.mismatches !== 0) fail(`${name}: ${f.mismatches} mismatches`)
  if (goldenCount !== undefined && f.cases !== goldenCount) fail(`${name}: tests counted ${f.cases} cases, the golden file's meta says ${goldenCount}`)
  families[name] = {
    cases: f.cases, identical: f.identical, tie_verified: f.tie_verified ?? 0, engine_supplied: f.engine_supplied ?? 0,
    excluded_operational: f.excluded_operational ?? 0, mismatches: f.mismatches,
  }
}
const one = (re, what) => {
  const m = re.exec(log)
  if (!m) fail(`no "${what}" line in the test output`)
  return m
}
const esc = (s) => s.replace(/\./g, '\\.')

// F1-F5 (lib/dsl/test/golden.test.ts prints "# golden F1 dsl.random: 7886 cases, 7886 identical, 0 mismatches")
for (const [id, fam] of [['F1', 'dsl.random'], ['F2', 'dsl.real'], ['F3', 'dsl.sweep'], ['F4', 'dsl.edge'], ['F5', 'dsl.text']]) {
  const m = one(new RegExp(`# golden ${id} ${esc(fam)}: (\\d+) cases, (\\d+) identical, (\\d+) mismatches`), `${id} ${fam}`)
  add(fam, { cases: +m[1], identical: +m[2], mismatches: +m[3] }, meta(DSL, fam).count)
}

// F6 synth.recorded, F7 synth.random (+ .sat): F7 synth.random (1298): {"identical":1260,"tie_verified":0,"engine_supplied":38,"mismatch":0} boxes ...
{
  const m = one(/F6 synth\.recorded \((\d+)\): (\{.*?\})/, 'F6 synth.recorded')
  const c = JSON.parse(m[2])
  add('synth.recorded', { cases: +m[1], identical: c.identical, tie_verified: c.tie_verified, engine_supplied: c.engine_supplied, mismatches: c.mismatch }, meta(SYN, 'synth.recorded').count)
}
for (const fam of ['synth.random', 'synth.random.sat']) {
  const m = one(new RegExp(`F7 ${esc(fam)} \\((\\d+)\\): (\\{.*?\\}) boxes \\d+ \\(mismatch (\\d+)\\) alternatives \\d+ \\(mismatch (\\d+)\\)`), `F7 ${fam}`)
  const c = JSON.parse(m[2])
  add(fam, { cases: +m[1], identical: c.identical, tie_verified: c.tie_verified, engine_supplied: c.engine_supplied, mismatches: c.mismatch + +m[3] + +m[4] }, meta(SYN, fam).count)
}

// F8 lab.grid: the full run over all slots
{
  const r = JSON.parse(readFileSync(abs('data/grid/parity-report.json'), 'utf-8'))
  const g = JSON.parse(readFileSync(abs('data/grid/grid-report.json'), 'utf-8'))
  if (r.problems.length) fail(`data/grid/parity-report.json lists ${r.problems.length} problems`)
  const mismatches = r.mismatch + r.missing + r.top6_mismatch + r.top6_missing + r.mdl_mismatch + r.alt_mismatch
  if (r.identical + r.tie_verified + r.engine_supplied !== r.entries) fail('F8: identical + tie-verified + engine-supplied does not add up to the entries')
  if (r.entries !== g.entries || r.slots !== g.valid_slots) fail('F8: parity-report.json and grid-report.json disagree')
  add('lab.grid', {
    cases: r.entries, identical: r.identical, tie_verified: r.tie_verified, engine_supplied: r.engine_supplied,
    excluded_operational: g.operational_entries.length, mismatches,
  })
}

// F9 cegis.presets: the event streams of the recorded presets, compared event by event. All streams in the golden file are
// compared and counted; the per-preset table lists only the runs the site publishes.
const UNPUBLISHED_RUNS = ['p2-generated', 'run2-identical']
const presets = {}
{
  const [, ...records] = golden(SYN, 'cegis.presets')
  let cases = 0
  let engineSupplied = 0
  for (const rec of records) {
    const m = one(new RegExp(`F9 ${esc(rec.id)}: (\\d+) events \\(engine (\\d+)\\), (\\d+) engine-supplied solves`), `F9 ${rec.id}`)
    const events = rec.expect.events.filter((e) => e.type !== 'done')
    if (+m[1] !== events.length) fail(`F9 ${rec.id}: the test replayed ${m[1]} events, the golden has ${events.length}`)
    const solves = events.filter((e) => e.type === 'solve_result').length
    cases += events.length
    engineSupplied += +m[3]
    if (!UNPUBLISHED_RUNS.includes(rec.id)) presets[rec.id] = { solves, identical: solves - +m[3], engine_supplied: +m[3] }
  }
  add('cegis.presets', { cases, identical: cases - engineSupplied, engine_supplied: engineSupplied, mismatches: 0 })
}

// F10 cal and cal.real, F11 mdl
{
  const m = one(/F10 cal: (\d+) cases, (\d+) mismatches/, 'F10 cal')
  add('cal', { cases: +m[1], identical: +m[1] - +m[2], mismatches: +m[2] })
  const r = one(/F10 cal\.real: (\d+) calibrations, \d+ evaluator scores, (\d+) mismatches/, 'F10 cal.real')
  add('cal.real', { cases: +r[1], identical: +r[1] - +r[2], mismatches: +r[2] }, meta(SYN, 'cal.real').count)
  const d = one(/F11 mdl: (\d+) cases x 2 inputs \((\d+) records\), (\d+) mismatches/, 'F11 mdl')
  add('mdl', { cases: +d[1], identical: +d[1] - +d[3], mismatches: +d[3] }, meta(SYN, 'mdl').count)
}

const report = { generated_on: new Date().toISOString().slice(0, 10), engine_commit, families, presets }
writeFileSync(abs('data/parity.json'), JSON.stringify(report, null, 1) + '\n', 'utf-8')
console.log(`data/parity.json: ${Object.keys(families).length} families, 0 mismatches, engine ${engine_commit.slice(0, 10)}`)
for (const [n, f] of Object.entries(families)) {
  console.log(`  ${n}: ${f.cases} cases, ${f.identical} identical, ${f.tie_verified} tie-verified, ${f.engine_supplied} engine-supplied`)
}
