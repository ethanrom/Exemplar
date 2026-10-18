// Exemplar design tokens: "refined dark". Ported from apps/web/tailwind.config.js (same values, same names)
// so components move across without a visual change. One source of truth: tailwind.config.js builds the
// `ex-*` colours and the --ex-* CSS custom properties from this object.
// Every text/background pair is meant to meet WCAG 2.2 AA (>= 4.5:1 for text, >= 3:1 for UI boundaries).

export const ex = {
  // Surfaces: elevation is expressed by tone, not by borders or glows.
  bg: '#0A0B0D',
  panel: '#111316',
  raised: '#16191D',
  hover: '#1C2025',
  // Hairlines (decorative dividers and quiet outlines, exempt from 1.4.11) and the control edge (>= 3:1).
  line: 'rgba(255, 255, 255, 0.07)',
  line2: 'rgba(255, 255, 255, 0.12)',
  edge: '#6A7079',
  // Text.
  ink: '#ECEDEF',
  ink2: '#B2B6BD',
  ink3: '#8A8F98',
  // One restrained accent: the primary action, focus and key data.
  accent: '#2A6BE0', // solid fill, white text (4.9:1)
  'accent-hover': '#2563D8',
  'accent-ink': '#7FAEFF', // accent as text / icon / data on dark surfaces
  'accent-soft': 'rgba(88, 142, 255, 0.12)',
  'accent-line': 'rgba(88, 142, 255, 0.38)',
  // Muted semantic colours. Always paired with an icon or a word, never colour alone.
  pos: '#69C48C',
  'pos-soft': 'rgba(105, 196, 140, 0.10)',
  'pos-line': 'rgba(105, 196, 140, 0.30)',
  neg: '#E88A85',
  'neg-soft': 'rgba(232, 138, 133, 0.10)',
  'neg-line': 'rgba(232, 138, 133, 0.32)',
  warn: '#E2B25C',
  'warn-soft': 'rgba(226, 178, 92, 0.10)',
  'warn-line': 'rgba(226, 178, 92, 0.30)',
  // Syntax highlighting for the rule language (all >= 7:1 on every surface).
  'syn-kw': '#B9A3F5', // exists / when / and / or / not
  'syn-temporal': '#7FB1FF', // eventually / always / then / holds_for
  'syn-type': '#6FD3D0', // Person, Package, ...
  'syn-zone': '#8FD694', // door, steps, ...
  'syn-num': '#F2B968', // 19.5
  'syn-hole': '#F58FA6', // ?b
}
