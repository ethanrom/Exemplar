// `npm run mock:contrast`: WCAG 2.2 contrast of the design tokens in tailwind.config.js (ex-*), read from
// the config itself so the check can never drift from the CSS, plus the chart colours used on the Eval screen.
// Text needs >= 4.5:1, UI components / graphics >= 3:1. Exits 1 if any pair fails.
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const T = require('../tailwind.config.js').exTokens

// ---------------------------------------------------------------------------------------------
const parse = (c) => {
  if (c.startsWith('#')) {
    const [r, g, b] = c.replace('#', '').match(/../g).map((h) => parseInt(h, 16))
    return { r, g, b, a: 1 }
  }
  const m = c.match(/rgba?\(([^)]+)\)/)
  const [r, g, b, a = 1] = m[1].split(',').map((x) => parseFloat(x))
  return { r, g, b, a }
}
/** Composite colour `fg` (possibly translucent) over opaque `bg`; returns #rrggbb. */
const over = (fg, bg) => {
  const f = parse(fg)
  const b = parse(bg)
  const mix = (x, y) => Math.round(x * f.a + y * (1 - f.a))
  const h = (n) => n.toString(16).padStart(2, '0')
  return `#${h(mix(f.r, b.r))}${h(mix(f.g, b.g))}${h(mix(f.b, b.b))}`
}
const lum = (hex) => {
  const { r, g, b } = parse(hex)
  const [R, G, B] = [r, g, b].map((v) => {
    v /= 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * R + 0.7152 * G + 0.0722 * B
}
const ratio = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const surfaces = { page: T.bg, panel: T.panel, raised: T.raised, hover: T.hover }
const soft = (tone, surface) => over(T[`${tone}-soft`], surface)

const text = []
for (const [sn, sv] of Object.entries(surfaces)) {
  text.push([`ink on ${sn}`, T.ink, sv], [`ink2 on ${sn}`, T.ink2, sv], [`ink3 (muted) on ${sn}`, T.ink3, sv])
  text.push([`accent text on ${sn}`, T['accent-ink'], sv])
  for (const tone of ['pos', 'neg', 'warn']) text.push([`${tone} text on ${sn}`, T[tone], sv])
  for (const k of ['syn-kw', 'syn-temporal', 'syn-type', 'syn-zone', 'syn-num', 'syn-hole']) text.push([`${k} (rule language) on ${sn}`, T[k], sv])
}
text.push(['primary button: white on accent', '#FFFFFF', T.accent], ['primary button hover: white on accent-hover', '#FFFFFF', T['accent-hover']])
for (const tone of ['pos', 'neg', 'warn']) {
  for (const s of ['panel', 'page']) text.push([`${tone} badge text on ${tone}-soft over ${s}`, T[tone], soft(tone, surfaces[s])])
}
text.push(['accent badge text on accent-soft over panel', T['accent-ink'], over(T['accent-soft'], T.panel)])
text.push(['neutral badge: ink2 on white/6% over panel', T.ink2, over('rgba(255,255,255,0.06)', T.panel)])
text.push(['source tag: white on black/70 over a white frame (worst case)', '#FFFFFF', over('rgba(0,0,0,0.7)', '#FFFFFF')])
text.push(['witness bar label: white on accent', '#FFFFFF', T.accent])
text.push(['witness bar label (failed): neg on neg-soft over page', T.neg, over(T['neg-soft'], T.bg)])

const graphics = []
for (const [sn, sv] of Object.entries(surfaces)) {
  graphics.push([`control edge on ${sn}`, T.edge, sv])
  graphics.push([`focus ring (accent-ink) on ${sn}`, T['accent-ink'], sv])
}
graphics.push(
  ['switch off: edge on page', T.edge, T.bg],
  ['switch on: pos knob on pos-soft track', T.pos, over('rgba(105,196,140,0.25)', T.bg)],
  ['witness bar: accent on page', T.accent, T.bg],
  ['witness bar: accent on panel', T.accent, T.panel],
  ['score bar fill (accent-ink) on panel', T['accent-ink'], T.panel],
  ['score bar fill (ink3) on panel', T.ink3, T.panel],
  ['bar: exemplar blue', '#3987e5', T.panel], ['bar: zero-shot orange', '#d95926', T.panel],
  ['bar: kNN aqua', '#199e70', T.panel], ['bar: Nova yellow', '#c98500', T.panel],
)

let bad = 0
const run = (title, rows, min) => {
  console.log(`\n${title} (need >= ${min}:1)`)
  for (const [name, fg, bg] of rows) {
    const r = ratio(fg, bg)
    const ok = r >= min
    if (!ok) bad++
    console.log(`  ${ok ? 'PASS' : 'FAIL'} ${r.toFixed(2).padStart(5)}:1  ${name}`)
  }
}
run('Text', text, 4.5)
run('UI components and graphics', graphics, 3)
const hair = (c, s) => ratio(over(c, s), s).toFixed(2)
console.log(`\nDecorative only (hairline dividers and quiet outlines, exempt from 1.4.11): line on page ${hair(T.line, T.bg)}:1, line2 on panel ${hair(T.line2, T.panel)}:1`)
console.log('Buttons are identified by their text and fill; every field, select, checkbox and switch uses the 3:1 edge above.')
console.log(bad ? `\n${bad} pair(s) below the WCAG 2.2 AA threshold` : '\nAll pairs pass WCAG 2.2 AA')
process.exit(bad ? 1 : 0)
