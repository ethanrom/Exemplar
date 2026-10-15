from pathlib import Path

from eval.data import cut, frollard, probe
from eval.data import select as S

CIDS = ["a", "b"]


def _cands():
    out = []
    for cam in ("G1", "G2", "G3", "G4"):
        for d in range(1, 5):
            for k in range(2):
                n = (ord(cam[1]) + 3 * d + k) % 7
                out.append(S.Candidate(f"2018-03-0{d}.10-00-0{k}.10-05-00.school.{cam}", cam, f"2018-03-0{d}", "10", "10", "k", 150_000_000,
                                       {"a": n, "b": (n * 3) % 5}))
    return out


def test_choose_videos_is_deterministic_and_respects_limits():
    c = _cands()
    a = S.choose_videos(c, CIDS, n_videos=10, n_cameras=3, per_camera_min=3, max_per_camera=4, max_per_cam_day=2)
    b = S.choose_videos(list(reversed(c)), CIDS, n_videos=10, n_cameras=3, per_camera_min=3, max_per_camera=4, max_per_cam_day=2)
    assert [x.stem for x in a] == [x.stem for x in b]
    assert len(a) == 10 and len({x.stem for x in a}) == 10
    cams = {x.camera for x in a}
    assert len(cams) == 3
    for cam in cams:
        mine = [x for x in a if x.camera == cam]
        assert 3 <= len(mine) <= 4
        assert all(sum(y.date == d for y in mine) <= 2 for d in {y.date for y in mine})


def test_committed_selection_meets_the_selection_criteria():
    from eval.data.config import load_yaml

    vids = load_yaml("videos.yaml")["videos"]
    assert 15 <= len(vids) <= 25
    assert len({v["camera"] for v in vids}) >= 3 and len({v["date"] for v in vids}) >= 2
    assert sum(v["size_bytes"] for v in vids) < 4.5e9
    for cid, total in load_yaml("videos.yaml")["instances_per_concept"].items():
        assert total >= 25, cid


def test_probe_parser():
    err = ("Input #0, avi, from 'x.avi':\n  Duration: 00:05:00.03, start: 0.000000, bitrate: 4679 kb/s\n"
           "  Stream #0:0: Video: h264 (High) (H264 / 0x34363248), yuv420p(progressive), 1920x1072, 4674 kb/s, 30 fps, 30 tbr, 30 tbn\n")
    assert probe.parse_ffmpeg_info(err) == {"width": 1920, "height": 1072, "fps": 30.0, "duration_ms": 300030}


def test_ffmpeg_cut_args_crop_scale_no_audio():
    args = cut.ffmpeg_cut_args(Path("in.avi"), Path("out.mp4"), 12_345, 15_000, (96, 0, 960, 540))
    vf = args[args.index("-vf") + 1]
    assert vf.startswith("crop=960:540:96:0,scale=1280:-2")
    assert "-an" in args and args[args.index("-ss") + 1] == "12.345" and args[args.index("-t") + 1] == "15.000"
    assert "crop" not in cut.ffmpeg_cut_args(Path("in.mp4"), Path("o.mp4"), 0, 1000, None)[args.index("-vf") + 1]


def test_frollard_rule():
    ev = {"theft": (20_500, 24_000), "walk_by": (48_300, 59_500), "person_walks_up": (13_000, 20_000), "box_on_steps": (0, 22_000)}
    assert frollard.classify(ev, 10_000, 15_000) == ("pos", "theft")
    assert frollard.classify(ev, 20_500, 15_000) == ("pos", "theft")
    assert frollard.classify(ev, 21_000, 15_000)[0] == "excluded"  # starts after the pickup began: ambiguous
    assert frollard.classify(ev, 5_000, 15_000) == ("neg", "person_walks_up_no_pickup")
    assert frollard.classify(ev, 50_000, 15_000) == ("neg", "walk_by")
    assert frollard.classify(ev, 70_000, 15_000) == ("neg", "empty_scene")
