# Model cost per event versus number of rules

![Cost per event as rules are added: Exemplar stays at $0.00179; zero-shot prompting grows by $0.0133 per rule](cost_vs_rules.svg)

Text twin of `cost_vs_rules.svg`. Dollar amounts are model spend per event while the rules are watching (one-time teaching cost is not included).

| Rules deployed | Exemplar, $ per event | Zero-shot prompting, $ per event | Zero-shot / Exemplar |
|---:|---:|---:|---:|
| 1 | $0.00179 | $0.0133 | 7x |
| 2 | $0.00179 | $0.0266 | 15x |
| 3 | $0.00179 | $0.0399 | 22x |
| 4 | $0.00179 | $0.0532 | 30x |
| 5 | $0.00179 | $0.0665 | 37x |
| 6 | $0.00179 | $0.0798 | 45x |
| 7 | $0.00179 | $0.0931 | 52x |
| 8 | $0.00179 | $0.1064 | 59x |
| 9 | $0.00179 | $0.1197 | 67x |
| 10 | $0.00179 | $0.1330 | 74x |

## How the numbers are obtained

- **Exemplar, $0.00179 per event, flat.** Mean cost of the fast model's perception of one clip: 1,005 clips, 16 frames each, p50 perception latency 15.6 s. The trace is cached, so adding a rule adds no model call: scoring a rule on a cached trace takes about 0.05 to 0.1 ms in the NumPy evaluator (`docs/DSL.md`, Performance).
- **Zero-shot prompting, $0.0133 per rule per event.** Median cost of one strong-model call on the same 16 frames (527 calls, mean $0.0135). The baseline asks one concept per call, so n rules cost n calls per event and the line is exactly n x the single-call cost.
- Both prices are computed from the token counts the model returned and the per-token prices in `eval/harness/budget.py`.
- Events that land close to a rule's decision boundary can be re-checked by the strong model; that is billed on top and was not needed in the live Playground run, where the measured cost was about $0.0015 per watched event.
- Source: `data/eval/precompute.jsonl` and `data/eval/costs.jsonl` (gitignored; regenerate with the commands in `eval/README.md`).

Regenerate: `uv run --project engine python eval/plots/cost_vs_rules.py`.
