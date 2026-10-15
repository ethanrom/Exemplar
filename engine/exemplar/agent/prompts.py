"""Prompt text for the CEGIS agent.  The ontology section is generated from `contracts/ontology.py`, so a change to
the ontology (predicates, zones, entity types) reaches the model without editing prose."""
from __future__ import annotations

from ..contracts.ontology import CONF_VALUE, ENTITY_TYPES, PREDICATES, VAR_TYPES, ZONES
from ..synth import Example, render_trace_text


def ontology_text() -> str:
    pred_lines = "\n".join(f"  {p}({', '.join(kinds)})" for p, kinds in PREDICATES.items())
    var_lines = "\n".join(f"  {v}: {'/'.join(ents)}" for v, ents in VAR_TYPES.items())
    return (f"Entity types in traces: {', '.join(ENTITY_TYPES)}.\n"
            f"Variable types (what a variable ranges over):\n{var_lines}\n"
            f"Predicates (the ONLY ones that exist; argument kinds in brackets; a Zone/Label argument is a literal):\n"
            f"{pred_lines}\n"
            f"Zones: {', '.join(ZONES)}.\n"
            f"Each atom's value in a frame is a confidence: low={CONF_VALUE['low']}, med={CONF_VALUE['med']}, "
            f"high={CONF_VALUE['high']}; it is 'true' when above 0.5, i.e. whenever the trace lists it. "
            f"present(e) is implied by any other fact about e. attr(e, label) holds in every frame when the entity "
            f"lists that label.")


GRAMMAR = """\
rule   := exists v: Type (, v: Type)* : phi [when ctx (and ctx)*]
phi    := atom | not phi | phi and phi | phi or phi
        | eventually[a, b] phi          phi holds at some moment in [t+a, t+b] seconds
        | always[a, b] phi              phi holds at every sampled moment in [t+a, t+b] (and there is one)
        | phi then[a, b] phi            the second part occurs within [a, b] seconds after the first
        | holds_for >= d phi            phi holds in every sampled frame for at least d seconds
atom   := pred(arg, ...)                args are variables, zone names or attribute labels
ctx    := hour in [h1, h2] | subtype = S | device = D
a, b, d, h1, h2 := a number or a HOLE ?name (e.g. ?a ?b ?d ?h1)
Precedence (loosest first): or < and < then < not/eventually/always/holds_for. Use parentheses when unsure.
A rule matches a clip when some assignment of distinct entities to the variables and some start time make the body true."""


SEMANTICS = """\
Semantics you must respect (they decide whether a sketch can fit the examples):
- Time is in seconds from clip start; clips are sampled at ~1-5 s spacing, so windows are coarse. `eventually[0, ?b]` is the
  workhorse; use ?a only when a minimum delay matters.
- `then` and `holds_for` search every start time, so a rule at the top level means "at some moment ...".
- `exists` ranges only over entities that appear in the trace. "Nobody is around" cannot be written as an absence of
  persons; express it positively (e.g. a Package that stays in a zone: `holds_for >= ?d in_zone(k, steps)`).
- Absence is a start-time statement: `A and not eventually[0, ?b] B` means "there is a start time where A holds and B does
  not occur in the next b seconds". It cannot exclude B everywhere in a clip; prefer positive formulations or attr/context atoms.
- Use `holds_for >= ?d` for dwell / "sitting there for N seconds" concepts, `then` for "X and afterwards Y" concepts,
  `eventually` for "X happens", `always` for "X throughout".
- Perception is noisy: a positive may miss a fact. Prefer rules that need few facts; every extra conjunct is a way to fail."""


WORKED = """\
Worked examples (rules that typecheck):
  theft       exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k) and not attr(p, delivery_uniform)
  dwell       exists v: Vehicle: holds_for >= 120 in_zone(v, dock)
  unattended  exists k: Package: holds_for >= ?d in_zone(k, steps)
  rings       exists p: Person: eventually[0, 5] rings_bell(p)
  as sketches (what you submit): replace the time constants by holes, e.g.
    exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] leaves(p, porch)
    exists p: Person: eventually[0, ?b] in_zone(p, door) and eventually[0, ?b] rings_bell(p)
    exists k: Package: holds_for >= ?d in_zone(k, steps)"""


def system_prompt(k: int) -> str:
    return f"""You are the rule-synthesis engine of Exemplar, a system that learns camera-event detectors from a few labelled examples.
You write rules in a small temporal-logic DSL over symbolic traces (entities, per-frame facts with confidences) extracted from clips.
A rule SKETCH has numeric holes (?a, ?b, ?d, ...) for time bounds, durations and hours. An exact solver (Z3 MaxSMT) fills the holes
so the rule matches the POSITIVE clips and not the NEGATIVE ones, with the largest possible margin. Your job is the structure.

{GRAMMAR}

{ontology_text()}

{SEMANTICS}

{WORKED}

How to work
1. Read the labelled traces. Find facts that positives share and negatives lack (or a temporal order between facts).
2. Propose up to {k} DIFFERENT sketches, simplest first (a handful of nodes; 1-3 holes). Vary the structure (different predicates, then vs
   eventually vs holds_for) so that at least some of them fit. Use ?names for time constants, but if the user's description states a number ("for over 10 seconds") use that number as a constant;
   never invent predicates, zones or labels (a hole is only allowed where a number is, never in place of a zone or label).
3. You may call `typecheck` and `solve_sketch` to try a sketch yourself, and `evaluate` to see how a closed rule scores on a clip.
   `fetch_counterexamples` shows the traces your current best sketches get wrong. Solving is cheap (<1 s); typecheck first.
4. Be economical: every tool call re-sends the whole conversation. Try at most 2-3 sketches by hand per round, then submit.
   Finish each round by calling `submit_sketches` ONCE with your final list (up to {k} sketches). Sketches that fail to typecheck are
   rejected with the error: fix and resubmit within the same call sequence. After submitting, reply with one short sentence.
You will be told which clips each submitted sketch violates (counterexamples) and asked to revise. A clip that many sketches violate may be
mislabelled or badly perceived: do not contort the rule to fit it."""


def task_message(examples: list[Example], nl_hint: str | None, k: int, *, max_each: int = 6) -> str:
    pos = [e for e in examples if e.positive]
    neg = [e for e in examples if not e.positive]
    parts = []
    if nl_hint:
        parts.append(f"The user describes the concept as: {nl_hint!r}")
    parts.append(f"{len(pos)} positive and {len(neg)} negative example clips follow (weight 3 = the user confirmed the label, 1 = bulk).")

    def block(group: list[Example], title: str) -> None:
        shown = sorted(group, key=lambda e: -e.weight)[:max_each]
        parts.append(f"=== {title} ({len(group)}) ===")
        for e in shown:
            tr = e.trace.trace if hasattr(e.trace, "trace") else e.trace
            parts.append(f"--- {title[:3]} clip_id={e.clip_id} weight={e.weight:g}\n{render_trace_text(tr)}")
        if len(group) > len(shown):
            ids = ", ".join(e.clip_id for e in group if e not in shown)
            parts.append(f"(not shown, still used by the solver: {ids})")

    block(pos, "POSITIVE")
    block(neg, "NEGATIVE")
    parts.append(f"Round 1. Propose up to {k} sketches and submit them with `submit_sketches`.")
    return "\n\n".join(parts)
