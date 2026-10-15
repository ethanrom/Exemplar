# Exemplar — Ring track, Amazon Developer Hackathon 2026

Teach-by-example detectors for Ring cameras: LLM perception → symbolic traces → Z3-based rule synthesis (CEGIS) → STL robustness → conformal false-alarm calibration → live monitor on the Ring Developer Playground.

- **Read `PROPOSAL.md` (what/why) and `PLAN.md` (how, specs, schedule) before doing anything.** PLAN.md §2 holds the exact semantics and encodings — follow them; if you change one, update `docs/DSL.md` and the tests in the same change.
- Deadline **Oct 23 2026 12:00 PT**; target submission 09:00 PT. Respect the cut list in PLAN.md §4.
- Built by parallel Sonnet subagents, one branch/worktree per workstream (PLAN.md §4). Stay inside your stream's owned paths; contracts in `engine/exemplar/contracts/` change only via the integrator.
- Host is Windows 10 + Git Bash. Engine = Python (FastAPI, z3-solver, numpy, strands-agents, boto3); web = Next.js 15 fork of `AmazonAppDev/ring-api-helloworld`.
- Python only through **uv** (`uv sync`/`uv add --project engine`, `uv run --project engine …`, env in `engine/.venv`); never install into the base Python. Windows defaults to cp1252, so always pass `encoding="utf-8"` (or set `PYTHONUTF8=1`).
- Commit messages: no `Co-Authored-By` / AI-attribution trailers.
- Ring API calls are server-side only. Bedrock models come from `.env` (`CLAUDE_AWS_MODEL`, `CLAUDE_AWS_FAST_MODEL`) — never hard-code model IDs or commit `.env`.
- Log every Ring/AWS tooling problem in `docs/FRICTION_LOG.md` as it happens (judging bonus).
- Hackathon rules/updates: `challange.txt`, `rules.txt`, `updates.txt`.
