"""The benchmark windows (committed manifest) and the CC BY demo windows, with paths resolved under the data dir."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from eval.data.config import SPLITS, load_concepts, load_yaml, read_manifest

# Perception parameters every stage shares: the baseline must see the SAME frames the rules were built from.
N_FRAMES = 16
SOURCE_MEVA = "meva"
SOURCE_UPLOAD = "upload"


def data_dir() -> Path:
    from exemplar.settings import get_settings
    return get_settings().data_dir


def eval_dir(base: Optional[Path] = None) -> Path:
    d = Path(base or data_dir()) / "eval"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass(frozen=True)
class Window:
    id: str
    concept: str
    label: str                    # "pos" | "neg"
    split: Optional[str]          # train | calib | test (None for the demo windows)
    clip: str                     # path relative to the data dir
    source: str                   # perceive source: "meva" | "upload"
    camera: Optional[str] = None
    hard: Optional[bool] = None

    @property
    def positive(self) -> bool:
        return self.label == "pos"

    def path(self, base: Optional[Path] = None) -> Path:
        return Path(base or data_dir()) / self.clip


def load_windows(*, concepts: Optional[Iterable[str]] = None, splits: Optional[Iterable[str]] = None) -> list[Window]:
    """Manifest windows, in manifest order (deterministic), optionally filtered."""
    cs = set(concepts) if concepts else None
    ss = set(splits) if splits else None
    if ss and not ss <= set(SPLITS):
        raise ValueError(f"unknown split(s): {sorted(ss - set(SPLITS))}")
    out = []
    for r in read_manifest():
        if cs and r["concept"] not in cs:
            continue
        if ss and r["split"] not in ss:
            continue
        out.append(Window(id=r["id"], concept=r["concept"], label=r["label"], split=r["split"], clip=r["clip"],
                          source=SOURCE_MEVA, camera=r.get("camera"), hard=r.get("hard")))
    return out


def load_frollard_windows() -> list[Window]:
    fr = load_yaml("frollard.yaml")
    return [Window(id=w["id"], concept=w["concept"], label=w["label"], split=None,
                   clip=f"external/windows/{w['id']}.mp4", source=SOURCE_UPLOAD) for w in fr["windows"]]


def concept_descriptions() -> dict[str, str]:
    return {cid: c.description for cid, c in load_concepts().items()}


def concept_ids() -> list[str]:
    return list(load_concepts())
