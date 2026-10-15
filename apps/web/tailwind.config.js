/** @type {import('tailwindcss').Config} */
const plugin = require('tailwindcss/plugin')

// Exemplar design tokens: "refined dark".
// One source of truth. `npm run mock:contrast` reads this file, so every text/background pair below is
// checked against WCAG 2.2 AA (>= 4.5:1 text, >= 3:1 for UI component boundaries and graphics).
// The same values are exposed to plain CSS as --ex-* custom properties by the plugin at the bottom.
const ex = {
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

module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  darkMode: 'class',
  theme: {
    // Type scale: 12 / 13 / 14 / 16 / 20 / 24 / 32, plus two display sizes for the home page.
    fontSize: {
      xs: ['0.75rem', { lineHeight: '1rem' }], // 12
      sm: ['0.8125rem', { lineHeight: '1.25rem' }], // 13
      base: ['0.875rem', { lineHeight: '1.375rem' }], // 14
      md: ['1rem', { lineHeight: '1.5rem' }], // 16
      lg: ['1.25rem', { lineHeight: '1.75rem' }], // 20
      xl: ['1.5rem', { lineHeight: '2rem' }], // 24
      '2xl': ['2rem', { lineHeight: '2.5rem' }], // 32
      '3xl': ['2.75rem', { lineHeight: '1.1' }], // 44
      '4xl': ['3.25rem', { lineHeight: '1.06' }], // 52
    },
    borderRadius: {
      none: '0',
      sm: '4px',
      DEFAULT: '6px',
      md: '6px',
      lg: '8px',
      xl: '10px',
      '2xl': '10px',
      full: '9999px',
    },
    extend: {
      colors: {
        // Sample-app palette (only the unused legacy sample components still reference it).
        'dash-cyan': '#06B6D4',
        'dash-dark': '#0F172A',
        'dash-panel': '#1E293B',
        'dash-card': '#334155',
        'dash-accent': '#22D3EE',
        success: '#22C55E',
        warning: '#F59E0B',
        danger: '#EF4444',
        ...Object.fromEntries(Object.entries(ex).map(([k, v]) => [`ex-${k}`, v])),
      },
      fontFamily: {
        sans: ['var(--font-geist-sans)', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['var(--font-geist-mono)', 'ui-monospace', '"Cascadia Mono"', 'Consolas', 'monospace'],
      },
      transitionDuration: { DEFAULT: '150ms' },
      keyframes: {
        'ex-glow': {
          '0%': { boxShadow: '0 0 0 0 rgba(105, 196, 140, 0.55)' },
          '100%': { boxShadow: '0 0 0 12px rgba(105, 196, 140, 0)' },
        },
        'ex-in': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'ex-shimmer': {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        'ex-pulse': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.35' },
        },
      },
      animation: {
        'ex-glow': 'ex-glow 1.6s ease-out 1',
        'ex-in': 'ex-in 0.22s ease-out 1',
        'ex-shimmer': 'ex-shimmer 1.8s linear infinite',
        'ex-pulse': 'ex-pulse 1.4s ease-in-out infinite',
      },
    },
  },
  plugins: [
    plugin(({ addBase }) => {
      addBase({
        ':root': Object.fromEntries(Object.entries(ex).map(([k, v]) => [`--ex-${k}`, v])),
      })
    }),
  ],
  // read by mock/contrast.mjs
  exTokens: ex,
}
