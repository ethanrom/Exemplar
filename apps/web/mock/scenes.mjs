// Generated placeholder snapshots for the mock engine (SVG, 640x360). Ring-sourced events carry a
// mock "Ring watermark" (logo top-left, device + time top-right) so the Live/Library design can be
// reviewed against the real constraint that the watermark must stay uncovered.

function hash(s) {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

function person(x, y, color, carrying) {
  return `<g transform="translate(${x} ${y})">
    <ellipse cx="0" cy="62" rx="26" ry="6" fill="#0f172a" opacity=".25"/>
    <rect x="-17" y="-8" width="34" height="62" rx="14" fill="${color}"/>
    <circle cx="0" cy="-22" r="13" fill="#e2c7a8"/>
    <path d="M-14 -26 q14 -22 28 0 z" fill="#1e293b"/>
    ${carrying ? box(24, 18, 0.8) : ''}
  </g>`
}

function box(x, y, k = 1) {
  const w = 54 * k
  const h = 40 * k
  return `<g transform="translate(${x} ${y})">
    <rect x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" fill="#b98a55" stroke="#7c5a33" stroke-width="2"/>
    <rect x="-4" y="${-h / 2}" width="8" height="${h}" fill="#e7d3a8"/>
  </g>`
}

function car(x, y, color) {
  return `<g transform="translate(${x} ${y})">
    <ellipse cx="0" cy="34" rx="76" ry="8" fill="#0f172a" opacity=".3"/>
    <path d="M-72 22 v-22 q0 -8 10 -10 l28 -6 q10 -22 30 -22 h22 q14 0 22 14 l16 14 q18 2 18 18 v14 z" fill="${color}"/>
    <rect x="-34" y="-30" width="30" height="16" rx="3" fill="#bcd2e6"/>
    <rect x="2" y="-30" width="30" height="16" rx="3" fill="#bcd2e6"/>
    <circle cx="-44" cy="24" r="14" fill="#111827"/><circle cx="-44" cy="24" r="6" fill="#9ca3af"/>
    <circle cx="44" cy="24" r="14" fill="#111827"/><circle cx="44" cy="24" r="6" fill="#9ca3af"/>
  </g>`
}

function bird(x, y, color) {
  return `<g transform="translate(${x} ${y})">
    <ellipse cx="0" cy="0" rx="18" ry="12" fill="${color}"/>
    <circle cx="14" cy="-8" r="8" fill="${color}"/>
    <path d="M21 -8 l10 3 l-10 3 z" fill="#f59e0b"/>
    <circle cx="16" cy="-9" r="1.6" fill="#0f172a"/>
    <path d="M-16 4 l-22 10 l22 -2 z" fill="${color}"/>
  </g>`
}

/**
 * @param {{id:string, source:string, device_id?:string|null, start_ms:number}} ev
 * @param {object|null} trace
 */
export function sceneSvg(ev, trace) {
  const h = hash(ev.id)
  const ents = trace?.entities ?? []
  const has = (t) => ents.some((e) => e.type === t)
  const zones = new Set()
  for (const fr of trace?.frames ?? []) for (const f of fr.facts) for (const a of f.args) zones.add(a)
  const dock = zones.has('dock')
  const picks = (trace?.frames ?? []).some((fr) => fr.facts.some((f) => f.pred === 'picks_up' || f.pred === 'carrying'))
  const jackets = ['#334155', '#7c2d12', '#14532d', '#4c1d95', '#1e3a8a']
  const jacket = ents.find((e) => e.type === 'person')?.attrs?.includes('delivery_uniform')
    ? '#5b3a1e'
    : jackets[h % jackets.length]
  const px = 250 + (h % 160)
  let scene = ''
  if (dock) {
    scene += `<rect x="0" y="0" width="640" height="360" fill="#9aa5b1"/>
      <rect x="60" y="40" width="200" height="220" fill="#556270"/><rect x="70" y="50" width="180" height="200" fill="#6b7886"/>
      <rect x="0" y="260" width="640" height="100" fill="#6b7280"/>
      <rect x="0" y="300" width="640" height="6" fill="#facc15" opacity=".8"/>`
  } else if (has('animal')) {
    scene += `<rect width="640" height="360" fill="#dbe7f2"/><rect y="250" width="640" height="110" fill="#f3f6fa"/>
      <rect x="318" y="60" width="6" height="190" fill="#6b5b45"/><rect x="290" y="60" width="62" height="34" rx="6" fill="#8b6f47"/>`
  } else {
    scene += `<rect width="640" height="360" fill="#d3dce8"/><rect y="236" width="640" height="124" fill="#eef2f7"/>
      <rect x="0" y="40" width="190" height="196" fill="#8a97a8"/><rect x="40" y="70" width="90" height="166" fill="#5b6b82"/>
      <rect x="150" y="236" width="340" height="14" fill="#cbd5e1"/><rect x="130" y="250" width="380" height="14" fill="#d5dde8"/>
      <rect x="110" y="264" width="420" height="14" fill="#dfe6ee"/>`
  }
  if (has('vehicle')) scene += car(260 + (h % 140), 232, ['#6b7280', '#b91c1c', '#1d4ed8', '#e5e7eb'][h % 4])
  if (has('animal')) scene += bird(300, 118, '#b45309') + bird(352, 112, '#dc2626')
  if (has('package') && !(has('person') && picks && h % 2 === 0)) scene += box(has('person') ? 330 : 310, 252)
  if (has('person')) scene += person(px, 214, jacket, picks && h % 2 === 0)
  const isRing = ev.source === 'ring' || ev.source === 'ring_live'
  const stamp = new Date(ev.start_ms).toISOString().slice(11, 19)
  const mark = isRing
    ? `<g font-family="system-ui,sans-serif" fill="#ffffff">
         <rect x="0" y="0" width="640" height="34" fill="#0f172a" opacity=".55"/>
         <circle cx="22" cy="17" r="10" fill="#1b9be0"/><text x="38" y="22" font-size="14" font-weight="700">ring</text>
         <text x="624" y="14" font-size="10" text-anchor="end">${esc((ev.device_id || 'Playground Device').slice(-16))}</text>
         <text x="624" y="28" font-size="10" text-anchor="end">Exemplar mock - ${stamp} UTC</text>
       </g>`
    : `<text x="16" y="24" font-family="system-ui,sans-serif" font-size="12" fill="#334155">mock placeholder - ${esc(ev.source)}</text>`
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360" width="640" height="360">${scene}${mark}</svg>`
}
