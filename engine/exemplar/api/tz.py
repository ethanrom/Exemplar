"""Local time for `TraceContext.local_hour` / `weekday`.

A Ring device reports its location as `{country, state}` (e.g. US/CA); the local clock is that state's time
zone. Windows ships no IANA database and `tzdata` is not a project dependency, so `zoneinfo` can fail with
`ZoneInfoNotFoundError`; the fallback below implements the current US rules (DST: second Sunday of March
02:00 local standard time to first Sunday of November 02:00 local daylight time), which covers every device
Ring supports (US only).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

DEFAULT_TZ = "America/Los_Angeles"

# primary zone per US state (states split across zones use the zone covering most of the population)
_STATE_TZ: dict[str, str] = {
    **dict.fromkeys(["CT", "DE", "DC", "FL", "GA", "ME", "MD", "MA", "MI", "NH", "NJ", "NY", "NC", "OH", "PA", "RI",
                     "SC", "VT", "VA", "WV", "IN", "KY"], "America/New_York"),
    **dict.fromkeys(["AL", "AR", "IL", "IA", "KS", "LA", "MN", "MS", "MO", "NE", "ND", "OK", "SD", "TN", "TX", "WI"],
                    "America/Chicago"),
    **dict.fromkeys(["CO", "ID", "MT", "NM", "UT", "WY"], "America/Denver"),
    "AZ": "America/Phoenix",
    **dict.fromkeys(["CA", "NV", "OR", "WA"], "America/Los_Angeles"),
    "AK": "America/Anchorage",
    "HI": "Pacific/Honolulu",
}

# fallback rules: (standard UTC offset in hours, observes US DST)
_FALLBACK: dict[str, tuple[int, bool]] = {
    "America/New_York": (-5, True),
    "America/Chicago": (-6, True),
    "America/Denver": (-7, True),
    "America/Phoenix": (-7, False),
    "America/Los_Angeles": (-8, True),
    "America/Anchorage": (-9, True),
    "Pacific/Honolulu": (-10, False),
}


def tz_for_state(state: str | None, country: str | None = "US", default: str = DEFAULT_TZ) -> str:
    """IANA zone name for a Ring device location."""
    if country and country.upper() != "US":
        return default
    return _STATE_TZ.get((state or "").upper(), default)


def _nth_sunday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    first = d + timedelta(days=(6 - d.weekday()) % 7)
    return first + timedelta(weeks=n - 1)


def _fallback_offset(utc_dt: datetime, std_hours: int, dst: bool) -> timedelta:
    if dst:
        year = utc_dt.year
        std = timedelta(hours=std_hours)
        start = datetime.combine(_nth_sunday(year, 3, 2), datetime.min.time()) + timedelta(hours=2) - std
        end = datetime.combine(_nth_sunday(year, 11, 1), datetime.min.time()) + timedelta(hours=1) - std
        if start <= utc_dt.replace(tzinfo=None) < end:
            return std + timedelta(hours=1)
        return std
    return timedelta(hours=std_hours)


@lru_cache(maxsize=32)
def _zone(name: str):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # ZoneInfoNotFoundError (no tzdata on Windows), ValueError for bad keys
        return None


def local_datetime(utc_ms: int, tz_name: str = DEFAULT_TZ) -> datetime:
    """The wall-clock datetime (tz-aware) at `utc_ms` in `tz_name`."""
    utc_dt = datetime.fromtimestamp(utc_ms / 1000, tz=timezone.utc)
    zone = _zone(tz_name)
    if zone is not None:
        return utc_dt.astimezone(zone)
    std, dst = _FALLBACK.get(tz_name, _FALLBACK[DEFAULT_TZ])
    off = _fallback_offset(utc_dt, std, dst)
    return utc_dt.astimezone(timezone(off))


def local_parts(utc_ms: int, tz_name: str = DEFAULT_TZ) -> tuple[int, int]:
    """(hour 0-23, weekday 0=Monday) at `utc_ms` in `tz_name`."""
    d = local_datetime(utc_ms, tz_name)
    return d.hour, d.weekday()
