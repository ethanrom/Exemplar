// `npm run mock:contrast`: WCAG 2.2 contrast of the design tokens in tailwind.config.js (ex-*) and
// the chart colours used on the Eval screen. Text needs >= 4.5:1, UI components / graphics >= 3:1.
// Exits 1 if any pair fails.

const lum = (hex) => {
  const c = hex.replace('#', '').match(/../g).map((h) => parseInt(h, 16) / 255)
  const [r, g, b] = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const ratio = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const T = {
  bg: '#0B1220', panel: '#111C2F', raised: '#1A2740', line: '#3B4A63',
  ink: '#F1F5F9', ink2: '#CBD5E1', ink3: '#A3B1C6', accent: '#22D3EE', edge: '#6B7C99',
  pos: '#4ADE80', neg: '#F87171', warn: '#FBBF24', info: '#7DD3FC',
}

const text = [
  ['ink on page', T.ink, T.bg], ['ink on panel', T.ink, T.panel], ['ink on raised', T.ink, T.raised],
  ['ink2 on page', T.ink2, T.bg], ['ink2 on panel', T.ink2, T.panel], ['ink2 on raised', T.ink2, T.raised],
  ['ink3 (muted) on page', T.ink3, T.bg], ['ink3 (muted) on panel', T.ink3, T.panel], ['ink3 (muted) on raised', T.ink3, T.raised],
  ['link/info on panel', T.info, T.panel], ['accent on panel', T.accent, T.panel],
  ['primary button: slate-950 on accent', '#020617', T.accent],
  ['positive chip: green-200 on green-950', '#BBF7D0', '#052E16'],
  ['negative chip: red-200 on red-950', '#FECACA', '#450A0A'],
  ['warning chip: amber-100 on amber-950', '#FEF3C7', '#451A03'],
  ['info chip: sky-100 on sky-950', '#E0F2FE', '#082F49'],
  ['accent chip: cyan-100 on cyan-950', '#CFFAFE', '#083344'],
  ['label chip pressed +: slate-950 on green-400', '#020617', '#4ADE80'],
  ['label chip pressed -: slate-950 on red-400', '#020617', '#F87171'],
  ['code: cyan-100 on page', '#CFFAFE', T.bg],
  ['chart axis text (muted) on panel', T.ink3, T.panel],
]
const graphics = [
  ['control border (ex-edge) on page', T.edge, T.bg], ['control border (ex-edge) on panel', T.edge, T.panel],
  ['control border (ex-edge) on raised', T.edge, T.raised],
  ['focus ring cyan-300 on page', '#67E8F9', T.bg], ['focus ring cyan-300 on panel', '#67E8F9', T.panel],
  ['focus ring white (primary buttons) on page', '#FFFFFF', T.bg],
  ['bar: exemplar blue', '#3987e5', T.panel], ['bar: zero-shot orange', '#d95926', T.panel],
  ['bar: kNN aqua', '#199e70', T.panel], ['bar: Nova yellow', '#c98500', T.panel],
  ['witness bar green-400', '#4ADE80', T.bg], ['witness bar red-400', '#F87171', T.bg],
  ['switch off outline', T.ink3, T.bg],
]

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
console.log(`\nDecorative only (dividers and card outlines, exempt from 1.4.11): ex-line on page ${ratio(T.line, T.bg).toFixed(2)}:1, on panel ${ratio(T.line, T.panel).toFixed(2)}:1`)
console.log(bad ? `\n${bad} pair(s) below the WCAG 2.2 AA threshold` : '\nAll pairs pass WCAG 2.2 AA')
process.exit(bad ? 1 : 0)
