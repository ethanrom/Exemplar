// Mutable state + derived views for the mock engine: labels, rules (scores, margin, MDL,
// calibration), backtests, scripted Teach runs, firings and the cost meter.
import {
  ALPHA, QUESTIONS, buildEvalResults, buildEvents, ruleTemplates, seedConcepts, seedLabels,
} from './data.mjs'
import { C, ruleDslText, scoreRule, witnessFor } from './stl.mjs'

const round3 = (x) => Math.round(x * 1000) / 1000
const WEIGHT = { example: 3, active: 3, random: 1 }

// ------------------------------------------------------------------ statistics
function binomCdf(x, n, p) {
  // P(X <= x)
  let sum = 0
  let term = Math.pow(1 - p, n)
  for (let i = 0; i <= x; i++) {
    sum += term
    term *= ((n - i) / (i + 1)) * (p / (1 - p))
  }
  return Math.min(1, sum)
}

/** Clopper-Pearson interval by bisection on the binomial CDF. */
export function clopperPearson(x, n, alpha = 0.05) {
  if (n === 0) return null
  const bisect = (f) => {
    let lo = 0
    let hi = 1
    for (let i = 0; i < 60; i++) {
      const mid = (lo + hi) / 2
      if (f(mid)) hi = mid
      else lo = mid
    }
    return (lo + hi) / 2
  }
  // lower: smallest p with P(X >= x | p) >= alpha/2  <=>  1 - cdf(x-1) >= alpha/2
  const lower = x === 0 ? 0 : bisect((p) => 1 - binomCdf(x - 1, n, p) >= alpha / 2)
  // upper: largest p with P(X <= x | p) >= alpha/2
  const upper = x === n ? 1 : bisect((p) => binomCdf(x, n, p) <= alpha / 2)
  return [round3(lower), round3(upper)]
}

// ------------------------------------------------------------------ store
export function createStore() {
  const now = Date.now()
  const events = buildEvents(now)
  const byId = new Map(events.map((e) => [e.id, e]))
  const byClip = new Map(events.map((e) => [e.clip_id, e]))
  const concepts = seedConcepts()
  const labels = new Map()
  for (const [c, clip, value, provenance] of seedLabels()) {
    labels.set(`${c}|${clip}`, {
      concept_id: c, clip_id: clip, value, provenance, weight: WEIGHT[provenance],
      created_at: new Date(now - 60_000).toISOString(),
    })
  }
  const rules = ruleTemplates().map((t) => ({
    ...t,
    dsl_text: ruleDslText(t.ast),
    status: concepts.find((c) => c.id === t.concept_id)?.deployed_rule_id === t.id ? 'deployed' : 'candidate',
    actions: ['ui'],
  }))
  return {
    started_ms: now,
    events,
    byId,
    byClip,
    concepts,
    labels,
    rules,
    runs: new Map(),
    sampled: new Map(),
    answered: new Map(),
    scoreCache: new Map(),
    firings: [],
    seq: { run: 0, rule: 0, event: 0, firing: 0, concept: 0 },
    cost: { events: 0, stage0_dropped: 0, stage1_scored: 0, stage2_escalated: 0, tokens_in: 0, tokens_out: 0, usd_estimate: 0 },
    auth: {
      mode: 'playground', connected: true, expires_at_ms: now + 27.5 * 60_000, issued_at_ms: now - 2.5 * 60_000,
      user_name: 'Playground User',
    },
    evalResults: buildEvalResults(),
  }
}

// ------------------------------------------------------------------ views
export function labelSummary(st, conceptId, clipId) {
  const l = st.labels.get(`${conceptId}|${clipId}`)
  if (!l) return null
  return { concept_id: l.concept_id, clip_id: l.clip_id, value: l.value, provenance: l.provenance, weight: l.weight }
}

export function eventSummary(st, ev, conceptId = null) {
  return {
    id: ev.id,
    clip_id: ev.clip_id,
    source: ev.source,
    device_id: ev.device_id ?? null,
    kind: ev.kind ?? null,
    sub_type: ev.sub_type ?? null,
    start_ms: ev.start_ms,
    duration_ms: ev.duration_ms ?? null,
    clip_status: ev.clip_status,
    trace_status: ev.trace_status,
    summary: ev.trace_status === 'ok' ? ev.trace.summary || null : null,
    has_snapshot: !!ev.has_snapshot,
    attribution: ev.attribution ?? null,
    label: conceptId ? labelSummary(st, conceptId, ev.clip_id) : null,
  }
}

export function traceText(tr) {
  if (!tr || tr.status !== 'ok') return null
  const lines = [`clip ${tr.clip_id} (${(tr.duration_ms / 1000).toFixed(1)} s) - ${tr.summary}`]
  lines.push('entities: ' + tr.entities.map((e) => `${e.id}:${e.type}${e.attrs.length ? `[${e.attrs.join(',')}]` : ''}`).join(' ') || 'none')
  for (const fr of tr.frames) {
    const facts = fr.facts.map((f) => `${f.pred}(${f.args.join(',')})@${f.conf}`).join(' ')
    lines.push(`t=${(fr.t_ms / 1000).toFixed(1)}s ${facts}`)
  }
  return lines.join('\n')
}

export function eventDetail(st, ev, conceptId = null) {
  return {
    ...eventSummary(st, ev, conceptId),
    trace: ev.trace_status === 'none' ? null : ev.trace,
    strong_trace: ev.strong_trace ?? null,
    trace_text: traceText(ev.trace_status === 'none' ? null : ev.trace),
  }
}

export function conceptView(st, c) {
  const counts = { example_pos: 0, example_neg: 0, active_pos: 0, active_neg: 0, random_pos: 0, random_neg: 0 }
  for (const l of st.labels.values()) if (l.concept_id === c.id) counts[`${l.provenance}_${l.value}`] += 1
  return {
    id: c.id,
    name: c.name,
    nl_hint: c.nl_hint ?? null,
    alpha: c.alpha,
    counts,
    deployed_rule_id: st.rules.find((r) => r.concept_id === c.id && r.status === 'deployed')?.id ?? null,
  }
}

// ------------------------------------------------------------------ rules
export function scoreFor(st, rule, ev) {
  const key = `${rule.id}|${ev.clip_id}|${rule.dsl_text}`
  let hit = st.scoreCache.get(key)
  if (!hit) {
    hit = scoreRule(rule.ast, ev.trace)
    st.scoreCache.set(key, hit)
  }
  return hit.score
}

const okEvents = (st) => st.events.filter((e) => e.trace_status === 'ok' && e.trace.frames.length)

function nodeCount(n) {
  let c = 1
  for (const k of ['arg', 'left', 'right']) if (n[k]) c += nodeCount(n[k])
  if (n.args && n.op !== 'atom') for (const a of n.args) c += nodeCount(a)
  return c
}

export function calibrationFor(st, rule) {
  const concept = st.concepts.find((c) => c.id === rule.concept_id)
  const alpha = concept.alpha
  const rn = []
  const rp = []
  for (const l of st.labels.values()) {
    if (l.concept_id !== rule.concept_id || l.provenance !== 'random') continue
    const ev = st.byClip.get(l.clip_id)
    if (!ev || ev.trace_status !== 'ok') continue
    const s = scoreFor(st, rule, ev)
    ;(l.value === 'neg' ? rn : rp).push(s)
  }
  const n = rn.length
  const need = Math.ceil(1 / alpha - 1e-9) - 1
  const k = Math.ceil((n + 1) * (1 - alpha) - 1e-9)
  const sorted = [...rn].sort((a, b) => a - b)
  const guarantee = n > 0 && k <= n
  // Fire only above max(0, tau_alpha): the rule must also be true in the plain boolean sense.
  const tau = guarantee ? Math.max(0, round3(sorted[k - 1])) : 0
  const hits = rp.filter((s) => s > tau).length
  return {
    alpha,
    n_random_neg: n,
    n_random_pos: rp.length,
    k: guarantee ? k : null,
    tau,
    guarantee,
    message: guarantee ? null : `guarantee needs ≥ ${need} random negatives (have ${n})`,
    delta: 0.1,
    recall: rp.length ? round3(hits / rp.length) : null,
    recall_ci95: rp.length ? clopperPearson(hits, rp.length) : null,
  }
}

export function ruleSummary(st, rule) {
  const violated = []
  let margin = Infinity
  for (const l of st.labels.values()) {
    if (l.concept_id !== rule.concept_id || l.provenance === 'random') continue
    const ev = st.byClip.get(l.clip_id)
    if (!ev || ev.trace_status !== 'ok') continue
    const s = scoreFor(st, rule, ev)
    const signed = l.value === 'pos' ? s : -s
    if (signed <= 0) violated.push(l.clip_id)
    else margin = Math.min(margin, signed)
  }
  const holes = Object.keys(rule.holes).length
  const mdl = nodeCount(rule.ast.body) + 1
  return {
    id: rule.id,
    concept_id: rule.concept_id,
    sketch_text: rule.sketch_text,
    dsl_text: rule.dsl_text,
    english: rule.english,
    ast: rule.ast,
    holes: rule.holes,
    margin: round3(Number.isFinite(margin) ? Math.min(margin, C) : 0),
    mdl: round3(mdl * 3 + 8 * holes + 10 * violated.length),
    violated_clip_ids: violated,
    status: rule.status,
    calibration: calibrationFor(st, rule),
    actions: rule.actions,
  }
}

export function rulesOf(st, conceptId) {
  const c = st.concepts.find((x) => x.id === conceptId)
  if (!c || !c.rules_ready) return []
  return st.rules
    .filter((r) => r.concept_id === conceptId && r.status !== 'retired')
    .map((r) => ruleSummary(st, r))
    .sort((a, b) => a.mdl - b.mdl || b.margin - a.margin)
}

export function witnessOf(st, rule, ev, tau) {
  return witnessFor(rule.ast, rule.id, ev.trace, rule.english, tau)
}

export function backtest(st, rule) {
  const cal = calibrationFor(st, rule)
  const rows = okEvents(st).map((ev) => {
    const score = round3(scoreFor(st, rule, ev))
    const matched = score > cal.tau
    return {
      clip_id: ev.clip_id,
      event: eventSummary(st, ev, rule.concept_id),
      score,
      matched,
      label: labelSummary(st, rule.concept_id, ev.clip_id),
      witness: score > 0 ? witnessOf(st, rule, ev, cal.tau) : null,
    }
  })
  rows.sort((a, b) => b.score - a.score)
  const counts = { tp: 0, fp: 0, fn: 0, tn: 0, unlabelled_matches: 0 }
  for (const r of rows) {
    if (!r.label) counts.unlabelled_matches += r.matched ? 1 : 0
    else if (r.label.value === 'pos') counts[r.matched ? 'tp' : 'fn'] += 1
    else counts[r.matched ? 'fp' : 'tn'] += 1
  }
  return { rule_id: rule.id, rows, calibration: cal, counts }
}

// ------------------------------------------------------------------ concepts
export function createConcept(st, { name, nl_hint = null, alpha = ALPHA }) {
  const id = `cn_${++st.seq.concept}_${Math.random().toString(36).slice(2, 6)}`
  const c = { id, name, nl_hint, alpha, rules_ready: false }
  st.concepts.push(c)
  return c
}

/** New concepts have no templates of their own: give them the package-theft candidates (mock only). */
function ensureRules(st, concept) {
  if (st.rules.some((r) => r.concept_id === concept.id)) return
  for (const t of ruleTemplates().filter((x) => x.concept_id === 'cn_theft')) {
    const id = `${t.id}_${++st.seq.rule}`
    st.rules.push({ ...t, id, concept_id: concept.id, dsl_text: ruleDslText(t.ast), status: 'candidate', actions: ['ui'] })
  }
}

// ------------------------------------------------------------------ questions
export function nextQuestion(st, conceptId) {
  const queue = QUESTIONS[conceptId] ?? (st.concepts.find((c) => c.id === conceptId)?.rules_ready ? QUESTIONS.cn_theft : [])
  const skipped = st.answered.get(conceptId) ?? new Set()
  for (const q of queue) {
    if (skipped.has(q.clip_id) || st.labels.has(`${conceptId}|${q.clip_id}`)) continue
    const ev = st.byClip.get(q.clip_id)
    if (!ev) continue
    return {
      concept_id: conceptId, clip_id: q.clip_id, event: eventSummary(st, ev, conceptId), p: q.p, committee_size: q.committee_size,
    }
  }
  return null
}

// ------------------------------------------------------------------ teach runs
const BAD_SKETCH = {
  cn_theft: ['exists p: Person, k: Package: picks_up(p, k) then[0, ?b] rings_doorbell(p)', "unknown predicate 'rings_doorbell' (did you mean 'rings_bell'?)"],
  cn_unattended: ['exists k: Package: holds_for >= ?d on_steps(k)', "unknown predicate 'on_steps' (did you mean 'in_zone'?)"],
  cn_vehicle: ['exists v: Vehicle: holds_for >= ?d moving(v)', "unknown predicate 'moving' (did you mean 'in_zone'?)"],
}

export function startRun(st, concept) {
  ensureRules(st, concept)
  const id = `run_${++st.seq.run}`
  const t0 = Date.now()
  const step = 380
  const rs = st.rules.filter((r) => r.concept_id === concept.id)
  const sums = rs.map((r) => ruleSummary(st, r))
  const bad = BAD_SKETCH[concept.id] ?? BAD_SKETCH.cn_theft
  const events = []
  const push = (type, extra = {}) =>
    events.push({ seq: events.length + 1, at_ms: t0 + (events.length + 1) * step, type, violated_clip_ids: [], rule_ids: [], ...extra })
  const solved = (i, round) => {
    const s = sums[i]
    const sketch = rs[i].sketch_text
    push('solve_started', { round, sketch })
    push('solve_result', { round, sketch, result: 'sat', holes: s.holes, margin: s.margin, violated_clip_ids: s.violated_clip_ids })
    push('differential_check', {
      round,
      message: `NumPy evaluator agrees: labels match and rho >= m - eps (m = ${s.margin.toFixed(2)})`,
    })
  }
  push('round_started', { round: 1, message: 'Sketching rules from the labelled examples' })
  push('sketch_proposed', { round: 1, sketch: bad[0] })
  push('typecheck_failed', { round: 1, sketch: bad[0], error: bad[1] })
  push('sketch_proposed', { round: 1, sketch: rs[0].sketch_text })
  solved(0, 1)
  if (sums[0].violated_clip_ids.length) {
    push('counterexample', {
      round: 1,
      violated_clip_ids: sums[0].violated_clip_ids,
      message: `${sums[0].violated_clip_ids.length} labelled example(s) violated: perception suspect?`,
    })
  }
  push('round_started', { round: 2, message: 'Revising sketches with the counterexample' })
  for (let i = 1; i < rs.length; i++) {
    push('sketch_proposed', { round: 2, sketch: rs[i].sketch_text })
    solved(i, 2)
  }
  const ranked = [...sums].sort((a, b) => a.mdl - b.mdl || b.margin - a.margin)
  push('candidates', { round: 2, rule_ids: ranked.map((r) => r.id), message: `${ranked.length} consistent candidates, ranked by MDL` })
  const candidatesAt = events[events.length - 1].at_ms
  const queue = QUESTIONS[concept.id] ?? QUESTIONS.cn_theft
  if (queue.some((q) => !st.labels.has(`${concept.id}|${q.clip_id}`) && !(st.answered.get(concept.id) ?? new Set()).has(q.clip_id))) {
    push('question_ready', { round: 2, message: 'The committee of rule variants disagrees most on one unlabelled clip' })
  }
  push('done', { round: 2 })
  const run = {
    id, concept_id: concept.id, started_at_ms: t0, events,
    finished_at_ms: events[events.length - 1].at_ms,
  }
  st.runs.set(id, run)
  setTimeout(() => { concept.rules_ready = true }, Math.max(0, candidatesAt - Date.now()))
  return run
}

export function runView(run) {
  const done = Date.now() >= run.finished_at_ms
  return {
    id: run.id,
    concept_id: run.concept_id,
    status: done ? 'done' : 'running',
    error: null,
    started_at_ms: run.started_at_ms,
    finished_at_ms: done ? run.finished_at_ms : null,
  }
}

export const isRunning = (st, conceptId) =>
  [...st.runs.values()].some((r) => r.concept_id === conceptId && Date.now() < r.finished_at_ms)

// ------------------------------------------------------------------ monitor helpers
export function recordFiring(st, f) {
  const firing = { id: `fi_${++st.seq.firing}`, created_at_ms: Date.now(), ...f }
  st.firings.unshift(firing)
  st.firings.length = Math.min(st.firings.length, 200)
  return firing
}

const PRICE = { fast: 0.0014, strong: 0.028 }
export function bumpCost(st, { dropped0 = 0, scored1 = 0, escalated2 = 0 }) {
  const c = st.cost
  c.events += 1
  c.stage0_dropped += dropped0
  c.stage1_scored += scored1
  c.stage2_escalated += escalated2
  c.tokens_in += scored1 * 6400 + escalated2 * 6200
  c.tokens_out += scored1 * 1400 + escalated2 * 1600
}

export function costView(st) {
  const c = st.cost
  const usd = c.stage1_scored * PRICE.fast + c.stage2_escalated * PRICE.strong
  return { ...c, usd_estimate: +usd.toFixed(4), per_event_usd: c.events ? +(usd / c.events).toFixed(5) : 0 }
}
