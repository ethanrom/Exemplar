from __future__ import annotations

import io

import pytest
from PIL import Image

from exemplar.perception import SamplingError, probe, sample_frames, sample_window
from exemplar.perception.sampling import check_roi, sample_times_ms, window_bounds_ms


# ------------------------------------------------------------------ pure planning
@pytest.mark.parametrize("window_ms", [500, 999, 3000, 6001, 20000, 31730, 102000])
@pytest.mark.parametrize("n", [1, 2, 7, 16, 24, 32])
def test_times_are_integer_ordered_in_window_and_spaced(window_ms, n):
    ts = sample_times_ms(window_ms, n, 500)
    assert all(isinstance(t, int) for t in ts)
    assert 1 <= len(ts) <= min(n, max(1, window_ms // 500))
    assert ts == sorted(set(ts)) and ts[0] >= 0 and ts[-1] <= window_ms
    assert all(b - a >= 500 for a, b in zip(ts, ts[1:]))


def test_times_are_uniform_midpoints():
    assert sample_times_ms(20000, 16) == [625 + 1250 * i for i in range(16)]
    assert sample_times_ms(8000, 16) == [250 + 500 * i for i in range(16)]
    assert sample_times_ms(100, 5) == [50]                    # tiny window -> one frame


def test_short_window_reduces_n():
    assert len(sample_times_ms(3000, 16)) == 6
    assert len(sample_times_ms(900, 16)) == 1


def test_window_bounds():
    assert window_bounds_ms(31.73, 0, None) == (0, 31730)
    assert window_bounds_ms(31.73, 10, 5) == (10000, 5000)
    assert window_bounds_ms(31.73, 30, 10) == (30000, 1730)   # clipped to the clip end
    with pytest.raises(ValueError):
        window_bounds_ms(10, 10, None)
    with pytest.raises(ValueError):
        window_bounds_ms(10, -1, None)
    with pytest.raises(ValueError):
        window_bounds_ms(10, 0, 0)


def test_check_roi():
    assert check_roi(None) is None and check_roi((1, 2, 3, 4)) == (1, 2, 3, 4)
    for bad in [(0, 0, 0, 5), (-1, 0, 5, 5), (0, 0, 5), (0.5, 0, 5, 5)]:
        with pytest.raises(ValueError):
            check_roi(bad)  # type: ignore[arg-type]


# ------------------------------------------------------------------ ffmpeg
def jpeg_size(b: bytes) -> tuple[int, int]:
    assert b[:2] == b"\xff\xd8"
    return Image.open(io.BytesIO(b)).size


def red(b: bytes) -> float:
    return float(Image.open(io.BytesIO(b)).convert("RGB").resize((1, 1), Image.BOX).getpixel((0, 0))[0])


def test_probe(video):
    info = probe(video)
    assert abs(info.duration_s - 10.0) < 0.05 and (info.width, info.height) == (320, 240)


def test_probe_missing_file(tmp_path):
    with pytest.raises(SamplingError):
        probe(tmp_path / "nope.mp4")


def test_sample_frames_times_and_content(video):
    fr = sample_frames(video, 16)
    assert [f.t_ms for f in fr] == sample_times_ms(10000, 16) and len(fr) == 16
    assert all(jpeg_size(f.jpeg) == (320, 240) for f in fr)       # 320 < 640: never upscaled
    reds = [red(f.jpeg) for f in fr]
    assert reds == sorted(reds)                                    # the ramp: later time -> redder
    for f, r in zip(fr, reds):                                     # the frame really is from ~t_ms
        assert abs(r - 255 * f.t_ms / 10000) < 25


def test_window_times_are_relative_to_window_start(video):
    win = sample_window(video, 8, start_s=4, dur_s=4)
    assert win.duration_ms == 4000
    assert [f.t_ms for f in win.frames] == sample_times_ms(4000, 8) and len(win.frames) == 8
    # absolute time = 4 s + t_ms: red level should track it
    for f in win.frames:
        assert abs(red(f.jpeg) - 255 * (4000 + f.t_ms) / 10000) < 25


def test_window_runs_past_the_end_is_clipped(video):
    win = sample_window(video, 16, start_s=8, dur_s=100)
    assert win.duration_ms == 2000 and len(win.frames) == 4


def test_scaling_to_width(video):
    (f,) = sample_frames(video, 1, width=160)
    assert jpeg_size(f.jpeg) == (160, 120)


def test_roi_crop_applied_before_scaling(video):
    (f,) = sample_frames(video, 1, roi=(20, 40, 200, 100))
    assert jpeg_size(f.jpeg) == (200, 100)
    (g,) = sample_frames(video, 1, roi=(20, 40, 200, 100), width=100)
    assert jpeg_size(g.jpeg) == (100, 50)


def test_roi_outside_frame_rejected(video):
    with pytest.raises(ValueError):
        sample_frames(video, 1, roi=(300, 0, 100, 100))


def test_n_is_clamped_to_max_n_and_min_gap(video):
    assert len(sample_frames(video, 100, max_n=7)) == 7
    assert len(sample_frames(video, 100)) == 20                    # default cap 24, but 10 s / 0.5 s gap = 20
    fr = sample_frames(video, 100, min_gap_s=2.0)
    assert len(fr) == 5 and all(b.t_ms - a.t_ms >= 2000 for a, b in zip(fr, fr[1:]))
