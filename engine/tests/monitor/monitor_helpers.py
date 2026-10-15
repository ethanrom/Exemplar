"""Helpers for the monitor tests: fixture traces, fake perceivers, schema validators, event sinks."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from jsonschema import Draft202012Validator

from exemplar.contracts.trace import PerceptionMeta, Trace, TraceContext
from exemplar.dsl import parse, to_english
from exemplar.monitor import DeployedRule, EventInput

FIXTURES = Path(__file__).parents[1] / "fixtures" / "traces"
API = Path(__file__).parents[2] / "exemplar" / "contracts" / "api.yaml"
_SPEC = yaml.safe_load(API.read_text(encoding="utf-8"))

THEFT = "exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k) and not attr(p, delivery_uniform)"
UNATTENDED = "exists k: Package: always[0, 24] in_zone(k, steps)"
DWELL = "exists v: Vehicle: holds_for >= 120 in_zone(v, dock)"


def load(name: str) -> Trace:
    return Trace.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def with_conf(trace: Trace, pred: str, conf: str) -> Trace:
    """Copy of ``trace`` with every ``pred`` fact set to ``conf``."""
    d = json.loads(trace.model_dump_json())
    for fr in d["frames"]:
        for f in fr["facts"]:
            if f["pred"] == pred:
                f["conf"] = conf
    return Trace.model_validate(d)


def paid(trace: Trace, tokens_in: int, tokens_out: int, mode: str = "fast") -> Trace:
    return trace.model_copy(update={"perception": PerceptionMeta(mode=mode, tokens_in=tokens_in, tokens_out=tokens_out)})


def deployed(rule_id: str, text: str, *, tau: float = 0.0, delta: float = 0.1, actions=("ui",), concept="c1") -> DeployedRule:
    rule = parse(text)
    return DeployedRule(rule_id=rule_id, concept_id=concept, rule=rule, tau=tau, delta=delta, actions=tuple(actions),
                        english=to_english(rule))


def event(event_id: str = "e1", *, sub_type: Optional[str] = None, trace: Optional[Trace] = None,
          device_id: Optional[str] = "dev1", context: Optional[TraceContext] = None, **kw) -> EventInput:
    return EventInput(event_id=event_id, clip_id=kw.pop("clip_id", f"clip_{event_id}"), clip_path=None, sub_type=sub_type,
                      device_id=device_id, context=context or TraceContext(), trace=trace, **kw)


@dataclass
class Perceiver:
    """Fake perceive_* callable: returns the configured trace (or raises it) per event id, and counts calls."""
    by_event: dict = field(default_factory=dict)
    default: Any = None
    calls: list = field(default_factory=list)

    def __call__(self, ev: EventInput):
        self.calls.append(ev.event_id)
        out = self.by_event.get(ev.event_id, self.default)
        if isinstance(out, BaseException):
            raise out
        if out is None:
            raise AssertionError(f"unexpected perception call for {ev.event_id}")
        return out


class Sink:
    """Collects MonitorEvents and FiringRecords."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.firings: list = []

    def on_event(self, e: dict) -> None:
        self.events.append(e)

    def on_firing(self, f) -> None:
        self.firings.append(f)

    def types(self) -> list[str]:
        return [e["type"] for e in self.events]

    def of(self, type_: str) -> list[dict]:
        return [e for e in self.events if e["type"] == type_]


def validator(schema_name: str) -> Draft202012Validator:
    """Validator for components.schemas.<name> of api.yaml ($refs resolve inside the same document)."""
    return Draft202012Validator({"$ref": f"#/components/schemas/{schema_name}", "components": _SPEC["components"]})
