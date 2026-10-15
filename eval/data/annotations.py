"""MEVA KPF annotation parsing (activities + geometry) and frame <-> millisecond arithmetic.

Frame indexing
--------------
`tsr0 = [f0, f1]` and geometry `ts0` are frame numbers of the 30 fps AVI, both ends **inclusive**.
We treat them as **0-based** (frame 0 is the first decoded frame, at t = 0 ms), so frame `f` is shown
during `[f * 1000/30, (f + 1) * 1000/30)` ms.  An activity therefore covers
`[frame_to_ms(f0), frame_to_ms(f1 + 1))`.  If the annotators were actually 1-based, every time here is
off by one frame (33 ms), which is far below the 10-20 s window padding; see README.md for the check.

All YAML is read with `yaml.safe_load` (the data repo is untrusted input).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

import yaml

FPS = 30  # MEVA drops-123-r13 AVIs are 30 fps

try:  # libyaml speeds up the 6 MB geometry files ~10x; still a safe loader
    _SafeLoader = yaml.CSafeLoader
except AttributeError:  # pragma: no cover
    _SafeLoader = yaml.SafeLoader

Box = tuple[float, float, float, float]  # x1, y1, x2, y2 in native pixels


def frame_to_ms(frame: int, fps: int = FPS) -> int:
    """Start time of `frame` in integer ms (round half up)."""
    return (frame * 1000 + fps // 2) // fps


def ms_to_frame(ms: int, fps: int = FPS) -> int:
    """Index of the frame whose start time is nearest to `ms` (inverse of `frame_to_ms`)."""
    return (ms * fps + 500) // 1000


_NAME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\.(?P<start>\d{2}-\d{2}-\d{2})\.(?P<end>\d{2}-\d{2}-\d{2})\.(?P<site>[a-z]+)\.(?P<camera>G\d{3})$"
)


@dataclass(frozen=True)
class VideoName:
    stem: str
    date: str
    start: str  # HH-MM-SS
    end: str
    site: str
    camera: str


def parse_video_name(stem: str) -> VideoName:
    """`2018-03-07.10-55-07.11-00-07.school.G339` (a trailing `.r13.avi` / `.activities.yml` is tolerated)."""
    stem = re.sub(r"(\.r13\.avi|\.activities\.yml|\.geom\.yml|\.types\.yml)$", "", stem)
    m = _NAME_RE.match(stem)
    if not m:
        raise ValueError(f"not a MEVA clip name: {stem!r}")
    return VideoName(stem=stem, **m.groupdict())


@dataclass(frozen=True)
class Activity:
    video: str                  # clip stem
    name: str                   # 2020 activity name, e.g. person_exits_vehicle
    act_id: int                 # id2 in the KPF file (unique per video)
    actor_ids: tuple[int, ...]  # id1 of the participating actors (matches geometry `id1`)
    f0: int                     # first frame, inclusive
    f1: int                     # last frame, inclusive
    start_ms: int               # frame_to_ms(f0)
    end_ms: int                 # frame_to_ms(f1 + 1), exclusive

    @property
    def dur_ms(self) -> int:
        return self.end_ms - self.start_ms


def _activity_name(act: dict) -> str | None:
    for key, val in act.items():
        if key.startswith("act") and isinstance(val, dict) and val:
            return next(iter(val))
    return None


def parse_activities(text: str, video: str, fps: int = FPS) -> list[Activity]:
    """Parse the text of a `*.activities.yml` file. Entries without an `act` (e.g. `meta`) are skipped."""
    out: list[Activity] = []
    for item in yaml.load(text, Loader=_SafeLoader) or []:
        act = item.get("act") if isinstance(item, dict) else None
        if not act:
            continue
        name = _activity_name(act)
        spans = [list(v) for ts in act.get("timespan", []) for k, v in ts.items() if k.startswith("tsr")]
        if name is None or not spans:
            continue
        f0 = min(s[0] for s in spans)
        f1 = max(s[1] for s in spans)
        actors = tuple(a["id1"] for a in act.get("actors", []) if "id1" in a)
        out.append(Activity(video=video, name=name, act_id=int(act.get("id2", -1)), actor_ids=actors, f0=int(f0),
                            f1=int(f1), start_ms=frame_to_ms(int(f0), fps), end_ms=frame_to_ms(int(f1) + 1, fps)))
    out.sort(key=lambda a: (a.f0, a.f1, a.name, a.act_id))
    return out


def load_activities(path: Path, fps: int = FPS) -> list[Activity]:
    stem = parse_video_name(path.name).stem
    return parse_activities(path.read_text(encoding="utf-8"), stem, fps)


@dataclass
class Geometry:
    """Per-actor boxes keyed by frame: `boxes[actor_id][frame] = (x1, y1, x2, y2)`."""
    boxes: dict[int, dict[int, Box]] = field(default_factory=dict)

    def actor_boxes(self, actor_id: int, f0: int, f1: int, step: int = 1) -> Iterator[Box]:
        track = self.boxes.get(actor_id, {})
        for f in range(f0, f1 + 1, step):
            b = track.get(f)
            if b is not None:
                yield b


def parse_geometry(text: str) -> Geometry:
    geo = Geometry()
    for item in yaml.load(text, Loader=_SafeLoader) or []:
        g = item.get("geom") if isinstance(item, dict) else None
        if not g or "g0" not in g:
            continue
        x1, y1, x2, y2 = (float(v) for v in str(g["g0"]).split())
        geo.boxes.setdefault(int(g["id1"]), {})[int(g["ts0"])] = (x1, y1, x2, y2)
    return geo


def load_geometry(path: Path) -> Geometry:
    return parse_geometry(path.read_text(encoding="utf-8"))


def activity_boxes(act: Activity, geo: Geometry, step: int = 5) -> list[Box]:
    """Boxes of all actors of `act` during its timespan (every `step`-th frame)."""
    boxes: list[Box] = []
    for aid in act.actor_ids:
        boxes.extend(geo.actor_boxes(aid, act.f0, act.f1, step))
    return boxes


def index_annotation_files(root: Path) -> dict[str, tuple[str, str]]:
    """Map clip stem -> (date, hour-folder) for every `*.activities.yml` under `root` (kitware/<date>/<hour>/)."""
    out: dict[str, tuple[str, str]] = {}
    for p in sorted(root.glob("*/*/*.activities.yml")):
        out[parse_video_name(p.name).stem] = (p.parent.parent.name, p.parent.name)
    return out


def activities_path(root: Path, stem: str, hour: str) -> Path:
    return root / parse_video_name(stem).date / hour / f"{stem}.activities.yml"


def geometry_path(root: Path, stem: str, hour: str) -> Path:
    return root / parse_video_name(stem).date / hour / f"{stem}.geom.yml"


def overlaps(a0: int, a1: int, b0: int, b1: int) -> bool:
    """Half-open interval overlap `[a0, a1)` vs `[b0, b1)`."""
    return a0 < b1 and b0 < a1


def count_by_name(acts: Iterable[Activity]) -> dict[str, int]:
    out: dict[str, int] = {}
    for a in acts:
        out[a.name] = out.get(a.name, 0) + 1
    return out
