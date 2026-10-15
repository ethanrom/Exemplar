"""Live checks against real Bedrock and the real clips under $EXEMPLAR_DATA_DIR.  Opt-in:

    EXEMPLAR_LIVE=1 EXEMPLAR_DOTENV=<.env> EXEMPLAR_DATA_DIR=<data> uv run pytest tests/perception -m live -s

Costs roughly $0.05 per full run (three fast calls ~$0.002 each, one strong round trip ~$0.04).  Model output is
not deterministic, so assertions are deliberately loose: they check the facts the downstream demo needs.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from exemplar.perception import perceive_detailed

pytestmark = pytest.mark.live

DATA = Path(os.environ.get("EXEMPLAR_DATA_DIR") or Path(__file__).parents[3] / "data")
FROLLARD = DATA / "external" / "frollard_thief.mp4"
# Point EXEMPLAR_PACKAGE_CLIP at the recorded Playground package clip (default: <data>/spike/ring/<event id>/clip.mp4).
PKG = Path(os.environ.get("EXEMPLAR_PACKAGE_CLIP") or DATA / "spike" / "ring" / "EVENT_ID" / "clip.mp4")
MEVA = DATA / "meva" / "clips" / "G339_unloads_280.mp4"


def facts(tr, pred):
    return [(fr.t_ms, f.args, f.conf) for fr in tr.frames for f in fr.facts if f.pred == pred]


def need(path: Path):
    if not path.is_file():
        pytest.skip(f"missing {path}")


def test_theft_window_has_pick_up_carrying_leave():
    need(FROLLARD)
    res = perceive_detailed(FROLLARD, clip_id="live_frollard_10_30", source="upload", start_s=10, dur_s=20)
    tr = res.trace
    assert tr.status == "ok", tr.error
    picks = facts(tr, "picks_up")
    assert picks, tr.summary                                         # the thief takes the box ~18-21 s = 8-11 s into the window
    (t_ms, args, _) = picks[0]
    assert 6000 <= t_ms <= 12500 and tr.entity(args[0]).type == "person" and tr.entity(args[1]).type == "package"
    assert any(a == args for _, a, _ in facts(tr, "carrying"))       # same ids across frames
    assert facts(tr, "leaves") or tr.signal("present", (args[0],))[-1] < 0.5   # and the person is gone by the end


def test_playground_package_clip_has_a_package_and_nobody():
    need(PKG)
    tr = perceive_detailed(PKG, clip_id="live_pg_package", source="ring").trace
    assert tr.status == "ok", tr.error
    assert any(e.type == "package" for e in tr.entities) and not any(e.type == "person" for e in tr.entities)
    assert not facts(tr, "picks_up")


def test_meva_crop_sees_person_near_the_open_door_suv():
    need(MEVA)
    tr = perceive_detailed(MEVA, clip_id="live_meva_crop", source="meva", roi=(0, 340, 480, 270)).trace
    assert tr.status == "ok", tr.error
    near = [a for _, a, _ in facts(tr, "near") if tr.entity(a[0]).type == "person" and tr.entity(a[1]).type == "vehicle"]
    assert near


def test_strong_mode_retry_roundtrip_with_real_model():
    """Corrupts the first real answer so the retry path (assistant turn incl. any reasoning blocks + toolResult
    error) is exercised against the real strong model."""
    need(FROLLARD)
    from exemplar.perception.extract import make_client

    real = make_client()

    class BreakFirst:
        n = 0

        def converse(self, **kw):
            r = real.converse(**kw)
            BreakFirst.n += 1
            if BreakFirst.n == 1:
                for c in r["output"]["message"]["content"]:
                    if "toolUse" in c:
                        c["toolUse"]["input"]["frames"][0]["facts"].append(
                            {"pred": "rings_doorbell", "args": ["p1"], "conf": "high"})
            return r

    res = perceive_detailed(FROLLARD, clip_id="live_strong_retry", source="upload", mode="strong", n_frames=8,
                            start_s=12, dur_s=12, client=BreakFirst())
    assert res.report.attempts == 2 and any("rings_doorbell" in e for e in res.report.retry_errors)
    assert res.trace.status == "ok", res.trace.error
