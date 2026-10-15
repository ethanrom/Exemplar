"""Seed CLI for demos and UI integration.

    uv run --project engine python -m exemplar.api.seed --media-dir "<main checkout>/data" --playground-spike --frollard
    uv run --project engine python -m exemplar.api.seed --fixtures

* `--playground-spike`  the recorded Developer Playground events (`<media>/spike/ring/<id>/{event.json,clip.mp4,
                        snapshot.jpg}`) become `ring` / `on_demand` events with their media.
* `--frollard`          `<media>/external/frollard_thief.mp4` ("Thief stealing our package" by frollard, CC BY 4.0)
                        is cut into 20 s windows every 5 s and imported as `upload` events with the attribution.
* `--fixtures`          `engine/tests/fixtures/traces/*.json` as `fixture` events without media (no perception).

Each imported clip gets a fast trace (B's cache makes repeats free; the cost ledger skips cached results).
The target database is `settings.db_path` (`EXEMPLAR_DATA_DIR` / `EXEMPLAR_DB`); the server need not be running.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from exemplar.contracts.trace import Trace
from exemplar.settings import REPO_ROOT, get_settings
from exemplar.store import ClipRow, EventRow, now_ms

from . import media, uploads
from .config import configure_logging
from .state import AppState

log = logging.getLogger("exemplar.api.seed")

FROLLARD_ATTRIBUTION = ('"Thief stealing our package" by frollard, CC BY 4.0, '
                        'https://www.youtube.com/watch?v=TfTFu8lGrwk')
FROLLARD_URL = "https://www.youtube.com/watch?v=TfTFu8lGrwk"
FIXTURE_DIR = REPO_ROOT / "engine" / "tests" / "fixtures" / "traces"
_DEVICE_RE = re.compile(r"ava1\.ring\.device\.(?!status|capabilities|configurations)[A-Z0-9]+")


def discover_device_id(spike_dir: Path) -> str:
    """The Playground device id, from the spike's request log (event.json does not carry it)."""
    try:
        m = _DEVICE_RE.search((spike_dir / "log.jsonl").read_text(encoding="utf-8"))
        if m:
            return m.group(0)
    except OSError:
        pass
    return "ava1.ring.device.PLAYGROUND"


def import_playground(state: AppState, spike_dir: Path) -> list[str]:
    """Register + copy media for every recorded Playground event. Returns the new/known clip ids."""
    device_id = discover_device_id(spike_dir)
    ids: list[str] = []
    for d in sorted(p for p in spike_dir.iterdir() if p.is_dir()):
        ev_file, clip_file = d / "event.json", d / "clip.mp4"
        if not ev_file.is_file() or not clip_file.is_file():
            continue
        ev = json.loads(ev_file.read_text(encoding="utf-8"))
        eid = ev["id"]
        row = EventRow(id=eid, source="ring", device_id=device_id, kind="on_demand", sub_type="on_demand",
                       start_ms=int(ev["start"]), end_ms=int(ev["end"]) if ev.get("end") else None,
                       raw_json=json.dumps(ev), created_at_ms=now_ms())
        if state.store.events.insert(row):
            state.store.clips.insert(ClipRow(id=eid, event_id=eid, created_at_ms=now_ms(), status="pending"))
        clip = state.store.clips.by_event(eid)
        if clip is not None and clip.status != "ready":
            dst, snap = state.clip_path(eid), state.snapshot_path(eid)
            shutil.copyfile(clip_file, dst)
            if (d / "snapshot.jpg").is_file():
                shutil.copyfile(d / "snapshot.jpg", snap)
            else:
                media.middle_frame_jpeg(dst, snap)
            dur = int(ev["end"]) - int(ev["start"]) if ev.get("end") else None
            state.store.clips.set_media(eid, path=str(dst), snapshot_path=str(snap), sha256=media.sha256_file(dst),
                                        duration_ms=dur, status="ready")
        ids.append(eid)
    return ids


def import_fixtures(state: AppState, fixture_dir: Path = FIXTURE_DIR) -> list[str]:
    """Hand-written fixture traces as `fixture` events (no media; the trace is the data)."""
    ids: list[str] = []
    base = 1_760_000_000_000
    for i, path in enumerate(sorted(fixture_dir.glob("*.json"))):
        tr = Trace.model_validate_json(path.read_text(encoding="utf-8"))
        eid = f"fx_{tr.clip_id}"
        ctx = tr.context
        start = ctx.started_at_ms or base + i * 3_600_000
        row = EventRow(id=eid, source="fixture", device_id=ctx.device_id, kind=ctx.event_kind, sub_type=ctx.sub_type,
                       start_ms=start, end_ms=start + tr.duration_ms, created_at_ms=now_ms())
        if state.store.events.insert(row):
            state.store.clips.insert(ClipRow(id=tr.clip_id, event_id=eid, created_at_ms=now_ms(),
                                             duration_ms=tr.duration_ms, status="not_found",
                                             error="fixture: trace only, no media"))
        state.store.traces.put(tr.clip_id, tr, mode="fixture")
        ids.append(tr.clip_id)
    return ids


def import_frollard(state: AppState, video: Path, window_s: float = 20.0, stride_s: float = 5.0) -> list[uploads.WindowSpec]:
    src, sha = uploads.import_file(state, video)
    return uploads.register_upload(state, src, sha, filename=video.name, attribution=FROLLARD_ATTRIBUTION,
                                   source_url=FROLLARD_URL, window_s=window_s, stride_s=stride_s)


def perceive_clips(state: AppState, clip_ids: list[str], workers: int = 2) -> int:
    """Fast perception for clips without a trace (cached results cost nothing). Returns how many got a trace."""
    todo = [c for c in clip_ids if not state.store.traces.has_any(c)]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        outs = list(pool.map(lambda c: state.processor.process_clip(c, monitor=False), todo))
    return sum(1 for o in outs if o is not None)


def run_seed(state: AppState, *, media_dir: Path, playground: bool, frollard: bool, fixtures: bool,
             perceive: bool = True, workers: int = 2, spike_dir: Path | None = None,
             video: Path | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if playground:
        sd = spike_dir or media_dir / "spike" / "ring"
        ids = import_playground(state, sd)
        out["playground_events"] = len(ids)
        out["playground_traced"] = perceive_clips(state, ids, workers) if perceive else 0
    if frollard:
        vp = video or media_dir / "external" / "frollard_thief.mp4"
        if not vp.is_file():
            raise FileNotFoundError(f"frollard clip not found: {vp}")
        specs = import_frollard(state, vp)
        out["frollard_windows"] = len(specs)
        if perceive:
            uploads.process_upload(state, specs, perceive=True, workers=workers)
        else:
            uploads.process_upload(state, specs, perceive=False, workers=1)
        out["frollard_traced"] = sum(1 for s in specs if state.store.traces.has_any(s.event_id))
    if fixtures:
        out["fixture_events"] = len(import_fixtures(state))
    out["totals"] = {"events": state.store.events.count(),
                     "ring": state.store.events.count("ring"), "upload": state.store.events.count("upload"),
                     "fixture": state.store.events.count("fixture")}
    out["cost"] = state.cost_summary()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m exemplar.api.seed", description=__doc__.split("\n\n")[0])
    ap.add_argument("--playground-spike", action="store_true", help="import the recorded Playground events")
    ap.add_argument("--frollard", action="store_true", help="import the frollard clip as 20 s / 5 s upload windows")
    ap.add_argument("--fixtures", action="store_true", help="load engine/tests/fixtures/traces/*.json as fixture events")
    ap.add_argument("--media-dir", type=Path, help="dir holding spike/ring/ and external/ (default: <data_dir>)")
    ap.add_argument("--spike-dir", type=Path, help="override <media-dir>/spike/ring")
    ap.add_argument("--video", type=Path, help="override <media-dir>/external/frollard_thief.mp4")
    ap.add_argument("--no-perceive", action="store_true", help="import media only; skip perception (no Bedrock calls)")
    ap.add_argument("--workers", type=int, default=2, help="concurrent perception calls (default 2)")
    args = ap.parse_args(argv)
    if not (args.playground_spike or args.frollard or args.fixtures):
        ap.error("pick at least one of --playground-spike --frollard --fixtures")
    configure_logging()
    settings = get_settings()
    state = AppState(settings=settings)
    print(f"database: {settings.db_path}")
    res = run_seed(state, media_dir=args.media_dir or settings.data_dir, playground=args.playground_spike,
                   frollard=args.frollard, fixtures=args.fixtures, perceive=not args.no_perceive,
                   workers=args.workers, spike_dir=args.spike_dir, video=args.video)
    print(json.dumps(res, indent=2))
    state.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
