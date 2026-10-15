// Mock Exemplar engine (stream F). Implements every path in engine/exemplar/contracts/api.yaml with
// realistic in-memory data so the UI can be built and reviewed without the real engine.
//
//   node mock/server.mjs            # http://127.0.0.1:8787  (PORT / HOST override)
//   MOCK_VALIDATE=0 node ...        # skip response validation against api.yaml
//   MOCK_TOKEN_MINUTES=30 node ...  # initial Playground token lifetime (default 6, to show the warning)
//
// Mock-only helpers (not part of the contract): POST /__mock/reset, POST /__mock/trigger?kind=
// package|vehicle|motion|human. Paste the token "short" on Connect to get a 3 minute token.
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { execFile } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { sceneSvg } from './scenes.mjs'
import { FROLLARD_ATTRIBUTION, DEVICE_ID, uploadWindowTrace } from './data.mjs'
import {
  backtest, bumpCost, conceptView, costView, createConcept, createStore, eventDetail, eventSummary,
  isRunning, labelSummary, nextQuestion, recordFiring, ruleSummary, rulesOf, runView, scoreFor, startRun, witnessOf,
  calibrationFor,
} from './logic.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const WEIGHT = { example: 3, active: 3, random: 1 }

// ------------------------------------------------------------------ placeholder MP4 (best effort)
function findFfmpeg() {
  if (process.env.FFMPEG) return process.env.FFMPEG
  const bin = path.resolve(HERE, '../../../engine/.venv/Lib/site-packages/imageio_ffmpeg/binaries')
  if (fs.existsSync(bin)) {
    const f = fs.readdirSync(bin).find((n) => n.startsWith('ffmpeg'))
    if (f) return path.join(bin, f)
  }
  return 'ffmpeg'
}

function ensurePlaceholderMp4() {
  const dir = path.join(HERE, '.cache')
  const file = path.join(dir, 'placeholder.mp4')
  fs.mkdirSync(dir, { recursive: true })
  if (fs.existsSync(file)) return Promise.resolve(file)
  const args = [
    '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=0x1e293b:s=640x360:r=15:d=6',
    '-vf', "drawbox=x='40+t*80':y=200:w=60:h=60:color=0x22d3ee:t=fill,drawbox=x=0:y=300:w=640:h=60:color=0x334155:t=fill",
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', file,
  ]
  return new Promise((resolve) => {
    execFile(findFfmpeg(), args, (err) => resolve(err || !fs.existsSync(file) ? null : file))
  })
}

// ------------------------------------------------------------------ app
export async function createApp({ validate = process.env.MOCK_VALIDATE !== '0' } = {}) {
  let st = createStore()
  const tokenMin = Number(process.env.MOCK_TOKEN_MINUTES || 6)
  st.auth.expires_at_ms = Date.now() + tokenMin * 60_000
  st.auth.issued_at_ms = Date.now() - (30 - tokenMin) * 60_000

  let contract = null
  if (validate) {
    try {
      contract = await (await import('./contract.mjs')).loadContract()
    } catch (err) {
      console.warn(`[mock] contract validation disabled: ${err.message}`)
    }
  }
  const violations = []
  const coverage = new Set()
  const violation = (where, errs) => {
    const msg = `${where}: ${errs.join('; ')}`
    violations.push(msg)
    console.warn(`[mock] CONTRACT VIOLATION ${msg}`)
  }
  let mp4 = null
  ensurePlaceholderMp4().then((f) => { mp4 = f })

  // -------------------------------------------------------------- routing
  const routes = []
  const route = (method, template, handler) => {
    const keys = []
    const re = new RegExp(
      '^' + template.replace(/:([a-z_]+)/g, (_, k) => { keys.push(k); return '([^/]+)' }) + '/?$',
    )
    routes.push({ method, re, keys, handler, apiPath: template.replace(/:([a-z_]+)/g, '{$1}') })
  }

  const baseHeaders = { 'access-control-allow-origin': '*', 'cache-control': 'no-store' }
  function sendJson(res, r, status, body) {
    if (contract && r && !r.apiPath.startsWith('/__mock')) {
      const errs = contract.validateResponse(r.method, r.apiPath, status, body)
      if (errs.length) violation(`${r.method} ${r.apiPath} -> ${status}`, errs)
      coverage.add(`${r.method} ${r.apiPath}`)
    }
    res.writeHead(status, { ...baseHeaders, 'content-type': 'application/json' })
    res.end(JSON.stringify(body))
  }
  const sendErr = (res, r, status, error, code = null) => sendJson(res, r, status, { error, code })

  function readBody(req, limit = 800 * 1024 * 1024) {
    return new Promise((resolve, reject) => {
      const chunks = []
      let n = 0
      req.on('data', (c) => {
        n += c.length
        if (n > limit) { reject(new Error('body too large')); req.destroy() } else chunks.push(c)
      })
      req.on('end', () => resolve(Buffer.concat(chunks)))
      req.on('error', reject)
    })
  }
  async function readJson(req) {
    const buf = await readBody(req)
    if (!buf.length) return {}
    return JSON.parse(buf.toString('utf8'))
  }

  /** Minimal multipart/form-data text-field extraction (files are skipped). */
  function multipartFields(buf, contentType) {
    const m = /boundary=(?:"([^"]+)"|([^;]+))/.exec(contentType || '')
    const out = {}
    if (!m) return out
    const boundary = Buffer.from('--' + (m[1] || m[2]))
    let pos = buf.indexOf(boundary)
    while (pos !== -1) {
      const next = buf.indexOf(boundary, pos + boundary.length)
      if (next === -1) break
      const part = buf.subarray(pos + boundary.length, next)
      const headEnd = part.indexOf('\r\n\r\n')
      if (headEnd !== -1) {
        const head = part.subarray(0, headEnd).toString('utf8')
        const name = /name="([^"]+)"/.exec(head)?.[1]
        if (name && !/filename=/.test(head)) out[name] = part.subarray(headEnd + 4, part.length - 2).toString('utf8')
      }
      pos = next
    }
    return out
  }

  // -------------------------------------------------------------- SSE
  function openSse(req, res, r, schemaName) {
    res.writeHead(200, {
      ...baseHeaders,
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-cache, no-transform',
      connection: 'keep-alive',
      'x-accel-buffering': 'no',
    })
    res.write('retry: 2000\n\n')
    const ping = setInterval(() => res.write('event: ping\ndata: {}\n\n'), 15_000)
    const client = {
      res,
      send(type, data, id) {
        if (contract && schemaName) {
          const errs = contract.validateComponent(schemaName, data)
          if (errs.length) violation(`SSE ${schemaName}.${type}`, errs)
        }
        res.write(`${id != null ? `id: ${id}\n` : ''}event: ${type}\ndata: ${JSON.stringify(data)}\n\n`)
      },
      close() { clearInterval(ping); res.end() },
    }
    req.on('close', () => { clearInterval(ping); client.closed = true; client.onClose?.() })
    if (r) coverage.add(`${r.method} ${r.apiPath}`)
    return client
  }

  // -------------------------------------------------------------- monitor hub (scripted deployed-rule monitoring)
  const hub = { clients: new Set(), busy: false, running: false, eventId: 0, current: null }
  const broadcast = (type, data) => {
    const frame = { type, at_ms: Date.now(), event_id: null, rule_id: null, ...data }
    const id = ++hub.eventId
    for (const c of hub.clients) c.send(type, frame, id)
    return frame
  }

  const SCENARIOS = {
    package: { fixture: 'pg_package_a', kind: 'on_demand', sub_type: null, label: 'Playground simulation: package' },
    vehicle: { fixture: 'pg_vehicle_a', kind: 'on_demand', sub_type: null, label: 'Playground simulation: vehicle' },
    motion: { fixture: 'pg_motion_a', kind: 'on_demand', sub_type: null, label: 'Playground simulation: motion' },
    human: { fixture: 'ring_pkg_taken', kind: 'motion', sub_type: 'human', label: 'Signed webhook: motion.human' },
  }
  const ORDER = ['package', 'vehicle', 'motion', 'human']
  let scenarioN = 0

  const deployedRules = () => st.rules.filter((r) => r.status === 'deployed')
  const needType = (rule) => rule.ast.vars[0].type.toLowerCase()
  const SUB_IMPOSSIBLE = {
    vehicle: ['person', 'package'],
    human: ['vehicle'],
    package_delivery: ['vehicle'],
    other_motion: ['vehicle', 'package'],
  }

  async function runScenario(kind) {
    const spec = SCENARIOS[kind]
    const base = st.byClip.get(spec.fixture)
    if (!base) return
    const n = ++scenarioN
    const clipId = `live_${kind}_${n}`
    const ev = {
      ...base,
      id: `ev_${clipId}`, clip_id: clipId, kind: spec.kind, sub_type: spec.sub_type, start_ms: Date.now(),
      clip_status: 'pending', trace_status: 'none', attribution: null,
      trace: { ...JSON.parse(JSON.stringify(base.trace)), clip_id: clipId },
    }
    ev.trace.context.sub_type = spec.sub_type
    ev.trace.context.event_kind = spec.kind
    st.events.unshift(ev)
    st.byId.set(ev.id, ev)
    st.byClip.set(ev.clip_id, ev)
    hub.current = { trace: ev.trace, t0: Date.now(), span: 14_000 }

    broadcast('event_ingested', { event_id: ev.id, message: spec.label })
    await sleep(700)
    ev.clip_status = 'ready'
    broadcast('clip_ready', { event_id: ev.id })
    await sleep(900)
    ev.trace_status = 'ok'
    broadcast('trace_ready', { event_id: ev.id, message: ev.trace.summary })

    let perception = 0
    let escalated = 0
    let dropped0 = 0
    const rules = deployedRules()
    for (const rule of rules) {
      await sleep(600)
      const cal = calibrationFor(st, rule)
      const impossible = SUB_IMPOSSIBLE[ev.sub_type] || []
      if (ev.sub_type && impossible.includes(needType(rule))) {
        dropped0 += 1
        const firing = recordFiring(st, { rule_id: rule.id, event_id: ev.id, stage: 0, score: null, tau: null, fired: false, witness: null, actions: [] })
        broadcast('rule_dropped', { event_id: ev.id, rule_id: rule.id, firing, message: `Stage 0: sub_type ${ev.sub_type} cannot contain a ${needType(rule)}` })
        continue
      }
      perception = 1
      let score = scoreFor(st, rule, ev)
      let stage = 1
      if (Math.abs(score - cal.tau) <= cal.delta && score > 0) {
        escalated = 1
        broadcast('escalated', { event_id: ev.id, rule_id: rule.id, message: `score ${score.toFixed(2)} is within ${cal.delta} of tau ${cal.tau.toFixed(2)}: re-checking with the strong model` })
        await sleep(1500)
        score = Math.round((score - 0.03) * 1000) / 1000
        stage = 2
      }
      if (score > cal.tau) {
        const witness = witnessOf(st, rule, ev, cal.tau)
        const actions = rule.actions.map((a) => {
          if (a === 'ui') return { action: 'ui', status: 'ok', detail: 'Notification shown on the Live screen' }
          if (a === 'chime') return { action: 'chime', status: 'skipped', detail: 'Chime playback is behind a flag (early access)' }
          if (a === 'slack') return { action: 'slack', status: 'skipped', detail: 'No Slack webhook configured' }
          return { action: a, status: 'skipped', detail: 'No webhook_out URL configured' }
        })
        const firing = recordFiring(st, { rule_id: rule.id, event_id: ev.id, stage, score, tau: cal.tau, fired: true, witness, actions })
        broadcast('rule_fired', { event_id: ev.id, rule_id: rule.id, firing, message: witness.english })
        for (const a of actions) {
          await sleep(250)
          broadcast('action_result', { event_id: ev.id, rule_id: rule.id, firing, message: `${a.action}: ${a.status}${a.detail ? ` - ${a.detail}` : ''}` })
        }
      } else {
        const firing = recordFiring(st, { rule_id: rule.id, event_id: ev.id, stage, score, tau: cal.tau, fired: false, witness: null, actions: [] })
        broadcast('rule_dropped', { event_id: ev.id, rule_id: rule.id, firing, message: `Stage ${stage}: score ${score.toFixed(2)} did not exceed tau ${cal.tau.toFixed(2)}` })
      }
    }
    bumpCost(st, { dropped0: dropped0 === rules.length && rules.length ? 1 : 0, scored1: perception, escalated2: escalated })
    await sleep(300)
    broadcast('cost_update', { event_id: ev.id, cost: costView(st) })
  }

  async function hubLoop() {
    if (hub.running) return
    hub.running = true
    let i = 0
    await sleep(1500)
    while (hub.clients.size) {
      if (!hub.busy) {
        hub.busy = true
        try { await runScenario(ORDER[i++ % ORDER.length]) } finally { hub.busy = false }
      }
      for (let k = 0; k < 90 && hub.clients.size; k++) await sleep(100)
    }
    hub.running = false
  }

  // live_facts ticker + auth_expiring watcher
  setInterval(() => {
    if (!hub.clients.size) return
    const cur = hub.current
    const frames = cur?.trace.frames ?? []
    const elapsed = cur ? Date.now() - cur.t0 : 0
    const scaled = cur ? (elapsed / cur.span) * cur.trace.duration_ms : 0
    let facts = []
    if (cur && elapsed < cur.span + 4000) {
      const upto = frames.filter((f) => f.t_ms <= scaled)
      const last = upto[upto.length - 1]
      if (last) facts = last.facts.map((f) => ({ t_ms: Math.round(elapsed), pred: f.pred, args: f.args, conf: f.conf }))
    }
    broadcast('live_facts', { facts, message: facts.length ? null : 'No entities in view' })
  }, 1100)
  let lastExpiring = 0
  setInterval(() => {
    if (!hub.clients.size || !st.auth.expires_at_ms) return
    const left = st.auth.expires_at_ms - Date.now()
    if (left <= 5 * 60_000 && Date.now() - lastExpiring > 25_000) {
      lastExpiring = Date.now()
      const m = Math.max(0, Math.round(left / 60_000))
      broadcast('auth_expiring', { message: left > 0 ? `Playground token expires in ${m} min: paste a fresh one on Connect` : 'Playground token expired: paste a fresh one on Connect' })
    }
  }, 5000)

  // -------------------------------------------------------------- handlers
  const concept = (id) => st.concepts.find((c) => c.id === id)
  const authView = () => {
    const a = st.auth
    const expired = a.expires_at_ms != null && a.expires_at_ms <= Date.now()
    return { mode: a.mode, connected: !!a.connected && !expired, expires_at_ms: a.expires_at_ms, issued_at_ms: a.issued_at_ms ?? null, user_name: a.user_name ?? null }
  }

  route('GET', '/health', ({ res, r }) => sendJson(res, r, 200, { ok: true, version: 'mock-1.0.0' }))

  route('GET', '/ring/auth', ({ res, r }) => sendJson(res, r, 200, authView()))
  route('PUT', '/ring/auth', async ({ req, res, r }) => {
    const body = await readJson(req).catch(() => ({}))
    const token = typeof body.access_token === 'string' ? body.access_token.trim() : ''
    if (!token) return sendErr(res, r, 400, 'access_token is required', 'INVALID_PAYLOAD')
    const mins = token.toLowerCase().startsWith('short') ? 3 : 30
    st.auth = { mode: 'playground', connected: true, expires_at_ms: Date.now() + mins * 60_000, issued_at_ms: Date.now(), user_name: 'Playground User' }
    lastExpiring = 0
    sendJson(res, r, 200, authView())
  })
  route('GET', '/ring/oauth/start', ({ res, r }) => {
    st.auth = { mode: 'oauth', connected: true, expires_at_ms: null, issued_at_ms: Date.now(), user_name: 'Ring account (mock)' }
    coverage.add(`${r.method} ${r.apiPath}`)
    res.writeHead(302, { ...baseHeaders, location: '/connect?oauth=ok' })
    res.end()
  })
  route('GET', '/ring/oauth/callback', ({ res, r, query }) => {
    coverage.add(`${r.method} ${r.apiPath}`)
    if (!query.get('code')) return sendErr(res, r, 400, 'code is required', 'INVALID_PAYLOAD')
    res.writeHead(302, { ...baseHeaders, location: '/connect?oauth=ok' })
    res.end()
  })
  route('GET', '/ring/devices', ({ res, r }) => {
    if (!authView().connected) return sendErr(res, r, 401, 'Ring token missing or expired', 'TOKEN_EXPIRED')
    sendJson(res, r, 200, [{
      id: DEVICE_ID, name: 'Playground Device', online: true, image_url: 'https://app-content.ring.com/shared/images/devices/square_device_images/DoorbellPro/rvdp_3x.png', codecs: ['h264'], snapshot: true, chime: false,
    }])
  })
  route('POST', '/ring/sync', ({ res, r }) => {
    const kinds = ['package', 'vehicle', 'motion']
    const spec = SCENARIOS[kinds[st.seq.event++ % kinds.length]]
    const base = st.byClip.get(spec.fixture)
    const n = ++scenarioN
    const clipId = `pg_sync_${n}`
    const ev = {
      ...base, id: `ev_${clipId}`, clip_id: clipId, start_ms: Date.now() - 30_000, clip_status: 'pending', trace_status: 'none',
      trace: { ...JSON.parse(JSON.stringify(base.trace)), clip_id: clipId },
    }
    st.events.unshift(ev); st.byId.set(ev.id, ev); st.byClip.set(clipId, ev)
    setTimeout(() => { ev.clip_status = 'downloading' }, 800)
    setTimeout(() => { ev.clip_status = 'ready' }, 2500)
    setTimeout(() => { ev.trace_status = 'ok' }, 5000)
    sendJson(res, r, 202, { new_events: 1 })
  })
  const seenWebhooks = new Set()
  route('POST', '/ring/webhook-events', async ({ req, res, r }) => {
    const body = await readJson(req).catch(() => null)
    const rid = body?.meta?.request_id
    if (!rid) return sendErr(res, r, 400, 'meta.request_id is required', 'INVALID_PAYLOAD')
    if (seenWebhooks.has(rid)) { coverage.add(`${r.method} ${r.apiPath}`); res.writeHead(409, baseHeaders); return res.end() }
    seenWebhooks.add(rid)
    coverage.add(`${r.method} ${r.apiPath}`)
    res.writeHead(202, baseHeaders)
    res.end()
    if (body.data?.type === 'motion_detected' && !hub.busy) {
      hub.busy = true
      runScenario(body.data.subType === 'vehicle' ? 'vehicle' : 'human').finally(() => { hub.busy = false })
    }
  })

  // ---- library
  route('POST', '/uploads', async ({ req, res, r }) => {
    const buf = await readBody(req).catch(() => null)
    if (!buf) return sendErr(res, r, 400, 'upload too large for the mock', 'INVALID_PAYLOAD')
    const f = multipartFields(buf, req.headers['content-type'])
    if (!f.attribution) return sendErr(res, r, 400, 'attribution is required', 'INVALID_PAYLOAD')
    const win = Math.max(2, Number(f.window_s) || 20)
    const stride = Math.max(1, Number(f.stride_s) || 10)
    const total = 60
    const count = Math.max(1, Math.min(12, Math.floor((total - win) / stride) + 1))
    const up = ++st.seq.event
    const out = []
    for (let i = 0; i < count; i++) {
      const clipId = `upload_${up}_w${String(i).padStart(2, '0')}`
      const tr = uploadWindowTrace(i, clipId)
      const ev = {
        id: `ev_${clipId}`, clip_id: clipId, source: 'upload', kind: 'upload', device_id: null, sub_type: null,
        start_ms: Date.now() + i * stride * 1000 - total * 1000, duration_ms: Math.max(win * 1000, tr.duration_ms),
        clip_status: 'ready', trace_status: 'none', has_snapshot: true, attribution: f.attribution, trace: tr, strong_trace: null,
      }
      st.events.unshift(ev); st.byId.set(ev.id, ev); st.byClip.set(clipId, ev)
      setTimeout(() => { ev.trace_status = 'ok' }, 1500 + i * 700)
      out.push(eventSummary(st, ev))
    }
    st.events.sort((a, b) => b.start_ms - a.start_ms)
    sendJson(res, r, 202, out)
  })

  route('GET', '/events', ({ res, r, query }) => {
    const cid = query.get('concept_id')
    const source = query.get('source')
    const labelled = query.get('labelled') || 'any'
    const limit = Math.min(500, Number(query.get('limit')) || 100)
    const offset = Number(query.get('cursor')) || 0
    let list = st.events
    if (source) list = list.filter((e) => e.source === source)
    if (cid && labelled !== 'any') {
      list = list.filter((e) => {
        const l = st.labels.get(`${cid}|${e.clip_id}`)
        return labelled === 'unlabelled' ? !l : l?.value === labelled
      })
    }
    const page = list.slice(offset, offset + limit)
    const next = offset + limit < list.length ? String(offset + limit) : null
    sendJson(res, r, 200, { items: page.map((e) => eventSummary(st, e, cid)), next_cursor: next })
  })
  route('GET', '/events/:event_id', ({ res, r, params, query }) => {
    const ev = st.byId.get(params.event_id)
    if (!ev) return sendErr(res, r, 404, `event ${params.event_id} not found`, 'NOT_FOUND')
    sendJson(res, r, 200, eventDetail(st, ev, query.get('concept_id')))
  })
  route('GET', '/events/:event_id/snapshot', ({ res, r, params }) => {
    coverage.add(`${r.method} ${r.apiPath}`)
    const ev = st.byId.get(params.event_id)
    if (!ev || !ev.has_snapshot) return sendErr(res, r, 404, 'no snapshot', 'NOT_FOUND')
    res.writeHead(200, { ...baseHeaders, 'content-type': 'image/svg+xml', 'cache-control': 'public, max-age=300' })
    res.end(sceneSvg(ev, ev.trace_status === 'ok' ? ev.trace : null))
  })
  route('GET', '/events/:event_id/clip', ({ req, res, r, params }) => {
    coverage.add(`${r.method} ${r.apiPath}`)
    const ev = st.byId.get(params.event_id)
    if (!ev || ev.clip_status !== 'ready') return sendErr(res, r, 404, 'clip not available', 'NOT_FOUND')
    if (!mp4) return sendErr(res, r, 404, 'the mock has no ffmpeg to generate a placeholder clip', 'NOT_FOUND')
    const size = fs.statSync(mp4).size
    const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range || '')
    if (range) {
      const start = range[1] ? Number(range[1]) : 0
      const end = range[2] ? Math.min(Number(range[2]), size - 1) : size - 1
      res.writeHead(206, { ...baseHeaders, 'content-type': 'video/mp4', 'accept-ranges': 'bytes', 'content-range': `bytes ${start}-${end}/${size}`, 'content-length': end - start + 1 })
      return fs.createReadStream(mp4, { start, end }).pipe(res)
    }
    res.writeHead(200, { ...baseHeaders, 'content-type': 'video/mp4', 'accept-ranges': 'bytes', 'content-length': size })
    fs.createReadStream(mp4).pipe(res)
  })

  // ---- concepts / labels / teach
  route('GET', '/concepts', ({ res, r }) => sendJson(res, r, 200, st.concepts.map((c) => conceptView(st, c))))
  route('POST', '/concepts', async ({ req, res, r }) => {
    const body = await readJson(req).catch(() => ({}))
    if (!body.name || !String(body.name).trim()) return sendErr(res, r, 400, 'name is required', 'INVALID_PAYLOAD')
    const alpha = body.alpha ?? 0.1
    if (!(alpha > 0 && alpha < 1)) return sendErr(res, r, 400, 'alpha must be in (0, 1)', 'INVALID_PAYLOAD')
    sendJson(res, r, 201, conceptView(st, createConcept(st, { name: String(body.name).trim(), nl_hint: body.nl_hint ?? null, alpha })))
  })
  route('GET', '/concepts/:concept_id/labels', ({ res, r, params }) => {
    if (!concept(params.concept_id)) return sendErr(res, r, 404, 'concept not found', 'NOT_FOUND')
    const out = []
    for (const l of st.labels.values()) if (l.concept_id === params.concept_id) {
      out.push({ concept_id: l.concept_id, clip_id: l.clip_id, value: l.value, provenance: l.provenance, weight: l.weight, created_at: l.created_at })
    }
    sendJson(res, r, 200, out)
  })
  const summaryFor = (cid) => ({ concept: cid })
  route('PUT', '/concepts/:concept_id/labels', async ({ req, res, r, params }) => {
    const cid = params.concept_id
    if (!concept(cid)) return sendErr(res, r, 404, 'concept not found', 'NOT_FOUND')
    const b = await readJson(req).catch(() => ({}))
    if (!b.clip_id || !['example', 'active', 'random'].includes(b.provenance) || ![null, 'pos', 'neg'].includes(b.value ?? null)) {
      return sendErr(res, r, 400, 'clip_id, value (pos|neg|null) and provenance are required', 'INVALID_PAYLOAD')
    }
    if (!st.byClip.has(b.clip_id)) return sendErr(res, r, 404, `clip ${b.clip_id} not found`, 'NOT_FOUND')
    if (b.provenance === 'random' && !(st.sampled.get(cid)?.has(b.clip_id)) && !st.labels.get(`${cid}|${b.clip_id}`)?.provenance?.startsWith('random')) {
      return sendErr(res, r, 400, 'provenance=random is only valid for clips drawn by /random-sample (calibration labels must be uniformly sampled)', 'INVALID_PROVENANCE')
    }
    const key = `${cid}|${b.clip_id}`
    if (b.value == null) {
      st.labels.delete(key)
      return sendJson(res, r, 200, { concept_id: cid, clip_id: b.clip_id, value: null, provenance: b.provenance, weight: WEIGHT[b.provenance] })
    }
    st.labels.set(key, { concept_id: cid, clip_id: b.clip_id, value: b.value, provenance: b.provenance, weight: WEIGHT[b.provenance], created_at: new Date().toISOString() })
    sendJson(res, r, 200, labelSummary(st, cid, b.clip_id))
  })
  route('POST', '/concepts/:concept_id/labels/bulk-negative', async ({ req, res, r, params }) => {
    const cid = params.concept_id
    if (!concept(cid)) return sendErr(res, r, 404, 'concept not found', 'NOT_FOUND')
    const b = await readJson(req).catch(() => ({}))
    if (!Array.isArray(b.clip_ids) || !['example', 'random'].includes(b.provenance)) {
      return sendErr(res, r, 400, 'clip_ids and provenance (example|random) are required', 'INVALID_PAYLOAD')
    }
    if (b.provenance === 'random') {
      const drawn = st.sampled.get(cid)
      if (!b.clip_ids.every((c) => drawn?.has(c))) {
        return sendErr(res, r, 400, 'provenance=random is only valid for clips drawn by /random-sample', 'INVALID_PROVENANCE')
      }
    }
    for (const clip of b.clip_ids) {
      if (!st.byClip.has(clip)) continue
      st.labels.set(`${cid}|${clip}`, { concept_id: cid, clip_id: clip, value: 'neg', provenance: b.provenance, weight: 1, created_at: new Date().toISOString() })
    }
    sendJson(res, r, 200, { concept_id: cid, clip_id: b.clip_ids[0] ?? '', value: 'neg', provenance: b.provenance, weight: 1 })
  })
  route('POST', '/concepts/:concept_id/random-sample', ({ res, r, params, query }) => {
    const cid = params.concept_id
    if (!concept(cid)) return sendErr(res, r, 404, 'concept not found', 'NOT_FOUND')
    const n = Math.max(1, Math.min(50, Number(query.get('n')) || 10))
    let seed = query.get('seed') != null ? Number(query.get('seed')) : Math.floor(Math.random() * 1e9)
    const rnd = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296 }
    const pool = st.events.filter((e) => e.trace_status === 'ok' && !st.labels.has(`${cid}|${e.clip_id}`) && !e.id.startsWith('ev_live_'))
    for (let i = pool.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [pool[i], pool[j]] = [pool[j], pool[i]] }
    const pick = pool.slice(0, n)
    const drawn = st.sampled.get(cid) ?? new Set()
    pick.forEach((e) => drawn.add(e.clip_id))
    st.sampled.set(cid, drawn)
    sendJson(res, r, 200, pick.map((e) => eventSummary(st, e, cid)))
  })
  route('POST', '/concepts/:concept_id/teach', ({ res, r, params }) => {
    const c = concept(params.concept_id)
    if (!c) return sendErr(res, r, 404, 'concept not found', 'NOT_FOUND')
    if (isRunning(st, c.id)) { coverage.add(`${r.method} ${r.apiPath}`); res.writeHead(409, { ...baseHeaders, 'content-type': 'application/json' }); return res.end(JSON.stringify({ error: 'a run is already in progress' })) }
    sendJson(res, r, 202, runView(startRun(st, c)))
  })
  route('GET', '/concepts/:concept_id/question', ({ res, r, params }) => {
    const q = nextQuestion(st, params.concept_id)
    coverage.add(`${r.method} ${r.apiPath}`)
    if (!q) { res.writeHead(204, baseHeaders); return res.end() }
    sendJson(res, r, 200, q)
  })
  route('GET', '/concepts/:concept_id/rules', ({ res, r, params }) => {
    if (!concept(params.concept_id)) return sendErr(res, r, 404, 'concept not found', 'NOT_FOUND')
    sendJson(res, r, 200, rulesOf(st, params.concept_id))
  })
  route('GET', '/runs/:run_id', ({ res, r, params }) => {
    const run = st.runs.get(params.run_id)
    if (!run) return sendErr(res, r, 404, 'run not found', 'NOT_FOUND')
    sendJson(res, r, 200, runView(run))
  })
  route('GET', '/runs/:run_id/stream', ({ req, res, r, params }) => {
    const run = st.runs.get(params.run_id)
    if (!run) return sendErr(res, r, 404, 'run not found', 'NOT_FOUND')
    const last = Number(req.headers['last-event-id'] || 0)
    const client = openSse(req, res, r, 'RunEvent')
    const timers = []
    for (const e of run.events) {
      if (e.seq <= last) continue
      const delay = e.at_ms - Date.now()
      if (delay <= 0) client.send(e.type, e, e.seq)
      else timers.push(setTimeout(() => !client.closed && client.send(e.type, e, e.seq), delay))
    }
    client.onClose = () => timers.forEach(clearTimeout)
  })

  // ---- rules
  const findRule = (id) => st.rules.find((x) => x.id === id)
  route('GET', '/rules/:rule_id', ({ res, r, params }) => {
    const rule = findRule(params.rule_id)
    if (!rule) return sendErr(res, r, 404, 'rule not found', 'NOT_FOUND')
    sendJson(res, r, 200, ruleSummary(st, rule))
  })
  route('PATCH', '/rules/:rule_id', async ({ req, res, r, params }) => {
    const rule = findRule(params.rule_id)
    if (!rule) return sendErr(res, r, 404, 'rule not found', 'NOT_FOUND')
    const b = await readJson(req).catch(() => ({}))
    if (b.status) {
      if (!['candidate', 'selected', 'deployed', 'retired'].includes(b.status)) return sendErr(res, r, 400, 'invalid status', 'INVALID_PAYLOAD')
      if (b.status === 'deployed') for (const o of st.rules) if (o.concept_id === rule.concept_id && o.status === 'deployed') o.status = 'selected'
      rule.status = b.status
    }
    if (Array.isArray(b.actions)) rule.actions = b.actions.filter((a) => ['ui', 'webhook_out', 'slack', 'chime'].includes(a))
    sendJson(res, r, 200, ruleSummary(st, rule))
  })
  route('GET', '/rules/:rule_id/backtest', ({ res, r, params }) => {
    const rule = findRule(params.rule_id)
    if (!rule) return sendErr(res, r, 404, 'rule not found', 'NOT_FOUND')
    sendJson(res, r, 200, backtest(st, rule))
  })

  // ---- live
  route('POST', '/live/frames', async ({ req, res, r }) => {
    await readBody(req).catch(() => null)
    coverage.add(`${r.method} ${r.apiPath}`)
    res.writeHead(202, baseHeaders)
    res.end()
  })
  route('POST', '/live/sessions/:session_id/finish', ({ res, r }) => sendJson(res, r, 202, { event_id: 'ev_live_1' }))
  route('GET', '/monitor/stream', ({ req, res, r }) => {
    const client = openSse(req, res, r, 'MonitorEvent')
    hub.clients.add(client)
    client.onClose = () => hub.clients.delete(client)
    hubLoop()
  })
  route('GET', '/monitor/cost', ({ res, r }) => sendJson(res, r, 200, costView(st)))
  route('GET', '/monitor/firings', ({ res, r, query }) => {
    const ruleId = query.get('rule_id')
    const limit = Number(query.get('limit')) || 50
    sendJson(res, r, 200, st.firings.filter((f) => !ruleId || f.rule_id === ruleId).slice(0, limit))
  })

  // ---- eval
  route('GET', '/eval/results', ({ res, r }) => sendJson(res, r, 200, st.evalResults))

  // ---- mock-only
  route('POST', '/__mock/reset', ({ res, r }) => {
    st = createStore()
    st.auth.expires_at_ms = Date.now() + tokenMin * 60_000
    sendJson(res, r, 200, { ok: true })
  })
  route('POST', '/__mock/trigger', ({ res, r, query }) => {
    const kind = query.get('kind') || 'package'
    if (!SCENARIOS[kind]) return sendErr(res, r, 400, `kind must be one of ${Object.keys(SCENARIOS).join(', ')}`)
    if (!hub.busy) { hub.busy = true; runScenario(kind).finally(() => { hub.busy = false }) }
    sendJson(res, r, 200, { ok: true, kind })
  })

  // -------------------------------------------------------------- server
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://mock')
    if (req.method === 'OPTIONS') { res.writeHead(204, { ...baseHeaders, 'access-control-allow-methods': '*', 'access-control-allow-headers': '*' }); return res.end() }
    for (const rt of routes) {
      if (rt.method !== req.method) continue
      const m = rt.re.exec(url.pathname)
      if (!m) continue
      const params = Object.fromEntries(rt.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])]))
      try {
        await rt.handler({ req, res, r: rt.apiPath.startsWith('/__mock') ? null : { method: rt.method, apiPath: rt.apiPath }, params, query: url.searchParams })
      } catch (err) {
        console.error('[mock] handler error', req.method, url.pathname, err)
        if (!res.headersSent) res.writeHead(500, { ...baseHeaders, 'content-type': 'application/json' })
        res.end(JSON.stringify({ error: String(err.message || err), code: 'MOCK_ERROR' }))
      }
      return
    }
    res.writeHead(404, { ...baseHeaders, 'content-type': 'application/json' })
    res.end(JSON.stringify({ error: `no mock route for ${req.method} ${url.pathname}`, code: 'NOT_FOUND' }))
  })
  // __mock routes need the route object even though they skip validation
  return {
    server,
    violations,
    coverage,
    contract,
    operations: contract?.operations ?? [],
    get state() { return st },
    async listen(port = 8787, host = '127.0.0.1') {
      await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, host, resolve) })
      return server.address()
    },
  }
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href
if (isMain) {
  const port = Number(process.env.PORT || 8787)
  const host = process.env.HOST || '127.0.0.1'
  const app = await createApp()
  app.listen(port, host).then(() => {
    console.log(`[mock] Exemplar mock engine on http://${host}:${port}  (contract validation ${app.contract ? 'on' : 'off'}, ${FROLLARD_ATTRIBUTION})`)
  }).catch((err) => {
    console.error(`[mock] cannot listen on ${host}:${port}: ${err.message}`)
    process.exit(1)
  })
}
