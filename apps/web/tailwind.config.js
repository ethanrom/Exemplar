/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Sample-app palette (kept: the legacy components still reference it).
        'dash-cyan': '#06B6D4',
        'dash-dark': '#0F172A',
        'dash-panel': '#1E293B',
        'dash-card': '#334155',
        'dash-accent': '#22D3EE',
        'success': '#22C55E',
        'warning': '#F59E0B',
        'danger': '#EF4444',
        // Exemplar semantic tokens. Every text/background pair used with these is checked by
        // `npm run mock:contrast` (WCAG 2.2 AA: >= 4.5:1 text, >= 3:1 UI components).
        'ex-bg': '#0B1220',
        'ex-panel': '#111C2F',
        'ex-raised': '#1A2740',
        'ex-line': '#3B4A63', // decorative dividers and card outlines
        'ex-edge': '#6B7C99', // boundaries of controls: >= 3:1 on every surface (WCAG 1.4.11)
        'ex-ink': '#F1F5F9',
        'ex-ink2': '#CBD5E1',
        'ex-ink3': '#A3B1C6',
        'ex-accent': '#22D3EE',
        'ex-pos': '#4ADE80',
        'ex-neg': '#F87171',
        'ex-warn': '#FBBF24',
        'ex-info': '#7DD3FC',
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', '"Cascadia Mono"', '"SFMono-Regular"', 'Consolas', 'monospace'],
      },
      keyframes: {
        'ex-glow': {
          '0%': { boxShadow: '0 0 0 0 rgba(74, 222, 128, 0.7)' },
          '100%': { boxShadow: '0 0 0 14px rgba(74, 222, 128, 0)' },
        },
        'ex-in': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'ex-glow': 'ex-glow 1.6s ease-out 1',
        'ex-in': 'ex-in 0.25s ease-out 1',
      },
    },
  },
  plugins: [],
}
