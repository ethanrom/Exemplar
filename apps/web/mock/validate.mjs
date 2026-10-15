// `npm run mock:validate`: boot the mock engine on a random port, exercise every operation in
// engine/exemplar/contracts/api.yaml, and fail if any response or SSE frame breaks the contract.
import { createApp } from './server.mjs'

const app = await createApp({ validate: true })
if (!app.contract) {
  console.error('contract validation could not be loaded (npm install ajv yaml)')
  process.exit(2)
}
const { port } = await app.listen(0)
const base = `http://127.0.0.1:${port}`
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function call(method, path, body, headers = {}) {
  const init = { method, headers: { ...headers } }
  if (body !== undefined) {
    if (body instanceof FormData) init.body = body
    else { init.body = JSON.stringify(body); init.headers['content-type'] = 'application/json' }
  }
  const res = await fetch(base + path, init)
  const text = await res.text()
  let json = null
  try { json = JSON.parse(text) } catch { /* not json */ }
  return { status: res.status, json, text }
}

async function sse(path, ms, headers = {}) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), ms)
  const frames = []
  try {
    const res = await fetch(base + path, { signal: ctrl.signal, headers })
    const reader = res.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let i
      while ((i = buf.indexOf('\n\n')) !== -1) {
        const raw = buf.slice(0, i); buf = buf.slice(i + 2)
        const type = /^event: (.*)$/m.exec(raw)?.[1]
        if (type) frames.push(type)
      }
    }
  } catch { /* aborted */ }
  clearTimeout(t)
  return frames
}

const ok = (cond, msg) => { if (!cond) { console.error('FAIL', msg); process.exitCode = 1 } }

// ring
ok((await call('GET', '/health')).status === 200, 'health')
ok((await call('GET', '/ring/auth')).json.connected, 'auth connected')
ok((await call('PUT', '/ring/auth', { access_token: '' })).status === 400, 'empty token rejected')
ok((await call('PUT', '/ring/auth', { access_token: 'abc' })).status === 200, 'token accepted')
ok((await call('GET', '/ring/devices')).json.length === 1, 'devices')
await call('GET', '/ring/oauth/callback')
await fetch(base + '/ring/oauth/callback?code=x', { redirect: 'manual' })
await fetch(base + '/ring/oauth/start', { redirect: 'manual' })
await call('PUT', '/ring/auth', { access_token: 'abc' })
ok((await call('POST', '/ring/sync')).status === 202, 'sync')
ok((await call('POST', '/ring/webhook-events', { meta: { request_id: 'r1' }, data: { type: 'button_press' } })).status === 202, 'webhook 202')
ok((await call('POST', '/ring/webhook-events', { meta: { request_id: 'r1' }, data: { type: 'button_press' } })).status === 409, 'webhook dup 409')

// library
const fd = new FormData()
fd.append('file', new Blob(['x']), 'clip.mp4')
fd.append('attribution', '"Thief stealing our package" by frollard, CC BY 4.0')
fd.append('window_s', '10'); fd.append('stride_s', '5')
const up = await call('POST', '/uploads', fd)
ok(up.status === 202 && up.json.length > 1, 'upload windows')
const ev = await call('GET', '/events?limit=200')
ok(ev.status === 200 && ev.json.items.length > 20, 'events list')
await call('GET', '/events?concept_id=cn_theft&labelled=pos&source=upload&limit=5&cursor=0')
const one = await call('GET', '/events/ev_pg_package_a')
ok(one.status === 200 && one.json.trace && one.json.trace_text, 'event detail')
ok((await call('GET', '/events/nope')).status === 404, 'event 404')
ok((await fetch(base + '/events/ev_pg_package_a/snapshot')).status === 200, 'snapshot')
ok((await fetch(base + '/events/nope/snapshot')).status === 404, 'snapshot 404')
await sleep(1500)
const clip = await fetch(base + '/events/ev_pg_package_a/clip', { headers: { range: 'bytes=0-99' } })
console.log('clip status', clip.status, '(404 = no ffmpeg, 200/206 = placeholder mp4)')
await clip.arrayBuffer()
await fetch(base + '/events/nope/clip').then((r) => r.arrayBuffer())

// concepts / labels / teach
const concepts = await call('GET', '/concepts')
ok(concepts.json.length === 3, 'concepts')
const created = await call('POST', '/concepts', { name: 'Test concept', nl_hint: null, alpha: 0.2 })
ok(created.status === 201, 'create concept')
ok((await call('POST', '/concepts', { name: '' })).status === 400, 'create concept validation')
await call('GET', '/concepts/cn_theft/labels')
const put = await call('PUT', '/concepts/cn_theft/labels', { clip_id: 'theft_b', value: 'pos', provenance: 'example' })
ok(put.status === 200, 'put label')
ok((await call('PUT', '/concepts/cn_theft/labels', { clip_id: 'theft_b', value: null, provenance: 'example' })).status === 200, 'delete label')
ok((await call('PUT', '/concepts/cn_theft/labels', { clip_id: 'pg_motion_b', value: 'neg', provenance: 'random' })).status === 400, 'random provenance needs a sample')
const sample = await call('POST', '/concepts/cn_theft/random-sample?n=10&seed=7')
ok(sample.json.length === 10, 'random sample')
const ids = sample.json.map((e) => e.clip_id)
ok((await call('PUT', '/concepts/cn_theft/labels', { clip_id: ids[0], value: 'pos', provenance: 'random' })).status === 200, 'random label after sample')
ok((await call('POST', '/concepts/cn_theft/labels/bulk-negative', { clip_ids: ids.slice(1), provenance: 'random' })).status === 200, 'bulk negative')
const rules0 = await call('GET', '/concepts/cn_theft/rules')
ok(rules0.json.length === 0, 'theft rules empty before teach')
const run = await call('POST', '/concepts/cn_theft/teach')
ok(run.status === 202, 'teach')
ok((await call('POST', '/concepts/cn_theft/teach')).status === 409, 'teach 409')
const frames = await sse(`/runs/${run.json.id}/stream`, 10500)
console.log('run frames:', frames.join(' > '))
ok(frames.includes('candidates') && frames.includes('done'), 'run reached done')
ok((await call('GET', `/runs/${run.json.id}`)).json.status === 'done', 'run done')
ok((await call('GET', '/runs/none')).status === 404, 'run 404')
const rules = await call('GET', '/concepts/cn_theft/rules')
ok(rules.json.length === 3, 'theft rules after teach')
console.log('theft rules:', rules.json.map((r) => `${r.id} mdl=${r.mdl} m=${r.margin} viol=[${r.violated_clip_ids}] guarantee=${r.calibration.guarantee}`).join(' | '))
const q = await call('GET', '/concepts/cn_theft/question')
ok(q.status === 200 && q.json.p > 0, 'question')
await call('PUT', '/concepts/cn_theft/labels', { clip_id: q.json.clip_id, value: 'pos', provenance: 'active' })
await call('GET', '/concepts/cn_vehicle/question')

// rules / backtest
const rid = rules.json[0].id
ok((await call('GET', `/rules/${rid}`)).status === 200, 'rule')
ok((await call('GET', '/rules/none')).status === 404, 'rule 404')
ok((await call('PATCH', `/rules/${rid}`, { status: 'selected', actions: ['ui', 'chime'] })).status === 200, 'patch rule')
const bt = await call('GET', `/rules/${rid}/backtest`)
ok(bt.status === 200 && bt.json.rows.length > 20, 'backtest')
console.log('backtest counts:', JSON.stringify(bt.json.counts), 'calibration:', JSON.stringify(bt.json.calibration))
const bt2 = await call('GET', '/rules/r_unatt_steps24/backtest')
console.log('unattended calibration:', JSON.stringify(bt2.json.calibration))
const wit = bt2.json.rows.find((r) => r.witness)?.witness
console.log('sample witness spans:', JSON.stringify(wit?.spans))

// live
const live = new FormData()
live.append('session_id', 's1'); live.append('t_ms', '0'); live.append('image', new Blob(['x']), 'f.jpg')
ok((await call('POST', '/live/frames', live)).status === 202, 'live frame')
ok((await call('POST', '/live/sessions/s1/finish')).status === 202, 'live finish')
await call('POST', '/__mock/trigger?kind=package')
const mon = await sse('/monitor/stream', 11000)
console.log('monitor frames:', [...new Set(mon)].join(', '))
for (const t of ['live_facts', 'rule_fired', 'rule_dropped', 'cost_update']) ok(mon.includes(t), `monitor emitted ${t}`)
ok((await call('GET', '/monitor/cost')).json.events > 0, 'cost')
ok((await call('GET', '/monitor/firings?limit=5')).json.length > 0, 'firings')
ok((await call('GET', '/eval/results')).json.rows.length > 50, 'eval')

// coverage
const missing = app.operations.map((o) => `${o.method} ${o.path}`).filter((k) => !app.coverage.has(k))
console.log(`operations covered: ${app.operations.length - missing.length}/${app.operations.length}`)
if (missing.length) { console.error('not exercised:', missing.join(', ')); process.exitCode = 1 }
if (app.violations.length) { console.error(`${app.violations.length} contract violation(s)`); process.exitCode = 1 }
else console.log('no contract violations')
app.server.closeAllConnections?.()
app.server.close()
setTimeout(() => process.exit(process.exitCode ?? 0), 200)
