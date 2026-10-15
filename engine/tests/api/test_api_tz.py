"""Local time for TraceContext (no tzdata on Windows: the fallback must implement the US rules)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from exemplar.api import tz


def ms(y, mo, d, h=0, mi=0) -> int:
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


@pytest.fixture(params=["fallback", "zoneinfo"])
def backend(request, monkeypatch):
    if request.param == "fallback":
        monkeypatch.setattr(tz, "_zone", lambda name: None)
    elif tz._zone("America/Los_Angeles") is None:
        pytest.skip("no IANA tz database on this machine (the fallback test covers it)")


def test_pacific_dst_boundaries(backend):
    assert tz.local_parts(ms(2026, 3, 8, 9, 59), "America/Los_Angeles") == (1, 6)      # 01:59 PST, Sunday
    assert tz.local_parts(ms(2026, 3, 8, 10, 0), "America/Los_Angeles") == (3, 6)      # DST began: 03:00 PDT
    assert tz.local_parts(ms(2026, 11, 1, 8, 59), "America/Los_Angeles") == (1, 6)     # 01:59 PDT
    assert tz.local_parts(ms(2026, 11, 1, 9, 0), "America/Los_Angeles") == (1, 6)      # fell back: 01:00 PST again
    assert tz.local_parts(ms(2026, 11, 1, 10, 0), "America/Los_Angeles") == (2, 6)


def test_playground_event_time(backend):
    assert tz.local_parts(1792048103109, "America/Los_Angeles") == (0, 3)              # 00:08 PDT Thursday


def test_other_us_zones(backend):
    t = ms(2026, 7, 1, 12, 0)
    assert tz.local_parts(t, "America/New_York")[0] == 8
    assert tz.local_parts(t, "America/Chicago")[0] == 7
    assert tz.local_parts(t, "America/Denver")[0] == 6
    assert tz.local_parts(t, "America/Phoenix")[0] == 5           # Arizona: no DST
    assert tz.local_parts(t, "America/Anchorage")[0] == 4
    assert tz.local_parts(t, "Pacific/Honolulu")[0] == 2
    w = ms(2026, 1, 1, 12, 0)
    assert tz.local_parts(w, "America/New_York")[0] == 7 and tz.local_parts(w, "America/Phoenix")[0] == 5


def test_weekday_rolls_with_the_local_date(backend):
    assert tz.local_parts(ms(2026, 10, 16, 3, 0), "America/Los_Angeles") == (20, 3)    # still Thursday evening in LA


def test_state_to_zone():
    assert tz.tz_for_state("CA", "US") == "America/Los_Angeles"
    assert tz.tz_for_state("ny") == "America/New_York"
    assert tz.tz_for_state("AZ") == "America/Phoenix"
    assert tz.tz_for_state("ZZ") == tz.DEFAULT_TZ and tz.tz_for_state(None) == tz.DEFAULT_TZ
    assert tz.tz_for_state("CA", "DE", default="UTC") == "UTC"


def test_unknown_zone_name_falls_back_to_pacific(monkeypatch):
    monkeypatch.setattr(tz, "_zone", lambda name: None)
    assert tz.local_parts(ms(2026, 7, 1, 12, 0), "Mars/Olympus") == (5, 2)
