// Exploratory probe used while integrating with the Ring Developer Playground: drive the web app's live view
// in an installed Google Chrome and report whether the WHEP stream decodes, plus the negotiated codec.
//
//   NODE_PATH=<dir with playwright-core>/node_modules node scripts/spikes/whep_check.mjs [http://localhost:3000]
import { createRequire } from 'node:module'
import { writeFileSync, mkdirSync } from 'node:fs'
const require = createRequire(process.env.NODE_PATH + '/')
const { chromium } = require('playwright-core')

const url = process.argv[2] || 'http://localhost:3000'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage()
// Capture the RTCPeerConnection the page creates so we can read inbound-rtp stats.
await page.addInitScript(() => {
  const Orig = window.RTCPeerConnection
  window.__pcs = []
  window.RTCPeerConnection = function (...a) { const pc = new Orig(...a); window.__pcs.push(pc); return pc }
  window.RTCPeerConnection.prototype = Orig.prototype
})
await page.goto(url)
const btn = page.getByRole('button', { name: /Start Live Stream/ })
await btn.waitFor({ timeout: 30000 })
await page.waitForFunction(() => !document.querySelector('button[disabled]'), null, { timeout: 30000 })
const t0 = Date.now()
await btn.click()
let res = null
try {
  await page.waitForFunction(() => { const v = document.querySelector('video'); return v && v.videoWidth > 0 && v.currentTime > 1 }, null, { timeout: 30000 })
  res = await page.evaluate(async () => {
    const v = document.querySelector('video')
    const pc = window.__pcs[window.__pcs.length - 1]
    const out = { videoWidth: v.videoWidth, videoHeight: v.videoHeight }
    const stats = await pc.getStats()
    const codecs = {}
    stats.forEach(s => { if (s.type === 'codec') codecs[s.id] = s.mimeType + (s.sdpFmtpLine ? ' ' + s.sdpFmtpLine : '') })
    stats.forEach(s => {
      if (s.type === 'inbound-rtp' && s.kind === 'video')
        Object.assign(out, { codec: codecs[s.codecId], framesDecoded: s.framesDecoded, fps: s.framesPerSecond, decoder: s.decoderImplementation })
    })
    return out
  })
  res.firstFrameMs = Date.now() - t0
} catch (e) {
  res = { error: String(e).slice(0, 300), pageText: (await page.locator('body').innerText()).slice(0, 500) }
}
mkdirSync('data/spike/whep', { recursive: true })
await page.screenshot({ path: 'data/spike/whep/live.png' })
writeFileSync('data/spike/whep/result.json', JSON.stringify(res, null, 2))
console.log(JSON.stringify(res))
await page.getByRole('button', { name: /Stop/ }).click().catch(() => {})
await page.waitForTimeout(1500)
await browser.close()
