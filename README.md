# Exemplar — teach your Ring camera new detectors by example

Show Exemplar one to three clips and say "alert me about things like *this*". It learns a readable temporal-logic rule (an LLM proposes the structure and Z3 solves the thresholds), asks you one well-chosen question, backtests the rule with a calibrated false-alarm guarantee, and runs it live on Ring events with an explanation for every alert.

Ring track + AWS Builder entry, Amazon Developer Hackathon 2026. See [PROPOSAL.md](PROPOSAL.md) for what and why, and [PLAN.md](PLAN.md) for how.

> **Status:** Phase 0 (spikes and frozen contracts) is done; the workstreams are being built. Full setup and run instructions come with the first runnable build.

## Layout
- `apps/web/`: Next.js 15 app, forked from [AmazonAppDev/ring-api-helloworld](https://github.com/AmazonAppDev/ring-api-helloworld). Ring auth, WHEP live view, webhook route, UI.
- `engine/`: Python 3.11 FastAPI engine, package `exemplar` (Ring client, perception, DSL, synthesis, active learning, calibration, monitor).
- `engine/exemplar/contracts/`: frozen interfaces between workstreams (trace, DSL AST and grammar, labels, REST/SSE API, SQLite schema).
- `eval/`: MEVA benchmark.
- `scripts/spikes/`: Phase 0 probes (Ring Playground, WHEP, Bedrock, Strands, Z3, MEVA).
- `docs/`: DSL semantics, friction log, feedback.

## Developer setup (so far)
Prerequisites: [uv](https://docs.astral.sh/uv/) and Node 20+. ffmpeg is bundled through `imageio-ffmpeg`, so no system install is needed.

```bash
cp .env.example .env            # fill in Bedrock + Ring values
cd engine && uv sync && uv run pytest        # contract tests
cd ../apps/web && npm ci && npm run dev      # http://localhost:3000
```

## Attributions
- `apps/web` is derived from **ring-api-helloworld**, © 2026 Amazon, MIT. See `apps/web/LICENSE` and `apps/web/UPSTREAM.md`.
- Porch footage: **"Thief stealing our package" by frollard**, [youtube.com/watch?v=TfTFu8lGrwk](https://www.youtube.com/watch?v=TfTFu8lGrwk), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). It is also the source of the Ring Developer Playground's package clip. We cut it into short windows and do not redistribute it in this repo.
- Evaluation data: **MEVA, Multiview Extended Video with Activities** (Kitware, Inc. and IARPA), [CC BY 4.0](https://mevadata.org/resources/MEVA-data-license.txt), accessed 2026-10-15 from https://registry.opendata.aws/mevadata. Corona et al., "MEVA: A Large-Scale Multiview, Multimodal Video Dataset for Activity Detection", WACV 2021. We cut and crop windows from it.

## License
MIT. See [LICENSE](LICENSE).
