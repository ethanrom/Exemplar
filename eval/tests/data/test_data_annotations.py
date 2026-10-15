import pytest

from eval.data import annotations as A

KPF = """
- {meta: 'some header line'}
- {'act': {'act2': {'person_exits_vehicle': 1.0}, 'actors': [{'id1': 11, 'timespan': [{'tsr0': [300, 389]}]}, {'id1': 12, 'timespan': [{'tsr0': [310, 389]}]}], 'id2': 5, 'src_status': 'good', 'timespan': [{'tsr0': [300, 389]}]}}
- {'act': {'act2': {'vehicle_stops': 1.0}, 'actors': [{'id1': 3, 'timespan': [{'tsr0': [0, 59]}]}], 'id2': 1, 'src_status': 'good', 'timespan': [{'tsr0': [0, 59]}]}}
- {'act': {'act2': {'empty_37': 1.0}, 'id2': 99, 'src': 'truth', 'timespan': [{'tsr0': [10, 20]}, {'tsr0': [40, 50]}]}}
"""

GEOM = """
- {'geom': {'g0': '100 200 130 260', 'id0': 1, 'id1': 11, 'keyframe': True, 'ts0': 300}}
- {'geom': {'g0': '102 200 132 260', 'id0': 2, 'id1': 11, 'keyframe': False, 'ts0': 301}}
- {'geom': {'g0': '500 400 700 500', 'id0': 3, 'id1': 12, 'keyframe': True, 'ts0': 310}}
- {'geom': {'g0': '1 2 3 4', 'id0': 4, 'id1': 77, 'keyframe': True, 'ts0': 5}}
"""


def test_parse_activities_snippet():
    acts = A.parse_activities(KPF, "2018-03-07.10-55-07.11-00-07.school.G339")
    assert [a.name for a in acts] == ["vehicle_stops", "empty_37", "person_exits_vehicle"]  # sorted by start frame
    ex = next(a for a in acts if a.name == "person_exits_vehicle")
    assert (ex.f0, ex.f1, ex.act_id, ex.actor_ids) == (300, 389, 5, (11, 12))
    assert ex.start_ms == 10_000 and ex.end_ms == 13_000  # frames 300..389 inclusive -> [10.000 s, 13.000 s)
    assert ex.dur_ms == 3_000
    empty = next(a for a in acts if a.name == "empty_37")  # several tsr -> hull; no actors
    assert (empty.f0, empty.f1, empty.actor_ids) == (10, 50, ())


def test_parse_activities_skips_meta_and_empty():
    assert A.parse_activities("", "x") == []
    assert A.parse_activities("- {meta: hello}\n", "x") == []


def test_frame_to_ms_arithmetic():
    assert A.frame_to_ms(0) == 0
    assert A.frame_to_ms(30) == 1000
    assert A.frame_to_ms(1) == 33 and A.frame_to_ms(2) == 67  # round half up of 33.33 / 66.67
    assert A.frame_to_ms(9000) == 300_000
    assert A.frame_to_ms(15, fps=15) == 1000
    for ms in (0, 1000, 12_345, 299_999):
        f = A.ms_to_frame(ms)
        assert A.frame_to_ms(f) <= ms + 17 and A.frame_to_ms(f + 1) >= ms - 17  # within half a frame
    assert A.ms_to_frame(A.frame_to_ms(4321)) == 4321


def test_inclusive_end_frame_is_exclusive_end_ms():
    a = A.parse_activities("- {'act': {'act2': {'x': 1.0}, 'id2': 1, 'timespan': [{'tsr0': [0, 29]}]}}", "v")[0]
    assert (a.start_ms, a.end_ms) == (0, 1000)  # 30 frames = exactly one second


def test_parse_geometry_and_activity_boxes():
    geo = A.parse_geometry(GEOM)
    assert geo.boxes[11][300] == (100.0, 200.0, 130.0, 260.0)
    acts = A.parse_activities(KPF, "v")
    ex = next(a for a in acts if a.name == "person_exits_vehicle")
    boxes = A.activity_boxes(ex, geo, step=1)
    assert (500.0, 400.0, 700.0, 500.0) in boxes and (102.0, 200.0, 132.0, 260.0) in boxes
    assert (1.0, 2.0, 3.0, 4.0) not in boxes  # actor 77 does not take part


def test_yaml_is_safe_loaded():
    evil = "- !!python/object/apply:os.system ['echo pwned']\n"
    with pytest.raises(Exception):
        A.parse_activities(evil, "v")


def test_parse_video_name():
    n = A.parse_video_name("2018-03-07.10-55-07.11-00-07.school.G339.r13.avi")
    assert (n.date, n.start, n.end, n.site, n.camera) == ("2018-03-07", "10-55-07", "11-00-07", "school", "G339")
    assert A.parse_video_name("2018-03-05.13-15-00.13-20-00.bus.G340.activities.yml").stem == "2018-03-05.13-15-00.13-20-00.bus.G340"
    with pytest.raises(ValueError):
        A.parse_video_name("not-a-clip")


def test_overlaps_is_half_open():
    assert A.overlaps(0, 10, 9, 20) and not A.overlaps(0, 10, 10, 20) and not A.overlaps(10, 20, 0, 10)
