"""Loaders for the committed configs: concepts.yaml, videos.yaml, rois.yaml, splits.yaml, manifest.jsonl."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from .paths import EVAL_DATA

# Exterior EO cameras. G474-G479 are thermal 352x240 and are skipped.
EXTERIOR_CAMERAS = ("G300", "G301", "G328", "G336", "G339", "G340", "G341", "G424", "G436", "G505", "G506", "G509", "G638", "G639")
SPLITS = ("train", "calib", "test")


@dataclass(frozen=True)
class Concept:
    id: str
    title: str
    activities: tuple[str, ...]
    description: str
    hint: str
    confusers: tuple[str, ...] = ()  # related activities: windows containing them (but no target) are *hard* negatives


def load_concepts(path: Path | None = None) -> dict[str, Concept]:
    raw = yaml.safe_load((path or EVAL_DATA / "concepts.yaml").read_text(encoding="utf-8"))["concepts"]
    return {cid: Concept(cid, c["title"], tuple(c["activities"]), c["description"].strip(), c["hint"].strip(),
                          tuple(c.get("confusers", ()))) for cid, c in raw.items()}


def activity_to_concepts(concepts: dict[str, Concept]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in concepts.values():
        for a in c.activities:
            out.setdefault(a, []).append(c.id)
    return out


def load_yaml(name: str) -> dict:
    return yaml.safe_load((EVAL_DATA / name).read_text(encoding="utf-8"))


def dump_yaml(name: str, data: dict, header: str = "") -> None:
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
    (EVAL_DATA / name).write_text(header + body, encoding="utf-8", newline="\n")


def read_manifest(path: Path | None = None) -> list[dict]:
    p = path or EVAL_DATA / "manifest.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
