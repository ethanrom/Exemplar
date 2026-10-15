"""Turn the raw `emit_trace` tool input into validated `Trace` pieces.

Two kinds of problems, handled differently:

* **Harmless** — repaired silently and *counted* (`Normalized.dropped`): ids/zones/labels/types in the wrong
  case, `medium` for `med`, duplicate facts or entities, frames the model skipped or numbered out of range,
  facts that mention an entity id that was never declared (dropped), entities that no fact mentions (dropped),
  `near(a, a)` (dropped), a minority of frame indices left out (they become empty frames).  `near` is symmetric, so the mirrored fact is added: a rule written `near(k, p)` and one
  written `near(p, k)` then both see the observation.
* **Everything else** — unknown predicates, wrong arity, wrong argument types, unknown zone names, bad `conf`
  values — is reported as an error string; the caller sends the list back to the model for one retry.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from pydantic import ValidationError

from exemplar.contracts.ontology import ENTITY_TYPES, PREDICATES, ZONES
from exemplar.contracts.trace import Entity, Fact, Frame, PerceptionMeta, Trace, TraceContext, trace_errors

_CONF_ALIASES = {"low": "low", "l": "low", "med": "med", "medium": "med", "mid": "med", "m": "med",
                 "high": "high", "h": "high"}
_ENTITY_KINDS = {"Entity", "Person", "Vehicle", "Package", "Animal", "Object", "Carryable"}


@dataclass
class Normalized:
    entities: list[Entity] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    summary: str = ""
    errors: list[str] = field(default_factory=list)          # problems the model must fix (retry message)
    dropped: Counter = field(default_factory=Counter)        # harmless repairs, by category


def norm_id(raw: Any) -> Optional[str]:
    """Entity-id sanitiser: lowercase, `[a-z][a-z0-9_]*`.  None when nothing usable remains."""
    if not isinstance(raw, str):
        return None
    s = re.sub(r"[^a-z0-9_]+", "_", raw.strip().lower()).strip("_")
    if not s:
        return None
    return s if s[0].isalpha() else "e_" + s


def norm_label(raw: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(raw).strip().lower()).strip("_") if raw is not None else ""


def _as_list(v: Any) -> list:
    return v if isinstance(v, list) else []


def normalize(obj: Any, times_ms: Sequence[int]) -> Normalized:
    """Normalise the tool input `obj` against the sampled frame times (`times_ms[i]` -> `Frame.t_ms`)."""
    out = Normalized()
    if not isinstance(obj, dict) or not isinstance(obj.get("entities"), list) or not isinstance(obj.get("frames"), list):
        out.errors.append("tool input must be an object with `entities` (array), `frames` (array) and `summary`")
        return out
    out.summary = str(obj.get("summary") or "").strip()

    # ---- entities
    idmap: dict[str, str] = {}           # raw id (as given, or stripped+lowercased) -> normalised id
    ents: dict[str, Entity] = {}
    for e in obj["entities"]:
        if not isinstance(e, dict):
            out.dropped["entity_malformed"] += 1
            continue
        raw = e.get("id")
        nid = norm_id(raw)
        etype = str(e.get("type") or "").strip().lower()
        if nid is None or etype not in ENTITY_TYPES:
            out.dropped["entity_bad_id_or_type"] += 1
            continue
        if nid in ents:
            out.dropped["entity_duplicate"] += 1
            continue
        attrs: list[str] = []
        for a in _as_list(e.get("attrs")):
            la = norm_label(a)
            if la and la not in attrs:
                attrs.append(la)
        ents[nid] = Entity(id=nid, type=etype, attrs=tuple(attrs))
        idmap[str(raw)] = nid
        idmap[str(raw).strip().lower()] = nid
        idmap[nid] = nid

    # ---- frames / facts
    n = len(times_ms)
    by_frame: dict[int, dict[tuple[str, tuple[str, ...]], str]] = {i: {} for i in range(n)}
    rank = {"low": 0, "med": 1, "high": 2}
    listed: set[int] = set()
    for fr in obj["frames"]:
        idx = fr.get("i") if isinstance(fr, dict) else None
        if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < n:
            out.dropped["frame_bad_index"] += 1
            continue
        listed.add(idx)
        for f in _as_list(fr.get("facts")):
            if not isinstance(f, dict) or not isinstance(f.get("pred"), str) or not isinstance(f.get("args"), list):
                out.dropped["fact_malformed"] += 1
                continue
            pred = f["pred"].strip().lower()
            conf = _CONF_ALIASES.get(str(f.get("conf")).strip().lower())
            if conf is None:
                out.errors.append(f"frame {idx}: {pred}: conf must be one of low|med|high, got {f.get('conf')!r}")
                continue
            kinds = PREDICATES.get(pred)
            raw_args = [str(a) for a in f["args"]]
            if kinds is None or len(kinds) != len(raw_args):
                args = tuple(a.strip() for a in raw_args)           # trace_errors() will report it
            else:
                fixed: list[str] = []
                unknown = False
                for kind, a in zip(kinds, raw_args):
                    if kind == "Zone":
                        fixed.append(a.strip().lower())
                    elif kind == "Label":
                        fixed.append(norm_label(a))
                    else:                                              # entity slot
                        nid = idmap.get(a) or idmap.get(a.strip().lower()) or idmap.get(norm_id(a) or "")
                        if nid is None:
                            unknown = True
                            break
                        fixed.append(nid)
                if unknown:
                    out.dropped["fact_unknown_entity"] += 1
                    continue
                args = tuple(fixed)
            if pred == "near" and len(args) == 2 and args[0] == args[1]:
                out.dropped["fact_self_near"] += 1
                continue
            keys = [(pred, args)] + ([(pred, args[::-1])] if pred == "near" and len(args) == 2 else [])
            for j, key in enumerate(keys):
                prev = by_frame[idx].get(key)
                if prev is not None and j == 0:
                    out.dropped["fact_duplicate"] += 1
                by_frame[idx][key] = conf if prev is None or rank[conf] > rank[prev] else prev

    # A few skipped frames are harmless (they become empty frames), but a model that skipped most of them did not do
    # the task, and an all-empty trace would silently read as "nothing happened" -> make it retry.
    if len(listed) * 2 < n:
        out.errors.append(f"`frames` must list every frame index 0..{n - 1} (with an empty `facts` list when nothing "
                          f"is visible); you listed {len(listed)} of {n}")

    # ---- entities no fact mentions are dead weight (they would only add useless bindings)
    mentioned = {a for d in by_frame.values() for (_, args) in d for a in args}
    for eid in list(ents):
        if eid not in mentioned:
            out.dropped["entity_unreferenced"] += 1
            del ents[eid]

    out.entities = list(ents.values())
    for i, t in enumerate(times_ms):
        out.frames.append(Frame(t_ms=int(t), facts=tuple(Fact(pred=p, args=a, conf=c)
                                                         for (p, a), c in by_frame[i].items())))
    return out


def build_trace(norm: Normalized, *, clip_id: str, source: str, duration_ms: int, context: TraceContext,
                meta: PerceptionMeta) -> tuple[Optional[Trace], list[str]]:
    """Validate against the schema + ontology.  Returns (trace, []) or (None, errors)."""
    fields: dict[str, Any] = dict(clip_id=clip_id, source=source, duration_ms=duration_ms, entities=tuple(norm.entities),
                                  frames=tuple(norm.frames), context=context, summary=norm.summary, perception=meta)
    errs = list(norm.errors) + trace_errors(Trace.model_construct(**fields))
    if errs:
        return None, errs
    try:
        return Trace(**fields), []
    except ValidationError as e:                                       # pragma: no cover - belt and braces
        return None, [f"{'.'.join(str(p) for p in x['loc'])}: {x['msg']}" for x in e.errors()][:20]


def failed_trace(*, clip_id: str, source: str, duration_ms: int, context: TraceContext, meta: PerceptionMeta,
                 error: str) -> Trace:
    return Trace(clip_id=clip_id, source=source, duration_ms=duration_ms, status="perception_failed",
                 error=error[:600], context=context, perception=meta)
