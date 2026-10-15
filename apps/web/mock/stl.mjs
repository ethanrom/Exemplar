// Mini STL evaluator + witness extractor for the mock engine (PLAN.md section 2.2 semantics).
//
// Only what the mock needs: robustness of a closed Rule AST on a Trace, on the discrete sample grid,
// with the clamp C = 0.5 and integer-ms offsets computed as (t_j - t_i) / 1000. The scores and
// witnesses the mock serves are therefore consistent with the fixture traces; they are NOT the
// reference implementation (that is stream C's evaluator).

export const C = 0.5
export const THRESHOLD = 0.5
export const CONF = { low: 0.6, med: 0.8, high: 0.95 }
export const ABSENT = 0.05

const VAR_TYPES = {
  Entity: ['person', 'vehicle', 'package', 'animal', 'object'],
  Person: ['person'],
  Vehicle: ['vehicle'],
  Package: ['package'],
  Animal: ['animal'],
  Object: ['object'],
  Carryable: ['package', 'object'],
}

/** s_pred(args)(t_i) for every frame (PLAN 2.1.5). */
export function signal(trace, pred, args) {
  const n = trace.frames.length
  const s = new Array(n).fill(ABSENT)
  let floor = ABSENT
  if (pred === 'attr' && args.length === 2) {
    const ent = trace.entities.find((e) => e.id === args[0])
    if (ent && ent.attrs.includes(args[1])) floor = CONF.med
  }
  trace.frames.forEach((fr, i) => {
    for (const f of fr.facts) {
      if (f.pred === pred && f.args.length === args.length && f.args.every((a, k) => a === args[k])) {
        s[i] = Math.max(s[i], CONF[f.conf])
      } else if (pred === 'present' && args.length === 1 && f.args.includes(args[0])) {
        s[i] = Math.max(s[i], CONF[f.conf])
      }
    }
  })
  return s.map((v) => Math.max(v, floor))
}

function bindingsFor(trace, vars) {
  const pools = vars.map((v) => trace.entities.filter((e) => VAR_TYPES[v.type].includes(e.type)).map((e) => e.id))
  let acc = [[]]
  for (const pool of pools) {
    const next = []
    for (const a of acc) for (const id of pool) if (!a.includes(id)) next.push([...a, id])
    acc = next
  }
  return acc
}

const off = (t, i, j) => (t[j] - t[i]) / 1000

function ctxRho(trace, c) {
  const ctx = trace.context || {}
  if (c.op === 'hour_in') {
    if (ctx.local_hour == null) return -C
    const h = ctx.local_hour
    const ok = c.h1 <= c.h2 ? h >= c.h1 && h <= c.h2 : h >= c.h1 || h <= c.h2
    return ok ? C : -C
  }
  if (c.op === 'subtype_eq') return ctx.sub_type === c.value ? C : -C
  if (c.op === 'device_eq') return ctx.device_id === c.value ? C : -C
  return -C
}

/** rho of `node` for every grid index under a variable binding. */
function rho(node, tr, t, bind) {
  const n = t.length
  switch (node.op) {
    case 'atom': {
      const args = node.args.map((a) => bind[a] ?? a)
      return signal(tr, node.pred, args).map((v) => v - THRESHOLD)
    }
    case 'not':
      return rho(node.arg, tr, t, bind).map((v) => -v)
    case 'and': {
      const parts = node.args.map((a) => rho(a, tr, t, bind))
      return Array.from({ length: n }, (_, i) => Math.min(...parts.map((p) => p[i])))
    }
    case 'or': {
      const parts = node.args.map((a) => rho(a, tr, t, bind))
      return Array.from({ length: n }, (_, i) => Math.max(...parts.map((p) => p[i])))
    }
    case 'eventually':
    case 'always': {
      const r = rho(node.arg, tr, t, bind)
      const pick = node.op === 'eventually' ? Math.max : Math.min
      return Array.from({ length: n }, (_, i) => {
        let best = null
        for (let j = i; j < n; j++) {
          const d = off(t, i, j)
          if (d >= node.a && d <= node.b) best = best === null ? r[j] : pick(best, r[j])
        }
        return best === null ? -C : best
      })
    }
    case 'then': {
      const l = rho(node.left, tr, t, bind)
      const r = rho(node.right, tr, t, bind)
      const inner = Array.from({ length: n }, (_, i1) => {
        let best = -C
        let seen = false
        for (let j = i1; j < n; j++) {
          const d = off(t, i1, j)
          if (d >= node.a && d <= node.b) {
            best = seen ? Math.max(best, r[j]) : r[j]
            seen = true
          }
        }
        return seen ? best : -C
      })
      const comb = l.map((v, i1) => Math.min(v, inner[i1]))
      return Array.from({ length: n }, (_, i) => Math.max(...comb.slice(i)))
    }
    case 'holds_for': {
      const r = rho(node.arg, tr, t, bind)
      const tEnd = t[n - 1]
      const per = Array.from({ length: n }, (_, i1) => {
        if (t[i1] + node.d * 1000 > tEnd) return null
        let m = Infinity
        for (let j = i1; j < n; j++) if (off(t, i1, j) <= node.d) m = Math.min(m, r[j])
        return m
      })
      return Array.from({ length: n }, (_, i) => {
        const vals = per.slice(i).filter((v) => v !== null)
        return vals.length ? Math.max(...vals) : -C
      })
    }
    default:
      throw new Error(`stl: unsupported op ${node.op}`)
  }
}

/** Clip score of a closed Rule: max over bindings and t of rho(body) (ctx atoms combined with min). */
export function scoreRule(rule, tr) {
  const t = tr.frames.map((f) => f.t_ms)
  if (!t.length) return { score: -C, binding: null, index: 0 }
  const ctx = (rule.when || []).map((c) => ctxRho(tr, c))
  let best = { score: -C, binding: null, index: 0 }
  for (const ids of bindingsFor(tr, rule.vars)) {
    const bind = Object.fromEntries(rule.vars.map((v, k) => [v.name, ids[k]]))
    const r = rho(rule.body, tr, t, bind)
    r.forEach((v, i) => {
      const s = Math.min(v, ...ctx)
      if (s > best.score || best.binding === null) best = { score: s, binding: bind, index: i }
    })
  }
  return best
}

// ---------------------------------------------------------------- text of subformulas (mock printer)
const num = (x) => (Number.isInteger(x) ? String(x) : String(x))
export function dslText(node) {
  switch (node.op) {
    case 'atom': return `${node.pred}(${node.args.join(', ')})`
    case 'not': return `not ${wrap(node.arg)}`
    case 'and': return node.args.map(wrap).join(' and ')
    case 'or': return node.args.map(wrap).join(' or ')
    case 'eventually': return `eventually[${num(node.a)}, ${num(node.b)}] ${wrap(node.arg)}`
    case 'always': return `always[${num(node.a)}, ${num(node.b)}] ${wrap(node.arg)}`
    case 'then': return `${wrap(node.left)} then[${num(node.a)}, ${num(node.b)}] ${wrap(node.right)}`
    case 'holds_for': return `holds_for >= ${num(node.d)} ${wrap(node.arg)}`
    default: return '?'
  }
}
function wrap(node) {
  const s = dslText(node)
  return ['and', 'or', 'then'].includes(node.op) ? `(${s})` : s
}
export function ruleDslText(rule) {
  const vars = rule.vars.map((v) => `${v.name}: ${v.type}`).join(', ')
  let s = `exists ${vars}: ${dslText(rule.body)}`
  if (rule.when && rule.when.length) {
    s += ' when ' + rule.when.map((c) =>
      c.op === 'hour_in' ? `hour in [${c.h1}, ${c.h2}]` : c.op === 'subtype_eq' ? `subtype = ${c.value}` : `device = ${c.value}`).join(' and ')
  }
  return s
}

// ---------------------------------------------------------------- witness
function explain(node, tr, t, bind, i, path, out) {
  const r = rho(node, tr, t, bind)
  const here = r[i]
  const row = (op, a, b, rhoVal = here) =>
    out.push({ path, op, text: dslText(substitute(node, bind)), t_start_ms: a, t_end_ms: b, rho: round(rhoVal) })
  switch (node.op) {
    case 'atom':
      row('atom', t[i], t[i])
      return
    case 'not':
      explain(node.arg, tr, t, bind, i, path ? `${path}.arg` : 'body.arg', out)
      return
    case 'and':
    case 'or':
      node.args.forEach((a, k) => explain(a, tr, t, bind, i, `${path}.args[${k}]`, out))
      return
    case 'eventually':
    case 'always': {
      const rc = rho(node.arg, tr, t, bind)
      let jBest = i
      let seen = false
      for (let j = i; j < t.length; j++) {
        const d = off(t, i, j)
        if (d < node.a || d > node.b) continue
        const better = node.op === 'eventually' ? rc[j] > rc[jBest] : rc[j] < rc[jBest]
        if (!seen || better) jBest = j
        seen = true
      }
      row(node.op, t[i], t[jBest])
      explain(node.arg, tr, t, bind, jBest, `${path}.arg`, out)
      return
    }
    case 'then': {
      const l = rho(node.left, tr, t, bind)
      const rr = rho(node.right, tr, t, bind)
      let best = { v: -Infinity, i1: i, j: i }
      for (let i1 = i; i1 < t.length; i1++) {
        let jb = null
        for (let j = i1; j < t.length; j++) {
          const d = off(t, i1, j)
          if (d >= node.a && d <= node.b && (jb === null || rr[j] > rr[jb])) jb = j
        }
        if (jb === null) continue
        const v = Math.min(l[i1], rr[jb])
        if (v > best.v) best = { v, i1, j: jb }
      }
      row('then', t[best.i1], t[best.j])
      explain(node.left, tr, t, bind, best.i1, `${path}.left`, out)
      explain(node.right, tr, t, bind, best.j, `${path}.right`, out)
      return
    }
    case 'holds_for': {
      const rc = rho(node.arg, tr, t, bind)
      let best = { v: -Infinity, i1: i }
      for (let i1 = i; i1 < t.length; i1++) {
        if (t[i1] + node.d * 1000 > t[t.length - 1]) continue
        let m = Infinity
        for (let j = i1; j < t.length; j++) if (off(t, i1, j) <= node.d) m = Math.min(m, rc[j])
        if (m > best.v) best = { v: m, i1 }
      }
      row('holds_for', t[best.i1], Math.round(t[best.i1] + node.d * 1000))
      // critical (weakest) point inside the window
      let jc = best.i1
      for (let j = best.i1; j < t.length; j++) if (off(t, best.i1, j) <= node.d && rc[j] < rc[jc]) jc = j
      explain(node.arg, tr, t, bind, jc, `${path}.arg`, out)
      return
    }
    default:
  }
}

const round = (x) => Math.round(x * 1000) / 1000

function substitute(node, bind) {
  const sub = (n) => {
    if (n.op === 'atom') return { ...n, args: n.args.map((a) => bind[a] ?? a) }
    const c = { ...n }
    if (n.arg) c.arg = sub(n.arg)
    if (n.args) c.args = n.args.map(sub)
    if (n.left) c.left = sub(n.left)
    if (n.right) c.right = sub(n.right)
    return c
  }
  return sub(node)
}

/** Witness (api.yaml Witness) for a rule on a trace, or null when no binding exists. */
export function witnessFor(rule, ruleId, tr, englishRule, tau) {
  const s = scoreRule(rule, tr)
  if (!s.binding) return null
  const t = tr.frames.map((f) => f.t_ms)
  const spans = []
  explain(rule.body, tr, t, s.binding, s.index, 'body', spans)
  const entities = Object.values(s.binding).map((id) => tr.entities.find((e) => e.id === id)).filter(Boolean)
  let english = englishRule
  for (const [v, id] of Object.entries(s.binding)) english = english.replace(new RegExp(`\\b${v}\\b`, 'g'), id)
  return {
    rule_id: ruleId,
    clip_id: tr.clip_id,
    score: round(s.score),
    tau: round(tau),
    margin: round(s.score - tau),
    bindings: s.binding,
    entities,
    spans,
    english,
  }
}
