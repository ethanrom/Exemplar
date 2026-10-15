// Seed data for the mock engine: events (built from the engine fixture traces, Playground-like
// on_demand events and CC BY upload windows), concepts, labels and rule templates.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
export const FIXTURE_DIR = path.resolve(HERE, '../../../engine/tests/fixtures/traces')

export const DEVICE_ID = 'ava1.ring.device.PLAYGROUND0001'
export const FROLLARD_ATTRIBUTION = '"Thief stealing our package" by frollard, CC BY 4.0'
export const FROLLARD_URL = 'https://www.youtube.com/watch?v=TfTFu8lGrwk'

const MIN = 60_000
const HOUR = 60 * MIN

function loadFixture(name) {
  const file = path.join(FIXTURE_DIR, `${name}.json`)
  if (!fs.existsSync(file)) {
    throw new Error(`mock: fixture trace not found: ${file} (expected the engine fixtures next to apps/web)`)
  }
  return JSON.parse(fs.readFileSync(file, 'utf8'))
}

const FAST_META = (n) => ({
  mode: 'fast',
  model_alias: 'fast',
  n_frames: n,
  samples: 1,
  tokens_in: 6400,
  tokens_out: 1400,
  latency_ms: 11000,
})

function cloneTrace(base, o) {
  const tr = JSON.parse(JSON.stringify(base))
  tr.clip_id = o.clip_id
  tr.source = o.source
  if (o.duration_ms) tr.duration_ms = o.duration_ms
  tr.context = { ...tr.context, ...(o.context || {}) }
  if (o.summary) tr.summary = o.summary
  if (o.source !== 'fixture' && tr.status === 'ok') tr.perception = FAST_META(tr.frames.length)
  if (o.mutate) o.mutate(tr)
  return tr
}

// ------------------------------------------------------------------ the frollard source clip
// "Thief stealing our package": box on the steps, a person arrives at ~12 s, takes it at ~18 s and
// leaves with it at ~21 s. Windows are cut like POST /uploads would (window_s=10, stride_s=5).
const BOX = ['in_zone', ['k1', 'porch'], 'high']
function frollardFacts(t) {
  if (t < 12) return [BOX]
  if (t === 12) return [BOX, ['enters', ['p1', 'porch'], 'med']]
  if (t === 13) return [BOX, ['in_zone', ['p1', 'porch'], 'med']]
  if (t <= 17) return [BOX, ['in_zone', ['p1', 'porch'], 'high'], ['near', ['p1', 'k1'], 'high']]
  if (t === 18) return [['picks_up', ['p1', 'k1'], 'high'], ['in_zone', ['p1', 'porch'], 'high']]
  if (t === 19 || t === 20) return [['carrying', ['p1', 'k1'], 'high'], ['in_zone', ['p1', 'porch'], 'high']]
  if (t === 21) return [['carrying', ['p1', 'k1'], 'high'], ['leaves', ['p1', 'porch'], 'med']]
  if (t <= 25) return [['carrying', ['p1', 'k1'], 'med'], ['in_zone', ['p1', 'sidewalk'], 'med']]
  return []
}
const FROLLARD_SUMMARIES = [
  'A cardboard box sits on snowy steps; nobody appears.',
  'A box on the steps; a person walks into view at the very end.',
  'A person walks up to the box and picks it up.',
  'A person picks up the box from the steps and walks away carrying it.',
  'A person carries the box away across the sidewalk.',
  'A person with a box leaves the frame; the steps are empty.',
  'Empty snowy steps.',
  'Empty snowy steps.',
]
export const FROLLARD_WINDOWS = 8

function frollardTrace(n, source = 'upload', clipId = `frollard_w0${n}`) {
  const start = n * 5
  const frames = []
  for (let t = start; t <= start + 10; t += 1) {
    frames.push({
      t_ms: (t - start) * 1000,
      facts: frollardFacts(t).map(([pred, args, conf]) => ({ pred, args, conf })),
    })
  }
  const mentioned = new Set(frames.flatMap((f) => f.facts.flatMap((x) => x.args)))
  const entities = []
  if (mentioned.has('p1')) entities.push({ id: 'p1', type: 'person', attrs: ['dark_jacket'] })
  if (mentioned.has('k1')) entities.push({ id: 'k1', type: 'package', attrs: ['box'] })
  return {
    schema_version: 1,
    clip_id: clipId,
    source,
    duration_ms: 10_000,
    status: 'ok',
    error: null,
    entities,
    frames,
    context: { sub_type: null, event_kind: 'upload', local_hour: null, weekday: null, device_id: null, started_at_ms: null },
    summary: FROLLARD_SUMMARIES[n],
    perception: FAST_META(frames.length),
  }
}

/** Variants used for newly uploaded windows (POST /uploads) so the mock can accept any file. */
export function uploadWindowTrace(i, clipId) {
  return frollardTrace(i % FROLLARD_WINDOWS, 'upload', clipId)
}

// ------------------------------------------------------------------ events
/** @returns {Array<object>} internal event records (newest first); `trace` is the Trace JSON. */
export function buildEvents(now = Date.now()) {
  const events = []
  const add = (e) => {
    events.push({
      device_id: DEVICE_ID,
      sub_type: null,
      clip_status: 'ready',
      trace_status: 'ok',
      has_snapshot: true,
      attribution: null,
      strong_trace: null,
      ...e,
    })
  }

  // Playground simulations: each is an `on_demand` event with no sub_type (the Playground does not report one).
  const pg = [
    ['pg_package_a', 'unattended_package', 31_700, 6 * MIN],
    ['pg_vehicle_a', 'vehicle_passby', 21_500, 11 * MIN],
    ['pg_motion_a', 'birds_feeder', 39_200, 16 * MIN],
    ['pg_package_b', 'unattended_package', 31_700, 95 * MIN],
    ['pg_vehicle_b', 'vehicle_passby', 21_500, 101 * MIN],
    ['pg_motion_b', 'birds_feeder', 39_200, 110 * MIN],
  ]
  for (const [id, fx, dur, ago] of pg) {
    const tr = cloneTrace(loadFixture(fx), {
      clip_id: id,
      source: 'ring',
      duration_ms: dur,
      context: { sub_type: null, event_kind: 'on_demand', device_id: DEVICE_ID, started_at_ms: now - ago },
      mutate: (t) => {
        if (fx === 'vehicle_passby') {
          // the Playground vehicle clip is clearer than the fixture: first sighting is high confidence
          for (const f of t.frames) for (const x of f.facts) if (x.pred === 'in_zone' && x.conf === 'med') x.conf = 'high'
        }
      },
    })
    add({ id: `ev_${id}`, clip_id: id, source: 'ring', kind: 'on_demand', start_ms: now - ago, duration_ms: dur, trace: tr })
  }

  // Ring history (motion / ding) with smart-alert sub_types, cloned from fixtures.
  const hist = [
    ['ring_visit_ring', 'visitor_rings', 'ding', 'human', 3 * HOUR],
    ['ring_visit_noring', 'visitor_no_ring', 'motion', 'human', 5 * HOUR],
    ['ring_empty', 'empty_scene', 'motion', 'other_motion', 28 * HOUR],
    ['ring_delivery_1', 'delivery_a', 'motion', 'package_delivery', 26 * HOUR],
    ['ring_delivery_2', 'delivery_b', 'ding', 'package_delivery', 29 * HOUR],
    ['ring_vehicle_1', 'vehicle_passby', 'motion', 'vehicle', 30 * HOUR],
    ['ring_birds', 'birds_feeder', 'motion', 'other_motion', 50 * HOUR],
    ['ring_vehicle_2', 'vehicle_dwell_dock', 'motion', 'vehicle', 52 * HOUR],
  ]
  for (const [id, fx, kind, sub, ago] of hist) {
    const base = loadFixture(fx)
    const tr = cloneTrace(base, {
      clip_id: id,
      source: 'ring',
      context: { sub_type: sub, event_kind: kind, device_id: DEVICE_ID, started_at_ms: now - ago },
    })
    add({
      id: `ev_${id}`, clip_id: id, source: 'ring', kind, sub_type: sub, start_ms: now - ago,
      duration_ms: base.duration_ms, trace: tr, has_snapshot: id !== 'ring_empty',
    })
  }

  // Hand-tuned package clips used by the calibration story (hard negative / soft positive).
  const pkgBase = loadFixture('unattended_package')
  add({
    id: 'ev_ring_pkg_taken', clip_id: 'ring_pkg_taken', source: 'ring', kind: 'motion', sub_type: 'human',
    start_ms: now - 72 * HOUR, duration_ms: 31_000,
    trace: cloneTrace(pkgBase, {
      clip_id: 'ring_pkg_taken', source: 'ring', duration_ms: 31_000,
      summary: 'A package sits on the steps for most of the clip; someone collects it at the end.',
      context: { sub_type: 'human', event_kind: 'motion', device_id: DEVICE_ID, started_at_ms: now - 72 * HOUR },
      mutate: (t) => {
        t.entities.push({ id: 'p1', type: 'person', attrs: ['jacket'] })
        for (const f of t.frames) for (const x of f.facts) x.conf = 'med'
        t.frames.push({ t_ms: 31_000, facts: [{ pred: 'picks_up', args: ['p1', 'k1'], conf: 'high' }] })
      },
    }),
  })
  add({
    id: 'ev_ring_pkg_soft', clip_id: 'ring_pkg_soft', source: 'ring', kind: 'motion', sub_type: 'package_delivery',
    start_ms: now - 75 * HOUR, duration_ms: 30_000,
    trace: cloneTrace(pkgBase, {
      clip_id: 'ring_pkg_soft', source: 'ring', duration_ms: 30_000,
      summary: 'A parcel, barely visible through snowfall, rests on the steps.',
      context: { sub_type: 'package_delivery', event_kind: 'motion', device_id: DEVICE_ID, started_at_ms: now - 75 * HOUR },
      mutate: (t) => { for (const f of t.frames) for (const x of f.facts) x.conf = 'low' },
    }),
  })
  add({
    id: 'ev_ring_parked', clip_id: 'ring_parked', source: 'ring', kind: 'motion', sub_type: 'vehicle',
    start_ms: now - 77 * HOUR, duration_ms: 20_000,
    trace: cloneTrace(loadFixture('vehicle_passby'), {
      clip_id: 'ring_parked', source: 'ring', duration_ms: 20_000,
      summary: 'A car sits parked at the kerb for the whole clip.',
      context: { sub_type: 'vehicle', event_kind: 'motion', device_id: DEVICE_ID, started_at_ms: now - 77 * HOUR },
      mutate: (t) => {
        t.frames = t.frames.map((f) => ({ t_ms: f.t_ms, facts: [{ pred: 'in_zone', args: ['v1', 'street'], conf: 'low' }] }))
      },
    }),
  })

  // A live capture from the WHEP view (ring_live).
  add({
    id: 'ev_live_1', clip_id: 'live_1', source: 'ring_live', kind: 'live', start_ms: now - 22 * MIN, duration_ms: 12_000,
    trace: cloneTrace(loadFixture('visitor_no_ring'), {
      clip_id: 'live_1', source: 'ring_live', duration_ms: 15_000,
      context: { sub_type: null, event_kind: 'live', device_id: DEVICE_ID, started_at_ms: now - 22 * MIN },
    }),
  })

  // Engine fixtures, as they appear in a dev library.
  const fixtures = [
    'theft_a', 'theft_b', 'delivery_a', 'delivery_b', 'unattended_package', 'vehicle_passby',
    'vehicle_dwell_dock', 'visitor_rings', 'visitor_no_ring', 'birds_feeder', 'empty_scene', 'perception_failed',
  ]
  fixtures.forEach((fx, i) => {
    const tr = loadFixture(fx)
    const failed = tr.status === 'perception_failed'
    add({
      id: `ev_fx_${fx}`, clip_id: fx, source: 'fixture', kind: tr.context.event_kind ?? 'motion',
      sub_type: tr.context.sub_type ?? null, device_id: tr.context.device_id ?? DEVICE_ID,
      start_ms: now - (7 * 24 + 3 * i) * HOUR, duration_ms: tr.duration_ms, trace: tr,
      trace_status: failed ? 'perception_failed' : 'ok', has_snapshot: !failed,
    })
  })

  // CC BY source footage cut into windows by the engine's `upload` source.
  const uploadedAt = now - 40 * MIN
  for (let n = 0; n < FROLLARD_WINDOWS; n++) {
    add({
      id: `ev_frollard_w0${n}`, clip_id: `frollard_w0${n}`, source: 'upload', kind: 'upload', device_id: null,
      start_ms: uploadedAt + n * 5000, duration_ms: 10_000, attribution: FROLLARD_ATTRIBUTION,
      trace: frollardTrace(n),
    })
  }

  events.sort((a, b) => b.start_ms - a.start_ms)
  return events
}

// ------------------------------------------------------------------ concepts and labels
export const ALPHA = 0.1

export function seedConcepts() {
  return [
    {
      id: 'cn_theft', name: 'Package theft', nl_hint: 'a person who is not the courier takes a package from the porch',
      alpha: ALPHA, rules_ready: false,
    },
    {
      id: 'cn_unattended', name: 'Package left on the steps', nl_hint: 'a package sits on the steps and nobody comes for it',
      alpha: ALPHA, rules_ready: true, deployed_rule_id: 'r_unatt_steps24',
    },
    {
      id: 'cn_vehicle', name: 'Vehicle moving through the lot', nl_hint: 'a car drives through the lot',
      alpha: ALPHA, rules_ready: true, deployed_rule_id: 'r_veh_street4',
    },
  ]
}

/** [concept, clip_id, value, provenance] */
export function seedLabels() {
  const L = []
  const lab = (c, clip, value, prov) => L.push([c, clip, value, prov])
  // Package theft: taught from the frollard windows; only 4 random negatives so far (no guarantee yet).
  for (const c of ['theft_a', 'frollard_w03', 'frollard_w04']) lab('cn_theft', c, 'pos', 'example')
  for (const c of ['delivery_a', 'frollard_w00']) lab('cn_theft', c, 'neg', 'example')
  for (const c of ['empty_scene', 'birds_feeder', 'ring_visit_ring', 'ring_vehicle_1']) lab('cn_theft', c, 'neg', 'random')
  // Unattended package: guarantee available (12 random negatives), 3 random positives.
  lab('cn_unattended', 'pg_package_a', 'pos', 'example')
  for (const c of ['pg_vehicle_a', 'pg_motion_a']) lab('cn_unattended', c, 'neg', 'example')
  for (const c of [
    'pg_vehicle_b', 'pg_motion_b', 'ring_empty', 'ring_birds', 'ring_visit_ring', 'ring_visit_noring',
    'ring_delivery_1', 'ring_delivery_2', 'ring_vehicle_1', 'theft_b', 'visitor_no_ring', 'ring_pkg_taken',
  ]) lab('cn_unattended', c, 'neg', 'random')
  for (const c of ['pg_package_b', 'unattended_package', 'ring_pkg_soft']) lab('cn_unattended', c, 'pos', 'random')
  // Vehicle through the lot: 10 random negatives, 2 random positives.
  lab('cn_vehicle', 'pg_vehicle_a', 'pos', 'example')
  for (const c of ['pg_package_a', 'pg_motion_a']) lab('cn_vehicle', c, 'neg', 'example')
  for (const c of [
    'pg_package_b', 'pg_motion_b', 'ring_empty', 'ring_birds', 'ring_visit_ring', 'ring_delivery_1',
    'ring_delivery_2', 'ring_parked', 'theft_a', 'delivery_a',
  ]) lab('cn_vehicle', c, 'neg', 'random')
  for (const c of ['pg_vehicle_b', 'ring_vehicle_1']) lab('cn_vehicle', c, 'pos', 'random')
  return L
}

// ------------------------------------------------------------------ rules (AST templates)
const A = (pred, ...args) => ({ op: 'atom', pred, args })
const Not = (arg) => ({ op: 'not', arg })
const And = (...args) => ({ op: 'and', args })
const Then = (a, b, left, right) => ({ op: 'then', a, b, left, right })
const Hold = (d, arg) => ({ op: 'holds_for', d, arg })
const Ev = (a, b, arg) => ({ op: 'eventually', a, b, arg })
const R = (vars, body, when = []) => ({ vars: vars.map(([name, type]) => ({ name, type })), body, when })

/** Rule templates; `english` is what the engine's deterministic printer would produce. */
export function ruleTemplates() {
  const PK = [['p', 'Person'], ['k', 'Package']]
  return [
    {
      id: 'r_theft_pickup', concept_id: 'cn_theft',
      sketch_text: 'exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch)',
      ast: R(PK, Then(0, 15.5, A('picks_up', 'p', 'k'), A('leaves', 'p', 'porch'))), holes: { b: 15.5 },
      english: 'There is a person p and a package k such that p picks up k, and then within 0 to 15.5 s p leaves the porch.',
    },
    {
      id: 'r_theft_nouniform', concept_id: 'cn_theft',
      sketch_text: 'exists p: Person, k: Package: picks_up(p, k) and not attr(p, delivery_uniform)',
      ast: R(PK, And(A('picks_up', 'p', 'k'), Not(A('attr', 'p', 'delivery_uniform')))), holes: {},
      english: 'There is a person p and a package k such that p picks up k, and p does not have the attribute delivery_uniform.',
    },
    {
      id: 'r_theft_carry', concept_id: 'cn_theft',
      sketch_text: 'exists p: Person, k: Package: carrying(p, k) then[0, ?b] leaves(p, porch) and not attr(p, delivery_uniform)',
      ast: R(PK, And(Then(0, 6, A('carrying', 'p', 'k'), A('leaves', 'p', 'porch')), Not(A('attr', 'p', 'delivery_uniform')))),
      holes: { b: 6 },
      english: 'There is a person p and a package k such that p carries k and then within 0 to 6 s p leaves the porch, and p does not have the attribute delivery_uniform.',
    },
    {
      id: 'r_unatt_steps24', concept_id: 'cn_unattended',
      sketch_text: 'exists k: Package: holds_for >= ?d in_zone(k, steps)',
      ast: R([['k', 'Package']], Hold(24, A('in_zone', 'k', 'steps'))), holes: { d: 24 },
      english: 'There is a package k such that k stays in the steps for at least 24 s.',
    },
    {
      id: 'r_unatt_steps18', concept_id: 'cn_unattended',
      sketch_text: 'exists k: Package: holds_for >= ?d in_zone(k, steps)',
      ast: R([['k', 'Package']], Hold(18, A('in_zone', 'k', 'steps'))), holes: { d: 18 },
      english: 'There is a package k such that k stays in the steps for at least 18 s.',
    },
    {
      id: 'r_veh_street4', concept_id: 'cn_vehicle',
      sketch_text: 'exists v: Vehicle: holds_for >= ?d in_zone(v, street)',
      ast: R([['v', 'Vehicle']], Hold(4, A('in_zone', 'v', 'street'))), holes: { d: 4 },
      english: 'There is a vehicle v such that v stays in the street for at least 4 s.',
    },
    {
      id: 'r_veh_street10', concept_id: 'cn_vehicle',
      sketch_text: 'exists v: Vehicle: eventually[0, ?b] in_zone(v, street)',
      ast: R([['v', 'Vehicle']], Ev(0, 10, A('in_zone', 'v', 'street'))), holes: { b: 10 },
      english: 'There is a vehicle v such that within 0 to 10 s v is in the street.',
    },
  ]
}

/** Scripted "question" queue per concept: unlabelled clips the committee disagrees on. */
export const QUESTIONS = {
  cn_theft: [
    { clip_id: 'frollard_w02', p: 0.47, committee_size: 24 },
    { clip_id: 'frollard_w01', p: 0.38, committee_size: 24 },
  ],
  cn_unattended: [{ clip_id: 'ring_pkg_taken', p: 0.52, committee_size: 24 }],
  cn_vehicle: [],
}

// ------------------------------------------------------------------ eval results (MEVA)
function rng(seed) {
  let s = seed >>> 0
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0
    return s / 4294967296
  }
}

export function buildEvalResults() {
  const concepts = ['vehicle_dwell', 'door_entry_exit', 'exit_vehicle', 'load_unload']
  const hard = { vehicle_dwell: 0.04, door_entry_exit: 0, exit_vehicle: -0.03, load_unload: -0.07 }
  const rows = []
  const rand = rng(20261015)
  const jitter = (sd) => (rand() + rand() + rand() - 1.5) * (sd / 0.5)
  const clamp = (x, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, x))
  const push = (concept, method, k, q, seed, f1, fa, tokens, usd, lat, esc) =>
    rows.push({
      concept, method, k, q, seed,
      f1: +clamp(f1).toFixed(3),
      precision: +clamp(f1 + 0.04 + jitter(0.03)).toFixed(3),
      recall: +clamp(f1 - 0.03 + jitter(0.04)).toFixed(3),
      false_alarm_rate: +clamp(fa, 0, 0.6).toFixed(3),
      tokens_per_event: Math.round(tokens),
      usd_per_event: +usd.toFixed(5),
      p50_latency_ms: Math.round(lat),
      escalated_fraction: +esc.toFixed(3),
    })
  for (const concept of concepts) {
    const h = hard[concept]
    for (let seed = 0; seed < 5; seed++) {
      for (const k of [1, 3]) {
        for (const q of [0, 3, 5]) {
          const f1 = 0.5 + 0.09 * (k === 3 ? 1 : 0) + 0.035 * q * 0.6 + h + jitter(0.045)
          const esc = clamp(0.1 + 0.02 * q + jitter(0.02), 0.03, 0.4)
          push(concept, 'exemplar', k, q, seed, f1, 0.082 + jitter(0.03), 8200 + esc * 7800, 0.0014 + esc * 0.028, 11400 + esc * 9000, esc)
        }
        push(concept, 'knn_embed', k, 0, seed, 0.36 + 0.05 * (k === 3 ? 1 : 0) + h * 0.6 + jitter(0.05), 0.11 + jitter(0.05), 0, 0.0002, 900, 0)
      }
      push(concept, 'zero_shot_vlm', 0, 0, seed, 0.49 + h * 0.5 + jitter(0.05), 0.24 + jitter(0.07), 7800, 0.028, 25000, 0)
      push(concept, 'nova_video', 0, 0, seed, 0.44 + h * 0.5 + jitter(0.06), 0.27 + jitter(0.08), 9400, 0.0092, 18000, 0)
    }
  }
  return { generated_at: new Date().toISOString(), alpha: ALPHA, rows }
}
