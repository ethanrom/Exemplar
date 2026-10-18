import plugin from 'tailwindcss/plugin'
import { ex } from './styles/tokens.js'

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./app/**/*.{js,ts,jsx,tsx,mdx}', './components/**/*.{js,ts,jsx,tsx,mdx}'],
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
      colors: Object.fromEntries(Object.entries(ex).map(([k, v]) => [`ex-${k}`, v])),
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
}
