// Claims this page needs that are not (yet) in data/claims.json. Each one is copied as published from a cited
// repository document, with the file, the line and the quoted text. If data/claims.json defines the same id,
// the data file wins (see claims.ts).
import type { Claim } from '../../lib/data/types.ts'

export const EXTRA_CLAIMS: readonly Claim[] = [
  {
    id: 'verify.encoding_split',
    display: '2,000 randomly generated sketches compare the Z3 encoding with a NumPy evaluator and 1,850 more compare the solver with an exhaustive search',
    source: {
      path: 'README.md',
      line: 215,
      quote: '2,000 randomly generated sketches compare the Z3 encoding with a NumPy evaluator and 1,850 more compare the solver with an exhaustive search, with no mismatches.',
    },
  },
  {
    id: 'verify.encoding_total_dev',
    display: 'Over 6,000 randomized cases ran during development with 0 mismatches',
    source: {
      path: 'README.md',
      line: 215,
      quote: 'Over 6,000 randomized cases ran during development with 0 mismatches',
    },
  },
  {
    id: 'tests.webhook_node',
    display: '22 tests',
    source: {
      path: 'README.md',
      line: 188,
      quote: 'cd apps/web && node --test lib/ring/ring.test.mjs     # webhook verification and WHEP URL allow-list (22 tests)',
    },
  },
  {
    id: 'a11y.axe',
    display: '0 axe violations',
    source: {
      path: 'README.md',
      line: 220,
      quote: 'an axe-core scan of every screen reports 0 violations.',
    },
  },
  {
    id: 'cost.exemplar_flat',
    display: '$0.00179',
    source: {
      path: 'docs/eval/cost_vs_rules.md',
      line: 22,
      quote: 'Exemplar, $0.00179 per event, flat. Mean cost of the fast model\'s perception of one clip: 1,005 clips, 16 frames each, p50 perception latency 15.6 s.',
    },
  },
  {
    id: 'cost.zero_shot_per_rule',
    display: '$0.0133',
    source: {
      path: 'docs/eval/cost_vs_rules.md',
      line: 23,
      quote: 'Zero-shot prompting, $0.0133 per rule per event. Median cost of one strong-model call on the same 16 frames (527 calls, mean $0.0135).',
    },
  },
  {
    id: 'rule.example_published',
    display: 'There is a package k such that (k is on the steps or k is on the porch) continuously for at least 15 s.',
    source: {
      path: 'docs/DEVPOST.md',
      line: 54,
      quote: 'Z3 then chose the duration, giving *"There is a package k such that (k is on the steps or k is on the porch) continuously for at least 15 s."*',
    },
  },
]
